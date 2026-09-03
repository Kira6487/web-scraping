#!/usr/bin/env python3
"""Extractor de leads B2B usando Google Places API (New) v1.

Usa el endpoint oficial REST ``https://places.googleapis.com/v1/places:searchText``.
La clave puede configurarse mediante ``GOOGLE_PLACES_API_KEY`` o asignarse
directamente a la constante del script.

Ejemplo:
    export GOOGLE_PLACES_API_KEY="AIza..."
    python extract_leads.py
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Auto-instalador: se ejecuta antes de importar paquetes de terceros.
REQUIRED_PACKAGES = {
    "pandas": "pandas",
    "openpyxl": "openpyxl",
    "bs4": "beautifulsoup4",
    "requests": "requests",
}


def ensure_dependencies() -> None:
    """Instala las dependencias faltantes en el mismo Python del script."""
    missing = [
        package
        for import_name, package in REQUIRED_PACKAGES.items()
        if importlib.util.find_spec(import_name) is None
    ]
    if not missing:
        return
    print(f"[INFO] Instalando dependencias: {', '.join(missing)}")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *missing]
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "No fue posible instalar las dependencias. "
            f"Ejecuta: {sys.executable} -m pip install {' '.join(missing)}"
        ) from exc


ensure_dependencies()

import pandas as pd  # noqa: E402
import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402


PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Recomendado: variable de entorno. Alternativamente, reemplaza "" por la key.
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

OUTPUT_FILE = "US_B2B_Google_Places_Leads.xlsx"
HTTP_TIMEOUT_SECONDS = 5
PLACES_PAGE_SIZE = 20
FIELD_MASK = (
    "places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
    "places.websiteUri,places.rating,places.userRatingCount,"
    "places.primaryTypeDisplayName"
)

TARGET_QUERIES = {
    "Home Services": [
        "Roofing contractors in Austin TX",
        "HVAC services in Phoenix AZ",
    ],
    "Law Firms": [
        "Personal injury lawyer in Dallas TX",
        "Family law attorney in Houston TX",
    ],
    "Real Estate": [
        "Property management in Miami FL",
        "Commercial real estate in Atlanta GA",
    ],
}

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


@dataclass
class WebsiteAnalysis:
    """Resultado de la evaluación rápida de un sitio web."""

    status: str
    opportunity_score: str
    emails: str
    link_count: int = 0
    word_count: int = 0
    http_status: str = ""
    error: str = ""


def get_api_key() -> str:
    """Obtiene la key desde entorno o desde la constante global."""
    return os.getenv("GOOGLE_PLACES_API_KEY", "").strip() or GOOGLE_PLACES_API_KEY.strip()


def extract_display_name(place: dict[str, Any]) -> str:
    display_name = place.get("displayName", "")
    return str(display_name.get("text", "")) if isinstance(display_name, dict) else str(display_name)


def format_us_phone(phone: str | None) -> str:
    """Normaliza un número estadounidense a formato +1 (XXX) XXX-XXXX."""
    if not phone:
        return "N/A"
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("1") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return f"+{digits}" if digits else "N/A"


def extract_emails(html: str) -> str:
    emails = {email.lower().rstrip(".,;:)") for email in EMAIL_REGEX.findall(html)}
    return "; ".join(sorted(emails)) if emails else "N/A"


def analyze_website(website_uri: str | None) -> WebsiteAnalysis:
    """Analiza la web con timeout de cinco segundos y cuenta enlaces/palabras."""
    if not website_uri:
        return WebsiteAnalysis("No Website", "CRITICAL", "N/A")

    try:
        response = requests.get(
            website_uri,
            timeout=HTTP_TIMEOUT_SECONDS,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; B2BProspectExtractor/1.0)"},
        )
        response.raise_for_status()
        html = response.text or ""
        soup = BeautifulSoup(html, "html.parser")
        link_count = len(soup.find_all("a", href=True))
        word_count = len(soup.get_text(" ", strip=True).split())
        simple_site = link_count < 8 or word_count < 350
        return WebsiteAnalysis(
            status="Simple Site (<3 pages)" if simple_site else "Standard Site",
            opportunity_score="HIGH" if simple_site else "LOW",
            emails=extract_emails(html),
            link_count=link_count,
            word_count=word_count,
            http_status=str(response.status_code),
        )
    except requests.Timeout:
        return WebsiteAnalysis(
            "Unreachable / Timeout", "HIGH", "N/A", error=f"Timeout > {HTTP_TIMEOUT_SECONDS}s"
        )
    except requests.RequestException as exc:
        return WebsiteAnalysis("Unreachable", "HIGH", "N/A", error=type(exc).__name__)


def search_text(query: str, api_key: str) -> list[dict[str, Any]]:
    """Ejecuta la búsqueda REST oficial Places API (New) v1."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body = {"textQuery": query, "pageSize": PLACES_PAGE_SIZE}
    response = requests.post(PLACES_SEARCH_URL, headers=headers, json=body, timeout=15)
    if not response.ok:
        detail = response.text[:500].replace("\n", " ")
        raise RuntimeError(f"Google Places API HTTP {response.status_code}: {detail}")
    payload = response.json()
    places = payload.get("places", [])
    return places if isinstance(places, list) else []


