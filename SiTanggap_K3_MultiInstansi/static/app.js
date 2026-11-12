const API_BASE = new URL('.', window.location.href).pathname.replace(/\/$/, '');
function apiUrl(path) {
  return `${API_BASE}${path.startsWith('/') ? path : '/' + path}`;
}

const state = { user: null, csrf: '', reports: [], currentReportId: null, forcedPasswordChange: false };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function fmtDate(value, includeTime = false) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat('id-ID', includeTime ? {dateStyle:'medium',timeStyle:'short'} : {dateStyle:'medium'}).format(d);
}
function localDateTime() {
  const d = new Date();
  const offset = d.getTimezoneOffset() * 60000;
  return new Date(d - offset).toISOString().slice(0,16);
}
function toast(message) {
  const el = $('#toast'); el.textContent = message; el.classList.add('show');
  window.clearTimeout(toast._timer); toast._timer = window.setTimeout(() => el.classList.remove('show'), 3400);
}
function setBusy(button, busy, text = 'Memproses...') {
  if (!button) return;
  if (busy) { button.dataset.originalText = button.innerHTML; button.disabled = true; button.textContent = text; }
  else { button.disabled = false; if (button.dataset.originalText) button.innerHTML = button.dataset.originalText; }
}
async function requestJSON(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!(options.body instanceof FormData) && options.body !== undefined && !headers.has('Content-Type')) headers.set('Content-Type','application/json');
  if (options.method && !['GET','HEAD'].includes(options.method.toUpperCase()) && state.csrf) headers.set('X-CSRF-Token', state.csrf);
  const response = await fetch(apiUrl(url), {...options, headers, credentials:'same-origin'});
  const type = response.headers.get('content-type') || '';
  const payload = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const error = new Error(payload?.error || `Permintaan gagal (${response.status}).`);
    error.status = response.status; error.payload = payload; throw error;
  }
  return payload;
}
async function requestBlob(url) {
  const response = await fetch(apiUrl(url), {credentials:'same-origin', headers:{'X-CSRF-Token':state.csrf}});
  if (!response.ok) {
    let message = 'Ekspor gagal.';
    try { message = (await response.json()).error || message; } catch {}
    throw new Error(message);
  }
  return response.blob();
}
function levelClass(level) { return level === 'Tinggi' ? 'high' : level === 'Sedang' ? 'medium' : 'low'; }
function statusClass(status) { return status === 'Selesai' ? 'done' : status === 'Dalam Proses' ? 'progress' : 'open'; }
function roleLabel(role) { return ({admin:'Administrator Instansi',hse:'Petugas K3 / HSE',pelapor:'Pelapor'})[role] || role; }
function emptyRow(cols, text) { return `<tr><td colspan="${cols}" class="no-data">${esc(text)}</td></tr>`; }

function switchAuthMode(mode) {
  $$('.auth-tab').forEach(btn => btn.classList.toggle('active', btn.dataset.authMode === mode));
  $('#login-form').classList.toggle('hidden', mode !== 'login');
  $('#join-form').classList.toggle('hidden', mode !== 'join');
  $('#register-org-form').classList.toggle('hidden', mode !== 'register-org');
  $('#login-error').textContent = '';
  $('#join-error').textContent = '';
  $('#register-org-error').textContent = '';

  if (mode === 'login') {
    $('#auth-heading').textContent = 'Masuk ke Instansi Anda';
    $('#auth-subtitle').textContent = 'Masukkan Kode Instansi, Username, dan Kata Sandi Anda.';
  } else if (mode === 'join') {
    $('#auth-heading').textContent = 'Gabung ke Instansi';
    $('#auth-subtitle').textContent = 'Daftar sebagai Pelapor menggunakan Kode Undangan dari Admin K3 instansi Anda.';
  } else {
    $('#auth-heading').textContent = 'Daftarkan Instansi Baru';
    $('#auth-subtitle').textContent = 'Buat ruang kerja (workspace) terpisah khusus untuk instansi atau proyek Anda.';
  }
}

