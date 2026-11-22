'use strict';

// Each opening belongs to one workspace. Ignore responses from older openings.
const channelsState = { workspaceId: null, rows: [], version: 0, opening: 0, page: 1, canManage: false };
const channelPlatforms = { facebook: 'Facebook', instagram: 'Instagram', tiktok: 'TikTok' };
const channelStatuses = {
  connected: 'Đã kết nối', expired: 'Cần kết nối lại',
  error: 'Lỗi kết nối', disconnected: 'Đã ngắt kết nối', revoked: 'Đã thu hồi quyền'
};
const channelTypes = { page: 'Trang', business: 'Doanh nghiệp', creator: 'Nhà sáng tạo', profile: 'Cá nhân' };
const channelSelection = $('#channel-selection');
const channelConnect = $('#connect-channel');
let channelResult = null;
let searchTimer;
let channelDetailRequest = 0;
const pageSize = 20;
const platformPicker = $('#channel-platform-picker');
let availablePlatforms = [];
$('#channel-status').add(new Option('Đã thu hồi quyền', 'revoked'));

function channelDate(value) {
  if (!value) return 'Chưa có';
  return new Date(value.replace(' ', 'T') + 'Z').toLocaleString('vi-VN');
}

function renderChannels() {
  const rows = channelsState.rows;
  const list = $('#channel-list');
  list.replaceChildren();
  const connected = channelsState.rows.filter(row => row.connection_status === 'connected').length;
  $('#channels-summary').hidden = false;
  $('#channels-summary').textContent = `${rows.length} kênh trên trang này · ${connected} đang kết nối`;
  $('#channels-status').textContent = rows.length ? '' : 'Không tìm thấy kênh phù hợp.';

  for (const row of rows) {
    const card = element('article', 'channel-card');
    const header = element('div', 'channel-header');
    const platform = channelPlatforms[row.platform] || row.platform;
    const identity = element('div', 'channel-identity');
    const icon = element('span', `channel-icon channel-${row.platform}`, ({ facebook: 'f', instagram: '◎', tiktok: '♪' })[row.platform]);
    icon.setAttribute('aria-hidden', 'true');
    const name = element('div');
    const demo = row.external_account_id === `mock-${row.platform}`;
    name.append(element('small', 'channel-platform', demo ? platform + ' · Kênh mẫu' : platform), element('h3', '', row.account_name));
    identity.append(icon, name);
    if (row.avatar_url && /^https:\/\//i.test(row.avatar_url)) {
      const avatar = element('img', 'channel-avatar');
      avatar.src = row.avatar_url;
      avatar.alt = '';
      avatar.loading = 'lazy';
      avatar.referrerPolicy = 'no-referrer';
      avatar.onerror = () => avatar.remove();
      identity.prepend(avatar);
    }
    const badge = element('span', `channel-badge channel-status-${row.connection_status}`,
      channelStatuses[row.connection_status] || 'Chưa xác định');
    header.append(identity, badge);
    const details = element('dl', 'channel-details');
    for (const [label, value] of [
      ['ID tài khoản', row.external_account_id],
      ['Workspace', $('#channels-workspace').textContent],
      ['Loại tài khoản', channelTypes[row.account_type] || row.account_type],
      ['Ngày kết nối', channelDate(row.connected_at)],
      ['Đồng bộ số liệu', channelDate(row.last_metrics_sync_at)],
      ['Đồng bộ hộp thư', channelDate(row.last_inbox_sync_at)],
      ['Quyền API', row.scopes == null ? 'Chưa ghi nhận' : `${row.scopes.split(',').filter(Boolean).length} quyền`],
      ['Hạn token', row.token_expires_at ? channelDate(row.token_expires_at) : 'Không có thông tin']
    ]) {
      const item = element('div');
      item.append(element('dt', '', label), element('dd', '', value));
      details.append(item);
    }
    card.append(header, details);
    if (row.connection_status === 'expired') card.append(element('p', 'channel-note', 'Quyền truy cập đã hết hạn hoặc không còn token. Cần kết nối lại tài khoản.'));
    if (row.connection_status === 'disconnected') card.append(element('p', 'channel-note', 'Tài khoản đã ngắt kết nối với workspace này.'));
    if (row.status_message && row.connection_status !== 'disconnected') card.append(element('p', 'channel-note', channelErrorMessage(row.status_message)));
    card.append(channelMenu(row));
    list.append(card);
  }
}

