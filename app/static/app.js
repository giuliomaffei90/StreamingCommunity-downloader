/* StreamingCommunity Web Panel — app.js */

// ── State ──────────────────────────────────────────────────────────────────────
let currentDomain = '';
let currentVersion = '';
let currentSource = 'streamingcommunity'; // 'streamingcommunity' | 'animeunity'
let _searchResults = [];
let _jobPhases = {};      // job_id → current phase string
const _jobs = new Map();  // job_id → job dict (source of truth)
let _animeCtx = {};       // context for anime episode browser

// ── Utilities ──────────────────────────────────────────────────────────────────

function scConfirm(msg) {
  return new Promise(resolve => {
    document.getElementById('sc-confirm-msg').textContent = msg;
    const ok = document.getElementById('sc-confirm-ok');
    const cancel = document.getElementById('sc-confirm-cancel');
    function cleanup() {
      ok.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
    }
    function onOk()     { cleanup(); hideModal('sc-confirm-modal'); resolve(true); }
    function onCancel() { cleanup(); hideModal('sc-confirm-modal'); resolve(false); }
    ok.addEventListener('click', onOk, {once:true});
    cancel.addEventListener('click', onCancel, {once:true});
    showModal('sc-confirm-modal');
  });
}

function scPrompt(msg, defaultVal='') {
  return new Promise(resolve => {
    document.getElementById('sc-prompt-msg').textContent = msg;
    const input = document.getElementById('sc-prompt-input');
    input.value = defaultVal;
    const ok = document.getElementById('sc-prompt-ok');
    const cancel = document.getElementById('sc-prompt-cancel');
    function cleanup() {
      ok.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
      input.removeEventListener('keydown', onKey);
    }
    function onOk()     { cleanup(); hideModal('sc-prompt-modal'); resolve(input.value); }
    function onCancel() { cleanup(); hideModal('sc-prompt-modal'); resolve(null); }
    function onKey(e)   { if (e.key === 'Enter') onOk(); }
    ok.addEventListener('click', onOk, {once:true});
    cancel.addEventListener('click', onCancel, {once:true});
    input.addEventListener('keydown', onKey);
    showModal('sc-prompt-modal');
    setTimeout(() => input.focus(), 50);
  });
}

function escapeHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function formatSize(bytes) {
  if (bytes == null) return '—';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
  if (bytes < 1073741824) return (bytes/1048576).toFixed(1) + ' MB';
  return (bytes/1073741824).toFixed(2) + ' GB';
}
function fmtEta(sec) {
  if (sec == null || sec <= 0) return '';
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m < 60) return `${m}m ${s.toString().padStart(2,'0')}s`;
  const h = Math.floor(m / 60), rm = m % 60;
  return `${h}h ${rm}m`;
}
function itemYear(item) {
  const d = item.release_date || item.last_air_date || '';
  return d ? d.slice(0, 4) : null;
}
async function safeJson(res) {
  const text = await res.text();
  try { return JSON.parse(text); }
  catch { throw new Error(`HTTP ${res.status}: ${text.slice(0,120)}`); }
}

// ── Modal helpers ──────────────────────────────────────────────────────────────

function showModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = 'block';
  el.classList.add('show');
  el.setAttribute('aria-modal', 'true');
  el.removeAttribute('aria-hidden');
  if (!document.querySelector('.modal-backdrop')) {
    const bd = document.createElement('div');
    bd.className = 'modal-backdrop fade show';
    document.body.appendChild(bd);
  }
  document.body.classList.add('modal-open');
}
function hideModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = 'none';
  el.classList.remove('show');
  el.setAttribute('aria-hidden', 'true');
  el.removeAttribute('aria-modal');
  document.querySelector('.modal-backdrop')?.remove();
  document.body.classList.remove('modal-open');
}
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal') && e.target.classList.contains('show'))
    hideModal(e.target.id);
  if (e.target.closest('[data-bs-dismiss="modal"]')) {
    const modal = e.target.closest('.modal');
    if (modal) hideModal(modal.id);
  }
});

// ── Toast ──────────────────────────────────────────────────────────────────────

function showToast(message, type = 'info') {
  const colors = { success:'bg-success', danger:'bg-danger', info:'bg-info', warning:'bg-warning' };
  const toast = document.createElement('div');
  toast.style.cssText = 'position:fixed;bottom:1rem;right:1rem;left:auto;z-index:9999;min-width:220px;max-width:calc(100vw - 2rem)';
  toast.innerHTML = `<div class="alert ${colors[type]||'bg-info'} alert-dismissible text-white mb-0 shadow" role="alert">
    ${escapeHtml(message)}
    <button type="button" class="btn-close btn-close-white" onclick="this.closest('.alert').parentElement.remove()"></button>
  </div>`;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ── Init ───────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  await loadDomainStatus();
  loadDomainCandidate();
  await Promise.all([loadDownloadDir(), loadPerfSettings()]);
  connectGlobalStream();
  setupFileManager();
  setupSettingsTabs();
  setupSearchDebounce();
  showPage('search');
});

// ── Domain ─────────────────────────────────────────────────────────────────────

async function loadDomainStatus() {
  try {
    const res = await fetch('/api/domain');
    const data = await safeJson(res);
    currentDomain = data.domain || '';
    currentVersion = data.version || '';
    const badge = document.getElementById('domain-badge');
    if (data.valid) {
      badge.className = 'badge bg-success';
      badge.textContent = currentDomain;
    } else {
      badge.className = 'badge bg-danger';
      badge.textContent = 'Domain non configurato';
      openSettings();
    }
  } catch(e) { console.error('loadDomainStatus:', e); }
}

// ── Source domain moved ────────────────────────────────────────────────────────
//
// The panel proposes; a person applies. See app/core/domain_recovery.py for why
// adopting a domain published on a page we do not control is not something that
// happens quietly.

let _domainCandidate = null;

async function loadDomainCandidate() {
  try {
    const res = await fetch('/api/domain/candidate');
    if (!res.ok) return;
    const data = await safeJson(res);
    _domainCandidate = data.candidate || null;
    renderDomainBanner();
  } catch (e) { /* a missing banner is not worth a console error */ }
}

function renderDomainBanner() {
  const banner = document.getElementById('domain-banner');
  if (!banner) return;
  if (!_domainCandidate) { banner.style.display = 'none'; return; }
  document.getElementById('domain-banner-host').textContent = _domainCandidate.host;
  banner.style.display = '';
}

async function applyDomainCandidate() {
  if (!_domainCandidate) return;
  const btn = document.getElementById('domain-banner-apply');
  btn.disabled = true;
  try {
    const res = await fetch('/api/domain/candidate/apply', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      // Echoed back as a confirmation token: the server compares it with what
      // it found and refuses a mismatch rather than trusting this value.
      body: JSON.stringify({domain: _domainCandidate.host}),
    });
    if (res.ok) {
      const data = await safeJson(res);
      showToast(`Dominio aggiornato: ${data.domain}`, 'success');
      _domainCandidate = null;
      renderDomainBanner();
      await loadDomainStatus();
    } else {
      const d = await safeJson(res);
      showToast(d.detail || 'Impossibile applicare il dominio', 'danger');
    }
  } catch (e) { showToast('Errore di rete', 'danger'); }
  finally { btn.disabled = false; }
}

async function dismissDomainCandidate() {
  if (!await scConfirm('Ignorare il dominio trovato? Il pannello resta sul dominio attuale.')) return;
  try {
    await fetch('/api/domain/candidate/dismiss', {method: 'POST'});
  } catch (e) { /* clearing a banner is best effort */ }
  _domainCandidate = null;
  renderDomainBanner();
}

// ── Source selector ────────────────────────────────────────────────────────────

function setSource(src) {
  currentSource = src;
  document.getElementById('src-sc').classList.toggle('active', src === 'streamingcommunity');
  document.getElementById('src-au').classList.toggle('active', src === 'animeunity');
  const input = document.getElementById('search-input');
  if (input) input.placeholder = src === 'animeunity' ? 'Cerca anime...' : 'Film, serie TV...';
  document.getElementById('search-results').innerHTML = '';
}

// ── Navigation ─────────────────────────────────────────────────────────────────

function showPage(page) {
  // Close mobile menu if open
  const mobileMenu = document.getElementById('sidebar-menu');
  if (mobileMenu && mobileMenu.classList.contains('show')) {
    mobileMenu.classList.remove('show');
  }
  ['search','downloads','files'].forEach(p => {
    const el = document.getElementById(`page-${p}`);
    if (el) el.style.display = p === page ? '' : 'none';
  });
  document.getElementById('page-title').textContent = {
    search:'Cerca', downloads:'Download', files:'File',
  }[page] || 'Cerca';
  document.querySelectorAll('.nav-link[data-page]').forEach(el =>
    el.classList.toggle('active', el.dataset.page === page));
  if (page === 'downloads') refreshJobs();
  if (page === 'files') loadFiles();
}

// ── Settings ───────────────────────────────────────────────────────────────────

// Every section in the settings modal saves itself, so each one reports into its
// own feedback line rather than sharing one status area.
const _SETTINGS_FEEDBACK_IDS = [
  'domain-feedback', 'download-dir-feedback', 'perf-settings-feedback',
  'domain-recovery-feedback', 'naming-feedback',
];

// FastAPI answers a validation failure with an *array* of error objects, so the
// `data.detail || 'Errore'` idiom used throughout renders "[object Object]".
function _detailText(data) {
  const detail = data && data.detail;
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(e => (e && (e.msg || e.message)) || '').filter(Boolean).join('; ');
  }
  return String(detail);
}

function _feedback(id, message = '', kind = 'muted') {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = message;
  el.className = 'form-text' + (message ? ` text-${kind}` : '');
}

// Each tab fetches its own data the first time it is opened, so opening the
// modal no longer waits on the slowest section (disk usage stats every library
// path, on an NFS mount that can be asleep).
const _SETTINGS_TAB_LOADERS = {
  sorgente: () => loadDomainRecoverySettings(),
  nomi: () => loadNamingTemplates(),
  download: () => Promise.all([loadDownloadDir(), loadPerfSettings()]),
};

// Two panes read the same endpoint. Shared per modal-open so switching between
// them does not fetch it twice; cleared alongside _settingsLoaded.
let _appSettingsPromise = null;

function _loadAppSettings() {
  if (!_appSettingsPromise) {
    _appSettingsPromise = fetch('/api/domain/settings')
      .then(res => (res.ok ? safeJson(res) : null))
      .catch(() => null);
  }
  return _appSettingsPromise;
}

// Tabs whose panes only talk to MANAGE_SETTINGS endpoints: without it they would
// render as empty panes fed by 403s.
let _settingsTab = 'sorgente';
const _settingsLoaded = new Set();

function setupSettingsTabs() {
  const tabs = document.getElementById('settings-tabs');
  if (!tabs) return;
  tabs.addEventListener('click', (e) => {
    const link = e.target.closest('[data-settings-tab]');
    if (!link) return;
    e.preventDefault();
    switchSettingsTab(link.dataset.settingsTab);
  });
}

function _visibleSettingsTabs() {
  return [...document.querySelectorAll('#settings-tabs [data-settings-tab]')]
    .filter(a => a.closest('.nav-item').style.display !== 'none')
    .map(a => a.dataset.settingsTab);
}

async function switchSettingsTab(name) {
  document.querySelectorAll('#settings-tabs [data-settings-tab]').forEach(a =>
    a.classList.toggle('active', a.dataset.settingsTab === name));
  document.querySelectorAll('[data-settings-pane]').forEach(pane => {
    pane.style.display = pane.dataset.settingsPane === name ? '' : 'none';
  });
  _settingsTab = name;
  const body = document.querySelector('#settings-modal .modal-body');
  if (body) body.scrollTop = 0;

  // Marked before awaiting, so a double click cannot fire two fetches.
  if (!_settingsLoaded.has(name)) {
    _settingsLoaded.add(name);
    await _SETTINGS_TAB_LOADERS[name]?.();
  }
}

async function openSettings() {
  document.getElementById('domain-input').value = currentDomain;
  _SETTINGS_FEEDBACK_IDS.forEach(id => _feedback(id));

  // Cleared on every open so a value changed elsewhere is picked up; within one
  // open, moving between tabs does not refetch.
  _settingsLoaded.clear();
  _appSettingsPromise = null;
  showModal('settings-modal');
  const tabs = _visibleSettingsTabs();
  await switchSettingsTab(tabs.includes('sorgente') ? 'sorgente' : tabs[0]);
}

