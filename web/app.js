const state = { options: null, running: false };
const $ = (id) => document.getElementById(id);

async function loadOptions() {
  const response = await fetch('/api/options');
  if (!response.ok) throw new Error('Could not load search options.');
  state.options = await response.json();
  const country = $('country');
  Object.entries(state.options.countries).forEach(([code, item]) => country.add(new Option(item.label, code)));
  country.value = 'US';
  renderRegions();
  renderCategories();
}

function renderRegions() {
  const country = $('country').value;
  const regions = state.options.countries[country].regions;
  const stateSelect = $('state'); stateSelect.replaceChildren();
  Object.entries(regions).forEach(([code, item]) => stateSelect.add(new Option(item.label, code)));
  stateSelect.disabled = false; renderCities();
}

function renderCities() {
  const country = $('country').value; const region = $('state').value;
  const cities = state.options.countries[country].regions[region].cities;
  const city = $('city'); city.replaceChildren();
  cities.forEach(name => city.add(new Option(name, name)));
  city.disabled = false; updateButton();
}

function renderCategories() {
  const groups = {};
  state.options.categories.forEach(item => { (groups[item.group] ||= []).push(item); });
  $('categories').replaceChildren(...Object.entries(groups).map(([group, items]) => {
    const box = document.createElement('div'); box.className = 'category-group';
    const heading = document.createElement('h4'); heading.textContent = group; box.appendChild(heading);
    items.forEach(item => {
      const label = document.createElement('label'); label.className = 'category-option';
      label.innerHTML = `<input type="checkbox" value="${item.id}"> ${item.label}`;
      label.querySelector('input').addEventListener('change', updateButton); box.appendChild(label);
    }); return box;
  }));
}

function selectedCategories() { return [...document.querySelectorAll('#categories input:checked')].map(input => input.value); }
function updateButton() { $('submit-button').disabled = !($('country').value && $('state').value && ($('city').value || $('custom-city').value.trim()) && selectedCategories().length && Number($('max-results').value)); }
function setBusy(busy) { state.running = busy; $('submit-button').disabled = busy; $('progress-card').classList.toggle('hidden', !busy); $('result-card').classList.add('hidden'); }
function showError(message) { $('form-error').textContent = message || ''; }

async function startSearch(event) {
  event.preventDefault(); if (state.running) return; showError('');
  const payload = { country: $('country').value, state: $('state').value, city: $('city').value, custom_city: $('custom-city').value.trim(), categories: selectedCategories(), max_results: Number($('max-results').value) };
  setBusy(true);
  try {
    const response = await fetch('/api/search', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
    const body = await response.json(); if (!response.ok) throw new Error(body.error || 'Search could not start.');
    $('run-id').textContent = `Run ${body.run_id.slice(0, 8)}`; await poll(body.status_url, body.download_url);
  } catch (error) { setBusy(false); showError(error.message); }
}

async function poll(statusUrl, downloadUrl) {
  const response = await fetch(statusUrl); const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Could not read search status.');
  $('progress-title').textContent = body.stage || 'Working...';
  const count = body.total ? `${body.analyzed || 0} / ${body.total} prospects analyzed` : 'Working...'; $('progress-count').textContent = count;
  const width = body.total ? Math.max(8, Math.round(((body.analyzed || 0) / body.total) * 100)) : 30; document.querySelector('.progress-bar').style.width = `${width}%`;
  if (body.status === 'completed') { finishSearch(body.summary || {}, downloadUrl); return; }
  if (body.status === 'error') { setBusy(false); showError(body.error || 'Search failed.'); return; }
  setTimeout(() => poll(statusUrl, downloadUrl).catch(error => { setBusy(false); showError(error.message); }), 1000);
}

function finishSearch(summary, downloadUrl) {
  setBusy(false); $('progress-card').classList.add('hidden'); $('result-card').classList.remove('hidden'); $('download-button').href = downloadUrl;
  const values = [['Total discovered', summary.total_discovered || 0], ['Validated', summary.total_validated || 0], ['A+ opportunities', summary['A+'] || 0], ['A opportunities', summary.A || 0], ['Demo candidates', summary.demo_candidates || 0], ['Errors', summary.total_errors || 0]];
  $('summary').replaceChildren(...values.map(([label, value]) => { const item = document.createElement('div'); item.className = 'summary-item'; item.innerHTML = `<strong>${value}</strong><span>${label}</span>`; return item; }));
}

document.addEventListener('DOMContentLoaded', async () => {
  try { await loadOptions(); } catch (error) { showError(error.message); }
  $('country').addEventListener('change', renderRegions); $('state').addEventListener('change', renderCities); $('city').addEventListener('change', updateButton); $('custom-city').addEventListener('input', updateButton); $('max-results').addEventListener('change', updateButton); $('search-form').addEventListener('submit', startSearch);
  $('select-all').addEventListener('click', () => { document.querySelectorAll('#categories input').forEach(input => { input.checked = true; }); updateButton(); });
  $('clear-all').addEventListener('click', () => { document.querySelectorAll('#categories input').forEach(input => { input.checked = false; }); updateButton(); });
});