async function loadChannels() {
  const version = ++channelsState.version;
  const workspaceId = channelsState.workspaceId;
  const page = channelsState.page;
  channelsState.rows = [];
  $('#channel-list').replaceChildren();
  $('#channels-summary').hidden = true;
  $('#channels-error').hidden = true;
  $('#channels-status').textContent = 'Đang tải danh sách kênh…';
  $('#channel-list').setAttribute('aria-busy', 'true');
  $('#refresh-channels').disabled = true;
  try {
    const filters = new URLSearchParams({ limit: pageSize, page, q: $('#channel-search').value.trim() });
    if ($('#channel-platform').value) filters.set('platform', $('#channel-platform').value);
    if ($('#channel-status').value) filters.set('status', $('#channel-status').value);
    const path = `/workspaces/${workspaceId}/social-accounts?`;
    const rows = await api(path + filters);
    if (version !== channelsState.version || !$('#channels-dialog').open) return;
    if (!rows.length && page > 1) {
      channelsState.page--;
      return loadChannels();
    }
    filters.set('page', page + 1);
    const hasNext = rows.length === pageSize && (await api(path + filters)).length > 0;
    if (version !== channelsState.version || !$('#channels-dialog').open) return;
    channelsState.rows = rows;
    $('#channel-pagination').hidden = page === 1 && !hasNext;
    $('#channel-prev').disabled = page === 1;
    $('#channel-next').disabled = !hasNext;
    $('#channel-page').textContent = `Trang ${page}`;
    renderChannels();
  } catch (error) {
    if (version !== channelsState.version || !$('#channels-dialog').open) return;
    $('#channels-status').textContent = '';
    $('#channels-error').textContent = error.message;
    $('#channels-error').hidden = false;
  } finally {
    if (version === channelsState.version) {
      $('#refresh-channels').disabled = false;
      $('#channel-list').setAttribute('aria-busy', 'false');
    }
  }
}

async function openChannels(workspaceId, name) {
  const opening = ++channelsState.opening;
  channelsState.workspaceId = workspaceId;
  channelsState.page = 1;
  channelsState.canManage = false;
  $('#channels-workspace').textContent = name;
  $('#channel-search').value = '';
  $('#channel-status').value = '';
  $('#channel-platform').value = '';
  $('#channel-pagination').hidden = true;
  $('#channel-detail').hidden = true;
  platformPicker.hidden = true;
  channelConnect.setAttribute('aria-expanded', 'false');
  $('#channel-connect-controls').hidden = true;
  $('#channel-connect-mode').hidden = true;
  $('#channel-connect-error').hidden = true;
  channelConnect.disabled = false;
  availablePlatforms = [];
  resetChannelSelection();
  $('#channels-dialog').showModal();
  loadChannels();
  try {
    const [access, ...capabilities] = await Promise.all([
      api(`/workspaces/${workspaceId}/access`),
      ...Object.keys(channelPlatforms).map(platform => api(`/platforms/${platform}/capabilities`))
    ]);
    if (opening !== channelsState.opening || !isCurrentChannels(workspaceId)) return;
    channelsState.canManage = access.permissions.includes('channel.manage');
    availablePlatforms = capabilities.filter(option => option.oauth_enabled);
    const hasDemo = availablePlatforms.some(option => option.oauth_ready && option.mode === 'mock');
    $('#channel-connect-mode').hidden = !hasDemo;
    $('#channel-connect-controls').hidden = !channelsState.canManage && !hasDemo;
    channelConnect.hidden = !channelsState.canManage || !availablePlatforms.length;
    channelConnect.disabled = !availablePlatforms.some(option => option.oauth_ready);
    const singlePlatform = availablePlatforms.length === 1 ? availablePlatforms[0].platform : null;
    channelConnect.textContent = singlePlatform ? `Kết nối ${channelPlatforms[singlePlatform]}` : '+ Kết nối kênh';
    for (const button of platformPicker.querySelectorAll('button')) {
      const option = availablePlatforms.find(item => item.platform === button.dataset.platform);
      button.hidden = !option;
      button.disabled = !option?.oauth_ready;
    }
    if (!$('#refresh-channels').disabled) renderChannels();
    return channelsState.canManage;
  } catch (error) {
    if (isCurrentChannels(workspaceId)) showChannelError(error.message);
  }
}