// ── Spazio disco ─────────────────────────────────────────────────────────────

// formatSize() stops at GB and is used for file rows; volumes are routinely in
// terabytes, so the disk readout gets its own scale.
function fmtBytes(bytes) {
  if (bytes == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let value = bytes, i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return `${value.toFixed(value >= 100 || i === 0 ? 0 : 1).replace('.', ',')} ${units[i]}`;
}

// Reported per volume, not per library: the three libraries are almost always
// folders on one mount, and three identical bars said nothing.
async function loadDiskUsage() {
  const el = document.getElementById('fm-disk-usage');
  if (!el) return;
  try {
    const res = await fetch('/api/files/disk-usage');
    if (!res.ok) { el.textContent = ''; return; }
    renderDiskUsage(await safeJson(res));
  } catch (e) { el.textContent = ''; }
}

function renderDiskUsage(data) {
  const el = document.getElementById('fm-disk-usage');
  if (!el) return;
  const volumes = (data && data.volumes) || [];
  if (!volumes.length) {
    el.textContent = data && data.errors && data.errors.length ? 'Spazio non leggibile' : '';
    return;
  }
  // Several distinct mounts is the unusual case; show the fullest, since that
  // is the one that will stop a download.
  const worst = volumes.reduce((a, b) => (a.free <= b.free ? a : b));
  const pct = worst.total ? Math.round((worst.used / worst.total) * 100) : 0;
  // Amber past 80%, red past 92%: at that point a 4K season may not fit.
  const color = pct >= 92 ? 'text-danger' : pct >= 80 ? 'text-warning' : '';
  const suffix = volumes.length > 1 ? ` (volume più pieno di ${volumes.length})` : '';
  el.innerHTML =
    `<i class="ti ti-database me-1"></i><span class="${color}">${fmtBytes(worst.free)} liberi` +
    `</span> su ${fmtBytes(worst.total)}${suffix}`;
  el.title = worst.paths.join('\n');
}

async function loadPerfSettings() {
  const data = await _loadAppSettings();
  if (!data) return;
  document.getElementById('setting-max-concurrent').value = data.max_concurrent_downloads ?? 3;
  document.getElementById('setting-max-workers').value = data.max_segment_workers ?? 16;
  document.getElementById('setting-transcode').checked = !!data.transcode_enabled;
}

async function loadDomainRecoverySettings() {
  const data = await _loadAppSettings();
  if (!data) return;
  document.getElementById('domain-auto-check').checked =
    data.domain_auto_check_enabled !== false;
  document.getElementById('domain-auto-apply').checked = !!data.domain_auto_apply;
  document.getElementById('domain-check-interval').value =
    data.domain_check_interval_minutes ?? 360;
}


// ── Naming templates ───────────────────────────────────────────────────────────
//
// The preview is rendered by the server, using the same engine the downloader
// uses. Reimplementing it here would give two renderers that drift, and this way
// an invalid template shows its real validation error while it is being typed.

let _namingDefaults = null;
let _namingPreviewTimer = null;

function _namingInputs() {
  return [...document.querySelectorAll('[data-naming-slot]')];
}

async function loadNamingTemplates() {
  // The defaults come first: they are what every placeholder shows, and the
  // markup's hardcoded ones are only a fallback for when this fetch fails.
  // Without this the two copies drift the day a default changes server-side.
  if (!_namingDefaults) {
    try {
      const res = await fetch('/api/domain/settings/naming-defaults');
      if (res.ok) _namingDefaults = (await safeJson(res)).templates;
    } catch (e) { /* the markup's placeholders stand in */ }
  }

  const data = await _loadAppSettings();
  const templates = (data && data.naming_templates) || {};
  _namingInputs().forEach(input => {
    const slot = input.dataset.namingSlot;
    if (_namingDefaults && _namingDefaults[slot]) input.placeholder = _namingDefaults[slot];
    // Left blank when it matches the default, so the placeholder — which *is*
    // the default — stays visible, and the field reads as "nothing changed
    // here" rather than as a value somebody chose.
    const stored = templates[slot] || '';
    input.value = stored === input.placeholder ? '' : stored;
    if (!input.dataset.wired) {
      input.addEventListener('input', scheduleNamingPreview);
      input.dataset.wired = '1';
    }
  });
  refreshNamingPreview();
}

function scheduleNamingPreview() {
  clearTimeout(_namingPreviewTimer);
  _namingPreviewTimer = setTimeout(refreshNamingPreview, 200);
}

function _collectNamingTemplates() {
  // An empty field means the default, which is what its placeholder shows. The
  // server rejects an empty template outright, so the substitution happens here
  // rather than turning a blank box into a validation error.
  const templates = {};
  _namingInputs().forEach(i => {
    templates[i.dataset.namingSlot] = i.value.trim() || i.placeholder;
  });
  return templates;
}

async function refreshNamingPreview() {
  try {
    const res = await fetch('/api/domain/settings/naming-preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({templates: _collectNamingTemplates()}),
    });
    if (!res.ok) return;
    const data = await safeJson(res);
    _namingInputs().forEach(input => {
      const slot = data.slots[input.dataset.namingSlot];
      const line = document.getElementById(`naming-preview-${input.dataset.namingSlot}`);
      if (!line || !slot) return;
      if (slot.error) {
        line.className = 'form-text text-danger';
        line.textContent = slot.error;
      } else {
        line.className = 'form-text';
        line.textContent = `Esempio: ${slot.preview}`;
      }
    });
  } catch (e) { /* previews are a convenience; saving still validates */ }
}

async function saveNamingTemplates() {
  const btn = document.getElementById('save-naming-btn');
  btn.disabled = true;
  _feedback('naming-feedback', 'Salvataggio...');
  try {
    const res = await fetch('/api/domain/settings', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({naming_templates: _collectNamingTemplates()}),
    });
    if (res.ok) {
      _feedback('naming-feedback', 'Salvato.', 'success');
      showToast('Schema dei nomi salvato', 'success');
    } else {
      const d = await safeJson(res);
      _feedback('naming-feedback', _detailText(d) || 'Errore salvataggio.', 'danger');
    }
  } catch (e) { _feedback('naming-feedback', 'Errore di rete.', 'danger'); }
  finally { btn.disabled = false; }
}

async function resetNamingTemplates() {
  if (!await scConfirm('Ripristinare lo schema dei nomi predefinito?')) return;
  // Blank means default, so restoring is emptying every field.
  _namingInputs().forEach(input => { input.value = ''; });
  refreshNamingPreview();
  _feedback('naming-feedback', 'Predefiniti ripristinati: premi Salva per applicarli.');
}



async function saveDomainRecovery() {
  const btn = document.getElementById('save-domain-recovery-btn');
  const interval = parseInt(document.getElementById('domain-check-interval').value, 10);
  if (!(interval >= 30 && interval <= 1440)) {
    _feedback('domain-recovery-feedback', 'Intervallo tra 30 e 1440 minuti.', 'danger');
    return;
  }
  const autoApply = document.getElementById('domain-auto-apply').checked;
  // Turning this on hands a page we do not control the ability to move the
  // panel's source. Worth one deliberate click.
  if (autoApply && !await scConfirm(
      'Con l\'applicazione automatica il pannello adotta il dominio trovato senza chiedere. ' +
      'Verranno accettati solo domini verificati e con un nome riconosciuto. Continuare?')) {
    return;
  }
  btn.disabled = true;
  _feedback('domain-recovery-feedback', 'Salvataggio...');
  try {
    const res = await fetch('/api/domain/settings', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        domain_auto_check_enabled: document.getElementById('domain-auto-check').checked,
        domain_auto_apply: autoApply,
        domain_check_interval_minutes: interval,
      }),
    });
    if (res.ok) {
      _feedback('domain-recovery-feedback', 'Salvato.', 'success');
      showToast('Impostazioni salvate', 'success');
    } else {
      const d = await safeJson(res);
      _feedback('domain-recovery-feedback', d.detail || 'Errore salvataggio.', 'danger');
    }
  } catch (e) { _feedback('domain-recovery-feedback', 'Errore di rete.', 'danger'); }
  finally { btn.disabled = false; }
}

async function checkDomainNow() {
  const btn = document.getElementById('domain-check-btn');
  btn.disabled = true;
  _feedback('domain-recovery-feedback', 'Controllo in corso...');
  try {
    const res = await fetch('/api/domain/check', {method: 'POST'});
    if (!res.ok) {
      const d = await safeJson(res);
      _feedback('domain-recovery-feedback', d.detail || 'Controllo fallito.', 'danger');
      return;
    }
    const data = await safeJson(res);
    if (data.applied) {
      _feedback('domain-recovery-feedback', `Applicato ${data.candidate}.`, 'success');
      await loadDomainStatus();
    } else if (data.candidate) {
      _feedback('domain-recovery-feedback', `Trovato ${data.candidate}: da applicare.`, 'success');
    } else if (data.current_ok) {
      _feedback('domain-recovery-feedback', 'Il dominio attuale risponde.', 'success');
    } else {
      // Rejections are shown rather than swallowed: a rebranded source and an
      // edited page look identical from here, and only a person can tell them
      // apart.
      const why = (data.rejected || []).map(r => `${r.host} (${r.reason})`).join(', ');
      _feedback('domain-recovery-feedback',
        why ? `Nessun dominio adottabile. Scartati: ${why}` : 'Nessun dominio trovato.',
        'danger');
    }
    await loadDomainCandidate();
  } catch (e) { _feedback('domain-recovery-feedback', 'Errore di rete.', 'danger'); }
  finally { btn.disabled = false; }
}

async function savePerfSettings() {
  const btn = document.getElementById('save-perf-btn');
  const concurrent = parseInt(document.getElementById('setting-max-concurrent').value, 10);
  const workers = parseInt(document.getElementById('setting-max-workers').value, 10);
  if (!concurrent || !workers) {
    _feedback('perf-settings-feedback', 'Valori non validi.', 'danger'); return;
  }
  btn.disabled = true;
  _feedback('perf-settings-feedback', 'Salvataggio...');
  try {
    const res = await fetch('/api/domain/settings', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        max_concurrent_downloads: concurrent,
        max_segment_workers: workers,
        transcode_enabled: document.getElementById('setting-transcode').checked,
      }),
    });
    if (res.ok) {
      _feedback('perf-settings-feedback', 'Salvato.', 'success');
      showToast('Performance salvate', 'success');
    } else {
      const d = await safeJson(res);
      _feedback('perf-settings-feedback', d.detail || 'Errore salvataggio.', 'danger');
    }
  } catch (e) { _feedback('perf-settings-feedback', 'Errore di rete.', 'danger'); }
  finally { btn.disabled = false; }
}

async function saveDomain() {
  const domain = document.getElementById('domain-input').value.trim();
  const btn = document.getElementById('save-domain-btn');
  if (!domain) { _feedback('domain-feedback', 'Inserisci un domain.', 'danger'); return; }
  btn.disabled = true;
  _feedback('domain-feedback', 'Verifica in corso...');
  try {
    const res = await fetch('/api/domain', {
      method:'PUT', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({domain}),
    });
    const data = await safeJson(res);
    if (res.ok) {
      currentDomain = data.domain; currentVersion = data.version;
      _feedback('domain-feedback', `OK — versione ${data.version}`, 'success');
      const badge = document.getElementById('domain-badge');
      badge.className = 'badge bg-success';
      badge.textContent = data.domain;
      showToast('Domain salvato', 'success');
    } else {
      _feedback('domain-feedback', data.detail || 'Errore', 'danger');
    }
  } catch(e) {
    _feedback('domain-feedback', 'Errore di rete', 'danger');
  } finally { btn.disabled = false; }
}

// ── Cartella di destinazione ───────────────────────────────────────────────────
//
// One folder, not a path per content type. The per-type version was the only
// reason the file manager and the downloads could point at different places.

async function loadDownloadDir() {
  try {
    const res = await fetch('/api/domain/download-dir');
    if (!res.ok) return;
    const data = await safeJson(res);
    const input = document.getElementById('download-dir-input');
    if (!input) return;
    input.value = data.path || '';
    // Nothing configured: show the folder actually in use as the placeholder,
    // so the empty field reads as "the default" rather than as "nowhere".
    if (data.effective) input.placeholder = data.effective;
  } catch (e) { console.error('loadDownloadDir:', e); }
}