function showLogin() {
  $('#login-screen').classList.remove('hidden');
  $('#app-shell').classList.add('hidden');
  $('#login-form').reset();
  $('#join-form').reset();
  $('#register-org-form').reset();
  const savedOrg = localStorage.getItem('sitanggap_last_org_code');
  if (savedOrg && $('#login-form input[name="org_code"]')) {
    $('#login-form input[name="org_code"]').value = savedOrg;
  }
  switchAuthMode('login');
}

function syncOrgUI() {
  if (!state.user) return;
  localStorage.setItem('sitanggap_last_org_code', state.user.org_code);
  $('#sidebar-org-name').textContent = state.user.org_name;
  $('#sidebar-org-badge').textContent = state.user.org_name;
  $('#sidebar-org-code').textContent = `Kode: ${state.user.org_code}`;
  $('#topbar-org-name').textContent = state.user.org_name;
  $('#mobile-org-name').textContent = state.user.org_name;
  $('#dash-org-eyebrow').textContent = `WORKSPACE · ${state.user.org_name.toUpperCase()}`;

  if (state.user.role === 'admin') {
    $('#org-info-code').textContent = state.user.org_code;
    $('#org-info-invite').textContent = state.user.invite_code || '—';
    $('#org-settings-name').value = state.user.org_name;
    $('#org-settings-signup').value = state.user.allow_member_signup ? '1' : '0';
  }
}

function showApp() {
  $('#login-screen').classList.add('hidden');
  $('#app-shell').classList.remove('hidden');
  $('#account-name').textContent = state.user.full_name;
  $('#account-role').textContent = roleLabel(state.user.role);
  $('#avatar').textContent = state.user.full_name.split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase();
  $$('.admin-only').forEach(el => el.classList.toggle('hidden', state.user.role !== 'admin'));
  $('#reporter').value = state.user.full_name;
  $('#report-date').value = localDateTime();
  syncOrgUI();
}

function openPasswordModal(force = false) {
  state.forcedPasswordChange = force;
  $('#password-modal').classList.remove('hidden');
  $('#password-close').classList.toggle('hidden', force);
  $('#password-help').textContent = force
    ? 'Kata sandi awal harus diganti sebelum Anda dapat menggunakan aplikasi. Gunakan minimal 10 karakter.'
    : 'Gunakan kata sandi minimal 10 karakter dan jangan gunakan kata sandi yang sama dengan akun lain.';
  $('#password-error').textContent = '';
}
function closePasswordModal() {
  if (state.forcedPasswordChange) return;
  $('#password-modal').classList.add('hidden');
  $('#password-form').reset();
}