def place_to_lead(place: dict[str, Any], category: str, query: str) -> dict[str, Any]:
    """Convierte un objeto Places API New en una fila del Excel."""
    website_uri = place.get("websiteUri") or ""
    analysis = analyze_website(website_uri)
    primary_type = place.get("primaryTypeDisplayName", "")
    if isinstance(primary_type, dict):
        primary_type = primary_type.get("text", "")
    return {
        "Company Name": extract_display_name(place),
        "Target Category": category,
        "Search Query": query,
        "Address": place.get("formattedAddress", "N/A"),
        "Phone": format_us_phone(place.get("nationalPhoneNumber")),
        "Google Rating": place.get("rating", "N/A"),
        "Google Review Count": place.get("userRatingCount", 0),
        "Primary Type": primary_type or "N/A",
        "Website URL": website_uri or "N/A",
        "Web Status": analysis.status,
        "Opportunity Score": analysis.opportunity_score,
        "Email": analysis.emails,
        "Link Count": analysis.link_count,
        "Word Count": analysis.word_count,
        "HTTP Status": analysis.http_status or "N/A",
        "Inspection Error": analysis.error,
    }


def export_to_excel(leads: list[dict[str, Any]], output_file: str = OUTPUT_FILE) -> Path:
    """Exporta Excel con estilo oscuro, anchos automáticos, filtros y bordes."""
    columns = [
        "Company Name", "Target Category", "Search Query", "Address", "Phone",
        "Google Rating", "Google Review Count", "Primary Type", "Website URL",
        "Web Status", "Opportunity Score", "Email", "Link Count", "Word Count",
        "HTTP Status", "Inspection Error",
    ]
    dataframe = pd.DataFrame(leads, columns=columns)
    dataframe.sort_values(
        by=["Opportunity Score", "Google Review Count"],
        ascending=[True, False],
        inplace=True,
        ignore_index=True,
    )
    dataframe.to_excel(output_file, index=False, sheet_name="B2B Leads")

    workbook = load_workbook(output_file)
    worksheet = workbook["B2B Leads"]
    header_fill = PatternFill("solid", fgColor="1F2937")
    header_font = Font(name="Segoe UI", bold=True, color="FFFFFF")
    body_font = Font(name="Segoe UI", size=10, color="111827")
    thin = Side(style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    worksheet.row_dimensions[1].height = 32

    header_indexes = {cell.value: cell.column for cell in worksheet[1]}
    centered_columns = {"Web Status", "Opportunity Score", "HTTP Status"}
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = body_font
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        for column_name in centered_columns:
            worksheet.cell(row[0].row, header_indexes[column_name]).alignment = Alignment(
                horizontal="center", vertical="top", wrap_text=True
            )

    for row_number in range(2, worksheet.max_row + 1):
        url_cell = worksheet.cell(row_number, header_indexes["Website URL"])
        if url_cell.value and str(url_cell.value).startswith(("http://", "https://")):
            url_cell.hyperlink = str(url_cell.value)
            url_cell.style = "Hyperlink"

    for column_cells in worksheet.columns:
        column_letter = column_cells[0].column_letter
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 55)
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    workbook.save(output_file)
    return Path(output_file).resolve()


def main() -> None:
    api_key = get_api_key()
    if not api_key:
        raise SystemExit(
            "ERROR: falta GOOGLE_PLACES_API_KEY. Configúrala en el entorno "
            "o asígnala directamente en el script."
        )

    leads: list[dict[str, Any]] = []
    total_queries = sum(len(queries) for queries in TARGET_QUERIES.values())
    query_number = 0
    for category, queries in TARGET_QUERIES.items():
        for query in queries:
            query_number += 1
            print(f"[{query_number}/{total_queries}] Buscando: {query}")
            try:
                places = search_text(query, api_key)
            except Exception as exc:
                print(f"  [WARN] {exc}")
                continue
            print(f"  Encontrados: {len(places)}")
            for place in places:
                try:
                    leads.append(place_to_lead(place, category, query))
                except Exception as exc:
                    print(f"  [WARN] No se pudo analizar un lugar: {exc}")

    output_path = export_to_excel(leads)
    print(f"[OK] {len(leads)} leads exportados a: {output_path}")


if __name__ == "__main__":
    main()