async function browseDownloadDir() {
  const btn = document.getElementById('download-dir-browse');
  const input = document.getElementById('download-dir-input');
  if (!input) return;
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/files/pick-folder', {method: 'POST'});
    if (!res.ok) { showToast('Impossibile aprire il selettore', 'danger'); return; }
    const data = await safeJson(res);
    // A cancelled dialog answers with null: leave what was already there.
    if (data.path) input.value = data.path;
  } catch (e) {
    showToast('Errore di rete', 'danger');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function saveDownloadDir() {
  const btn = document.getElementById('save-download-dir-btn');
  const input = document.getElementById('download-dir-input');
  btn.disabled = true;
  _feedback('download-dir-feedback', 'Salvataggio...');
  try {
    const res = await fetch('/api/domain/download-dir', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: input.value.trim()}),
    });
    if (res.ok) {
      _feedback('download-dir-feedback', 'Salvato.', 'success');
      showToast('Cartella salvata', 'success');
      await loadDownloadDir();
      // The file manager is rooted at this folder, so it is now showing the
      // wrong tree until it is re-read.
      if (document.getElementById('page-files')?.style.display !== 'none') loadFiles();
    } else {
      const d = await safeJson(res);
      _feedback('download-dir-feedback', _detailText(d) || 'Errore salvataggio.', 'danger');
    }
  } catch (e) { _feedback('download-dir-feedback', 'Errore di rete.', 'danger'); }
  finally { btn.disabled = false; }
}


// ── Search ─────────────────────────────────────────────────────────────────────

let _searchAbort = null;
let _searchDebounceTimer = null;

function setupSearchDebounce() {
  const input = document.getElementById('search-input');
  if (!input) return;
  input.addEventListener('input', () => {
    clearTimeout(_searchDebounceTimer);
    const q = input.value.trim();
    if (q.length >= 3) {
      _searchDebounceTimer = setTimeout(() => doSearch(), 400);
    }
  });
}

function _showSearchSkeletons() {
  const container = document.getElementById('search-results');
  container.innerHTML = '';
  for (let i = 0; i < 6; i++) {
    const col = document.createElement('div');
    col.className = 'col-6 col-sm-4 col-md-3 col-lg-2';
    col.innerHTML = '<div class="skeleton skeleton-card"></div>';
    container.appendChild(col);
  }
}

