'use strict';
// EstateHDR local web UI (no external dependencies).

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};

const STAGES = { wczytywanie: 'wczytywanie', 'wyrównanie': 'wyrównywanie klatek', 'scalanie HDR': 'scalanie HDR',
  'korekcja obiektywu': 'korekcja obiektywu', okna: 'okna', 'balans bieli': 'balans bieli', 'tone mapping': 'tonowanie',
  odszumianie: 'odszumianie', 'moduły': 'moduły dodatkowe', geometria: 'geometria', eksport: 'eksport', gotowe: 'gotowe' };

let OPTS = { presets: {}, extensions: [] };
let job = null;          // current job status from the server
let groups = [];         // editable copy of the grouping
let preset = 'neutral';
let poll = null;

async function api(method, url, body) {
  const init = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) { init.body = JSON.stringify(body); init.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  return r.headers.get('content-type')?.includes('json') ? r.json() : r;
}

function show(id, on = true) { $(id).classList.toggle('hidden', !on); }
function setHash() { if (job) history.replaceState(null, '', '#job=' + job.id); }

// ------------------------------------------------------------------------------------------
// init
// ------------------------------------------------------------------------------------------
async function init() {
  OPTS = await api('GET', '/api/options');
  renderPresets();
  bindUpload();
  $('#btn-regroup').onclick = regroup;
  $('#btn-start').onclick = start;
  $('#btn-new').onclick = () => { location.hash = ''; location.reload(); };
  $('#btn-jobs').onclick = toggleJobs;
  const m = location.hash.match(/job=([\w-]+)/);
  if (m) await openJob(m[1]);
}

function renderPresets() {
  const box = $('#presets');
  box.innerHTML = '';
  for (const [k, label] of Object.entries(OPTS.presets)) {
    const [title, ...rest] = label.split(' - ');
    const d = el('div', { class: 'preset' + (k === preset ? ' sel' : ''), onclick: () => { preset = k; renderPresets(); } },
      el('b', {}, title), el('span', {}, rest.join(' - ')));
    box.append(d);
  }
}

async function toggleJobs() {
  const p = $('#jobs-panel');
  if (!p.classList.contains('hidden')) { show('#jobs-panel', false); return; }
  const list = await api('GET', '/api/jobs');
  const box = $('#jobs-list');
  box.innerHTML = '';
  if (!list.length) box.append(el('p', { class: 'muted' }, 'Brak zapisanych zadań.'));
  for (const j of list) {
    box.append(el('div', { class: 'jobrow' },
      el('b', {}, j.id), el('span', {}, stateLabel(j.state)), el('span', { class: 'muted' }, `${j.series} serii, ${j.files} plików`),
      el('button', { class: 'btn small', onclick: () => { show('#jobs-panel', false); openJob(j.id); } }, 'Otwórz'),
      el('button', { class: 'btn small secondary', onclick: async () => {
        if (!confirm('Usunąć zadanie i jego pliki?')) return;
        await api('DELETE', `/api/jobs/${j.id}`); show('#jobs-panel', false); toggleJobs(); } }, 'Usuń')));
  }
  show('#jobs-panel', true);
}

function stateLabel(s) {
  return { new: 'nowe', grouped: 'pogrupowane', queued: 'w kolejce', running: 'w trakcie', done: 'zakończone', error: 'błąd' }[s] || s;
}

function clearResults() {
  $('#results').innerHTML = '';
  for (const k of Object.keys(rendered)) delete rendered[k];
}

async function openJob(id) {
  job = await api('GET', `/api/jobs/${id}`);
  clearResults();
  setHash();
  groups = job.groups || [];
  if (job.settings && job.settings.preset) { preset = job.settings.preset; renderPresets(); applySettings(job.settings); }
  if (groups.length) { renderGroups(); show('#step-groups'); show('#step-settings'); }
  if (['queued', 'running', 'done', 'error'].includes(job.state)) { show('#step-results'); renderResults(); startPolling(); }
}

function applySettings(s) {
  $('#opt-verticals').checked = s.verticals !== false;
  $('#opt-windows').checked = s.windows !== false;
  $('#opt-sky').value = s.sky || '';
  $('#opt-twilight').value = s.twilight || '';
  $('#opt-grass').checked = !!s.grass;
  $('#opt-remove').checked = !!s.remove;
  if (s.mls_size) $('#opt-mls').value = s.mls_size;
}