function navigate(page) {
  if (page === 'users' && state.user?.role !== 'admin') return toast('Menu hanya tersedia untuk Administrator Instansi.');
  $$('.page').forEach(el => el.classList.toggle('active', el.id === `page-${page}`));
  $$('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  const names = {dashboard:'Dashboard',report:'Buat Laporan',monitoring:'Monitoring',users:'Instansi & Pengguna',guide:'Panduan'};
  $('#breadcrumb').textContent = names[page] || 'Dashboard';
  if (page === 'dashboard') loadDashboard();
  if (page === 'monitoring') loadReports();
  if (page === 'users') loadUsers();
  window.scrollTo({top:0, behavior:'smooth'});
}

async function initPublicConfig() {
  try {
    const cfg = await requestJSON('/api/public/config');
    $('#tab-register-org')?.classList.toggle('hidden', !cfg.allow_org_register);
  } catch {}
}

async function bootstrap() {
  await initPublicConfig();
  try {
    const data = await requestJSON('/api/auth/me');
    state.user = data.user; state.csrf = data.csrf_token;
    showApp();
    if (state.user.must_change_password) openPasswordModal(true);
    else navigate('dashboard');
  } catch {
    showLogin();
  }
}

async function loadDashboard() {
  try {
    const data = await requestJSON('/api/dashboard');
    $('#stat-total').textContent = data.total;
    $('#stat-high').textContent = data.high;
    $('#stat-progress').textContent = data.progress;
    $('#stat-done').textContent = data.done;
    const colors = {Tinggi:'high',Sedang:'medium',Rendah:'low'};
    $('#risk-bars').innerHTML = ['Tinggi','Sedang','Rendah'].map(level => {
      const count = data.distribution[level] || 0;
      const width = data.total ? Math.round(count / data.total * 100) : 0;
      return `<div><div class="risk-row-top"><span>Risiko ${level}</span><b>${count} laporan · ${width}%</b></div><div class="bar"><span class="${colors[level]}" style="width:${width}%"></span></div></div>`;
    }).join('');
    $('#recent-list').innerHTML = data.recent.length ? data.recent.map(r => `
      <div class="recent-item"><span class="pin" style="background:${r.level==='Tinggi'?'#ef4444':r.level==='Sedang'?'#f59e0b':'#22c55e'}"></span>
      <div><strong>${esc(r.title)}</strong><small>${esc(r.code)} · ${esc(r.location)}</small></div><span class="pill ${levelClass(r.level)}">${esc(r.level)}</span></div>`).join('') : '<div class="no-data">Belum ada laporan di instansi ini. Buat laporan pertama untuk memulai.</div>';
    $('#priority-table').innerHTML = data.priority.length ? data.priority.map(r => `
      <tr><td><button class="id-link" data-detail="${r.id}">${esc(r.code)}</button></td><td><b>${esc(r.title)}</b></td><td>${esc(r.location)}</td>
      <td><span class="pill ${levelClass(r.level)}">${esc(r.level)} · ${r.score}</span></td><td><span class="pill ${statusClass(r.status)}">${esc(r.status)}</span></td><td>${esc(r.assignee)}</td></tr>`).join('') : emptyRow(6,'Tidak ada tindak lanjut terbuka.');
  } catch (e) { handleApiError(e); }
}

function buildReportUrl() {
  const params = new URLSearchParams();
  const q = $('#search-input').value.trim();
  const risk = $('#filter-risk').value;
  const status = $('#filter-status').value;
  if (q) params.set('q', q);
  if (risk !== 'all') params.set('risk', risk);
  if (status !== 'all') params.set('status', status);
  return '/api/reports' + (params.size ? `?${params.toString()}` : '');
}
async function loadReports() {
  try {
    const data = await requestJSON(buildReportUrl());
    state.reports = data.items;
    $('#table-count').textContent = `${data.count} laporan tercatat di ${state.user.org_name}`;
    $('#table-empty').classList.toggle('hidden', data.items.length !== 0);
    $('#reports-table').innerHTML = data.items.length ? data.items.map(r => `
      <tr><td><button class="id-link" data-detail="${r.id}">${esc(r.code)}</button></td>
      <td><b>${esc(r.title)}</b><div class="muted">${esc(r.category)}</div></td><td>${esc(r.location)}</td>
      <td>${esc(fmtDate(r.report_date))}</td><td><b>${r.score}</b></td><td><span class="pill ${levelClass(r.level)}">${esc(r.level)}</span></td>
      <td><span class="pill ${statusClass(r.status)}">${esc(r.status)}</span></td><td><button class="icon-btn" data-detail="${r.id}">Detail</button></td></tr>`).join('') : '';
  } catch (e) { handleApiError(e); }
}

async function showDetail(id) {
  try {
    const r = await requestJSON(`/api/reports/${id}`);
    state.currentReportId = id;
    const attachments = (r.attachments || []).map(a => `<div><a href="${esc(apiUrl(a.url))}" target="_blank" rel="noopener">📎 ${esc(a.original_name)}</a><small class="muted"> · ${(a.size_bytes/1024).toFixed(0)} KB</small></div>`).join('') || '<span class="muted">Tidak ada foto terlampir.</span>';
    const history = (r.history || []).map(h => `<div class="timeline-item"><b>${esc(h.event)}</b><small>${esc(h.actor || 'Sistem')} · ${esc(fmtDate(h.created_at,true))}</small>${h.note ? `<p>${esc(h.note)}</p>` : ''}</div>`).join('') || '<div class="muted">Belum ada riwayat.</div>';
    const canManage = ['admin','hse'].includes(state.user.role);
    $('#detail-title').textContent = `${r.code} — ${r.title}`;
    $('#detail-content').innerHTML = `
      <div class="detail-layout"><div>
        <div class="detail-block"><div class="detail-label">Judul temuan</div><div class="detail-value"><b>${esc(r.title)}</b></div></div>
        <div class="detail-block"><div class="detail-label">Uraian kondisi bahaya</div><div class="detail-value">${esc(r.description)}</div></div>
        <div class="detail-block"><div class="detail-label">Lokasi dan kategori</div><div class="detail-value">${esc(r.location)} · ${esc(r.category)}</div></div>
        <div class="detail-block"><div class="detail-label">Pelapor dan waktu</div><div class="detail-value">${esc(r.reporter)} · ${esc(fmtDate(r.report_date,true))}</div></div>
        <div class="detail-block"><div class="detail-label">Foto temuan</div><div class="detail-value">${attachments}</div>${(r.attachments||[]).map(a => `<a href="${esc(apiUrl(a.url))}" target="_blank" rel="noopener"><img class="detail-photo" src="${esc(apiUrl(a.url))}" alt="Foto temuan" loading="lazy"></a>`).join('')}</div>
        <div class="detail-block"><div class="detail-label">Riwayat aktivitas</div><div class="timeline">${history}</div></div>
      </div><div>
        <div class="detail-block"><div class="detail-label">Tingkat risiko</div><div class="detail-value"><span class="pill ${levelClass(r.level)}">${esc(r.level)} · Skor ${r.score}</span><p>Kemungkinan ${r.likelihood} × Dampak ${r.impact}</p></div></div>
        <div class="detail-block"><div class="detail-label">Status</div><div class="detail-value"><span class="pill ${statusClass(r.status)}">${esc(r.status)}</span></div></div>
        <div class="detail-block"><div class="detail-label">Penanggung jawab</div><div class="detail-value">${esc(r.assignee)}</div></div>
        <div class="detail-block"><div class="detail-label">Target penyelesaian</div><div class="detail-value">${esc(fmtDate(r.due_date))}</div></div>
        <div class="detail-block"><div class="detail-label">Tindakan koreksi</div><div class="detail-value">${esc(r.corrective_action || 'Belum dicatat.')}</div></div>
        ${canManage ? `<form id="update-report-form" class="update-form"><h3>Pembaruan tindak lanjut</h3><div class="form-grid">
          <label>Status<select name="status"><option ${r.status==='Terbuka'?'selected':''}>Terbuka</option><option ${r.status==='Dalam Proses'?'selected':''}>Dalam Proses</option><option ${r.status==='Selesai'?'selected':''}>Selesai</option></select></label>
          <label>Penanggung jawab<input name="assignee" value="${esc(r.assignee)}" required></label>
          <label>Target penyelesaian<input name="due_date" type="date" value="${esc(r.due_date||'')}"></label>
          <label class="span-2">Tindakan koreksi / hasil verifikasi<textarea name="corrective_action" rows="3">${esc(r.corrective_action||'')}</textarea></label>
          <label class="span-2">Catatan pembaruan<textarea name="note" rows="2" placeholder="Catatan progres, bukti verifikasi, atau alasan perubahan status"></textarea></label>
        </div><div class="form-actions"><button class="btn primary" type="submit">Simpan pembaruan</button></div></form>` : ''}
        <form id="comment-form" class="update-form"><h3>Tambah catatan</h3><label class="stack-form"><textarea name="note" rows="2" required placeholder="Tambahkan informasi atau klarifikasi pada laporan ini"></textarea></label><div class="form-actions"><button class="btn secondary" type="submit">Kirim catatan</button></div></form>
      </div></div>`;
    $('#detail-modal').classList.remove('hidden');
    $('#update-report-form')?.addEventListener('submit', submitReportUpdate);
    $('#comment-form')?.addEventListener('submit', submitComment);
  } catch (e) { handleApiError(e); }
}
async function submitReportUpdate(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form); setBusy(button,true);
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    await requestJSON(`/api/reports/${state.currentReportId}`, {method:'PATCH',body:JSON.stringify(data)});
    toast('Pembaruan tindak lanjut tersimpan.');
    await showDetail(state.currentReportId); await loadDashboard();
    if ($('#page-monitoring').classList.contains('active')) await loadReports();
  } catch(e) { toast(e.message); } finally { setBusy(button,false); }
}
async function submitComment(event) {
  event.preventDefault();
  const form = event.currentTarget; const button = $('button[type="submit"]', form); setBusy(button,true);
  const note = new FormData(form).get('note');
  try {
    await requestJSON(`/api/reports/${state.currentReportId}/comments`, {method:'POST',body:JSON.stringify({note})});
    toast('Catatan berhasil ditambahkan.'); await showDetail(state.currentReportId);
  } catch(e) { toast(e.message); } finally { setBusy(button,false); }
}