$('#channels-button').onclick = () => {
  if (state.busy || !state.editing) return;
  $('#workspace-dialog').close();
  openChannels(state.editing, form.elements.name.value);
};
$('#close-channels').onclick = () => $('#channels-dialog').close();
$('#channels-dialog').addEventListener('close', () => {
  channelsState.version++;
  channelsState.opening++;
  channelDetailRequest++;
  clearTimeout(searchTimer);
  channelsState.rows = [];
  resetChannelSelection();
  $('#channel-list').replaceChildren();
});
$('#refresh-channels').onclick = loadChannels;
function filterChannels() {
  clearTimeout(searchTimer);
  channelsState.page = 1;
  loadChannels();
}
$('#channel-search').oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(filterChannels, 250);
};
$('#channel-status').onchange = $('#channel-platform').onchange = filterChannels;
$('#channel-prev').onclick = () => { channelsState.page--; loadChannels(); };
$('#channel-next').onclick = () => { channelsState.page++; loadChannels(); };

function isCurrentChannels(workspaceId) {
  return $('#channels-dialog').open && channelsState.workspaceId === workspaceId;
}

function showChannelError(message) {
  const box = $('#channel-connect-error');
  box.textContent = message;
  box.hidden = false;
}

function channelErrorMessage(code) {
  return ({
    TOKEN_EXPIRED: 'Quyền truy cập đã hết hạn. Hãy kết nối lại.',
    TOKEN_REVOKED: 'Nền tảng đã thu hồi quyền truy cập. Hãy kết nối lại.',
    RECONNECT_REQUIRED: 'Hãy cấp quyền lại trên nền tảng.',
    PROVIDER_NETWORK: 'Không liên lạc được với nền tảng. Hãy thử lại sau.',
    RATE_LIMIT: 'Nền tảng đang giới hạn yêu cầu. Hãy thử lại sau.',
    PROVIDER_SCOPE_MISSING: 'Nền tảng chưa cấp đủ quyền cho thao tác này.',
    CHANNEL_MODE_MISMATCH: 'Kênh thuộc chế độ kết nối khác với hệ thống hiện tại.'
  })[code] || `Nền tảng hoặc hệ thống báo lỗi (${code}).`;
}

function channelMenu(row) {
  const menu = element('details', 'channel-menu');
  menu.append(element('summary', '', 'Thao tác'));
  const actions = element('div', 'channel-menu-actions');
  function add(label, handler) {
    const button = element('button', 'secondary', label);
    button.type = 'button';
    button.onclick = async () => {
      const opening = channelsState.opening;
      button.disabled = true;
      $('#channel-connect-error').hidden = true;
      try {
        await handler(opening);
      } catch (error) {
        if (opening === channelsState.opening) notify(error.message);
      } finally {
        button.disabled = false;
      }
    };
    actions.append(button);
  }
  add('Xem chi tiết', opening => showChannelDetail(row, 'detail', opening));
  add('Xem quyền truy cập', opening => showChannelDetail(row, 'permissions', opening));
  add('Xem lịch sử', opening => showChannelDetail(row, 'activity-logs', opening));
  if (channelsState.canManage) {
    if (availablePlatforms.some(option => option.platform === row.platform && option.oauth_ready)) {
      add('Kết nối lại', () => startChannelConnection(row.platform, row.external_account_id));
    }
    if (row.connection_status !== 'disconnected') {
      add('Kiểm tra kết nối', opening => runChannelAction(row, 'check', 'Kết nối hợp lệ.', opening));
      if (row.platform === 'tiktok' && row.connection_status !== 'revoked') {
        add('Làm mới quyền truy cập', opening => runChannelAction(row, 'refresh', 'Đã làm mới quyền truy cập.', opening));
      }
      if (row.connection_status === 'connected') {
        add('Đồng bộ số liệu', opening => runChannelAction(row, 'sync/metrics', 'Đã yêu cầu đồng bộ số liệu.', opening));
        if (row.platform === 'facebook') add('Đồng bộ hộp thư', opening => runChannelAction(row, 'sync/inbox', 'Đã yêu cầu đồng bộ hộp thư.', opening));
      }
      add('Ngắt kết nối', opening => {
        if (!window.confirm(`Ngắt kết nối ${row.account_name}? Các lịch đăng đang chờ của kênh sẽ bị hủy.`)) return;
        return runChannelAction(row, 'disconnect', 'Đã ngắt kết nối.', opening);
      });
    }
  }
  menu.append(actions);
  return menu;
}