// ------------------------------------------------------------------------------------------
// upload (folder drag & drop, pickers)
// ------------------------------------------------------------------------------------------
function bindUpload() {
  const dz = $('#dropzone');
  dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('over'));
  dz.addEventListener('drop', async (e) => {
    e.preventDefault(); dz.classList.remove('over');
    const items = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    let files = [];
    if (items.length) for (const it of items) files = files.concat(await walkEntry(it, ''));
    else files = [...e.dataTransfer.files].map((f) => ({ file: f, path: f.name }));
    upload(files);
  });
  $('#pick-dir').onchange = (e) => upload([...e.target.files].map((f) => ({ file: f, path: f.webkitRelativePath || f.name })));
  $('#pick-files').onchange = (e) => upload([...e.target.files].map((f) => ({ file: f, path: f.name })));
}

function walkEntry(entry, prefix) {
  return new Promise((resolve) => {
    if (entry.isFile) entry.file((f) => resolve([{ file: f, path: prefix + f.name }]), () => resolve([]));
    else if (entry.isDirectory) {
      const reader = entry.createReader();
      let all = [];
      const readBatch = () => reader.readEntries(async (ents) => {
        if (!ents.length) { resolve(all); return; }
        for (const en of ents) all = all.concat(await walkEntry(en, prefix + entry.name + '/'));
        readBatch();
      }, () => resolve(all));
      readBatch();
    } else resolve([]);
  });
}

function okExt(name) {
  const low = name.toLowerCase();
  if (low.endsWith('.mask.png')) return true;
  return OPTS.extensions.some((x) => low.endsWith(x));
}

async function upload(list) {
  const files = list.filter((x) => okExt(x.file.name));
  const skipped = list.length - files.length;
  if (!files.length) { alert('Nie znaleziono obsługiwanych plików (RAW, JPEG, TIFF).'); return; }
  if (!job || ['queued', 'running', 'done'].includes(job.state)) {
    const j = await api('POST', '/api/jobs');
    job = { id: j.id, state: 'new' };
    setHash();
  }
  show('#upload-status');
  const total = files.reduce((a, x) => a + x.file.size, 0);
  let sent = 0;
  const batches = [];
  let cur = [], curBytes = 0;
  for (const x of files) {
    cur.push(x); curBytes += x.file.size;
    if (cur.length >= 12 || curBytes > 300e6) { batches.push(cur); cur = []; curBytes = 0; }
  }
  if (cur.length) batches.push(cur);
  for (const b of batches) {
    const fd = new FormData();
    for (const x of b) { fd.append('files', x.file, x.file.name); fd.append('paths', x.path); }
    const bytes = b.reduce((a, x) => a + x.file.size, 0);
    await xhrUpload(`/api/jobs/${job.id}/files`, fd, (loaded) => {
      $('#upload-bar').style.width = (100 * (sent + loaded) / total).toFixed(1) + '%';
      $('#upload-text').textContent = `Wysyłanie: ${fmtMB(sent + loaded)} / ${fmtMB(total)}`;
    });
    sent += bytes;
  }
  $('#upload-bar').style.width = '100%';
  $('#upload-text').textContent = `Wysłano ${files.length} plików (${fmtMB(total)})` + (skipped ? `, pominięto ${skipped} nieobsługiwanych` : '') + '. Grupowanie...';
  await regroup();
  $('#upload-text').textContent = `Wysłano ${files.length} plików (${fmtMB(total)})` + (skipped ? `, pominięto ${skipped} nieobsługiwanych.` : '.');
}

function xhrUpload(url, fd, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('POST', url);
    x.upload.onprogress = (e) => onProgress(e.loaded);
    x.onload = () => (x.status < 300 ? resolve(JSON.parse(x.responseText)) : reject(new Error(x.responseText)));
    x.onerror = () => reject(new Error('błąd sieci'));
    x.send(fd);
  });
}

const fmtMB = (b) => (b / 1048576).toFixed(1) + ' MB';