function updateRiskPreview() {
  const likelihood = Number($('#likelihood').value), impact = Number($('#impact').value);
  const scoreEl = $('#preview-score'), levelEl = $('#preview-level'), noteEl = $('#preview-note');
  if (!likelihood || !impact) { scoreEl.textContent='–'; levelEl.className='pill neutral'; levelEl.textContent='Menunggu penilaian'; noteEl.textContent='Pilih nilai kemungkinan dan dampak untuk menghitung skor.'; return; }
  const score = likelihood * impact; const level = score >= 15 ? 'Tinggi' : score >= 6 ? 'Sedang' : 'Rendah';
  scoreEl.textContent=score; levelEl.className=`pill ${levelClass(level)}`; levelEl.textContent=level;
  noteEl.textContent = level === 'Tinggi' ? 'Prioritaskan pengendalian segera dan koordinasikan tindakan dengan penanggung jawab proyek.' : level === 'Sedang' ? 'Rencanakan tindakan pengendalian dan pantau sampai risiko dapat diterima.' : 'Tetap lakukan pengendalian rutin dan pemantauan sesuai prosedur proyek.';
}

async function loadUsers() {
  try {
    syncOrgUI();
    const data = await requestJSON('/api/users');
    $('#users-table').innerHTML = data.items.length ? data.items.map(u => `
      <tr><td><b>${esc(u.full_name)}</b><div class="muted">@${esc(u.username)}</div></td><td>${esc(roleLabel(u.role))}</td>
      <td><span class="pill ${u.active?'done':'neutral'}">${u.active?'Aktif':'Nonaktif'}</span></td>
      <td>${u.id===state.user.id ? '<span class="muted">Akun Anda</span>' : `<button class="icon-btn" data-user-toggle="${u.id}" data-active="${u.active?0:1}">${u.active?'Nonaktifkan':'Aktifkan'}</button>`}</td></tr>`).join('') : emptyRow(4,'Belum ada pengguna.');
  } catch(e) { handleApiError(e); }
}
async function handleApiError(error) {
  if (error.status === 401) { state.user=null; state.csrf=''; showLogin(); return; }
  if (error.status === 428 && error.payload?.must_change_password) { openPasswordModal(true); return; }
  toast(error.message || 'Terjadi kesalahan.');
}

