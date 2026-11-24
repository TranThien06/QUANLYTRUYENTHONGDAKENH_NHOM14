'use strict';
const $ = (selector) => document.querySelector(selector);
const state = { token: sessionStorage.getItem('mintspace-token'), user: null, workspaces: [], editing: null, canEdit: false, busy: false, generation: 0 };
const roles = { admin: 'Quản trị viên', manager: 'Quản lý', editor: 'Biên tập viên', approver: 'Người duyệt', viewer: 'Người xem' };
const form = $('#workspace-form');
const prefetchedReads = new Map();
const prefetchLifetime = 5000;
let prefetchRevision = 0;

function prefetchRead(path) {
  if (!state.token || navigator.connection?.saveData) return;
  const cached = prefetchedReads.get(path);
  if (cached?.token === state.token && cached.expires > Date.now()) return;
  if (prefetchedReads.size >= 24) prefetchedReads.delete(prefetchedReads.keys().next().value);
  const entry = {
    token: state.token,
    revision: prefetchRevision,
    expires: Date.now() + prefetchLifetime,
    promise: api(path, {}, true).then(data => ({ data }), () => null),
  };
  prefetchedReads.set(path, entry);
}

async function readPrefetched(path) {
  const entry = prefetchedReads.get(path);
  prefetchedReads.delete(path);
  if (entry?.token === state.token && entry.expires > Date.now()) {
    const result = await entry.promise;
    if (result && entry.token === state.token && entry.revision === prefetchRevision) return result.data;
  }
  return api(path);
}

function clearPrefetchedReads() {
  prefetchRevision++;
  prefetchedReads.clear();
}