async function doSearch() {
  const q = document.getElementById('search-input').value.trim();
  if (!q) return;
  if (!currentDomain && currentSource !== 'animeunity') { openSettings(); return; }
  // Cancel previous in-flight request
  if (_searchAbort) _searchAbort.abort();
  _searchAbort = new AbortController();
  const btn = document.getElementById('search-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Cerca';
  _showSearchSkeletons();
  try {
    const searchParams = new URLSearchParams({ q, source: currentSource });
    const res = await fetch(`/api/search?${searchParams}`, {signal: _searchAbort.signal});
    const container = document.getElementById('search-results');
    const results = await safeJson(res);
    if (!res.ok) { container.innerHTML=`<div class="col-12"><div class="alert alert-danger">${results.detail||'Errore'}</div></div>`; return; }
    if (!results.length) { container.innerHTML='<div class="col-12"><p class="text-muted">Nessun risultato.</p></div>'; return; }
    container.innerHTML = '';
    results.forEach((item, idx) => {
      const isMovie = item.type==='movie';
      const year = itemYear(item);
      const score = item.score ? parseFloat(item.score).toFixed(1) : null;
      const posterUrl = item.poster
        ? (item.poster.startsWith('http') ? item.poster : `/api/image/${item.poster}`)
        : '';
      const card = document.createElement('div');
      card.className = 'col-6 col-sm-4 col-md-3 col-lg-2';
      const posterHtml = posterUrl
        ? `<img src="${posterUrl}" alt="" onerror="this.closest('.poster-wrap').querySelector('.poster-noimg').style.display='flex';this.style.display='none'">`
        : '';
      // Movie cards carry no status ribbon: a movie can be requested again
      // freely (denied/failed/cancelled never block it), so a "richiesto" chip
      // would just read as blocked when it is not. TV and anime keep it — their
      // status is read from the grouped request rows anyway, not per-title.
      const ribbonHtml = isMovie
        ? ''
        : `<div class="status-ribbon" data-ribbon-for="${escapeHtml(String(item.id))}"></div>`;
      card.innerHTML = `
        <div class="result-card" onclick="openDetailModal(${idx})">
          <div class="poster-wrap">
            ${posterHtml}
            <div class="poster-noimg" style="${posterUrl?'display:none':''}">&#127916;</div>
            <div class="poster-overlay"></div>
            ${ribbonHtml}
            <div class="poster-play"><i class="ti ti-player-play-filled" style="font-size:16px"></i></div>
          </div>
          <div class="card-meta">
            <div class="card-title-text" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
            <div class="card-badges">
              <span class="badge ${isMovie?'bg-blue-lt':'bg-green-lt'}">${isMovie?'Film':'TV'}</span>
              ${score?`<span class="badge bg-yellow-lt">★ ${score}</span>`:''}
              ${year?`<span style="font-size:10px;color:var(--text-muted)">${year}</span>`:''}
            </div>
          </div>
        </div>`;
      container.appendChild(card);
    });
    _searchResults = results;
  } catch(e) {
    if (e.name === 'AbortError') return; // cancelled by new search
    const container = document.getElementById('search-results');
    container.innerHTML=`<div class="col-12"><div class="alert alert-danger">Errore: ${escapeHtml(e.message)}</div></div>`;
  } finally {
    btn.disabled=false; btn.innerHTML='<i class="ti ti-search me-1"></i>Cerca';
  }
}

// ── Detail Modal ───────────────────────────────────────────────────────────────

const LANG_NAMES = {
  ita:'Italiano', eng:'English', fra:'Français', spa:'Español',
  deu:'Deutsch', por:'Português', jpn:'日本語', zho:'中文',
  ara:'العربية', rus:'Русский', kor:'한국어',
};
const langName = c => LANG_NAMES[c] || c;

function _getLangSelections() {
  const audio = [...document.querySelectorAll('.lang-audio-check:checked')].map(cb => cb.value);
  const subs  = [...document.querySelectorAll('.lang-sub-check:checked')].map(cb => cb.value);
  return {
    audio: audio.length ? audio : ['ita'],
    subs:  subs,
  };
}

// Guards against a stale response painting over a newer one: open a title, close
// it, open another before the first reply lands, and the first one used to win.
let _detailToken = 0;
// The two fetches of one open land in either order, and each needs something
// the other has: the failure message depends on whether a fallback exists.
let _detailState = { langsError: null };

function _resetDetailExtras() {
  _detailState = { langsError: null };
  document.getElementById('detail-backdrop').style.display = 'none';
  const plot = document.getElementById('detail-plot');
  plot.textContent = ''; plot.style.display = 'none';
  const genres = document.getElementById('detail-genres');
  genres.innerHTML = ''; genres.style.display = 'none';
  document.getElementById('detail-trailer-btn').style.display = 'none';
  // The class is rewritten further down on every open; the tooltip is not, so
  // a stale warning would follow the modal onto the next title.
  document.getElementById('detail-action-btn').title = '';
}

function renderTitleMetadata(meta) {
  if (!meta) return;

  if (meta.backdrop) {
    const backdrop = document.getElementById('detail-backdrop');
    backdrop.style.backgroundImage = `url("${encodeURI(meta.backdrop)}")`;
    backdrop.style.display = '';
  }
  if (meta.plot) {
    const plot = document.getElementById('detail-plot');
    plot.textContent = meta.plot;
    plot.style.display = '';
  }
  if (meta.genres?.length) {
    const genres = document.getElementById('detail-genres');
    genres.innerHTML = meta.genres.slice(0, 4)
      .map(g => `<span class="badge bg-secondary-lt">${escapeHtml(g)}</span>`).join('');
    genres.style.display = '';
  }
  if (meta.trailer_url) {
    const trailer = document.getElementById('detail-trailer-btn');
    trailer.href = meta.trailer_url;
    trailer.style.display = '';
  }
  // The source carries no rating for many titles; TMDB's fills that gap rather
  // than replacing a score already on screen.
  const scoreEl = document.getElementById('detail-score');
  if (meta.rating && !scoreEl.innerHTML) {
    scoreEl.innerHTML =
      `<span class="badge bg-yellow-lt fs-5"><i class="ti ti-star-filled me-1"></i>${meta.rating}</span>`;
  }
}

function renderDetailSourceError(detail) {
  _detailState.langsError = detail;
  const langsEl = document.getElementById('detail-langs');
  const trimmed = (detail || '').slice(0, 140);
  // No alternative provider is registered (see app/core/_shared.py), so this
  // must not promise one. Saying "the alternative source will be tried" when
  // nothing will be tried is worse than the silence this replaced.
  langsEl.innerHTML =
    `<div class="alert bg-warning py-1 px-2 mb-0 small" style="border-color:#e6a23c">
       <i class="ti ti-alert-triangle me-1"></i>
       Sorgente non raggiungibile per questo titolo. Le lingue non sono selezionabili
       e il download potrebbe fallire.
       ${trimmed ? `<div class="text-muted mt-1">${escapeHtml(trimmed)}</div>` : ''}
     </div>`;

  // Deliberately still enabled. The fallback may well work, and disabling the
  // button removes the one path that might; saying so is the honest version of
  // taking the choice away.
  const btn = document.getElementById('detail-action-btn');
  if (btn) {
    // The title goes on regardless: "Richiedi" is already btn-warning for its
    // own reason, and the tooltip is what actually carries the warning.
    btn.title = hasFallback
      ? 'La sorgente principale non risponde: verr\u00e0 tentata quella alternativa.'
      : 'La sorgente non risponde: il download potrebbe fallire.';
    if (!btn.className.includes('btn-warning')) btn.className = 'btn btn-warning';
  }
}

function openDetailModal(idx) {
  const item = _searchResults[idx];
  if (!item) return;
  // The modal is reused, so anything filled in asynchronously has to be cleared
  // first — a plot left over from the previous title under a new heading reads
  // as fact — and late responses have to be able to tell they are late.
  const token = ++_detailToken;
  _resetDetailExtras();
  const isAnime = item.type === 'anime';
  const isMovie = item.type === 'movie';
  const year = itemYear(item);
  const score = item.score ? parseFloat(item.score).toFixed(1) : null;
  const posterUrl = item.poster
    ? (item.poster.startsWith('http') ? item.poster : `/api/image/${item.poster}`)
    : '';

  const poster = document.getElementById('detail-poster');
  if (posterUrl) { poster.src=posterUrl; poster.style.display=''; poster.onerror=()=>poster.style.display='none'; }
  else poster.style.display='none';

  document.getElementById('detail-title').textContent = item.name;
  const tb = document.getElementById('detail-type-badge');
  if (isAnime) { tb.className='badge me-1 bg-purple-lt'; tb.textContent='Anime'; }
  else if (isMovie) { tb.className='badge me-1 bg-blue-lt'; tb.textContent='Film'; }
  else { tb.className='badge me-1 bg-green-lt'; tb.textContent='Serie TV'; }
  const ab = document.getElementById('detail-age-badge');
  if (item.age) { ab.textContent=`${item.age}+`; ab.style.display=''; } else ab.style.display='none';

  const meta = [];
  if (year) meta.push(year);
  if (isAnime && item.episodes_count) meta.push(`${item.episodes_count} episodi`);
  else if (!isMovie && item.seasons_count) meta.push(`${item.seasons_count} stagion${item.seasons_count===1?'e':'i'}`);
  document.getElementById('detail-meta').textContent = meta.join(' · ');
  document.getElementById('detail-score').innerHTML = score
    ? `<span class="badge bg-yellow-lt fs-5"><i class="ti ti-star-filled me-1"></i>${score}</span>` : '';

  const scheduleWrap = document.getElementById('detail-schedule-wrap');
  const scheduledAtInput = document.getElementById('detail-scheduled-at');
  scheduledAtInput.value = '';
  // Scheduling a download is part of the download privilege; a requester picks
  // tracks and the approver decides when it runs.
  scheduleWrap.style.display = '';

  const requestOnly = false;
  const btn = document.getElementById('detail-action-btn');
  const readAt = () => (scheduledAtInput.value)
    ? new Date(scheduledAtInput.value).toISOString() : null;

  if (isAnime) {
    btn.className='btn btn-success'; btn.innerHTML='<i class="ti ti-list me-1"></i>Episodi';
    btn.onclick = () => {
      const { audio, subs } = _getLangSelections();
      hideModal('detail-modal');
      openAnimeBrowser(item.id, item.name, item.type, year, readAt(), audio, subs);
    };
  } else if (isMovie) {
    btn.className = requestOnly ? 'btn btn-warning' : 'btn btn-primary';
    btn.innerHTML = requestOnly
      ? '<i class="ti ti-send me-1"></i>Richiedi'
      : '<i class="ti ti-download me-1"></i>Scarica';
    btn.onclick = () => {
      const { audio, subs } = _getLangSelections();
      hideModal('detail-modal');
      startFilmDownload(item.id, item.name, year, readAt(), audio, subs, item.poster);
    };
  } else {
    btn.className='btn btn-success'; btn.innerHTML='<i class="ti ti-list me-1"></i>Episodi';
    btn.onclick = () => {
      const { audio, subs } = _getLangSelections();
      hideModal('detail-modal');
      openEpisodeBrowser(item.id, item.name, item.slug, year, readAt(), audio, subs, item.poster);
    };
  }

  const langsEl = document.getElementById('detail-langs');
  if (isAnime) {
    langsEl.innerHTML = '';
    showModal('detail-modal');
    return;
  }

  langsEl.innerHTML='<span class="spinner-border spinner-border-sm me-1"></span>Caricamento lingue...';
  showModal('detail-modal');

  const p = new URLSearchParams({ type:isMovie?'movie':'tv', slug:item.slug||'', version:currentVersion||'' });

  // Independent of the languages call and started alongside it: one is metadata,
  // the other reaches the stream host, and neither should wait on the other.
  fetch(`/api/metadata/${isMovie ? 'movie' : 'tv'}/${item.id}?${p}`)
    .then(r => r.ok ? r.json() : null)
    .then(meta => { if (token === _detailToken) renderTitleMetadata(meta); })
    .catch(() => { /* the modal simply stays as it was */ });

  fetch(`/api/search/languages/${item.id}?${p}`)
    .then(async r => {
      if (r.ok) return r.json();
      // Used to be swallowed: no chips, no explanation, and a download button
      // that looked entirely fine.
      const body = await safeJson(r).catch(() => ({}));
      throw new Error(body.detail || `HTTP ${r.status}`);
    })
    .then(info => {
      if (token !== _detailToken) return;
      if (!info) { langsEl.innerHTML=''; return; }
      let html='';
      if (info.audio?.length) {
        const audioHtml = info.audio.map(c => {
          const checked = (c === 'ita' || (info.audio.length === 1)) ? 'checked' : '';
          return `<label class="me-2 mb-1" style="cursor:pointer"><input type="checkbox" class="lang-audio-check me-1" value="${escapeHtml(c)}" ${checked}><span class="badge bg-blue-lt">${langName(c)}</span></label>`;
        }).join('');
        html+=`<div class="mb-1"><span class="text-muted me-1"><i class="ti ti-volume ti-sm"></i> Audio:</span>${audioHtml}</div>`;
      } else {
        html+=`<div class="mb-1"><span class="text-muted me-1"><i class="ti ti-volume ti-sm"></i> Audio:</span><span class="text-muted fst-italic">originale</span></div>`;
      }
      if (info.subtitles?.length) {
        const subHtml = info.subtitles.map(c => {
          const checked = (c === 'ita' || c === 'eng') ? 'checked' : '';
          return `<label class="me-2 mb-1" style="cursor:pointer"><input type="checkbox" class="lang-sub-check me-1" value="${escapeHtml(c)}" ${checked}><span class="badge bg-teal-lt">${langName(c)}</span></label>`;
        }).join('');
        html+=`<div><span class="text-muted me-1"><i class="ti ti-subtitles ti-sm"></i> Sub:</span>${subHtml}</div>`;
      }
      langsEl.innerHTML=html;
    })
    .catch(err => {
      if (token !== _detailToken) return;
      renderDetailSourceError(err && err.message);
    });
}

// ── Film download ──────────────────────────────────────────────────────────────

async function startFilmDownload(id, title, year=null, scheduledAt=null, audioLangs=null, subLangs=null, poster=null) {
  try {
    const endpoint = scheduledAt ? '/api/download/schedule/film' : '/api/download/film';
    const body = {
      id, title, year,
      audio_languages: audioLangs || ['ita'],
      subtitle_languages: subLangs || ['ita', 'eng'],
    };
    if (scheduledAt) body.scheduled_at = scheduledAt;
    const res = await fetch(endpoint, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    const data = await safeJson(res);
    if (res.ok) {
      const msg = scheduledAt
        ? `Programmato: ${title} — ${new Date(scheduledAt).toLocaleString('it-IT')}`
        : `Download avviato: ${title}`;
      showToast(msg, 'success');
      showPage('downloads');
    } else showToast(data.detail||'Errore','danger');
  } catch(e) { showToast('Errore di rete','danger'); }
}

// ── Episode Browser ────────────────────────────────────────────────────────────

let _epCtx = {};

async function openEpisodeBrowser(tvId, tvName, slug, year=null, scheduledAt=null, audioLangs=null, subLangs=null, poster=null) {
  _epCtx = { tvId, tvName, slug, year, scheduledAt, token:null, episodes:[], currentSeason:null, poster,
    audioLangs: audioLangs || ['ita'], subLangs: subLangs || ['ita', 'eng'] };
  document.getElementById('episode-modal-title').textContent = tvName;
  document.getElementById('season-tabs-wrap').style.display='none';
  document.getElementById('dl-whole-series-btn').style.display='none';
  document.getElementById('episode-modal-body').innerHTML =
    '<div class="text-center py-4"><div class="spinner-border text-primary" role="status"></div></div>';
  showModal('episode-modal');

  try {
    const [tokenData, seasonsData] = await Promise.all([
      fetch(`/api/tv/${tvId}/token`).then(r=>r.json()),
      fetch(`/api/tv/${tvId}/seasons?slug=${encodeURIComponent(slug)}&version=${encodeURIComponent(currentVersion)}`).then(r=>r.json()),
    ]);
    _epCtx.token = tokenData.token;
    _epCtx.seasonsCount = seasonsData.seasons_count;
    renderSeasonTabs(seasonsData.seasons_count);
    loadSeason(1);
  } catch(e) {
    document.getElementById('episode-modal-body').innerHTML=`<div class="alert alert-danger">Errore: ${escapeHtml(e.message)}</div>`;
  }
}

function renderSeasonTabs(count) {
  const tabs = document.getElementById('season-tabs');
  tabs.innerHTML='';
  for (let s=1; s<=count; s++) {
    const li=document.createElement('li');
    li.className='nav-item';
    li.innerHTML=`<a class="nav-link${s===1?' active':''}" href="#" data-season="${s}">S${s}</a>`;
    li.querySelector('a').addEventListener('click', (e)=>{
      e.preventDefault();
      tabs.querySelectorAll('.nav-link').forEach(a=>a.classList.remove('active'));
      e.target.classList.add('active');
      loadSeason(s);
    });
    tabs.appendChild(li);
  }
  const wrap = document.getElementById('season-tabs-wrap');
  wrap.style.display = 'flex';
  const dlAllBtn = document.getElementById('dl-whole-series-btn');
  dlAllBtn.style.display = count > 1 ? '' : 'none';
}

async function loadSeason(season) {
  const { tvId, slug, token } = _epCtx;
  const container = document.getElementById('episode-modal-body');
  container.innerHTML='<div class="text-center py-3"><div class="spinner-border text-primary" role="status"></div></div>';
  try {
    const res = await fetch(`/api/tv/${tvId}/seasons/${season}/episodes?slug=${encodeURIComponent(slug)}&version=${encodeURIComponent(currentVersion)}&token=${encodeURIComponent(token)}`);
    const eps = await safeJson(res);
    if (!res.ok) { container.innerHTML=`<div class="alert alert-danger">${escapeHtml(eps.detail||'Errore caricamento episodi')}</div>`; return; }
    if (!Array.isArray(eps)) { container.innerHTML=`<div class="alert alert-danger">Risposta non valida dal server</div>`; return; }
    _epCtx.episodes=eps; _epCtx.currentSeason=season;

    const rows = eps.map((ep, idx) => `
      <tr>
        <td class="text-muted w-1 text-nowrap">${ep.n}</td>
        <td>${escapeHtml(ep.name)}</td>
        <td class="w-1">
          <button class="btn btn-sm btn-primary" onclick="startEpisodeDownload(${idx})" title="Scarica">
            <i class="ti ti-download"></i>
          </button>
        </td>
      </tr>`).join('');

    container.innerHTML=`
      <div class="d-flex align-items-center justify-content-between mb-2">
        <span class="text-muted small">${eps.length} episodi</span>
        <button class="btn btn-sm btn-outline-success" onclick="downloadWholeSeason(${season})">
          <i class="ti ti-download me-1"></i>Tutta la stagione
        </button>
      </div>
      <div class="table-responsive" style="max-height:380px;overflow-y:auto">
        <table class="table table-sm table-hover">
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  } catch(e) {
    container.innerHTML=`<div class="alert alert-danger">Errore: ${escapeHtml(e.message)}</div>`;
  }
}

async function startEpisodeDownload(epIndex) {
  const { tvId, tvName, slug, year, scheduledAt, token, episodes, currentSeason, audioLangs, subLangs, poster } = _epCtx;
  const ep = episodes[epIndex];
  const label = `${tvName} S${String(currentSeason).padStart(2,'0')}E${String(ep.n).padStart(2,'0')}`;

  const endpoint = scheduledAt ? '/api/download/schedule/episode' : '/api/download/episode';
  const body = {
    tv_id: tvId, eps: episodes, ep_index: epIndex, token,
    tv_name: tvName, season: currentSeason, year,
    audio_languages: audioLangs || ['ita'],
    subtitle_languages: subLangs || ['ita', 'eng'],
  };
  if (scheduledAt) body.scheduled_at = scheduledAt;
  try {
    const res = await fetch(endpoint, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    const data = await safeJson(res);
    if (res.ok) showToast(scheduledAt ? `Programmato: ${label}` : `In coda: ${label}`, 'success');
    else showToast(data.detail||'Errore','danger');
  } catch(e) { showToast('Errore di rete','danger'); }
}

// Whole seasons and whole series are one call: the server lists the episodes
// itself and queues them as a batch. That is also what lets it report the season
// once at the end instead of pinging for every episode.
async function _startBatch(path, body, modalId) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await safeJson(res);
  if (!res.ok) {
    showToast(data.detail || 'Errore avviando i download', 'danger');
    return false;
  }
  showToast(
    body.scheduled_at ? `${data.count} episodi programmati` : `${data.count} episodi in coda`,
    'success',
  );
  hideModal(modalId);
  showPage('downloads');
  return true;
}

async function downloadWholeSeason(season) {
  const { tvId, slug, tvName, year, episodes, scheduledAt, audioLangs, subLangs } = _epCtx;
  const label = scheduledAt ? 'Programmare' : 'Aggiungere alla coda';
  if (!await scConfirm(`${label} tutti i ${episodes.length} episodi della stagione ${season}?`)) return;
  await _startBatch('/api/download/season', {
    tv_id: tvId, slug, tv_name: tvName, season, year,
    audio_languages: audioLangs, subtitle_languages: subLangs,
    scheduled_at: scheduledAt || null,
  }, 'episode-modal');
}

async function downloadWholeSeries() {
  const { tvId, slug, tvName, year, scheduledAt, seasonsCount, audioLangs, subLangs } = _epCtx;
  const label = scheduledAt ? 'Programmare' : 'Aggiungere alla coda';
  if (!await scConfirm(`${label} tutte le ${seasonsCount} stagioni?`)) return;
  await _startBatch('/api/download/series', {
    tv_id: tvId, slug, tv_name: tvName, year,
    audio_languages: audioLangs, subtitle_languages: subLangs,
    scheduled_at: scheduledAt || null,
  }, 'episode-modal');
}

// ── Anime Browser (AnimeUnity) ─────────────────────────────────────────────────

async function openAnimeBrowser(animeId, animeName, animeType, animeYear = null, scheduledAt = null, audioLangs = null, subLangs = null) {
  // Auto-detect if film (1 episode) but allow user override
  const isAutoFilm = _searchResults.find(r => r.id === animeId)?.episodes_count === 1;
  const effectiveType = (isAutoFilm && animeType === 'anime') ? 'movie' : animeType;

  _animeCtx = { animeId, animeName, animeType: effectiveType, animeYear, scheduledAt, episodes: [], isAutoFilm,
    audioLangs: audioLangs || ['ita'], subLangs: subLangs || ['ita', 'eng'] };
  document.getElementById('anime-modal-title').textContent = animeName;
  document.getElementById('anime-modal-body').innerHTML =
    '<div class="text-center py-4"><div class="spinner-border text-primary" role="status"></div></div>';
  showModal('anime-modal');

  try {
    const res = await fetch(`/api/anime/${encodeURIComponent(animeId)}/episodes`);
    const episodes = await safeJson(res);
    if (!res.ok) throw new Error(episodes.detail || 'Errore');
    _animeCtx.episodes = episodes;

    if (!episodes.length) {
      document.getElementById('anime-modal-body').innerHTML =
        '<p class="text-muted">Nessun episodio trovato.</p>';
      return;
    }

    const rows = episodes.map((ep, idx) => {
      let epNum = ep.number;
      try { epNum = String(parseFloat(ep.number)); } catch(e) {}
      // If only one episode and it's auto-detected as film, don't show as series
      if (_animeCtx.isAutoFilm && episodes.length === 1) {
        return `
          <tr>
            <td class="text-muted w-1 text-nowrap">Film</td>
            <td class="text-muted" style="font-size:12px">1 episodio</td>
            <td class="w-1">
              <button class="btn btn-sm btn-primary" onclick="startAnimeDownload(${idx})" title="Scarica">
                <i class="ti ti-download"></i>
              </button>
            </td>
          </tr>`;
      }
      return `
        <tr>
          <td class="text-muted w-1 text-nowrap">E${epNum}</td>
          <td class="text-muted" style="font-size:12px">ep. ${epNum}</td>
          <td class="w-1">
            <button class="btn btn-sm btn-primary" onclick="startAnimeDownload(${idx})" title="Scarica">
              <i class="ti ti-download"></i>
            </button>
          </td>
        </tr>`;
    }).join('');

    let typeToggle = '';
    if (_animeCtx.isAutoFilm) {
      const currentType = _animeCtx.animeType === 'movie' ? 'Film' : 'Serie';
      typeToggle = `
        <div class="mb-2 d-flex align-items-center gap-2">
          <span class="text-muted small">Tipo:</span>
          <button class="btn btn-sm ${_animeCtx.animeType === 'movie' ? 'btn-primary' : 'btn-outline-secondary'}"
                  onclick="toggleAnimeType('movie')" title="Film">
            <i class="ti ti-ticket me-1"></i>Film
          </button>
          <button class="btn btn-sm ${_animeCtx.animeType === 'tv' ? 'btn-primary' : 'btn-outline-secondary'}"
                  onclick="toggleAnimeType('tv')" title="Serie">
            <i class="ti ti-list me-1"></i>Serie
          </button>
        </div>`;
    }

    document.getElementById('anime-modal-body').innerHTML = `
      ${typeToggle}
      <div class="d-flex align-items-center justify-content-between mb-2">
        <span class="text-muted small">${episodes.length} episodi</span>
        <button class="btn btn-sm btn-outline-success" onclick="downloadAllAnime()">
          <i class="ti ti-download me-1"></i>Scarica tutti
        </button>
      </div>
      <div class="table-responsive" style="max-height:380px;overflow-y:auto">
        <table class="table table-sm table-hover">
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  } catch(e) {
    document.getElementById('anime-modal-body').innerHTML =
      `<div class="alert alert-danger">Errore: ${escapeHtml(e.message)}</div>`;
  }
}

async function startAnimeDownload(epIndex) {
  const { animeId, animeName, animeType, animeYear, scheduledAt, episodes, audioLangs, subLangs } = _animeCtx;
  const episode = episodes[epIndex];
  const label = `${animeName} E${episode.number}`;

  const endpoint = scheduledAt ? '/api/download/schedule/anime' : '/api/download/anime';
  const body = {
    anime_id: animeId, episode, anime_name: animeName, anime_type: animeType, year: animeYear,
    audio_languages: audioLangs || ['ita'],
    subtitle_languages: subLangs || ['ita', 'eng'],
  };
  if (scheduledAt) body.scheduled_at = scheduledAt;
  try {
    const res = await fetch(endpoint, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await safeJson(res);
    if (res.ok) showToast(scheduledAt ? `Programmato: ${label}` : `In coda: ${label}`, 'success');
    else showToast(data.detail || 'Errore', 'danger');
  } catch(e) { showToast('Errore di rete', 'danger'); }
}

function toggleAnimeType(newType) {
  _animeCtx.animeType = newType;
  const { animeId, animeName, animeYear, scheduledAt, audioLangs, subLangs } = _animeCtx;
  openAnimeBrowser(animeId, animeName, newType, animeYear, scheduledAt, audioLangs, subLangs);
}

async function downloadAllAnime() {
  const { animeId, animeName, animeType, animeYear, episodes, scheduledAt,
          audioLangs, subLangs } = _animeCtx;
  const label = scheduledAt ? 'Programmare' : 'Aggiungere alla coda';
  if (!await scConfirm(`${label} tutti i ${episodes.length} episodi?`)) return;
  await _startBatch('/api/download/anime-all', {
    anime_id: String(animeId), anime_name: animeName, anime_type: animeType,
    year: animeYear,
    audio_languages: audioLangs, subtitle_languages: subLangs,
    scheduled_at: scheduledAt || null,
  }, 'anime-modal');
}

// ── Global SSE stream ──────────────────────────────────────────────────────────

function connectGlobalStream() {
  const es = new EventSource('/api/progress/stream');

  es.onopen = () => {
    document.getElementById('stream-label').textContent='Live';
    document.querySelector('.stream-dot').style.background='#2fb344';
  };

  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    switch (msg.type) {
      case 'snapshot':
        _jobs.clear();
        msg.jobs.forEach(j => _jobs.set(j.job_id, j));
        renderAllJobCards();
        updateActiveBadge();
        break;
      case 'job_created':
        _jobs.set(msg.job.job_id, msg.job);
        addJobCard(msg.job);
        updateActiveBadge();
        break;
      case 'job_status':
        if (_jobs.has(msg.job_id)) {
          _jobs.get(msg.job_id).status = msg.status;
          refreshCardAppearance(msg.job_id);
          updateActiveBadge();
        }
        break;
      case 'progress':
        handleProgressEvent(msg);
        break;
      case 'status':
        handlePhaseEvent(msg.job_id, msg.phase);
        break;
      case 'done':
        handleDoneEvent(msg.job_id, msg.output_path);
        break;
      case 'error':
        handleErrorEvent(msg.job_id, msg.message);
        break;
      case 'job_retried':
        // Same job_id, so the card is replaced rather than added: the phase
        // steps and the error line have to come back empty.
        delete _jobPhases[msg.job.job_id];
        _jobs.set(msg.job.job_id, msg.job);
        const oldCard = document.getElementById(`job-card-${msg.job.job_id}`);
        if (oldCard) oldCard.outerHTML = _buildJobCard(msg.job);
        updateActiveBadge();
        break;
      case 'job_dismissed':
        _jobs.delete(msg.job_id);
        document.getElementById(`job-card-${msg.job_id}`)?.remove();
        updateActiveBadge();
        break;
      case 'domain_candidate':
        loadDomainCandidate();
        break;
      case 'notification':
        // A bare signal: the payload lives behind /api/notifications, which is
        // scoped to the caller, so a shared stream leaks nothing.
        break;
    }
  };

  es.onerror = () => {
    es.close();
    document.getElementById('stream-label').textContent='Riconnessione...';
    document.querySelector('.stream-dot').style.background='#d63939';
    setTimeout(connectGlobalStream, 3000);
  };
}

// ── Job cards ──────────────────────────────────────────────────────────────────

const PHASE_LABELS = {
  scheduled:'Programmato', queued:'In coda', running:'In corso', joining:'Finalizzazione',
  audio:'Audio', merging:'Unione', transcoding:'Ricodifica', done:'Completato',
  error:'Errore', cancelled:'Annullato',
};
const PHASE_BADGE = {
  scheduled:'bg-yellow-lt', queued:'bg-secondary-lt', running:'bg-blue-lt', joining:'bg-yellow-lt',
  audio:'bg-teal-lt', merging:'bg-purple-lt', transcoding:'bg-orange-lt', done:'bg-success-lt',
  error:'bg-danger-lt', cancelled:'bg-secondary-lt',
};
const PHASE_BAR = {
  running:'bg-blue', joining:'phase-bar-joining bg-warning',
  audio:'phase-bar-audio bg-teal', merging:'phase-bar-merging bg-purple',
  transcoding:'bg-orange',
  done:'phase-bar-done bg-success', error:'phase-bar-error bg-danger',
};
const PHASE_BORDER_MAP = {
  scheduled:'var(--yellow)', queued:'var(--text-dim)', running:'var(--blue)', joining:'var(--yellow)',
  audio:'var(--teal)', merging:'var(--purple)', done:'var(--green)',
  error:'var(--accent)', cancelled:'var(--text-dim)',
};

function _stepLabel(phase) {
  const map = { video:'Video', joining:'Join', merging:'Merge', done:'Fine', audio:'Audio' };
  if (map[phase]) return map[phase];
  if (phase && phase.startsWith('audio_')) return 'Audio ' + phase.slice(6).toUpperCase();
  return phase;
}

function _buildStepsHtml(jobId, phases, currentPhase, status) {
  if (!phases || phases.length < 2) return '';
  let activeIdx;
  if (status === 'done') {
    activeIdx = phases.length;
  } else if (status === 'queued' || status === 'scheduled') {
    activeIdx = -1;
  } else {
    const lookup = currentPhase || 'video';
    activeIdx = phases.indexOf(lookup);
    if (activeIdx < 0) activeIdx = phases.indexOf('video') >= 0 ? 0 : -1;
  }
  const items = phases.map((p, i) => {
    let cls = 'jp';
    if (activeIdx === phases.length || i < activeIdx) cls += ' complete';
    else if (i === activeIdx) cls += ' active';
    return `<span class="${cls}" data-phase="${p}">${_stepLabel(p)}</span>`;
  }).join('');
  return `<div class="job-phases" id="job-steps-${jobId}">${items}</div>`;
}

function _updateSteps(jobId, phase) {
  const job = _jobs.get(jobId);
  if (!job || !job.phases || job.phases.length < 2) return;
  const container = document.getElementById(`job-steps-${jobId}`);
  if (!container) return;
  const phases = job.phases;
  const isDone = job.status === 'done';
  const activeIdx = isDone ? phases.length : phases.indexOf(phase || 'video');
  if (activeIdx < 0) return;
  container.querySelectorAll('.jp').forEach((el, i) => {
    el.className = 'jp';
    if (activeIdx === phases.length || i < activeIdx) el.className += ' complete';
    else if (i === activeIdx) el.className += ' active';
  });
}

function _phaseLabel(phase) {
  if (!phase) return '';
  if (PHASE_LABELS[phase]) return PHASE_LABELS[phase];
  if (phase.startsWith('audio_')) return 'Audio ' + phase.slice(6).toUpperCase();
  return phase;
}
function _phaseBadge(phase) {
  if (PHASE_BADGE[phase]) return PHASE_BADGE[phase];
  if (phase && phase.startsWith('audio_')) return 'bg-teal-lt';
  return 'bg-secondary-lt';
}
function _phaseBar(phase) {
  if (PHASE_BAR[phase]) return PHASE_BAR[phase];
  if (phase && phase.startsWith('audio_')) return 'phase-bar-audio bg-teal';
  return 'bg-secondary';
}
function _phaseBorder(phase) {
  if (PHASE_BORDER_MAP[phase]) return PHASE_BORDER_MAP[phase];
  if (phase && phase.startsWith('audio_')) return 'var(--teal)';
  return 'transparent';
}

// A download that failed can be run again from the list: the panel still holds
// what it was asked to fetch, so there is nothing to look up in search again.
function _retryBtnHtml(jobId, status) {
  if (status !== 'error' && status !== 'cancelled') return '';
  return `<button class="btn btn-sm btn-outline-primary ms-1" onclick="retryJob('${jobId}')" title="Riprova">
            <i class="ti ti-refresh"></i>
          </button>`;
}

// A finished download is a file somewhere, and the panel is the only thing that
// knows where. Without this the user has to go and find it by name.
function _revealBtnHtml(jobId, status, outputPath) {
  if (status !== 'done' || !outputPath) return '';
  return `<button class="btn btn-sm btn-outline-secondary ms-1" onclick="revealFile('${jobId}')" title="Mostra nel Finder">
            <i class="ti ti-folder-search"></i>
          </button>`;
}

// Segments per second while downloading; during a transcode the same number is
// video-seconds per real second, which is the multiplier ffmpeg itself reports.
function _rateText(phase, bytesSpeed, speed) {
  if (phase === 'transcoding') return speed > 0 ? `${speed}\u00d7` : '';
  if (bytesSpeed > 0) return formatSize(bytesSpeed) + '/s';
  return speed > 0 ? `${speed} seg/s` : '';
}

function _buildJobCard(j) {
  const phase = _jobPhases[j.job_id] || j.status;
  const isActive = j.status==='running' || j.status==='queued' || j.status==='scheduled';
  const isMovie = j.type==='film';
  const isAnimeJob = j.type==='anime';
  const pct = j.progress?.pct||0;
  const barClass = _phaseBar(phase);
  const animated = isActive && j.status!=='queued' ? ' progress-bar-striped progress-bar-animated' : '';
  const barWidth = j.status==='queued' ? 0 : (j.status==='done' ? 100 : pct);
  const badgeClass = _phaseBadge(phase);
  const label = _phaseLabel(phase);
  const borderColor = _phaseBorder(phase);

  const speed = j.progress?.speed;
  const bytesSpeed = j.progress?.bytes_speed;
  const eta = j.progress?.eta;
  const speedStr = (isActive && j.status!=='queued')
    ? _rateText(phase, bytesSpeed, speed)
    : '';
  const etaStr = eta ? fmtEta(eta) : '';
  const infoStr = [speedStr, etaStr].filter(Boolean).join(' · ');

  const fireBtn = j.status === 'scheduled'
    ? `<button class="btn btn-sm btn-outline-success ms-1" onclick="fireNow('${j.job_id}')" title="Lancia subito">
         <i class="ti ti-player-play"></i>
       </button>` : '';
  const stopBtn = isActive
    ? `<button class="btn btn-sm btn-outline-danger ms-1" onclick="cancelJob('${j.job_id}')" title="Interrompi">
         <i class="ti ti-player-stop"></i>
       </button>` : '';
  const retryBtn = _retryBtnHtml(j.job_id, j.status);
  const revealBtn = _revealBtnHtml(j.job_id, j.status, j.output_path);

  const rawTs = j.scheduled_at || j.created_at;
  const dateStr = rawTs
    ? new Date(/[Z+]/.test(rawTs)?rawTs:rawTs+'Z').toLocaleString('it-IT',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})
    : '';
  const dateLabel = j.scheduled_at ? `⏰ ${dateStr}` : dateStr;

  const stepsHtml = _buildStepsHtml(j.job_id, j.phases, phase, j.status);
  return `<div class="card mb-2 job-card${j.status==='done'?' is-done':''}${j.status==='error'?' is-error':''}" id="job-card-${j.job_id}" style="border-left:3px solid ${borderColor} !important">
    <div class="card-body py-2 px-3">
      <div class="d-flex align-items-center gap-2">
        <span class="badge ${isMovie?'bg-blue-lt':isAnimeJob?'bg-purple-lt':'bg-green-lt'} flex-shrink-0">${isMovie?'Film':isAnimeJob?'Anime':'TV'}</span>
        <span class="fw-medium text-truncate flex-1" style="min-width:0" title="${escapeHtml(j.title)}">${escapeHtml(j.title)}</span>
        <span class="badge ${badgeClass} flex-shrink-0" id="job-badge-${j.job_id}">${label}</span>
        <span id="job-fire-${j.job_id}">${fireBtn}</span>
        <span id="job-reveal-${j.job_id}">${revealBtn}</span>
        <span id="job-retry-${j.job_id}">${retryBtn}</span>
        ${stopBtn ? `<span id="job-stop-${j.job_id}">${stopBtn}</span>` : `<span id="job-stop-${j.job_id}"></span>`}
      </div>
      ${stepsHtml}
      <div class="progress my-1" style="height:5px">
        <div class="progress-bar ${barClass}${animated} job-progress-bar" id="job-bar-${j.job_id}" style="width:${barWidth}%"></div>
      </div>
      <div class="d-flex justify-content-between align-items-center">
        <small class="text-muted" id="job-info-${j.job_id}">${infoStr || (j.status==='error' ? escapeHtml(j.error||'Errore') : (j.status==='done'?'Completato':''))}</small>
        <small class="text-muted">${dateLabel}</small>
      </div>
    </div>
  </div>`;
}

function renderAllJobCards() {
  const container = document.getElementById('jobs-container');
  const empty = document.getElementById('jobs-empty');
  if (!_jobs.size) {
    empty.style.display=''; container.innerHTML='';
    return;
  }
  // Sort: active first, then by created_at desc
  const sorted = [..._jobs.values()].sort((a,b) => {
    const aActive = (a.status==='running'||a.status==='queued')?1:0;
    const bActive = (b.status==='running'||b.status==='queued')?1:0;
    if (aActive!==bActive) return bActive-aActive;
    return new Date(b.created_at)-new Date(a.created_at);
  });
  empty.style.display='none';
  const frag = document.createDocumentFragment();
  sorted.forEach(j => {
    const tmp = document.createElement('div');
    tmp.innerHTML = _buildJobCard(j);
    frag.appendChild(tmp.firstElementChild);
  });
  container.innerHTML = '';
  container.appendChild(frag);
  updateActiveSection();
}

function addJobCard(job) {
  const container = document.getElementById('jobs-container');
  const empty = document.getElementById('jobs-empty');
  empty.style.display='none';
  // Insert at top of container
  const tmp = document.createElement('div');
  tmp.innerHTML = _buildJobCard(job);
  container.insertBefore(tmp.firstElementChild, container.firstChild);
  updateActiveSection();
}

function refreshCardAppearance(jobId) {
  const j = _jobs.get(jobId);
  if (!j) return;
  const card = document.getElementById(`job-card-${jobId}`);
  if (!card) return;

  const phase = _jobPhases[j.job_id] || j.status;
  const isActive = j.status==='running' || j.status==='queued' || j.status==='scheduled';

  // Update card classes and border
  card.classList.toggle('is-done', j.status==='done');
  card.classList.toggle('is-error', j.status==='error');
  card.style.borderLeftColor = _phaseBorder(phase);

  // Update badge
  const badge = document.getElementById(`job-badge-${jobId}`);
  if (badge) {
    badge.className = `badge ${_phaseBadge(phase)} flex-shrink-0`;
    badge.textContent = _phaseLabel(phase);
  }

  // Update progress bar
  const bar = document.getElementById(`job-bar-${jobId}`);
  if (bar) {
    const barClass = _phaseBar(phase);
    const animated = isActive && j.status!=='queued' ? ' progress-bar-striped progress-bar-animated' : '';
    bar.className = `progress-bar ${barClass}${animated} job-progress-bar`;
    bar.style.width = (j.status==='queued' ? 0 : (j.status==='done' ? 100 : (j.progress?.pct||0))) + '%';
  }

  // Update fire/stop buttons
  const fire = document.getElementById(`job-fire-${jobId}`);
  if (fire) fire.innerHTML = j.status === 'scheduled'
    ? `<button class="btn btn-sm btn-outline-success ms-1" onclick="fireNow('${j.job_id}')" title="Lancia subito"><i class="ti ti-player-play"></i></button>`
    : '';
  const stop = document.getElementById(`job-stop-${jobId}`);
  if (stop) {
    stop.innerHTML = isActive && j.status !== 'scheduled'
      ? `<button class="btn btn-sm btn-outline-danger ms-1" onclick="cancelJob('${j.job_id}')" title="Interrompi"><i class="ti ti-player-stop"></i></button>`
      : '';
  }
  const retry = document.getElementById(`job-retry-${jobId}`);
  if (retry) retry.innerHTML = _retryBtnHtml(jobId, j.status);
  const reveal = document.getElementById(`job-reveal-${jobId}`);
  if (reveal) reveal.innerHTML = _revealBtnHtml(jobId, j.status, j.output_path);

  // Update info text
  const info = document.getElementById(`job-info-${jobId}`);
  if (info) {
    if (j.status==='error') info.textContent = j.error||'Errore';
    else if (j.status==='done') info.textContent = 'Completato';
    else if (j.status==='cancelled') info.textContent = 'Annullato';
    else info.textContent = '';
  }

  updateActiveSection();
}

function updateActiveSection() {
  const active = [..._jobs.values()].filter(j=>j.status==='running'||j.status==='queued'||j.status==='scheduled');
  const pill = document.getElementById('dl-active-pill');
  const countEl = document.getElementById('dl-active-count');
  if (active.length) {
    pill.style.display=''; countEl.textContent=active.length;
  } else {
    pill.style.display='none';
  }
}

function updateActiveBadge() {
  const count = [..._jobs.values()].filter(j=>j.status==='running'||j.status==='queued'||j.status==='scheduled').length;
  const badge = document.getElementById('active-jobs-badge');
  if (count>0) { badge.style.display=''; badge.textContent=count; }
  else badge.style.display='none';
  updateActiveSection();
}

function handleProgressEvent(msg) {
  const job = _jobs.get(msg.job_id);
  // Declared out here because the rate line below needs it: a transcode reports
  // a multiplier where a download reports segments per second.
  const phase = msg.phase || _jobPhases[msg.job_id] || 'running';
  if (job) {
    job.progress = { current:msg.current, total:msg.total, pct:msg.pct, speed:msg.speed||0, bytes_speed:msg.bytes_speed||0, eta:msg.eta||null };
    const prevPhase = _jobPhases[msg.job_id];
    _jobPhases[msg.job_id] = phase;
    if (phase !== prevPhase) _updateSteps(msg.job_id, phase);
  }
  // Update bar and info without full card rebuild
  const bar = document.getElementById(`job-bar-${msg.job_id}`);
  if (bar) bar.style.width = msg.pct + '%';
  const info = document.getElementById(`job-info-${msg.job_id}`);
  if (info) {
    const speedStr = _rateText(phase, msg.bytes_speed, msg.speed);
    const etaStr = msg.eta ? fmtEta(msg.eta) : '';
    info.textContent = [speedStr, etaStr, `${msg.pct}%`].filter(Boolean).join(' · ');
  }
}

function handlePhaseEvent(jobId, phase) {
  _jobPhases[jobId] = phase;
  const job = _jobs.get(jobId);
  if (job) job.status = 'running';

  const badge = document.getElementById(`job-badge-${jobId}`);
  if (badge) {
    badge.className = `badge ${_phaseBadge(phase)} flex-shrink-0`;
    badge.textContent = _phaseLabel(phase);
  }
  const card = document.getElementById(`job-card-${jobId}`);
  if (card) card.style.borderLeftColor = _phaseBorder(phase);
  const bar = document.getElementById(`job-bar-${jobId}`);
  if (bar) {
    bar.className = `progress-bar ${_phaseBar(phase)} progress-bar-striped progress-bar-animated job-progress-bar`;
    const isIndeterminate = phase === 'joining' || phase === 'merging' || phase.startsWith('audio_');
    if (isIndeterminate) bar.style.width = '100%';
  }
  const info = document.getElementById(`job-info-${jobId}`);
  if (info) {
    const isIndeterminate = phase === 'joining' || phase === 'merging';
    if (isIndeterminate) info.textContent = _phaseLabel(phase) + '...';
  }
  _updateSteps(jobId, phase);
}

function handleDoneEvent(jobId, outputPath) {
  delete _jobPhases[jobId];
  const job = _jobs.get(jobId);
  if (job) { job.status='done'; job.output_path=outputPath; }
  _updateSteps(jobId, 'done');

  const card = document.getElementById(`job-card-${jobId}`);
  if (card) card.classList.add('is-done');
  const badge = document.getElementById(`job-badge-${jobId}`);
  if (badge) { badge.className='badge bg-success-lt flex-shrink-0'; badge.textContent='Completato'; }
  const bar = document.getElementById(`job-bar-${jobId}`);
  if (bar) {
    bar.style.width='100%';
    bar.className='progress-bar phase-bar-done bg-success job-progress-bar';
  }
  const info = document.getElementById(`job-info-${jobId}`);
  if (info) info.textContent='Completato';
  const stop = document.getElementById(`job-stop-${jobId}`);
  if (stop) stop.innerHTML='';
  const reveal = document.getElementById(`job-reveal-${jobId}`);
  if (reveal) reveal.innerHTML = _revealBtnHtml(jobId, 'done', outputPath);

  updateActiveBadge();
  // Refresh file manager if open
  if (document.getElementById('page-files')?.style.display!=='none') loadFiles();
}

function handleErrorEvent(jobId, message) {
  delete _jobPhases[jobId];
  const job = _jobs.get(jobId);
  if (job) { job.status='error'; job.error=message; }

  const card = document.getElementById(`job-card-${jobId}`);
  if (card) card.classList.add('is-error');
  const badge = document.getElementById(`job-badge-${jobId}`);
  if (badge) { badge.className='badge bg-danger-lt flex-shrink-0'; badge.textContent='Errore'; }
  const bar = document.getElementById(`job-bar-${jobId}`);
  if (bar) { bar.className='progress-bar phase-bar-error bg-danger job-progress-bar'; bar.style.width='100%'; }
  const info = document.getElementById(`job-info-${jobId}`);
  if (info) info.textContent = message==='Annullato' ? 'Annullato' : escapeHtml(message||'Errore');
  const stop = document.getElementById(`job-stop-${jobId}`);
  if (stop) stop.innerHTML='';
  const retry = document.getElementById(`job-retry-${jobId}`);
  if (retry) retry.innerHTML = _retryBtnHtml(jobId, job ? job.status : 'error');

  updateActiveBadge();
}

async function fireNow(jobId) {
  try {
    const res = await fetch(`/api/download/${jobId}/fire`, {method:'POST'});
    if (!res.ok) { const d=await safeJson(res); showToast(d.detail||'Errore','danger'); }
  } catch(e) { showToast('Errore di rete','danger'); }
}

async function revealFile(jobId) {
  const job = _jobs.get(jobId);
  if (!job || !job.output_path) return;
  try {
    const res = await fetch('/api/files/reveal', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: job.output_path}),
    });
    if (!res.ok) { const d = await safeJson(res); showToast(_detailText(d) || 'Errore', 'danger'); }
  } catch (e) { showToast('Errore di rete', 'danger'); }
}