// Auth Event Listeners
$$('.auth-tab').forEach(tab => tab.addEventListener('click', () => switchAuthMode(tab.dataset.authMode)));

$('#login-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget; const button = $('button[type="submit"]',form); setBusy(button,true,'Memeriksa...');
  $('#login-error').textContent='';
  const formData = new FormData(form);
  try {
    const data = await requestJSON('/api/auth/login',{
      method:'POST',
      body:JSON.stringify({
        org_code: formData.get('org_code'),
        username: formData.get('username'),
        password: formData.get('password')
      })
    });
    state.user=data.user; state.csrf=data.csrf_token; showApp();
    if (state.user.must_change_password) openPasswordModal(true); else navigate('dashboard');
  } catch(e) { $('#login-error').textContent=e.message; } finally { setBusy(button,false); }
});

$('#join-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget; const button = $('button[type="submit"]',form); setBusy(button,true,'Bergabung...');
  $('#join-error').textContent='';
  const formData = new FormData(form);
  try {
    const data = await requestJSON('/api/auth/join-org',{
      method:'POST',
      body:JSON.stringify({
        invite_code: formData.get('invite_code'),
        full_name: formData.get('full_name'),
        username: formData.get('username'),
        password: formData.get('password')
      })
    });
    state.user=data.user; state.csrf=data.csrf_token; showApp();
    toast(data.message || 'Berhasil bergabung ke instansi!');
    navigate('dashboard');
  } catch(e) { $('#join-error').textContent=e.message; } finally { setBusy(button,false); }
});