function channelPath(row) {
  return `/workspaces/${channelsState.workspaceId}/social-accounts/${row.social_account_id}`;
}

async function runChannelAction(row, action, message, opening) {
  const result = await api(`${channelPath(row)}/${action}`, { method: 'POST' });
  if (opening !== channelsState.opening) return;
  notify(result.error_code ? channelErrorMessage(result.error_code) : message);
  await loadChannels();
}

async function showChannelDetail(row, section, opening) {
  const request = ++channelDetailRequest;
  const path = channelPath(row);
  const detail = $('#channel-detail');
  const title = { detail: 'Chi tiết kênh', permissions: 'Quyền truy cập', 'activity-logs': 'Lịch sử hoạt động' }[section];
  const close = element('button', 'secondary', 'Đóng chi tiết');
  close.onclick = () => { channelDetailRequest++; detail.hidden = true; };
  const body = element('div', '');
  body.setAttribute('aria-live', 'polite');
  body.append(element('p', '', 'Đang tải…'));
  detail.replaceChildren(element('h3', '', `${title} · ${row.account_name}`), body, close);
  detail.hidden = false;
  detail.focus();
  try {
    const result = await api(section === 'detail' ? path : path + '/' + section);
    if (opening !== channelsState.opening || request !== channelDetailRequest) return;
    body.replaceChildren();
    if (section === 'permissions') {
      const scopes = result.known ? result.scopes : [];
      if (!result.known) body.append(element('p', '', 'Chưa ghi nhận quyền. Hãy kết nối lại để cập nhật.'));
      else if (!scopes.length) body.append(element('p', '', 'Chưa có quyền API được cấp.'));
      else for (const scope of scopes) body.append(element('p', '', scope));
    } else if (section === 'activity-logs') {
      const labels = { 'channel.connect': 'Kết nối', 'channel.disconnect': 'Ngắt kết nối',
        'channel.check': 'Kiểm tra', 'channel.refresh': 'Làm mới quyền', 'channel.sync_request': 'Yêu cầu đồng bộ' };
      if (!result.length) body.append(element('p', '', 'Chưa có hoạt động.'));
      for (const entry of result) body.append(element('p', '', `${channelDate(entry.created_at)} · ${labels[entry.action] || entry.action} · Người dùng ${entry.user_id || 'hệ thống'}`));
    } else {
      body.append(element('p', '', `Trạng thái: ${channelStatuses[result.connection_status]} · Người kết nối: ${result.connected_by}`));
      if (!result.sync_logs.length) body.append(element('p', '', 'Chưa có kết quả đồng bộ.'));
      for (const log of result.sync_logs) {
        const kind = log.kind === 'metrics' ? 'Số liệu' : 'Hộp thư';
        const status = {
          pending: 'Đang chờ', syncing: 'Đang đồng bộ', success: `Thành công · ${log.records_updated} bản ghi`,
          failed: channelErrorMessage(log.error_code)
        }[log.status];
        body.append(element('p', '', `${channelDate(log.finished_at || log.started_at)} · ${kind} · ${status}`));
      }
    }
  } catch (error) {
    if (opening === channelsState.opening && request === channelDetailRequest) body.textContent = error.message;
  }
}

function resetChannelSelection() {
  channelResult = null;
  channelSelection.hidden = true;
  channelSelection.querySelector('fieldset').disabled = false;
  channelSelection.querySelector('[type=submit]').disabled = false;
  $('#cancel-channel-selection').disabled = false;
  $('#channel-choices').replaceChildren();
}

channelConnect.onclick = () => {
  if (availablePlatforms.length === 1) {
    startChannelConnection(availablePlatforms[0].platform);
    return;
  }
  platformPicker.hidden = !platformPicker.hidden;
  channelConnect.setAttribute('aria-expanded', String(!platformPicker.hidden));
  if (!platformPicker.hidden) platformPicker.querySelector('button').focus();
};
platformPicker.onclick = event => {
  const platform = event.target.dataset.platform;
  if (platform && !channelConnect.disabled) startChannelConnection(platform);
};

