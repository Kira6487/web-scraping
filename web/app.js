// Static catalogues are independent from the prospect-search backend.
// Configure window.FORM4TH_API_BASE_URL before this file when a public backend is available.
const API_BASE_URL = String(window.FORM4TH_API_BASE_URL || '').replace(/\/$/, '');
const state = {
  locations: null,
  categories: [],
  citiesCache: new Map(),
  running: false,
  cityRequest: 0,
};

const $ = (id) => document.getElementById(id);

async function fetchJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    error.backendUnavailable = true;
    throw error;
  }
  let body = null;
  try {
    body = await response.json();
  } catch (_) {
    // Keep the status-based error below when a server returns non-JSON content.
  }
  if (!response.ok) {
    const error = new Error(body && body.error ? body.error : `Request failed (${response.status}).`);
    error.status = response.status;
    error.backendUnavailable = response.status === 404 || response.status === 405 || response.status >= 500;
    throw error;
  }
  return body;
}

function backendUrl(path) {
  return `${API_BASE_URL}${path}`;
}

function returnedBackendUrl(url) {
  if (/^https?:\/\//i.test(url)) return url;
  return API_BASE_URL && url.startsWith('/') ? `${API_BASE_URL}${url}` : url;
}

function setMessage(id, message) {
  $(id).textContent = message || '';
}

function addPlaceholder(select, label) {
  select.replaceChildren(new Option(label, ''));
  select.value = '';
}

async function loadLocations() {
  const payload = await fetchJson('./data/locations.json');
  state.locations = payload.countries || payload;
  setMessage('location-error', '');
  const country = $('country');
  addPlaceholder(country, 'Select a country');
  Object.entries(state.locations).forEach(([code, item]) => country.add(new Option(item.label, code)));
  country.value = Object.prototype.hasOwnProperty.call(state.locations, 'US') ? 'US' : '';
  if (country.value) await renderRegions();
}

async function loadCategories() {
  state.categories = await fetchJson('./data/categories.json');
  renderCategories();
  setMessage('category-error', '');
}

function regionEntries(countryCode) {
  return Object.entries(state.locations?.[countryCode]?.regions || {});
}

async function renderRegions() {
  const countryCode = $('country').value;
  const stateSelect = $('state');
  const regionList = regionEntries(countryCode);
  addPlaceholder(stateSelect, countryCode && regionList.length ? 'Select a state / region' : 'No regions available');
  stateSelect.disabled = !countryCode || regionList.length === 0;
  regionList.forEach(([code, item]) => stateSelect.add(new Option(item.label, code)));
  await renderCities();
}

async function getCities(countryCode) {
  if (state.citiesCache.has(countryCode)) return state.citiesCache.get(countryCode);
  const metadata = state.locations[countryCode];
  const cityData = await fetchJson(`./data/${metadata.citiesFile}`);
  state.citiesCache.set(countryCode, cityData || {});
  return cityData || {};
}

async function renderCities() {
  const countryCode = $('country').value;
  const regionCode = $('state').value;
  const city = $('city');
  const requestId = ++state.cityRequest;
  const hasRegions = regionEntries(countryCode).length > 0;
  addPlaceholder(city, hasRegions && !regionCode ? 'Select a region first' : 'Loading...');
  city.disabled = true;
  updateButton();
  if (!countryCode || (hasRegions && !regionCode)) {
    if (!hasRegions) addPlaceholder(city, 'No cities available');
    updateButton();
    return;
  }
  try {
    const cityData = await getCities(countryCode);
    if (requestId !== state.cityRequest) return;
    const names = cityData[regionCode] || cityData.__country__ || [];
    addPlaceholder(city, names.length ? 'Select a city' : 'No cities available');
    names.forEach((name) => city.add(new Option(name, name)));
    city.disabled = names.length === 0;
    setMessage('location-error', '');
    updateButton();
  } catch (error) {
    if (requestId !== state.cityRequest) return;
    addPlaceholder(city, 'Cities unavailable');
    city.disabled = true;
    setMessage('location-error', 'Location data could not be loaded.');
    updateButton();
  }
}

function renderCategories() {
  const groups = {};
  state.categories.filter((item) => item.enabled !== false).forEach((item) => {
    (groups[item.group] ||= []).push(item);
  });
  $('categories').replaceChildren(...Object.entries(groups).map(([group, items]) => {
    const box = document.createElement('div');
    box.className = 'category-group';
    const heading = document.createElement('h4');
    heading.textContent = group;
    box.appendChild(heading);
    items.forEach((item) => {
      const label = document.createElement('label');
      label.className = 'category-option';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = item.id;
      input.addEventListener('change', updateButton);
      label.append(input, document.createTextNode(` ${item.label}`));
      box.appendChild(label);
    });
    return box;
  }));
  updateButton();
}

function selectedCategories() {
  return [...document.querySelectorAll('#categories input:checked')].map((input) => input.value);
}

function selectedCity() {
  return $('custom-city').value.trim() || $('city').value;
}

function updateButton() {
  const locationIsValid = Boolean(selectedCity());
  const formIsValid = Boolean(
    state.locations
      && state.categories.length
      && state.categories.some((item) => item.enabled !== false)
      && $('country').value
      && locationIsValid
      && selectedCategories().length
      && Number($('max-results').value),
  );
  $('submit-button').disabled = state.running || !formIsValid;
}

function setBusy(busy) {
  state.running = busy;
  $('progress-card').classList.toggle('hidden', !busy);
  $('result-card').classList.add('hidden');
  updateButton();
}

async function startSearch(event) {
  event.preventDefault();
  if (state.running) return;
  setMessage('form-error', '');
  const customCity = $('custom-city').value.trim();
  const payload = {
    country: $('country').value,
    state: $('state').value,
    city: customCity || $('city').value,
    custom_city: customCity,
    categories: selectedCategories(),
    max_results: Number($('max-results').value),
  };
  setBusy(true);
  try {
    const body = await fetchJson(backendUrl('/api/search'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    $('run-id').textContent = `Run ${body.run_id.slice(0, 8)}`;
    await poll(returnedBackendUrl(body.status_url), returnedBackendUrl(body.download_url));
  } catch (error) {
    setBusy(false);
    setMessage('form-error', error.backendUnavailable
      ? 'Prospect search backend is currently unavailable.'
      : error.message);
  }
}

async function poll(statusUrl, downloadUrl) {
  const body = await fetchJson(statusUrl);
  $('progress-title').textContent = body.stage || 'Working...';
  $('progress-count').textContent = body.total
    ? `${body.analyzed || 0} / ${body.total} prospects analyzed`
    : 'Working...';
  const width = body.total
    ? Math.max(8, Math.round(((body.analyzed || 0) / body.total) * 100))
    : 30;
  document.querySelector('.progress-bar').style.width = `${width}%`;
  if (body.status === 'completed') {
    finishSearch(body.summary || {}, downloadUrl);
    return;
  }
  if (body.status === 'error') {
    setBusy(false);
    setMessage('form-error', body.error || 'Search failed.');
    return;
  }
  setTimeout(() => poll(statusUrl, downloadUrl).catch((error) => {
    setBusy(false);
    setMessage('form-error', error.backendUnavailable
      ? 'Prospect search backend is currently unavailable.'
      : error.message);
  }), 1000);
}

function finishSearch(summary, downloadUrl) {
  setBusy(false);
  $('progress-card').classList.add('hidden');
  $('result-card').classList.remove('hidden');
  $('download-button').href = downloadUrl;
  const values = [
    ['Total discovered', summary.total_discovered || 0],
    ['Validated', summary.total_validated || 0],
    ['A+ opportunities', summary['A+'] || 0],
    ['A opportunities', summary.A || 0],
    ['Demo candidates', summary.demo_candidates || 0],
    ['Errors', summary.total_errors || 0],
  ];
  $('summary').replaceChildren(...values.map(([label, value]) => {
    const item = document.createElement('div');
    item.className = 'summary-item';
    const amount = document.createElement('strong');
    amount.textContent = value;
    const caption = document.createElement('span');
    caption.textContent = label;
    item.append(amount, caption);
    return item;
  }));
}

document.addEventListener('DOMContentLoaded', () => {
  $('country').addEventListener('change', () => { void renderRegions(); });
  $('state').addEventListener('change', () => { void renderCities(); });
  $('city').addEventListener('change', updateButton);
  $('custom-city').addEventListener('input', updateButton);
  $('max-results').addEventListener('change', updateButton);
  $('search-form').addEventListener('submit', startSearch);
  $('select-all').addEventListener('click', () => {
    document.querySelectorAll('#categories input').forEach((input) => { input.checked = true; });
    updateButton();
  });
  $('clear-all').addEventListener('click', () => {
    document.querySelectorAll('#categories input').forEach((input) => { input.checked = false; });
    updateButton();
  });

  Promise.allSettled([loadLocations(), loadCategories()]).then((results) => {
    const locationResult = results[0];
    const categoryResult = results[1];
    if (locationResult.status === 'rejected') setMessage('location-error', 'Location data could not be loaded.');
    if (categoryResult.status === 'rejected') setMessage('category-error', 'Business categories could not be loaded.');
    updateButton();
  });
});