function prefetchOnIntent(button, paths) {
  const prefetch = () => {
    if (!button.hidden && !button.disabled) paths().forEach(prefetchRead);
  };
  button.onpointerenter = button.onpointerdown = button.onfocus = prefetch;
}
function notify(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => { $('#toast').hidden = true; }, 4500); }
function message(text, login = false) {
  const box = $('#list-message'); box.replaceChildren(); box.hidden = !text;
  box.append(document.createTextNode(text));
  if (login) { const button = document.createElement('button'); button.className = 'secondary'; button.textContent = 'Đăng nhập'; button.onclick = () => $('#auth-dialog').showModal(); box.append(button); }
}
function clearSession() {
  clearPrefetchedReads();
  window.closePostSession?.();
  state.generation++; state.token = null; state.user = null; state.workspaces = []; sessionStorage.removeItem('mintspace-token');
  sessionStorage.removeItem('orbitspace-oauth-pending'); sessionStorage.removeItem('orbitspace-oauth-result');
  $('#avatar').hidden = true; $('#account-chevron').hidden = true; $('#register-button').hidden = false;
  $('#account-name').textContent = 'Đăng nhập'; $('#avatar').textContent = 'O';
  $('#channels-dialog').close(); $('#workspace-dialog').close(); $('#account-dialog').close(); $('#members-dialog').close(); $('#publish-dialog').close(); render();
  message('Đăng nhập để xem workspace của bạn và bắt đầu cộng tác.', true);
}
async function api(path, options = {}, speculative = false) {
  const isWrite = options.method && options.method.toUpperCase() !== 'GET';
  if (isWrite) clearPrefetchedReads();
  const authToken = state.token;
  let response;
  try { response = await fetch('/api/v1' + path, { ...options, headers: {
    ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(state.token ? { Authorization: 'Bearer ' + state.token } : {}), ...options.headers,
  } }); }
  catch { throw new Error('Không kết nối được máy chủ. Vui lòng kiểm tra kết nối và thử lại.'); }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !speculative && authToken === state.token && path !== '/auth/login') { clearSession(); notify('Phiên đăng nhập hết hạn. Vui lòng đăng nhập lại.'); }
    const error = new Error(body.error?.message || 'Không thể thực hiện thao tác. Vui lòng thử lại.');
    error.status = response.status; error.details = body.error?.details; throw error;
  }
  if (isWrite) clearPrefetchedReads();
  return body.data;
}
async function load(signedInUser = state.user) {
  if (!state.token) { clearSession(); return; }
  const generation = ++state.generation;
  message('Đang tải workspace…');
  try {
    const showUser = user => {
      if (generation !== state.generation) return;
      state.user = user;
      $('#avatar').hidden = false; $('#account-chevron').hidden = false; $('#register-button').hidden = true;
      $('#account-name').textContent = user.full_name; $('#avatar').textContent = user.full_name.trim().charAt(0).toUpperCase();
    };
    const profile = signedInUser ? showUser(signedInUser) : api('/me').then(showUser);
    const [, firstRows] = await Promise.all([profile, api('/workspaces?limit=100&page=1')]);
    if (generation !== state.generation) return;
    const items = [...firstRows];
    state.workspaces = items;
    render();
    let rows = firstRows;
    for (let page = 2; rows.length === 100; page++) {
      rows = await api(`/workspaces?limit=100&page=${page}`);
      if (generation !== state.generation) return;
      items.push(...rows);
      if (rows.length) render();
    }
  } catch (error) { if (generation === state.generation) { state.workspaces = []; render(); message(error.message); } }
}
function element(tag, className, text) { const el = document.createElement(tag); el.className = className; if (text !== undefined) el.textContent = text; return el; }
function render() {
  const list = $('#workspace-list'); list.replaceChildren();
  $('#total').textContent = state.workspaces.length; $('#nav-count').textContent = state.workspaces.length;
  const query = $('#search').value.trim().toLocaleLowerCase('vi');
  const visible = state.workspaces.filter(w => `${w.name} ${w.slug}`.toLocaleLowerCase('vi').includes(query));
  for (const ws of visible) {
    const card = element('button', 'workspace-card'); card.type = 'button'; card.setAttribute('aria-label', 'Xem workspace ' + ws.name);
    const top = element('div', 'card-top');
    // Initials keep the list readable without loading untrusted external logo URLs.
    top.append(element('span', 'workspace-icon', ws.name.trim().split(/\s+/).slice(0, 2).map(s => s[0]).join('').toUpperCase()), element('span', 'role-badge', roles[ws.role] || ws.role));
    const bottom = element('div', 'card-bottom'); bottom.append(element('span', '', ws.timezone === 'Asia/Ho_Chi_Minh' ? '◷ Việt Nam · UTC+7' : '◷ ' + ws.timezone), element('span', '', 'Chi tiết →'));
    card.append(top, element('h3', '', ws.name), element('div', 'workspace-slug', 'workspace / ' + ws.slug), bottom);
    card.onclick = () => openWorkspace(ws.workspace_id);
    prefetchOnIntent(card, () => ['/workspaces/' + ws.workspace_id + '/access?include_workspace=true']);
    list.append(card);
  }
  const add = element('button', 'workspace-card add-card'); add.type = 'button';
  add.append(element('span', 'add-circle', '+'), element('strong', '', 'Tạo workspace mới'), element('small', '', 'Thêm không gian cho ý tưởng tiếp theo'));
  add.onclick = createWorkspace; list.append(add);
  message(!state.token ? 'Đăng nhập để xem workspace của bạn và bắt đầu cộng tác.' : !state.workspaces.length ? 'Chưa có workspace. Tạo không gian đầu tiên cho đội ngũ của bạn.' : !visible.length ? 'Không tìm thấy workspace phù hợp.' : '', !state.token);
}
const workspaceFields = ['name', 'slug', 'logo_url'];
function resetErrors() {
  for (const key of workspaceFields) { $('#' + key + '-error').textContent = ''; form.elements[key].removeAttribute('aria-invalid'); }
  $('#form-error').hidden = true;
}
function formError(text) { $('#form-error').textContent = text; $('#form-error').hidden = false; }
function prepareForm(isNew) {
  $('#channels-button').hidden = true; $('#members-button').hidden = true; $('#posts-button').hidden = true; resetErrors(); form.reset(); state.editing = null; state.canEdit = false;
  $('#workspace-fields').disabled = true; $('#save-button').disabled = true;
  $('#save-button').hidden = false; $('#save-button').textContent = isNew ? 'Tạo workspace' : 'Lưu thay đổi';
  $('#dialog-title').textContent = isNew ? 'Tạo workspace mới' : 'Thông tin workspace';
  $('#permission-notice').hidden = true; $('#save-hint').textContent = 'Thông tin có dấu * là bắt buộc';
}
function createWorkspace() {
  if (!state.token) { $('#auth-dialog').showModal(); return; }
  prepareForm(true); state.canEdit = true; $('#workspace-fields').disabled = false; $('#save-button').disabled = false;
  $('#workspace-dialog').showModal(); form.elements.name.focus();
}
let detailRequest = 0;
function fillWorkspaceForm(ws) {
  for (const key of workspaceFields) {
    form.elements[key].value = ws[key] || '';
  }
}
async function openWorkspace(id) {
  prepareForm(false); state.editing = id;
  const request = ++detailRequest;
  const listed = state.workspaces.find(ws => ws.workspace_id === id);
  if (listed) fillWorkspaceForm(listed);
  $('#save-button').hidden = true;
  $('#permission-notice').textContent = 'Đang kiểm tra quyền truy cập…'; $('#permission-notice').hidden = false;
  $('#workspace-dialog').showModal();
  try {
    const base = '/workspaces/' + id;
    const access = await readPrefetched(base + '/access?include_workspace=true');
    if (request !== detailRequest || !$('#workspace-dialog').open) return;
    fillWorkspaceForm(access.workspace);
    $('#channels-button').hidden = false; $('#members-button').hidden = false; state.canEdit = access.permissions.includes('workspace.manage');
    $('#channels-button').onclick = () => {
      if (state.busy) return;
      $('#workspace-dialog').close();
      openChannels(id, access.workspace.name, access);
    };
    $('#members-button').onclick = () => {
      if (state.busy) return;
      $('#workspace-dialog').close();
      openMembers(id, access);
    };
    $('#posts-button').hidden = false;
    $('#posts-button').onclick = () => openPublishDialog(id, access.permissions);
    prefetchOnIntent($('#channels-button'), () => [channelListPath(id, 1), '/platforms/capabilities']);
    prefetchOnIntent($('#members-button'), () => [
      base + '/members?limit=100&page=1',
      ...(access.permissions.includes('member.manage') ? [base + '/invitations?limit=100&page=1'] : []),
    ]);
    prefetchOnIntent($('#posts-button'), () => [base + '/posts?limit=100&page=1']);
    $('#workspace-fields').disabled = !state.canEdit; $('#save-button').disabled = !state.canEdit; $('#save-button').hidden = !state.canEdit;
    $('#permission-notice').hidden = false; $('#permission-notice').textContent = state.canEdit ? `Vai trò: ${roles[access.role] || access.role}. Bạn có quyền cập nhật workspace này.` : `Vai trò: ${roles[access.role] || access.role}. Bạn chỉ có quyền xem thông tin workspace.`;
    $('#save-hint').textContent = state.canEdit ? 'Thông tin có dấu * là bắt buộc' : 'Thông tin đang ở chế độ chỉ xem';
  } catch (error) {
    if (request !== detailRequest || !$('#workspace-dialog').open) return;
    form.reset();
    $('#permission-notice').hidden = true;
    formError(error.message);
  }
}
$('#workspace-dialog').addEventListener('close', () => { detailRequest++; });
form.addEventListener('submit', async event => {
  event.preventDefault(); if (state.busy || !state.canEdit) return;
  resetErrors();
  const values = Object.fromEntries(workspaceFields.map(key => [key, form.elements[key].value.trim()]));
  const errors = {};
  if (!values.name) errors.name = 'Vui lòng nhập tên workspace.';
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(values.slug)) errors.slug = 'Nhập đường dẫn gồm chữ thường không dấu, số và dấu gạch ngang.';
  if (values.logo_url) { try { const url = new URL(values.logo_url); if (!['http:', 'https:'].includes(url.protocol)) throw new Error(); } catch { errors.logo_url = 'Nhập đường dẫn bắt đầu bằng http:// hoặc https://.'; } }
  for (const [key, text] of Object.entries(errors)) { $('#' + key + '-error').textContent = text; form.elements[key].setAttribute('aria-invalid', 'true'); }
  if (Object.keys(errors).length) { form.elements[Object.keys(errors)[0]].focus(); return; }
  state.busy = true; const id = state.editing;
  $('#save-button').disabled = true; $('#save-button').textContent = 'Đang lưu…'; $('#workspace-fields').disabled = true;
  $('#cancel-dialog').disabled = true; $('#close-dialog').disabled = true;
  try {
    const saved = await api(id ? '/workspaces/' + id : '/workspaces', { method: id ? 'PATCH' : 'POST', body: JSON.stringify({ ...values, logo_url: values.logo_url || null }) });
    const previous = state.workspaces.find(w => w.workspace_id === saved.workspace_id);
    if (previous) Object.assign(previous, saved); else state.workspaces.push({ ...saved, role: 'admin' });
    $('#search').value = ''; render(); $('#workspace-dialog').close(); notify(id ? 'Đã lưu thay đổi workspace.' : 'Đã tạo workspace thành công.');
  } catch (error) {
    formError(error.message);
    if ([403, 404].includes(error.status)) { state.canEdit = false; $('#permission-notice').hidden = false; $('#permission-notice').textContent = 'Bạn không còn quyền cập nhật workspace này. Vui lòng tải lại danh sách.'; }
    if (error.details) for (const detail of error.details) { const key = detail.loc?.at(-1); if (workspaceFields.includes(key)) { $('#' + key + '-error').textContent = 'Dữ liệu không hợp lệ. Vui lòng kiểm tra lại.'; form.elements[key].setAttribute('aria-invalid', 'true'); } }
  } finally {
    state.busy = false; $('#workspace-fields').disabled = !state.canEdit; $('#save-button').disabled = !state.canEdit;
    $('#save-button').textContent = id ? 'Lưu thay đổi' : 'Tạo workspace'; $('#cancel-dialog').disabled = false; $('#close-dialog').disabled = false;
  }
});
$('#workspace-dialog').addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
$('#create-button').onclick = createWorkspace;
$('#search').oninput = render;
$('#nav-workspaces').onclick = () => { $('#search').value = ''; load(); };
$('#close-dialog').onclick = $('#cancel-dialog').onclick = () => { if (!state.busy) $('#workspace-dialog').close(); };
$('#close-auth').onclick = () => $('#auth-dialog').close();
$('#account-button').onclick = () => {
  if (!state.user) { $('#auth-dialog').showModal(); return; }
  $('#profile-name').textContent = state.user.full_name; $('#profile-email').textContent = state.user.email; $('#account-dialog').showModal();
};
$('#close-account').onclick = () => $('#account-dialog').close();
$('#logout-button').onclick = async () => { try { await api('/auth/logout', { method: 'POST' }); clearSession(); notify('Đã đăng xuất.'); } catch (error) { notify(error.message); } };
$('#auth-form').addEventListener('submit', async event => {
  event.preventDefault();
  if ($('#login-button').disabled) return;
  $('#login-button').disabled = true; $('#login-button').textContent = 'Đang đăng nhập…'; $('#auth-error').hidden = true;
  try {
    const auth = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email: event.target.elements.email.value.trim(), password: event.target.elements.password.value }) });
    state.token = auth.access_token; sessionStorage.setItem('mintspace-token', state.token); event.target.reset(); $('#auth-dialog').close(); load(auth.user);
  } catch (error) { $('#auth-error').textContent = error.message; $('#auth-error').hidden = false; }
  finally { $('#login-button').disabled = false; $('#login-button').textContent = 'Đăng nhập'; }
});
let registering = false;
function openRegister() {
  $('#auth-dialog').close(); $('#register-form').reset();
  $('#register-error').hidden = true; $('#register-success').hidden = true;
  $('#register-fields').hidden = false; $('#register-submit').hidden = false; $('#register-verify-button').hidden = true;
  $('#register-dialog').showModal();
}
$('#register-button').onclick = $('#auth-register-button').onclick = openRegister;
$('#close-register').onclick = () => { if (!registering) $('#register-dialog').close(); };
$('#register-dialog').addEventListener('cancel', event => { if (registering) event.preventDefault(); });
$('#register-verify-button').onclick = () => {
  if (typeof window.openEmailVerification === 'function') window.openEmailVerification($('#auth-form').elements.email.value);
  else window.location.assign('/verify-email');
};
$('#register-login-button').onclick = () => { $('#register-dialog').close(); $('#auth-dialog').showModal(); };
$('#register-form').addEventListener('submit', async event => {
  event.preventDefault(); if (registering) return;
  const fields = event.target.elements;
  const full_name = fields.full_name.value.trim(), email = fields.email.value.trim(), password = fields.password.value;
  $('#register-error').hidden = true;
  function showError(text) { $('#register-error').textContent = text; $('#register-error').hidden = false; }
  if (!full_name) { showError('Vui lòng nhập họ và tên.'); fields.full_name.focus(); return; }
  if (password.length < 8 || new TextEncoder().encode(password).length > 72) { showError('Mật khẩu cần ít nhất 8 ký tự và không quá 72 byte UTF-8.'); fields.password.focus(); return; }
  if (password !== fields.confirm_password.value) { showError('Mật khẩu nhập lại chưa khớp.'); fields.confirm_password.focus(); return; }
  registering = true; $('#register-fields').disabled = true;
  $('#register-submit').disabled = true; $('#register-submit').textContent = 'Đang đăng ký…';
  $('#close-register').disabled = true; $('#register-login-button').disabled = true;
  try {
    const result = await api('/auth/register', { method: 'POST', body: JSON.stringify({ full_name, email, password }) });
    event.target.reset(); $('#register-fields').hidden = true; $('#register-submit').hidden = true;
    $('#register-success').textContent = result.message || 'Đăng ký thành công. Nhập mã 6 chữ số đã gửi qua email để xác minh.';
    $('#register-success').hidden = false; $('#auth-form').elements.email.value = email;
    $('#register-verify-button').hidden = false;
    if (typeof window.openEmailVerification === 'function') window.openEmailVerification(email);
  } catch (error) { showError(error.message); }
  finally {
    registering = false; $('#register-fields').disabled = false; $('#register-submit').disabled = false;
    $('#register-submit').textContent = 'Đăng ký'; $('#close-register').disabled = false; $('#register-login-button').disabled = false;
  }
});
load();