$('#register-org-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget; const button = $('button[type="submit"]',form); setBusy(button,true,'Membuat Workspace...');
  $('#register-org-error').textContent='';
  const formData = new FormData(form);
  try {
    const data = await requestJSON('/api/auth/register-org',{
      method:'POST',
      body:JSON.stringify({
        org_name: formData.get('org_name'),
        org_code: formData.get('org_code'),
        full_name: formData.get('full_name'),
        username: formData.get('username'),
        password: formData.get('password')
      })
    });
    state.user=data.user; state.csrf=data.csrf_token; showApp();
    toast(data.message || 'Workspace instansi berhasil dibuat!');
    navigate('users');
  } catch(e) { $('#register-org-error').textContent=e.message; } finally { setBusy(button,false); }
});

// Organization Admin Listeners
$('#copy-invite-btn')?.addEventListener('click', async () => {
  if (!state.user?.invite_code) return;
  const shareText = `Silakan gabung ke SiTanggap K3 (${state.user.org_name})
Kode Undangan: ${state.user.invite_code}
Kode Instansi (untuk login): ${state.user.org_code}`;
  try {
    await navigator.clipboard.writeText(shareText);
    toast('Info undangan instansi berhasil disalin ke clipboard.');
  } catch {
    toast(`Kode Undangan: ${state.user.invite_code}`);
  }
});

$('#rotate-invite-btn')?.addEventListener('click', async () => {
  if (!confirm('Buat Kode Undangan baru? Kode undangan lama tidak akan berlaku lagi.')) return;
  try {
    const data = await requestJSON('/api/organization/rotate-invite', {method:'POST', body:JSON.stringify({})});
    state.user.invite_code = data.invite_code;
    syncOrgUI();
    toast(data.message);
  } catch(e) { toast(e.message); }
});

$('#org-settings-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  setBusy(button, true, 'Menyimpan...');
  const formData = new FormData(form);
  try {
    const data = await requestJSON('/api/organization', {
      method: 'PATCH',
      body: JSON.stringify({
        name: formData.get('name'),
        allow_member_signup: formData.get('allow_member_signup') === '1'
      })
    });
    state.user.org_name = data.name;
    state.user.allow_member_signup = data.allow_member_signup;
    syncOrgUI();
    toast(data.message);
  } catch(e) { toast(e.message); } finally { setBusy(button, false); }
});