// ------------------------------------------------------------------------------------------
// grouping
// ------------------------------------------------------------------------------------------
async function regroup() {
  if (!job) return;
  const res = await api('POST', `/api/jobs/${job.id}/group`,
    { single: $('#opt-single').checked, bracket_size: parseInt($('#opt-bracket').value || '0', 10) });
  groups = res.groups;
  job.state = 'grouped';
  const un = $('#unreadable');
  if (res.unreadable && res.unreadable.length) {
    un.textContent = 'Nie udało się odczytać: ' + res.unreadable.map((u) => `${u.file} (${u.error})`).join('; ') + ' - te pliki zostaną pominięte.';
    show('#unreadable');
  } else show('#unreadable', false);
  renderGroups();
  show('#step-groups'); show('#step-settings');
}

let saveTimer = null;
function saveGroups() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const res = await api('PUT', `/api/jobs/${job.id}/groups`, { groups: groups.map((g) => ({ name: g.name, files: g.files })) });
    groups = res.groups.map((g, i) => ({ ...g, ev: groups.find((x) => x.name === g.name)?.ev || [] }));
    renderGroups();
  }, 250);
}

function refFrame(g) {
  // middle exposure = colour/geometry reference of the series (the mask is painted on it)
  const ev = g.ev || [];
  if (ev.length === g.files.length && ev.every((v) => v !== null)) {
    const order = g.files.map((f, i) => i).sort((a, b) => ev[a] - ev[b]);
    return g.files[order[Math.floor(order.length / 2)]];
  }
  return g.files[Math.floor(g.files.length / 2)];
}