async function retryJob(jobId) {
  try {
    const res = await fetch(`/api/download/${jobId}/retry`, {method:'POST'});
    if (!res.ok) { const d=await safeJson(res); showToast(d.detail||'Errore','danger'); }
  } catch(e) { showToast('Errore di rete','danger'); }
}

async function cancelJob(jobId) {
  if (!await scConfirm('Interrompere il download?')) return;
  try {
    const res = await fetch(`/api/download/${jobId}`, {method:'DELETE'});
    if (!res.ok) { const d=await safeJson(res); showToast(d.detail||'Errore','danger'); }
  } catch(e) { showToast('Errore di rete','danger'); }
}

// The list is normally kept current by the event stream. This re-reads it from
// the server for the times that is not enough — a laptop coming back from
// sleep, a proxy that closed the connection, a tab that fell far behind.
async function refreshJobs() {
  const btn = document.getElementById('dl-refresh-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) { showToast('Impossibile aggiornare i download', 'danger'); return; }
    const jobs = await safeJson(res);
    _jobs.clear();
    jobs.forEach(j => _jobs.set(j.job_id, j));
    renderAllJobCards();
    updateActiveBadge();
  } catch (e) {
    showToast('Errore di rete', 'danger');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function clearFinished() {
  const finished = [..._jobs.entries()]
    .filter(([,j]) => j.status==='done'||j.status==='error'||j.status==='cancelled')
    .map(([id]) => id);
  await Promise.allSettled(finished.map(id =>
    fetch(`/api/download/${id}`, {method:'DELETE'})
  ));
  // UI cleanup handled by job_dismissed SSE; also clean locally in case SSE lags
  for (const id of finished) {
    _jobs.delete(id);
    document.getElementById(`job-card-${id}`)?.remove();
  }
  if (!_jobs.size) {
    const container = document.getElementById('jobs-container');
    const empty = document.getElementById('jobs-empty');
    empty.style.display='';
    container.innerHTML='';
  }
  updateActiveBadge();
}

// ── File Manager ───────────────────────────────────────────────────────────────

let _expandedFolders = new Set();
let _cachedTree = null;
let _selectedPaths = new Set();
let _draggedPaths = [];
let _allVisiblePaths = [];  // flat list of visible paths for shift-click range
let _lastSelectedIndex = -1;
let _fmSearchActive = false;
let _fmSearchTimeout = null;

function setupFileManager() {
  // ── Drag & Drop (supports multi-drag) ──
  document.addEventListener('dragstart', (e) => {
    const row = e.target.closest('[data-drag-path]');
    if (!row) return;
    const path = row.dataset.dragPath;
    // If dragged item is selected, drag all selected; otherwise just the one
    if (_selectedPaths.has(path) && _selectedPaths.size > 1) {
      _draggedPaths = [..._selectedPaths];
    } else {
      _draggedPaths = [path];
    }
    e.dataTransfer.effectAllowed='move';
    e.dataTransfer.setData('text/plain', _draggedPaths.join('\n'));
    // Visual: mark all dragged rows
    _draggedPaths.forEach(p => {
      const el = document.querySelector(`[data-drag-path="${CSS.escape(p)}"]`);
      if (el) el.classList.add('dragging');
    });
  });
  document.addEventListener('dragend', () => {
    document.querySelectorAll('.dragging').forEach(el=>el.classList.remove('dragging'));
    document.querySelectorAll('.drag-over').forEach(el=>el.classList.remove('drag-over'));
    _draggedPaths=[];
  });
  document.addEventListener('dragover', (e) => {
    if (!e.target.closest('.fm-drop-zone')) return;
    e.preventDefault(); e.dataTransfer.dropEffect='move';
  });
  document.addEventListener('dragenter', (e) => {
    const zone = e.target.closest('.fm-drop-zone');
    if (!zone || !_draggedPaths.length) return;
    const dest = zone.dataset.dropPath;
    // Prevent dropping into any of the dragged items
    if (_draggedPaths.some(p => dest===p || dest.startsWith(p+'/'))) return;
    e.preventDefault();
    document.querySelectorAll('.drag-over').forEach(el=>el.classList.remove('drag-over'));
    zone.classList.add('drag-over');
  });
  document.addEventListener('dragleave', (e) => {
    const zone = e.target.closest('.fm-drop-zone');
    if (zone && !zone.contains(e.relatedTarget)) zone.classList.remove('drag-over');
  });
  document.addEventListener('drop', (e) => {
    const zone = e.target.closest('.fm-drop-zone');
    if (!zone) return;
    e.preventDefault(); zone.classList.remove('drag-over');
    const destDirPath = zone.dataset.dropPath;
    if (!_draggedPaths.length||destDirPath===undefined) return;
    if (_draggedPaths.some(p => destDirPath===p||destDirPath.startsWith(p+'/'))) return;
    if (_draggedPaths.length > 1) {
      batchMoveToPath(_draggedPaths, destDirPath);
    } else {
      const name = _draggedPaths[0].split(/[/\\]/).pop();
      moveToPath(_draggedPaths[0], name, destDirPath);
    }
    _draggedPaths=[];
  });

  // ── Click handlers ──
  document.addEventListener('click', (e) => {
    // Checkbox toggle
    const check = e.target.closest('.fm-check');
    if (check) {
      e.stopPropagation();
      const path = check.dataset.selectPath;
      const idx = _allVisiblePaths.indexOf(path);
      if (e.shiftKey && _lastSelectedIndex >= 0 && idx >= 0) {
        // Shift-click: range select
        const start = Math.min(_lastSelectedIndex, idx);
        const end = Math.max(_lastSelectedIndex, idx);
        for (let i = start; i <= end; i++) {
          _selectedPaths.add(_allVisiblePaths[i]);
        }
      } else {
        if (_selectedPaths.has(path)) _selectedPaths.delete(path);
        else _selectedPaths.add(path);
      }
      if (idx >= 0) _lastSelectedIndex = idx;
      syncSelectionUI();
      return;
    }

    // Folder toggle
    const toggle = e.target.closest('.fm-toggle');
    if (toggle) {
      const path = toggle.dataset.folderPath;
      if (_expandedFolders.has(path)) _expandedFolders.delete(path);
      else _expandedFolders.add(path);
      if (_cachedTree) renderFileTree(_cachedTree);
      return;
    }
    const renameBtn = e.target.closest('[data-rename-path]');
    if (renameBtn && renameBtn.closest('#files-left-pane')) {
      renamePath(renameBtn.dataset.renamePath, renameBtn.dataset.renameName); return;
    }
    const delBtn = e.target.closest('[data-delete-path]');
    if (delBtn && delBtn.closest('#files-left-pane')) {
      deletePath(delBtn.dataset.deletePath, delBtn.dataset.deleteName, !!delBtn.dataset.deleteDir); return;
    }
    const playBtn = e.target.closest('[data-play-path]');
    if (playBtn) playFile(playBtn.dataset.playPath, playBtn.dataset.playName);
  });

  // ── Batch toolbar buttons ──
  const batchMoveBtn = document.getElementById('fm-batch-move-btn');
  if (batchMoveBtn) batchMoveBtn.addEventListener('click', async () => {
    if (!_selectedPaths.size) return;
    const dest = await scPrompt('Percorso cartella di destinazione (vuoto = radice):','');
    if (dest === null) return;
    batchMoveToPath([..._selectedPaths], dest);
  });
  const batchDeleteBtn = document.getElementById('fm-batch-delete-btn');
  if (batchDeleteBtn) batchDeleteBtn.addEventListener('click', async () => {
    if (!_selectedPaths.size) return;
    if (!await scConfirm(`Eliminare ${_selectedPaths.size} elementi selezionati?`)) return;
    batchDeletePaths([..._selectedPaths]);
  });
  const deselectBtn = document.getElementById('fm-deselect-btn');
  if (deselectBtn) deselectBtn.addEventListener('click', () => {
    _selectedPaths.clear();
    _lastSelectedIndex = -1;
    syncSelectionUI();
  });
}

function syncSelectionUI() {
  // Update checkboxes and row highlights
  document.querySelectorAll('.fm-check').forEach(cb => {
    const path = cb.dataset.selectPath;
    cb.checked = _selectedPaths.has(path);
    const row = cb.closest('.fm-row');
    if (row) row.classList.toggle('fm-selected', _selectedPaths.has(path));
  });
  // Update toolbar
  const bar = document.getElementById('fm-selection-bar');
  const count = document.getElementById('fm-selection-count');
  if (bar) bar.style.visibility = _selectedPaths.size ? '' : 'hidden';
  if (count) count.textContent = `${_selectedPaths.size} selezionat${_selectedPaths.size===1?'o':'i'}`;
}

function onFmSearchInput(value) {
  const clearBtn = document.getElementById('fm-search-clear');
  if (clearBtn) clearBtn.style.display = value ? '' : 'none';
  clearTimeout(_fmSearchTimeout);
  if (!value || value.trim().length < 2) {
    if (_fmSearchActive) {
      _fmSearchActive = false;
      if (_cachedTree) renderFileTree(_cachedTree);
      else loadFiles();
    }
    return;
  }
  _fmSearchTimeout = setTimeout(() => searchFiles(value.trim()), 300);
}

function clearFmSearch() {
  const input = document.getElementById('fm-search-input');
  if (input) input.value = '';
  const clearBtn = document.getElementById('fm-search-clear');
  if (clearBtn) clearBtn.style.display = 'none';
  _fmSearchActive = false;
  if (_cachedTree) renderFileTree(_cachedTree);
  else loadFiles();
}

async function searchFiles(query) {
  const pane = document.getElementById('files-left-pane');
  if (!pane) return;
  _fmSearchActive = true;
  pane.innerHTML = '<div class="text-center py-4 text-muted" style="font-size:13px"><div class="spinner-border spinner-border-sm me-2"></div>Ricerca...</div>';
  try {
    const res = await fetch(`/api/files/search?q=${encodeURIComponent(query)}`);
    const results = await safeJson(res);
    if (!res.ok) {
      pane.innerHTML = `<div class="text-danger text-center py-4 px-3">${escapeHtml(results.detail || 'Errore ricerca')}</div>`;
      return;
    }
    renderSearchResults(results, query);
  } catch(e) {
    pane.innerHTML = `<div class="text-danger text-center py-4">Errore: ${escapeHtml(e.message)}</div>`;
  }
}

function renderSearchResults(results, query) {
  const pane = document.getElementById('files-left-pane');
  if (!pane) return;
  _allVisiblePaths = [];

  if (!results || !results.length) {
    pane.innerHTML = `<div class="text-muted text-center py-5" style="font-size:13px">
      <i class="ti ti-search-off" style="font-size:2em;display:block;margin-bottom:8px;opacity:.4"></i>
      Nessun risultato per <strong>${escapeHtml(query)}</strong>
    </div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  results.forEach(item => {
    _allVisiblePaths.push(item.path);
    const row = document.createElement('div');
    row.className = 'fm-row';
    if (_selectedPaths.has(item.path)) row.classList.add('fm-selected');
    row.style.paddingLeft = '10px';
    row.setAttribute('draggable', 'true');
    row.dataset.dragPath = item.path;
    const checked = _selectedPaths.has(item.path) ? 'checked' : '';
    const parentPath = item.path.includes('/') ? item.path.substring(0, item.path.lastIndexOf('/')) : '';
    const pathMeta = parentPath
      ? `<span class="fm-meta" style="font-size:11px;opacity:.55;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(parentPath)}">${escapeHtml(parentPath)}</span>`
      : '';
    if (item.type === 'directory') {
      row.classList.add('fm-drop-zone');
      row.dataset.dropPath = item.path;
      row.innerHTML = `
        <input type="checkbox" class="fm-check" data-select-path="${escapeHtml(item.path)}" ${checked}>
        <i class="ti ti-folder-filled text-yellow" style="flex-shrink:0"></i>
        <span class="fm-name">${escapeHtml(item.name)}</span>
        ${pathMeta}
        <div class="fm-actions">
          <button class="btn btn-sm btn-outline-secondary" data-rename-path="${escapeHtml(item.path)}" data-rename-name="${escapeHtml(item.name)}"><i class="ti ti-pencil"></i></button>
          <button class="btn btn-sm btn-outline-danger" data-delete-path="${escapeHtml(item.path)}" data-delete-name="${escapeHtml(item.name)}" data-delete-dir="1"><i class="ti ti-trash"></i></button>
        </div>`;
    } else {
      const size = formatSize(item.size);
      const isMp4 = item.name.toLowerCase().endsWith('.mp4');
      row.innerHTML = `
        <input type="checkbox" class="fm-check" data-select-path="${escapeHtml(item.path)}" ${checked}>
        <i class="ti ${isMp4 ? 'ti-file-type-mp4 text-red' : 'ti-file text-muted'}" style="flex-shrink:0"></i>
        <span class="fm-name">${escapeHtml(item.name)}</span>
        ${pathMeta}
        <span class="fm-meta">${size}</span>
        <div class="fm-actions">
          ${isMp4 ? `<button class="btn btn-sm btn-outline-primary" data-play-path="${escapeHtml(item.path)}" data-play-name="${escapeHtml(item.name)}"><i class="ti ti-player-play"></i></button>` : ''}
          <button class="btn btn-sm btn-outline-secondary" data-rename-path="${escapeHtml(item.path)}" data-rename-name="${escapeHtml(item.name)}"><i class="ti ti-pencil"></i></button>
          <a class="btn btn-sm btn-outline-secondary" href="/api/files/download/${encodeURI(item.path)}"><i class="ti ti-download"></i></a>
          <button class="btn btn-sm btn-outline-danger" data-delete-path="${escapeHtml(item.path)}" data-delete-name="${escapeHtml(item.name)}"><i class="ti ti-trash"></i></button>
        </div>`;
    }
    frag.appendChild(row);
  });

  const header = document.createElement('div');
  header.style.cssText = 'padding:6px 12px 5px;font-size:11px;color:var(--text-dim);border-bottom:1px solid var(--border)';
  header.textContent = `${results.length} risultat${results.length === 1 ? 'o' : 'i'} per "${query}"`;
  pane.innerHTML = '';
  pane.appendChild(header);
  pane.appendChild(frag);

  for (const p of _selectedPaths) {
    if (!_allVisiblePaths.includes(p)) _selectedPaths.delete(p);
  }
  syncSelectionUI();
}

async function loadFiles() {
  const pane = document.getElementById('files-left-pane');
  if (!pane) return;
  // Not awaited: the free-space readout is an aside, and stat'ing a sleeping
  // NFS mount must not hold up the file list.
  loadDiskUsage();
  // If search is active, refresh search results instead of reloading the tree
  const searchInput = document.getElementById('fm-search-input');
  if (_fmSearchActive && searchInput && searchInput.value.trim().length >= 2) {
    return searchFiles(searchInput.value.trim());
  }
  // Show skeleton while loading
  if (!_cachedTree) {
    let skeletonHtml = '';
    for (let i = 0; i < 5; i++) skeletonHtml += `<div class="skeleton skeleton-row"></div>`;
    pane.innerHTML = skeletonHtml;
  }
  try {
    const res = await fetch('/api/files');
    const tree = await safeJson(res);
    _cachedTree = tree;
    if (!tree||!tree.length) { pane.innerHTML='<div class="text-muted text-center py-4">Nessun file trovato</div>'; return; }
    renderFileTree(tree);
  } catch(e) {
    pane.innerHTML=`<div class="text-danger text-center py-4">Errore: ${escapeHtml(e.message)}</div>`;
  }
}

function renderFileTree(tree) {
  const pane = document.getElementById('files-left-pane');
  if (!pane) return;
  _allVisiblePaths = [];
  const frag = document.createDocumentFragment();
  const rootZone = document.createElement('div');
  rootZone.className='fm-row fm-drop-zone fm-root-zone';
  rootZone.dataset.dropPath='';
  rootZone.innerHTML=`<span style="min-width:14px;flex-shrink:0"></span>
    <i class="ti ti-home text-muted" style="flex-shrink:0"></i>
    <span class="fm-meta ms-1">radice</span>`;
  frag.appendChild(rootZone);
  renderTreeItems(tree, frag, 0);
  pane.innerHTML='';
  pane.appendChild(frag);
  // Clean stale selections (paths no longer visible)
  for (const p of _selectedPaths) {
    if (!_allVisiblePaths.includes(p)) _selectedPaths.delete(p);
  }
  syncSelectionUI();
}

function renderTreeItems(items, container, depth) {
  items.forEach(item => {
    _allVisiblePaths.push(item.path);
    const row = document.createElement('div');
    row.className='fm-row';
    if (_selectedPaths.has(item.path)) row.classList.add('fm-selected');
    row.style.paddingLeft=`${8+depth*16}px`;
    row.setAttribute('draggable','true');
    row.dataset.dragPath=item.path;
    const checked = _selectedPaths.has(item.path) ? 'checked' : '';
    if (item.type==='directory') {
      const expanded = _expandedFolders.has(item.path);
      row.classList.add('fm-drop-zone');
      row.dataset.dropPath=item.path;
      const actions = `
        <div class="fm-actions">
          <button class="btn btn-sm btn-outline-secondary" data-rename-path="${escapeHtml(item.path)}" data-rename-name="${escapeHtml(item.name)}"><i class="ti ti-pencil"></i></button>
          <button class="btn btn-sm btn-outline-danger"
                  data-delete-path="${escapeHtml(item.path)}"
                  data-delete-name="${escapeHtml(item.name)}"
                  data-delete-dir="1"><i class="ti ti-trash"></i></button>
        </div>`;
      if (item.empty) {
        row.innerHTML=`
          <input type="checkbox" class="fm-check" data-select-path="${escapeHtml(item.path)}" ${checked}>
          <span style="min-width:22px;flex-shrink:0"></span>
          <i class="ti ti-folder text-muted" style="flex-shrink:0;opacity:0.45"></i>
          <span class="fm-name text-muted">${escapeHtml(item.name)}</span>
          ${actions}`;
        container.appendChild(row);
      } else {
        row.innerHTML=`
          <input type="checkbox" class="fm-check" data-select-path="${escapeHtml(item.path)}" ${checked}>
          <i class="ti ${expanded?'ti-chevron-down':'ti-chevron-right'} text-muted fm-toggle"
             data-folder-path="${escapeHtml(item.path)}"
             style="font-size:1em;cursor:pointer;min-width:22px;flex-shrink:0;padding:4px 3px;margin:-4px -3px"></i>
          <i class="ti ti-folder-filled text-yellow" style="flex-shrink:0"></i>
          <span class="fm-name">${escapeHtml(item.name)}</span>
          ${actions}`;
        container.appendChild(row);
        if (expanded && item.children) renderTreeItems(item.children, container, depth+1);
      }
    } else {
      const size = formatSize(item.size);
      const isMp4 = item.name.toLowerCase().endsWith('.mp4');
      row.innerHTML=`
        <input type="checkbox" class="fm-check" data-select-path="${escapeHtml(item.path)}" ${checked}>
        <span style="min-width:14px;flex-shrink:0"></span>
        <i class="ti ${isMp4?'ti-file-type-mp4 text-red':'ti-file text-muted'}" style="flex-shrink:0"></i>
        <span class="fm-name">${escapeHtml(item.name)}</span>
        <span class="fm-meta">${size}</span>
        <div class="fm-actions">
          ${isMp4?`<button class="btn btn-sm btn-outline-primary" data-play-path="${escapeHtml(item.path)}" data-play-name="${escapeHtml(item.name)}"><i class="ti ti-player-play"></i></button>`:''}
          <button class="btn btn-sm btn-outline-secondary" data-rename-path="${escapeHtml(item.path)}" data-rename-name="${escapeHtml(item.name)}"><i class="ti ti-pencil"></i></button>
          <a class="btn btn-sm btn-outline-secondary" href="/api/files/download/${encodeURI(item.path)}"><i class="ti ti-download"></i></a>
          <button class="btn btn-sm btn-outline-danger" data-delete-path="${escapeHtml(item.path)}" data-delete-name="${escapeHtml(item.name)}"><i class="ti ti-trash"></i></button>
        </div>`;
      container.appendChild(row);
    }
  });
}

async function moveToPath(sourcePath, name, destDirPath) {
  try {
    const res = await fetch('/api/files/move', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path:sourcePath, dest_dir_path:destDirPath}),
    });
    const data = await safeJson(res);
    if (res.ok) { showToast(`Spostato: ${name}`,'success'); loadFiles(); }
    else showToast(data.detail||'Errore spostamento','danger');
  } catch(e) { showToast('Errore di rete','danger'); }
}

async function batchMoveToPath(paths, destDirPath) {
  try {
    const res = await fetch('/api/files/move-batch', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({paths, dest_dir_path:destDirPath}),
    });
    const data = await safeJson(res);
    if (res.ok) {
      const ok = data.results.filter(r=>r.ok).length;
      const fail = data.results.filter(r=>!r.ok).length;
      if (ok) showToast(`${ok} file spostati`,'success');
      if (fail) showToast(`${fail} file non spostati`,'danger');
      _selectedPaths.clear();
      loadFiles();
    } else showToast(data.detail||'Errore spostamento','danger');
  } catch(e) { showToast('Errore di rete','danger'); }
}

async function batchDeletePaths(paths) {
  try {
    const res = await fetch('/api/files/delete-batch', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({paths}),
    });
    const data = await safeJson(res);
    if (res.ok) {
      const ok = data.results.filter(r=>r.ok).length;
      const fail = data.results.filter(r=>!r.ok).length;
      if (ok) showToast(`${ok} file eliminati`,'success');
      if (fail) showToast(`${fail} file non eliminati`,'danger');
      _selectedPaths.clear();
      loadFiles();
    } else showToast(data.detail||'Errore eliminazione','danger');
  } catch(e) { showToast('Errore di rete','danger'); }
}

function playFile(path, name) {
  document.getElementById('player-modal-title').textContent=name;
  const video = document.getElementById('video-player');
  video.src=`/api/files/stream/${encodeURI(path)}`; video.load();
  showModal('player-modal');
  document.getElementById('player-modal').addEventListener('click', (e) => {
    if (e.target.closest('[data-bs-dismiss="modal"]')) { video.pause(); video.src=''; }
  }, {once:true});
}

async function renamePath(path, name) {
  const newName = await scPrompt(`Nuovo nome:`, name);
  if (!newName || newName === name) return;
  try {
    const res = await fetch('/api/files/rename', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ path, new_name: newName }),
    });
    if (res.ok) { showToast(`Rinominato in: ${newName}`, 'success'); loadFiles(); }
    else { const d = await safeJson(res); showToast(d.detail || 'Errore rinomina', 'danger'); }
  } catch(e) { showToast('Errore di rete', 'danger'); }
}

async function deletePath(path, name, isDir) {
  const msg = isDir ? `Eliminare la cartella "${name}" e tutto il suo contenuto?` : `Eliminare il file "${name}"?`;
  if (!await scConfirm(msg)) return;
  try {
    const res = await fetch(`/api/files/delete/${encodeURI(path)}`, {method:'DELETE'});
    if (res.ok||res.status===204) { showToast(`Eliminato: ${name}`,'success'); loadFiles(); }
    else { const d=await safeJson(res); showToast(d.detail||'Errore eliminazione','danger'); }
  } catch(e) { showToast('Errore di rete','danger'); }
}