$$('.nav-item').forEach(button => button.addEventListener('click', () => navigate(button.dataset.page)));
$$('[data-go]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.go)));
$('#logout-button').addEventListener('click', async () => {
  try { await requestJSON('/api/auth/logout',{method:'POST',body:JSON.stringify({})}); } catch {}
  state.user=null; state.csrf=''; showLogin();
});
$('#change-password-open').addEventListener('click', () => openPasswordModal(false));
$('#password-close').addEventListener('click', closePasswordModal);
$('#password-modal').addEventListener('click', event => { if(event.target.id==='password-modal') closePasswordModal(); });
$('#password-form').addEventListener('submit', async event => {
  event.preventDefault(); const form=event.currentTarget; const button=$('button[type="submit"]',form); const data=new FormData(form);
  $('#password-error').textContent='';
  if (data.get('new_password') !== data.get('confirm_password')) { $('#password-error').textContent='Konfirmasi kata sandi baru tidak sama.'; return; }
  setBusy(button,true);
  try {
    await requestJSON('/api/auth/change-password',{method:'POST',body:JSON.stringify({current_password:data.get('current_password'),new_password:data.get('new_password')})});
    state.user.must_change_password=false; state.forcedPasswordChange=false; $('#password-modal').classList.add('hidden'); form.reset(); toast('Kata sandi berhasil diubah.'); navigate('dashboard');
  } catch(e) { $('#password-error').textContent=e.message; } finally { setBusy(button,false); }
});

$('#report-form').addEventListener('reset', () => setTimeout(() => { $('#report-date').value=localDateTime(); $('#reporter').value=state.user?.full_name||''; updateRiskPreview(); },0));
$('#report-form').addEventListener('submit', async event => {
  event.preventDefault(); const form=event.currentTarget; const button=$('button[type="submit"]',form); setBusy(button,true,'Menyimpan...');
  try {
    const result=await requestJSON('/api/reports',{method:'POST',body:new FormData(form)});
    form.reset(); $('#report-date').value=localDateTime(); $('#reporter').value=state.user.full_name;
    updateRiskPreview(); toast(`Laporan ${result.code} berhasil disimpan.`); navigate('monitoring');
  } catch(e) { toast(e.message); } finally { setBusy(button,false); }
});
$('#likelihood').addEventListener('change',updateRiskPreview);
$('#impact').addEventListener('change',updateRiskPreview);
$('#search-input').addEventListener('input', debounce(loadReports,300));
$('#filter-risk').addEventListener('change',loadReports);
$('#filter-status').addEventListener('change',loadReports);
$('#export-button').addEventListener('click', async () => {
  try {
    const blob=await requestBlob(buildReportUrl().replace('/api/reports','/api/reports/export.csv'));
    const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=`sitanggap_k3_${state.user.org_code}_laporan.csv`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url); toast('File CSV instansi berhasil diunduh.');
  } catch(e) { toast(e.message); }
});
$('#modal-close').addEventListener('click',()=>$('#detail-modal').classList.add('hidden'));
$('#detail-modal').addEventListener('click',event=>{if(event.target.id==='detail-modal')$('#detail-modal').classList.add('hidden')});
$('#refresh-users').addEventListener('click',loadUsers);
$('#user-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget;const button=$('button[type="submit"]',form);const data=Object.fromEntries(new FormData(form).entries());setBusy(button,true,'Membuat...');
  try{await requestJSON('/api/users',{method:'POST',body:JSON.stringify(data)});form.reset();toast('Akun anggota berhasil dibuat.');await loadUsers();}
  catch(e){toast(e.message);}finally{setBusy(button,false);}
});
$('#users-table').addEventListener('click',async event=>{
  const button=event.target.closest('[data-user-toggle]');if(!button)return;
  const id=button.dataset.userToggle;const active=button.dataset.active==='1';
  const action=active?'mengaktifkan':'menonaktifkan';if(!confirm(`Yakin ingin ${action} akun ini?`))return;
  try{await requestJSON(`/api/users/${id}`,{method:'PATCH',body:JSON.stringify({active})});toast('Status akun diperbarui.');await loadUsers();}catch(e){toast(e.message);}
});

document.addEventListener('click',event=>{
  const target=event.target.closest('[data-detail]');if(target)showDetail(target.dataset.detail);
});
function debounce(fn,delay){let timer;return(...args)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...args),delay);};}

$('#report-date').value=localDateTime();
bootstrap();
