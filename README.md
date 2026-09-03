# FORM4TH B2B Prospect Engine

Motor determinista de prospección para empresas de Estados Unidos. Descubre negocios con Google Places API (New), valida su web oficial, hace crawling público controlado, extrae señales comerciales y calcula un `ai_fit_score` para un FORM4TH AI Front Desk / AI Lead Intake System.

No requiere una API de IA. No intenta evadir CAPTCHA, autenticación, robots.txt ni protecciones anti-bot.

## Instalación y configuración

El script instala automáticamente `pandas`, `openpyxl`, `beautifulsoup4` y `requests` si faltan.

Configura una API key de Google Cloud con Places API (New) habilitada:

```bash
export GOOGLE_PLACES_API_KEY="TU_API_KEY"
```

También se puede definir directamente en la constante `GOOGLE_PLACES_API_KEY` de `extract_leads.py`, aunque no se recomienda guardar secretos en el repositorio.

## Ejecución

Búsqueda predeterminada de seis consultas:

```bash
python extract_leads.py
```

Una categoría y ciudad:

```bash
python extract_leads.py --category "Home Services" --city "Austin, TX"
```

El punto de entrada histórico sigue siendo válido:

```bash
python extract_leads.py --category "Law Firms" --city "Dallas, TX" --max-pages 10
```

Configurable mediante JSON:

```json
{
  "queries": {
    "Home Services": ["Roofing contractors in Scottsdale AZ"],
    "Real Estate": ["Property management in Tampa FL"]
  }
}
```

```bash
python extract_leads.py --config searches.json --output-dir output
```

Parámetros principales: `--max-pages`, `--max-depth`, `--timeout`, `--min-reviews` y `--output-dir`.

## Flujo y arquitectura

`PlacesNewDiscovery` → `deduplicate_prospects` → `WebCrawler` → extractores HTML/JSON-LD → `calculate_ai_fit_score` → `export_workbook`.

Todo permanece en el punto de entrada actual para preservar compatibilidad, pero las responsabilidades están separadas por clases y funciones: discovery, validación, crawling, extracción, perfil comercial, scoring y exportación.

## Política de crawling

- Solo sigue enlaces HTTP/HTTPS internos al dominio oficial.
- Consulta `robots.txt` y no visita rutas desautorizadas.
- Busca `sitemap.xml` o sitemaps declarados en robots.
- Máximo predeterminado de 12 páginas y profundidad 1 por dominio.
- Prioriza contacto, servicios, ubicaciones, booking, quote, FAQ, team y páginas equivalentes.
- Excluye imágenes, PDF, JS, CSS, fuentes, vídeo y archivos binarios.
- Aplica timeout de 5 segundos, un retry moderado y rate limit por dominio.

## Scoring

`ai_fit_score` está limitado a 0–100 y se calcula sin inventar datos:

- high-ticket industry: 25
- no AI chat / smart intake: 20
- no easy online booking: 10
- limited hours / after-hours gap: 10
- easy contact: 15
- public data usable for a demo: 10
- strong business signals: 10

Penalizaciones configurables en `Config.penalties`: booking efectivo (-10), chatbot sofisticado (-20), intake 24/7 (-10), funnel sofisticado (-15), complejidad healthcare (-15), complejidad legal (-10) y enterprise (-10). El score nunca sale de 0–100.

Tiers: `A+` 85–100, `A` 70–84, `B` 55–69, `C` 40–54, `D` <40. Acciones: `BUILD_DEMO` desde 80, `CONTACT_DIRECTLY` desde 70, `REVIEW_MANUALLY` desde 40 y `SKIP` por debajo.

## Datos y trazabilidad

Se conserva cada dato original (`phone_original`, `website_original`) junto a sus datos validados (`verified_phone`, `verified_website`, `verified_email`). Los emails pasan por filtros de placeholders, dominios de Sentry/Wix, scripts, bundles y extensiones de assets. La confianza sigue la prioridad contacto → header/footer → about/team → JSON-LD → mailto → otras páginas.

También se registran JSON-LD/schema.org, formularios, chat y proveedor, booking y proveedor, horarios, servicios, áreas, CTA, business model y URLs de evidencia.

## Excel generado

Cada ejecución crea un archivo nuevo, sin sobrescribir anteriores:

`output/form4th_prospects_YYYY-MM-DD_HH-MM-SS.xlsx`

Si el timestamp ya existe, agrega `_02`, `_03`, etc. El workbook contiene:

1. `Prospects`: todos los prospectos, ordenados por `ai_fit_score DESC` y `google_review_count DESC`.
2. `Top Opportunities`: prospectos con score ≥70.
3. `Demo Candidates`: prospectos con score ≥80 y perfil reutilizable para demos.
4. `Validation Issues`: errores por empresa, etapa, URL, HTTP status y timestamp.
5. `Run Summary`: métricas, queries, tiers, candidatos y ruta generada.

Las hojas usan encabezados `#1F2937`, texto blanco, Segoe UI, bordes finos, autofilter, freeze panes, ajuste razonable de ancho y colores legibles por tier.

## Tests

Los tests usan mocks y fixtures locales, sin depender de sitios externos:

```bash
python -m unittest discover -s tests -v
```

Cubren limpieza de emails, normalización de URL, redirecciones y HTTP 202, JSON-LD, links internos, chat, booking, deduplicación, límites del score, tiers, filenames únicos, exportación y las cinco hojas del workbook.

## Problemas conocidos y Fase 2

- Places API y algunos sitios pueden requerir billing, presentar contenido solo tras ejecutar JavaScript o devolver bloqueos legítimos.
- `robots.txt` ausente se registra como no encontrado; un `robots.txt` que prohíbe la homepage detiene el crawling.
- La verificación de email confirma evidencia publicada en la web oficial, no existencia SMTP.
- El análisis no ejecuta navegador ni JavaScript para mantener el crawler ligero.

Fase 2 recomendada: adaptador opcional Playwright para sitios JS-only con límites explícitos, configuración YAML con validación de esquema, persistencia incremental, un verificador externo de teléfono/email y concurrencia global controlada con presupuesto por dominio.

## Prospect Engine UI

La interfaz web usa Python `http.server` y JavaScript/CSS nativos; no agrega un framework pesado ni duplica el motor. El backend lee `GOOGLE_PLACES_API_KEY` exclusivamente desde el entorno.

Iniciar:

```bash
export GOOGLE_PLACES_API_KEY="TU_API_KEY"
python web_app.py --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000`. La UI permite seleccionar país, región, ciudad o ciudad personalizada, múltiples categorías y un máximo global entre 1 y 500. Los catálogos compartidos están en `config/locations.json` y `config/business_categories.json`.

Endpoints:

- `POST /api/search`: inicia una ejecución asíncrona y devuelve un `run_id`.
- `GET /api/search/{run_id}`: devuelve etapa, progreso y resumen.
- `GET /api/results/{run_id}/download`: descarga el XLSX terminado; no acepta paths del cliente.
- `GET /api/options`: expone únicamente catálogos públicos, nunca secretos.

El botón se bloquea durante la ejecución y el backend impide búsquedas simultáneas dentro del proceso. Los resultados siguen generándose en `output/` con timestamp y no se versionan porque `output/*.xlsx` está ignorado.

Para ejecutar tests del backend y UI:

```bash
python -m unittest discover -s tests -v
```

No hay build frontend separado: los assets estáticos se sirven directamente desde `web/`.