function renderGroups() {
  const box = $('#groups');
  box.innerHTML = '';
  const nFiles = groups.reduce((a, g) => a + g.files.length, 0);
  $('#groups-summary').textContent = `${groups.length} serii, ${nFiles} zdjęć`;
  groups.forEach((g, gi) => {
    const hasMask = job && job.masks && job.masks[g.name];
    const nameIn = el('input', { class: 'name', value: g.name });
    nameIn.onchange = () => { g.name = nameIn.value.trim() || g.name; saveGroups(); };
    const head = el('div', { class: 'group-head' }, nameIn,
      el('span', { class: 'tag' }, g.files.length === 1 ? '1 zdjęcie' : `${g.files.length} klatek`),
      hasMask ? el('span', { class: 'tag mask' }, 'maska usuwania') : null,
      gi < groups.length - 1 ? el('button', { class: 'btn small secondary', onclick: () => {
        groups[gi].files = groups[gi].files.concat(groups[gi + 1].files); groups.splice(gi + 1, 1); saveGroups(); } }, 'Połącz z następną') : null,
      g.files.length > 1 ? el('button', { class: 'btn small secondary', onclick: () => {
        const parts = g.files.map((f) => ({ name: f.replace(/^.*\//, '').replace(/\.[^.]+$/, ''), files: [f], ev: [] }));
        groups.splice(gi, 1, ...parts); saveGroups(); } }, 'Rozdziel') : null,
      el('button', { class: 'btn small secondary', onclick: () => openMask(g) }, hasMask ? 'Edytuj maskę' : 'Maska usuwania'));
    const frames = el('div', { class: 'frames' });
    g.files.forEach((f, fi) => {
      const sel = el('select', {}, el('option', { value: '' }, 'przenieś do...'),
        ...groups.map((o, oi) => (oi === gi ? null : el('option', { value: String(oi) }, o.name))),
        el('option', { value: 'new' }, '+ nowa seria'));
      sel.onchange = () => {
        const v = sel.value;
        if (!v) return;
        g.files.splice(fi, 1);
        if (v === 'new') groups.splice(gi + 1, 0, { name: f.replace(/^.*\//, '').replace(/\.[^.]+$/, ''), files: [f], ev: [] });
        else groups[parseInt(v, 10)].files.push(f);
        groups = groups.filter((x) => x.files.length);
        saveGroups();
      };
      const ev = g.ev && g.ev[fi] !== undefined && g.ev[fi] !== null ? ` · EV ${g.ev[fi]}` : '';
      frames.append(el('div', { class: 'frame' },
        el('img', { loading: 'lazy', src: `/api/jobs/${job.id}/thumb?f=${encodeURIComponent(f)}&s=320`, alt: f }),
        el('div', {}, f.replace(/^.*\//, '') + ev), sel));
    });
    const card = el('div', { class: 'group' }, head, frames);
    if (g.warnings && g.warnings.length) card.append(el('div', { class: 'gwarn' }, 'Uwaga: ' + g.warnings.map(translateWarn).join('; ')));
    box.append(card);
  });
}

const MODULES = { sky: 'niebo', twilight: 'zmierzch', remove: 'usuwanie obiektów', grass: 'trawa' };
function translateReason(r) {
  if (!r) return '';
  if (r.startsWith('no mask')) return 'brak maski - namaluj ją przy serii';
  if (/sky|top region|smooth region/.test(r)) return 'nie wykryto nieba na zdjęciu';
  return r;
}
function translateError(e) {
  if (!e) return 'nieznany błąd';
  if (e.startsWith('DecodeError')) return 'nie można odczytać pliku (uszkodzony lub niepełny): ' + e.replace(/^DecodeError:\s*/, '');
  if (e.startsWith('MemoryError') || e.includes('out of memory')) return 'za mało pamięci RAM dla tej serii';
  return e;
}

function translateWarn(w) {
  return w.replace('no EXIF exposure data - exposures estimated from pixels', 'brak danych ekspozycji w EXIF - ekspozycje oszacowane z pikseli')
    .replace(/series has (\d+) frames, most series have (\d+)/, 'seria ma $1 klatek, większość ma $2')
    .replace(/incomplete series: (\d+) of (\d+) frames/, 'niepełna seria: $1 z $2 klatek');
}

// ------------------------------------------------------------------------------------------
// removal mask brush
// ------------------------------------------------------------------------------------------
let maskSeries = null;
async function openMask(g) {
  maskSeries = g.name;
  $('#mask-series').textContent = g.name;
  const bg = $('#mask-bg'), fg = $('#mask-fg');
  const img = new Image();
  img.src = `/api/jobs/${job.id}/thumb?f=${encodeURIComponent(refFrame(g))}&s=1600`;
  await img.decode();
  for (const c of [bg, fg]) { c.width = img.naturalWidth; c.height = img.naturalHeight; }
  bg.getContext('2d').drawImage(img, 0, 0);
  const fx = fg.getContext('2d');
  fx.clearRect(0, 0, fg.width, fg.height);
  if (job.masks && job.masks[g.name]) {
    try {
      const m = new Image();
      m.src = `/api/jobs/${job.id}/masks/${encodeURIComponent(g.name)}?t=${Date.now()}`;
      await m.decode();
      const t = document.createElement('canvas'); t.width = fg.width; t.height = fg.height;
      const tx = t.getContext('2d'); tx.drawImage(m, 0, 0, t.width, t.height);
      const d = tx.getImageData(0, 0, t.width, t.height);
      for (let i = 0; i < d.data.length; i += 4) {
        const on = d.data[i] > 127;
        d.data[i] = 255; d.data[i + 1] = 40; d.data[i + 2] = 40; d.data[i + 3] = on ? 255 : 0;
      }
      fx.putImageData(d, 0, 0);
    } catch (e) { /* no mask yet */ }
  }
  show('#modal');
}

(function bindBrush() {
  const fg = $('#mask-fg');
  let drawing = false, last = null;
  const pos = (e) => {
    const r = fg.getBoundingClientRect();
    return [(e.clientX - r.left) * fg.width / r.width, (e.clientY - r.top) * fg.height / r.height];
  };
  const stroke = (p) => {
    const fx = fg.getContext('2d');
    const scale = fg.width / fg.getBoundingClientRect().width;
    fx.globalCompositeOperation = $('#erase').checked ? 'destination-out' : 'source-over';
    fx.strokeStyle = 'rgb(255,40,40)'; fx.lineCap = 'round'; fx.lineJoin = 'round';
    fx.lineWidth = parseInt($('#brush').value, 10) * scale;
    fx.beginPath(); fx.moveTo(...(last || p)); fx.lineTo(...p); fx.stroke();
    last = p;
  };
  fg.addEventListener('pointerdown', (e) => { drawing = true; last = null; fg.setPointerCapture(e.pointerId); stroke(pos(e)); });
  fg.addEventListener('pointermove', (e) => { if (drawing) stroke(pos(e)); });
  fg.addEventListener('pointerup', () => { drawing = false; last = null; });
  $('#mask-clear').onclick = () => fg.getContext('2d').clearRect(0, 0, fg.width, fg.height);
  $('#mask-cancel').onclick = () => show('#modal', false);
  $('#mask-save').onclick = async () => {
    const out = document.createElement('canvas'); out.width = fg.width; out.height = fg.height;
    const ox = out.getContext('2d');
    const d = fg.getContext('2d').getImageData(0, 0, fg.width, fg.height);
    let n = 0;
    for (let i = 0; i < d.data.length; i += 4) {
      const on = d.data[i + 3] > 20; n += on;
      d.data[i] = d.data[i + 1] = d.data[i + 2] = on ? 255 : 0; d.data[i + 3] = 255;
    }
    ox.putImageData(d, 0, 0);
    if (n === 0) {
      await api('DELETE', `/api/jobs/${job.id}/masks/${encodeURIComponent(maskSeries)}`);
      if (job.masks) delete job.masks[maskSeries];
    } else {
      const blob = await new Promise((r) => out.toBlob(r, 'image/png'));
      const fd = new FormData(); fd.append('file', blob, 'mask.png');
      await api('POST', `/api/jobs/${job.id}/masks/${encodeURIComponent(maskSeries)}`, fd);
      job.masks = job.masks || {}; job.masks[maskSeries] = true;
      $('#opt-remove').checked = true;
    }
    show('#modal', false);
    renderGroups();
  };
})();

// ------------------------------------------------------------------------------------------
// processing, queue, results
// ------------------------------------------------------------------------------------------
async function start() {
  if (!job) { alert('Najpierw wgraj zdjęcia.'); return; }
  $('#btn-start').disabled = true;
  try {
    const body = {
      preset, verticals: $('#opt-verticals').checked, windows: $('#opt-windows').checked,
      sky: $('#opt-sky').value || null, twilight: $('#opt-twilight').value || null,
      grass: $('#opt-grass').checked, remove: $('#opt-remove').checked,
      mls_size: parseInt($('#opt-mls').value || '2048', 10), single: $('#opt-single').checked,
    };
    const r = await api('POST', `/api/jobs/${job.id}/start`, body);
    clearResults();
    $('#start-msg').textContent = r.queue_position ? `W kolejce (przed tobą: ${r.queue_position})` : 'Uruchomiono.';
    show('#step-results');
    startPolling();
  } catch (e) {
    alert('Nie udało się uruchomić: ' + e.message);
  } finally {
    $('#btn-start').disabled = false;
  }
}

function startPolling() {
  clearInterval(poll);
  const tick = async () => {
    try {
      job = await api('GET', `/api/jobs/${job.id}`);
      renderResults();
      if (!['queued', 'running'].includes(job.state)) clearInterval(poll);
    } catch (e) { /* server busy: try again */ }
  };
  tick();
  poll = setInterval(tick, 1000);
}

const rendered = {};  // series -> rendered compare (keep slider position)
function renderResults() {
  const box = $('#results');
  const names = (job.groups || []).map((g) => g.name);
  for (const n of Object.keys(job.results || {})) if (!names.includes(n)) names.push(n);
  let sum = 0;
  for (const n of names) sum += (job.progress[n] && job.progress[n].frac) || 0;
  $('#total-bar').style.width = (names.length ? 100 * sum / names.length : 0).toFixed(1) + '%';
  let st = stateLabel(job.state);
  if (job.state === 'queued' && job.queue_position) st += ` (przed tobą: ${job.queue_position})`;
  if (job.state === 'done' && job.report) st += ` - ${job.report.ok} OK, ${job.report.failed} błędów, ${job.report.seconds} s`;
  if (job.state === 'error') st += ': ' + (job.error || '');
  $('#job-state').textContent = st;
  const busy = ['queued', 'running'].includes(job.state);
  $('#btn-regroup').disabled = busy;
  $('#btn-start').disabled = busy;
  const run = job.run_id || 0;  // cache-buster: a new run reuses the same output file names
  const done = job.state === 'done' && Object.values(job.results).some((r) => r.status === 'ok');
  $('#zip-row').hidden = !done;
  if (done) {
    for (const w of ['mls', 'full', 'all']) $('#zip-' + w).href = `/api/jobs/${job.id}/zip?which=${w}`;
  }
  for (const n of names) {
    const p = job.progress[n] || {};
    const r = job.results[n];
    let row = box.querySelector(`[data-series="${CSS.escape(n)}"]`);
    if (!row) {
      row = el('div', { class: 'result', 'data-series': n },
        el('div', { class: 'result-head' }, el('b', {}, n), el('span', { class: 'status' }), el('div', { class: 'mini' }, el('div')),
          el('span', { class: 'muted stage' })),
        el('div', { class: 'body' }));
      box.append(row);
    }
    const status = r ? (r.status === 'ok' ? 'gotowe' : 'błąd') : (p.status === 'running' ? 'w trakcie' : (job.state === 'queued' ? 'w kolejce' : 'oczekuje'));
    const sEl = row.querySelector('.status');
    sEl.textContent = status;
    sEl.className = 'status' + (r ? (r.status === 'ok' ? ' ok' : ' error') : '');
    row.querySelector('.mini > div').style.width = (100 * (p.frac || 0)).toFixed(0) + '%';
    row.querySelector('.stage').textContent = r ? (r.seconds ? `${r.seconds} s` : '') : (STAGES[p.stage] || p.stage || '');
    const key = `${job.id}/${run}/${n}`;
    if (r && !rendered[key]) {
      rendered[key] = true;
      const body = row.querySelector('.body');
      body.innerHTML = '';
      if (r.status !== 'ok') { body.append(el('div', { class: 'err-text' }, 'Błąd: ' + translateError(r.error))); continue; }
      if (r.outputs.preview_after) body.append(compare(r.outputs.preview_before && `${r.outputs.preview_before.url}?v=${run}`,
        `${r.outputs.preview_after.url}?v=${run}`));
      const dl = el('div', { class: 'downloads' }, el('span', {}, 'Pobierz:'));
      for (const [k, v] of Object.entries(r.outputs)) {
        if (k.startsWith('preview')) continue;
        const label = k === 'mls' ? 'MLS' : k === 'full' ? 'pełna rozdzielczość' : k;
        dl.append(el('a', { class: 'btn small' + (k === 'mls' ? '' : ' secondary'), href: `${v.url}?download=1&v=${run}` },
          `${label}${v.width ? ` (${v.width}×${v.height})` : ''}`));
      }
      body.append(dl);
      const notes = [];
      for (const [m, info] of Object.entries(r.modules || {})) {
        if (!MODULES[m]) continue;
        if (info.error) notes.push(`${MODULES[m]}: błąd (${info.error})`);
        else if (info.applied === false && !(info.reason || '').startsWith('no mask'))
          notes.push(`${MODULES[m]}: nie zastosowano - ${translateReason(info.reason)}`);
      }
      if (r.warnings && r.warnings.length) notes.push(...r.warnings.map(translateWarn));
      if (notes.length) body.append(el('div', { class: 'gwarn' }, notes.join('; ')));
    }
  }
}

function compare(beforeUrl, afterUrl) {
  const wrap = el('div', { class: 'compare' });
  const after = el('img', { src: afterUrl, alt: 'po', draggable: 'false' });
  wrap.append(after);
  if (!beforeUrl) return wrap;
  const before = el('div', { class: 'before' }, el('img', { src: beforeUrl, alt: 'przed', draggable: 'false' }));
  const handle = el('div', { class: 'handle' });
  wrap.append(before, handle, el('span', { class: 'lbl l' }, 'przed'), el('span', { class: 'lbl r' }, 'po'));
  const set = (frac) => {
    frac = Math.max(0, Math.min(1, frac));
    before.style.clipPath = `inset(0 ${(100 - frac * 100).toFixed(2)}% 0 0)`;
    handle.style.left = (frac * 100).toFixed(2) + '%';
  };
  set(0.5);
  const move = (e) => { const r = wrap.getBoundingClientRect(); set((e.clientX - r.left) / r.width); };
  let down = false;
  wrap.addEventListener('pointerdown', (e) => { e.preventDefault(); down = true; wrap.setPointerCapture(e.pointerId); move(e); });
  wrap.addEventListener('pointermove', (e) => { if (down) move(e); });
  wrap.addEventListener('pointerup', () => { down = false; });
  return wrap;
}

init().catch((e) => alert('Błąd inicjalizacji: ' + e.message));
