'use strict';
const $ = id => document.getElementById(id);
const token = location.hash.slice(1) || sessionStorage.getItem('bench-token') || '';
sessionStorage.setItem('bench-token', token);
history.replaceState(null, '', '/');
let data, selected = new Set(), paused = false, lastApps = '', pendingIds = [], stopped = false;
const bytes = n => n == null ? '—' : n < 1024 ? `${n} B` : `${(n / 1024 ** Math.min(4, Math.floor(Math.log(n) / Math.log(1024)))).toFixed(1)} ${['B','KB','MB','GB','TB'][Math.min(4, Math.floor(Math.log(n) / Math.log(1024)))]}`;
const percent = n => n == null ? '—' : `${n.toFixed(1)}%`;
function el(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
function notice(message) { $('notice').textContent = message || ''; }
async function api(path, body) {
  const options = {headers: {'X-Bench-Token': token}};
  if (body !== undefined) { options.method = 'POST'; options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
  const response = await fetch(`/api/${path}`, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
function action(fn) { return async () => { try { await fn(); } catch (error) { notice(error.message); } }; }
function tab(id) { document.querySelectorAll('.panel').forEach(e => e.hidden = e.id !== id); document.querySelectorAll('nav button').forEach(e => e.classList.toggle('active', e.dataset.tab === id)); }
document.querySelectorAll('[data-tab]').forEach(e => e.addEventListener('click', () => tab(e.dataset.tab)));
function updateSelection() { $('selected-count').textContent = selected.size; $('remove-selected').disabled = !selected.size || data?.job.status === 'running'; }
function confirmApps(ids) {
  pendingIds = ids;
  $('confirm-list').replaceChildren(...ids.map(id => el('li', data.apps.find(a => a.id === id)?.name || id)));
  $('confirm-dialog').showModal();
}
$('confirm-dialog').addEventListener('close', action(async () => {
  if ($('confirm-dialog').returnValue !== 'confirm') return;
  await api('uninstall', {ids: pendingIds, confirmed: true}); selected.clear(); lastApps = ''; updateSelection(); await pollOnce();
}));
$('remove-selected').onclick = () => confirmApps([...selected]);
function renderApps() {
  const optional = data.apps.filter(a => a.optional && a.removable);
  const available = new Set(optional.map(a => a.id));
  selected = new Set([...selected].filter(id => available.has(id)));
  $('optional-count').textContent = data.apps_status === 'loading' ? 'Looking for optional apps…' : `${optional.length} optional apps found`;
  const signature = JSON.stringify(data.apps);
  if (signature !== lastApps) {
    lastApps = signature;
    $('optional-apps').replaceChildren(...optional.map(app => {
      const card = el('label', null, 'card'), check = el('input'); check.type = 'checkbox'; check.checked = selected.has(app.id);
      check.onchange = () => { check.checked ? selected.add(app.id) : selected.delete(app.id); updateSelection(); };
      const info = el('div'); info.append(el('strong', app.name.replace(/^Microsoft\./, '').replace(/^Clipchamp\./, '')), el('small', 'Optional Windows app'));
      card.append(check, info); return card;
    }));
    if (!optional.length) $('optional-apps').append(el('p', data.apps_status === 'loading' ? 'Reading your installed packages…' : 'No apps from the optional removal list are installed.', 'empty'));
  }
  updateSelection();
  const query = $('app-search').value.toLowerCase();
  $('app-rows').replaceChildren(...data.apps.filter(a => a.name.toLowerCase().includes(query)).map(app => {
    const row = el('tr'), name = el('td', app.name); name.append(el('small', app.publisher));
    const cell = el('td');
    if (app.removable) { const button = el('button', app.kind === 'store' ? 'Uninstall' : 'Open uninstaller ↗', 'outline'); button.disabled = data.job.status === 'running'; button.onclick = () => confirmApps([app.id]); cell.append(button); }
    else cell.textContent = 'Protected / unavailable';
    row.append(name, el('td', `${app.kind} / ${app.scope}`), el('td', bytes(app.size), 'number'), cell); return row;
  }));
}
function renderProcesses() {
  const m = data.metrics;
  $('cpu-total').textContent = percent(m.cpu); $('ram-total').textContent = bytes(m.memory.used); $('process-count').textContent = m.processes.length;
  $('gpu-note').textContent = m.gpu_error ? `GPU unavailable: ${m.gpu_error}` : 'GPU counters available. A dash means the sample is unavailable or warming up.';
  if (paused) return;
  const query = $('process-search').value.toLowerCase(), sort = $('process-sort').value;
  const rows = m.processes.filter(p => p.name.toLowerCase().includes(query) || String(p.pid).includes(query)).sort((a,b) => (b[sort] ?? -1) - (a[sort] ?? -1));
  $('process-rows').replaceChildren(...rows.map(p => {
    const row = el('tr'), app = data.apps.find(a => a.id === p.app), cell = el('td');
    if (app?.removable) { const button = el('button', 'Uninstall app', 'outline'); button.title = app.name; button.disabled = data.job.status === 'running'; button.onclick = () => confirmApps([app.id]); cell.append(button, el('small', app.name)); }
    else cell.textContent = app ? 'Protected' : 'No reliable match';
    row.append(el('td', p.name), el('td', p.pid, 'number'), el('td', percent(p.cpu), 'number'), el('td', bytes(p.ram), 'number'), el('td', percent(p.gpu), 'number'), cell); return row;
  }));
}
function renderStorage() {
  $('drives').replaceChildren(...data.drives.map(d => {
    const card = el('button', null, 'drive'), progress = el('progress'); progress.max = d.total; progress.value = d.used;
    progress.setAttribute('aria-label', `${d.path} used space`);
    card.append(el('span', d.path), el('strong', `${bytes(d.free)} free`), progress, el('span', `${bytes(d.used)} used / ${bytes(d.total)}`));
    card.onclick = () => { $('scan-path').value = d.path; }; return card;
  }));
  if (!$('scan-path').value && data.drives.length) $('scan-path').value = data.drives[0].path;
  const scan = data.storage;
  $('scan').disabled = scan.status === 'running'; $('cancel-scan').disabled = scan.status !== 'running';
  $('scan-status').textContent = scan.status === 'idle' ? 'Choose a location to start.' : `${scan.status.toUpperCase()} · ${scan.root} · ${bytes(scan.bytes)} · ${scan.files.toLocaleString()} files · ${scan.skipped.toLocaleString()} skipped${scan.error ? ' · '+scan.error : ''}`;
  function storageRow(item, clickable) {
    const row = el('div', null, 'storage-item'), label = el(clickable ? 'button' : 'span', item.path);
    if (clickable) { label.title = 'Scan this directory'; label.onclick = action(async () => { $('scan-path').value = item.path; await api('scan', {path: item.path}); }); }
    row.append(label, el('small', bytes(item.size))); return row;
  }
  $('folders').replaceChildren(...scan.entries.map(x => storageRow(x, x.directory)));
  $('files').replaceChildren(...scan.largest.map(x => storageRow(x, false)));
}
function renderJob() {
  $('job').hidden = data.job.status === 'idle'; $('job-status').textContent = data.job.status === 'running' ? 'Working… do not close the launcher.' : 'Job finished. Review each result below.';
  $('job-results').replaceChildren(...(data.job.results || []).map(r => el('p', `${r.success ? '✓' : '×'} ${r.name}: ${r.message}`, r.success ? '' : 'failure')));
}
async function pollOnce() {
  data = await api('state'); $('connection').textContent = '● CONNECTED / 127.0.0.1';
  renderApps(); renderProcesses(); renderStorage(); renderJob();
  if (data.warnings.length) notice(data.warnings.join('\n'));
}
async function poll() { if (stopped) return; try { await pollOnce(); } catch (error) { $('connection').textContent = 'DISCONNECTED'; notice(error.message); } if (!stopped) setTimeout(poll, 2000); }
$('app-search').oninput = () => data && renderApps();
$('process-search').oninput = $('process-sort').onchange = () => data && renderProcesses();
$('pause').onclick = () => { paused = !paused; $('pause').textContent = paused ? 'Resume table' : 'Pause table'; if (data) renderProcesses(); };
$('refresh').onclick = action(() => api('refresh', {}));
$('settings').onclick = action(() => api('settings', {}));
$('scan').onclick = action(() => api('scan', {path: $('scan-path').value}));
$('cancel-scan').onclick = action(() => api('cancel-scan', {}));
$('shutdown').onclick = action(async () => { await api('shutdown', {}); stopped = true; $('connection').textContent = 'SESSION ENDED'; notice('Local server stopped. You can close this tab.'); document.querySelectorAll('button').forEach(b => b.disabled = true); });
poll();
