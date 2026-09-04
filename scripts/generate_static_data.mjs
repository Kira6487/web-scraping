import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourceDir = path.resolve(process.argv[2] || path.join(repo, 'node_modules/country-state-city/lib/assets'));
const targetCodes = [
  'US', 'PE', 'CA', 'MX', 'BR', 'AR', 'CL', 'CO', 'EC', 'BO', 'UY', 'PY', 'CR', 'PA', 'DO',
  'PR', 'GB', 'IE', 'ES', 'PT', 'FR', 'DE', 'IT', 'NL', 'BE', 'CH', 'AT', 'AU', 'NZ',
];
const priorityCodes = ['US', 'PE', 'CA', 'MX'];

const readJson = (name) => JSON.parse(fs.readFileSync(path.join(sourceDir, name), 'utf8'));
const countries = readJson('country.json');
const regions = readJson('state.json');
const cities = readJson('city.json');
const countriesByCode = new Map(countries.map((country) => [country.isoCode, country]));
const missing = targetCodes.filter((code) => !countriesByCode.has(code));
if (missing.length) throw new Error(`Missing country codes: ${missing.join(', ')}`);

const dataDir = path.join(repo, 'web/data');
const citiesDir = path.join(dataDir, 'cities');
fs.mkdirSync(citiesDir, { recursive: true });
const orderedCodes = [
  ...priorityCodes,
  ...targetCodes
    .filter((code) => !priorityCodes.includes(code))
    .sort((a, b) => countriesByCode.get(a).name.localeCompare(countriesByCode.get(b).name)),
];
const locationData = {};

for (const code of orderedCodes) {
  const country = countriesByCode.get(code);
  const countryRegions = regions
    .filter((region) => region.countryCode === code)
    .sort((a, b) => a.name.localeCompare(b.name));
  const groupedCities = {};
  cities
    .filter((city) => city[1] === code)
    .forEach(([name, , regionCode]) => {
      const key = regionCode || '__country__';
      (groupedCities[key] ||= []).push(String(name).trim());
    });
  Object.keys(groupedCities).forEach((key) => {
    groupedCities[key] = [...new Set(groupedCities[key])]
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b));
  });
  fs.writeFileSync(path.join(citiesDir, `${code}.json`), `${JSON.stringify(groupedCities)}\n`);
  locationData[code] = {
    label: country.name,
    regions: Object.fromEntries(countryRegions.map((region) => [region.isoCode, { label: region.name }])),
    citiesFile: `cities/${code}.json`,
  };
}

fs.writeFileSync(path.join(dataDir, 'locations.json'), `${JSON.stringify({
  source: 'country-state-city@3.2.1',
  sourceLicense: 'GPL-3.0',
  countries: locationData,
}, null, 2)}\n`);
fs.copyFileSync(path.join(repo, 'config/business_categories.json'), path.join(dataDir, 'categories.json'));
console.log(`Generated ${orderedCodes.length} countries from ${sourceDir}`);