async function startChannelConnection(platform, externalId = null) {
  if (!channelsState.canManage || channelConnect.disabled) return;
  const workspaceId = channelsState.workspaceId;
  const opening = channelsState.opening;
  channelConnect.disabled = true;
  $('#channel-connect-error').hidden = true;
  try {
    const response = await api(`/workspaces/${workspaceId}/social-accounts/oauth/${platform}?browser=true`, { method: 'POST' });
    if (opening !== channelsState.opening || !isCurrentChannels(workspaceId)) return;
    if (new URL(response.callback_origin).origin !== location.origin) {
      throw new Error('Hãy mở hệ thống bằng địa chỉ APP_URL đã đăng ký cho OAuth.');
    }
    const url = new URL(response.authorization_url);
    sessionStorage.setItem('orbitspace-oauth-pending', JSON.stringify({
      workspaceId, platform, externalId, state: url.searchParams.get('state')
    }));
    location.assign(url.href);
  } catch (error) {
    if (opening !== channelsState.opening || !isCurrentChannels(workspaceId)) return;
    showChannelError(error.message);
    channelConnect.disabled = false;
  }
}

$('#cancel-channel-selection').onclick = () => {
  resetChannelSelection();
  channelConnect.focus();
};

channelSelection.onsubmit = async event => {
  event.preventDefault();
  const result = channelResult;
  if (!result) return;
  const ids = [...channelSelection.querySelectorAll('input:checked')].map(input => input.value);
  if (!ids.length || ids.length > 100) {
    showChannelError('Vui lòng chọn từ 1 đến 100 tài khoản.');
    return;
  }
  const fieldset = channelSelection.querySelector('fieldset');
  const submit = channelSelection.querySelector('[type=submit]');
  if (submit.disabled) return;
  fieldset.disabled = submit.disabled = $('#cancel-channel-selection').disabled = channelConnect.disabled = true;
  $('#channel-connect-error').hidden = true;
  try {
    await api(`/workspaces/${result.workspace_id}/social-accounts/oauth/complete-selection`, {
      method: 'POST',
      body: JSON.stringify({ connection_token: result.connection_token, external_account_ids: ids })
    });
    if (channelResult !== result) return;
    resetChannelSelection();
    channelConnect.disabled = false;
    $('#channel-search').value = '';
    $('#channel-status').value = 'connected';
    $('#channel-platform').value = result.platform;
    notify(result.isDemo ? 'Đã thêm kênh mẫu.' : 'Đã kết nối tài khoản.');
    filterChannels();
  } catch (error) {
    if (channelResult === result) showChannelError(error.message);
  } finally {
    if (channelResult === result) {
      fieldset.disabled = submit.disabled = $('#cancel-channel-selection').disabled = channelConnect.disabled = false;
    }
  }
};

async function resumeChannelConnection() {
  const stored = sessionStorage.getItem('orbitspace-oauth-result');
  if (!stored) return;
  const pending = sessionStorage.getItem('orbitspace-oauth-pending');
  sessionStorage.removeItem('orbitspace-oauth-result');
  sessionStorage.removeItem('orbitspace-oauth-pending');
  if (!pending || !state.token) return;
  const result = JSON.parse(stored);
  const { workspaceId, state: expectedState, platform, externalId } = JSON.parse(pending);
  if (result.state !== expectedState || (result.data && result.data.workspace_id !== workspaceId)) return;
  try {
    const workspace = await api(`/workspaces/${workspaceId}`);
    const canConnect = await openChannels(workspaceId, workspace.name);
    if (!canConnect || !isCurrentChannels(workspaceId)) return;
    if (result.error) {
      showChannelError(result.error);
      return;
    }
    const accounts = result.data.accounts.filter(account =>
      account.platform === platform && (!externalId || account.external_account_id === externalId)
    );
    if (!accounts.length) {
      showChannelError('Tài khoản cần kết nối lại không có trong danh sách đã cấp quyền.');
      return;
    }
    channelResult = { ...result.data, platform, isDemo: accounts.every(account => account.external_account_id === `mock-${platform}`) };
    $('#channel-selection-title').textContent = `Chọn ${platform === 'facebook' ? 'Trang' : 'tài khoản'} ${channelPlatforms[platform]}`;
    const pages = $('#channel-choices');
    for (const account of accounts) {
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = account.external_account_id;
      checkbox.checked = accounts.length === 1;
      const label = document.createElement('label');
      label.append(checkbox, document.createTextNode(`${account.account_name} · ID ${account.external_account_id}`));
      pages.append(label);
    }
    channelSelection.hidden = false;
    pages.querySelector('input')?.focus();
  } catch (error) {
    notify(error.message);
  }
}

resumeChannelConnection();
