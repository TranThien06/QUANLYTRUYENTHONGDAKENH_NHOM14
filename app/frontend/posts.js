'use strict';

const postsDialog = $('#posts-dialog');
const draftEditor = $('#draft-editor');
const draftPageSize = 20;
let postSession;

$('#members-button').after($('#posts-button'));

function postButton(label, action) {
  const button = element('button', 'secondary', label);
  button.type = 'button';
  button.onclick = action;
  return button;
}

function postError(message = '') {
  $('#posts-error').textContent = message;
  $('#posts-error').hidden = !message;
}

function draftStatus(message) {
  $('#draft-status').textContent = message;
}

function channelTitle(channel) {
  return `${channelPlatforms[channel.platform] || channel.platform} · ${channel.account_name}`;
}

window.closePostSession = () => {
  clearTimeout(postSession?.editor?.timer);
  postSession = undefined;
  postsDialog.close();
};

async function openPosts(workspace, permissions) {
  const session = {
    base: `/workspaces/${workspace.workspace_id}`,
    recoveryKey: `orbitspace-draft:${state.user.user_id}:${workspace.workspace_id}`,
    canCreate: permissions.includes('post.create'),
    canEdit: permissions.includes('post.edit'),
    page: 1,
  };
  postSession = session;
  $('#posts-workspace').textContent = workspace.name;
  postsDialog.showModal();
  await showDrafts(session);
}

async function showDrafts(session) {
  session.editor = null;
  draftEditor.hidden = true;
  $('#draft-library').hidden = false;
  $('#posts-title').textContent = 'Bản nháp';
  $('#draft-new').hidden = !session.canCreate;
  $('#draft-previous').hidden = true;
  $('#draft-next').hidden = true;
  const list = $('#draft-list');
  list.textContent = 'Đang tải bản nháp…';
  postError();
  try {
    const recovery = JSON.parse(sessionStorage.getItem(session.recoveryKey) || 'null');
    const drafts = await api(`${session.base}/posts?status=draft&page=${session.page}&limit=${draftPageSize}`);
    if (postSession !== session || session.editor) return;
    if (!drafts.length && session.page > 1) {
      session.page--;
      return showDrafts(session);
    }
    list.replaceChildren();
    if (recovery && (recovery.postId ? session.canEdit : session.canCreate)) {
      list.append(postButton('Khôi phục thay đổi chưa lưu', () => openDraft(session, recovery.postId, recovery)));
    }
    if (!drafts.length) list.append(element('p', '', 'Workspace chưa có bản nháp.'));
    for (const draft of drafts) {
      const row = element('article', 'draft-row');
      row.append(
        element('strong', '', draft.title || draft.base_caption?.slice(0, 80) || 'Bản nháp chưa có tiêu đề'),
        postButton(session.canEdit ? 'Mở và sửa' : 'Xem', () => openDraft(session, draft.post_id)),
      );
      if (session.canEdit) row.append(postButton('Xóa', async () => {
        if (!confirm('Xóa bản nháp này khỏi workspace?')) return;
        try {
          await api(`${session.base}/posts/${draft.post_id}`, { method: 'DELETE' });
          if (recovery?.postId === draft.post_id) sessionStorage.removeItem(session.recoveryKey);
          if (postSession === session && !session.editor) await showDrafts(session);
        } catch (error) {
          if (postSession === session) postError(error.message);
        }
      }));
      list.append(row);
    }
    $('#draft-previous').hidden = session.page === 1;
    $('#draft-next').hidden = drafts.length < draftPageSize;
  } catch (error) {
    if (postSession === session && !session.editor) {
      list.replaceChildren(postButton('Thử tải lại', () => showDrafts(session)));
      postError(error.message);
    }
  }
}

async function draftChannels(session) {
  const rows = [];
  for (let page = 1; ; page++) {
    const batch = await api(`${session.base}/social-accounts?page=${page}&limit=100`);
    rows.push(...batch);
    if (batch.length < 100) return rows;
  }
}

async function openDraft(session, postId, recovery) {
  if (session.opening) return;
  postError();
  session.opening = true;
  try {
    const local = JSON.parse(sessionStorage.getItem(session.recoveryKey) || 'null');
    if (local && !recovery && String(local.postId) === String(postId ?? null)) recovery = local;
    if (local && !recovery && !confirm('Mở bài khác sẽ bỏ thay đổi chưa đồng bộ đang lưu trong tab này. Tiếp tục?')) return;
    const [post, channels] = await Promise.all([
      postId ? api(`${session.base}/posts/${postId}`) : null,
      draftChannels(session),
    ]);
    if (postSession !== session) return;
    if (local && !recovery) sessionStorage.removeItem(session.recoveryKey);
    const content = recovery?.content || {
      title: post?.title || null,
      base_caption: post?.base_caption || null,
      media_ids: post?.media?.map(file => String(file.media_id)) || [],
      variants: (post?.variants || []).map(variant => ({
        social_account_id: String(variant.social_account_id),
        caption: variant.caption,
        platform_options: variant.platform_options || {},
      })),
    };
    const editor = {
      postId, content, channels, dirty: Boolean(recovery), pendingCreate: recovery?.pendingCreate,
      writable: postId ? session.canEdit && post.status === 'draft' : session.canCreate,
      existingChannels: new Set((post?.variants || []).map(row => String(row.social_account_id))),
      media: post?.media || [],
    };
    session.editor = editor;
    $('#draft-library').hidden = true;
    draftEditor.hidden = false;
    $('#posts-title').textContent = postId ? 'Bản nháp' : 'Soạn bài';
    $('#draft-title').value = content.title ?? '';
    $('#draft-caption').value = content.base_caption ?? '';
    $('#draft-title').readOnly = $('#draft-caption').readOnly = !editor.writable;
    $('#draft-save').hidden = !editor.writable;
    renderDraftChannels(session, editor);
    draftStatus(editor.dirty ? 'Đã khôi phục nội dung chưa đồng bộ.' : '');
    if (editor.dirty && editor.writable) queueDraftSave(session, editor);
  } catch (error) {
    if (postSession === session) postError(error.message);
  } finally {
    session.opening = false;
  }
}

function renderDraftChannels(session, editor) {
  const picker = $('#draft-channels');
  const captions = $('#draft-captions');
  const preview = $('#draft-preview-channel');
  const previous = preview.value;
  picker.replaceChildren();
  captions.replaceChildren();
  preview.replaceChildren();
  for (const channel of editor.channels) {
    const id = String(channel.social_account_id);
    const variant = editor.content.variants.find(item => item.social_account_id === id);
    const selectable = editor.existingChannels.has(id) || channel.connection_status === 'connected';
    const name = channelTitle(channel);
    const label = element('label', 'draft-choice');
    const checkbox = element('input', '');
    checkbox.type = 'checkbox';
    checkbox.checked = Boolean(variant);
    checkbox.disabled = !editor.writable || (!variant && (!selectable || editor.content.variants.length >= 30));
    checkbox.onchange = () => {
      if (checkbox.checked) {
        editor.content.variants.push({ social_account_id: id, caption: null, platform_options: {} });
      } else {
        if ((variant.caption !== null || Object.keys(variant.platform_options).length)
            && !confirm(`Bỏ kênh ${name} và nội dung riêng của kênh này?`)) {
          checkbox.checked = true;
          return;
        }
        editor.content.variants = editor.content.variants.filter(item => item !== variant);
      }
      renderDraftChannels(session, editor);
      draftChanged(session, editor);
    };
    label.append(checkbox, document.createTextNode(selectable ? name : `${name} · ${channelStatuses[channel.connection_status] || 'Không khả dụng'}`));
    picker.append(label);
    if (!variant) continue;

    preview.append(new Option(name, id));
    const field = element('fieldset', 'draft-variant');
    const inheritLabel = element('label', 'draft-choice');
    const inherit = element('input', '');
    inherit.type = 'checkbox';
    inherit.checked = variant.caption === null;
    inherit.disabled = !editor.writable;
    inheritLabel.append(inherit, document.createTextNode('Dùng caption gốc'));
    const caption = element('textarea', '');
    caption.rows = 3;
    caption.maxLength = 65000;
    caption.setAttribute('aria-label', `Caption của ${name}`);
    caption.dataset.channelId = id;
    caption.value = variant.caption ?? editor.content.base_caption ?? '';
    caption.readOnly = !editor.writable || inherit.checked;
    inherit.onchange = () => {
      if (inherit.checked && variant.caption !== (editor.content.base_caption ?? '')
          && !confirm(`Dùng caption gốc và bỏ caption riêng của ${name}?`)) {
        inherit.checked = false;
        return;
      }
      variant.caption = inherit.checked ? null : editor.content.base_caption ?? '';
      renderDraftChannels(session, editor);
      draftChanged(session, editor);
      if (!inherit.checked) captions.querySelector(`textarea[data-channel-id="${id}"]`)?.focus();
    };
    caption.oninput = () => {
      variant.caption = caption.value;
      draftChanged(session, editor);
    };
    caption.dataset.inherited = String(inherit.checked);
    field.append(element('legend', '', name), inheritLabel, caption);
    captions.append(field);
  }
  if (!editor.channels.length) picker.append(element('p', '', 'Workspace chưa có kênh. Thêm kênh trong Quản lý kênh.'));
  if (Array.from(preview.options).some(option => option.value === previous)) preview.value = previous;
  preview.disabled = !preview.options.length;
  renderDraftPreview(editor);
}

function renderDraftPreview(editor) {
  const card = $('#draft-preview-card');
  const id = $('#draft-preview-channel').value;
  const variant = editor.content.variants.find(item => item.social_account_id === id);
  card.className = '';
  if (!variant) {
    card.textContent = 'Chọn kênh đích để xem trước bài.';
    return;
  }
  const channel = editor.channels.find(item => String(item.social_account_id) === id);
  card.className = `draft-preview-card draft-preview-${channel.platform}`;
  const caption = variant.caption ?? editor.content.base_caption ?? '';
  card.replaceChildren(
    element('span', 'draft-preview-platform', channelPlatforms[channel.platform]),
    element('strong', '', channel.account_name),
    element('p', 'draft-preview-caption', caption || 'Chưa có caption'),
  );
  if (editor.media.length) {
    const files = element('ul', '');
    files.append(...editor.media.map(file => element('li', '', file.file_name)));
    card.append(files);
  }
}

function rememberDraft(session, editor) {
  const { postId, content, pendingCreate } = editor;
  try {
    sessionStorage.setItem(session.recoveryKey, JSON.stringify({ postId: postId ?? null, content, pendingCreate }));
  } catch {
    draftStatus('Không lưu được bản khôi phục trong tab. Giữ màn hình mở cho đến khi lưu lên máy chủ.');
  }
}

function queueDraftSave(session, editor) {
  clearTimeout(editor.timer);
  editor.timer = setTimeout(() => saveDraft(session, editor), 2000);
}

function draftChanged(session, editor) {
  editor.dirty = true;
  renderDraftPreview(editor);
  draftStatus('Có thay đổi chưa lưu.');
  rememberDraft(session, editor);
  queueDraftSave(session, editor);
}

async function saveDraft(session, editor, manual = false) {
  clearTimeout(editor.timer);
  if (!editor.writable) return;
  if (editor.saving) {
    editor.saveAgain = true;
    return editor.saving;
  }
  if (!editor.dirty && !manual) return;
  const hasContent = editor.content.title?.trim() || editor.content.base_caption?.trim()
    || editor.content.media_ids.length || editor.content.variants.some(item => item.caption?.trim());
  if (!editor.content.variants.length || (!editor.postId && !hasContent)) {
    draftStatus('Nhập nội dung và chọn ít nhất một kênh để lưu bản nháp lên máy chủ.');
    return;
  }
  const snapshot = JSON.stringify(editor.content);
  const creating = !editor.postId;
  if (creating && !editor.pendingCreate) {
    editor.pendingCreate = {
      key: typeof crypto.randomUUID === 'function' ? crypto.randomUUID()
        : Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join(''),
      body: snapshot,
    };
  }
  postError();
  draftStatus('Đang lưu bản nháp…');
  rememberDraft(session, editor);
  editor.saving = api(`${session.base}/posts${creating ? '' : '/' + editor.postId}`, {
    method: creating ? 'POST' : 'PUT',
    body: creating ? editor.pendingCreate.body : snapshot,
    headers: creating ? { 'Idempotency-Key': editor.pendingCreate.key } : undefined,
  }).then(saved => {
    const savedBody = creating ? editor.pendingCreate.body : snapshot;
    editor.postId = saved.post_id;
    editor.pendingCreate = null;
    editor.existingChannels = new Set(saved.variants.map(row => String(row.social_account_id)));
    editor.dirty = JSON.stringify(editor.content) !== savedBody;
    if (postSession !== session || session.editor !== editor) return;
    if (editor.dirty) {
      rememberDraft(session, editor);
      queueDraftSave(session, editor);
    } else {
      sessionStorage.removeItem(session.recoveryKey);
      draftStatus('Đã lưu bản nháp.');
    }
  }).catch(error => {
    if (postSession !== session || session.editor !== editor) return;
    if (creating && error.status >= 400 && error.status < 500) editor.pendingCreate = null;
    editor.dirty = true;
    postError(error.message);
    draftStatus('Lưu thất bại. Chọn Lưu bản nháp để thử lại.');
    rememberDraft(session, editor);
  }).finally(() => {
    editor.saving = null;
    if (editor.saveAgain && editor.dirty && postSession === session && session.editor === editor) {
      editor.saveAgain = false;
      queueDraftSave(session, editor);
    }
  });
  return editor.saving;
}

async function leaveDraft(close) {
  const session = postSession;
  const editor = session?.editor;
  if (editor?.leaving) return;
  if (editor) {
    editor.leaving = true;
    try {
      const wasSaving = Boolean(editor.saving);
      await saveDraft(session, editor);
      if (wasSaving && editor.dirty && postSession === session) await saveDraft(session, editor);
      if (postSession !== session) return;
      if (editor.dirty && !confirm('Bản nháp chưa được lưu lên máy chủ. Rời màn hình và giữ thay đổi trong tab này?')) return;
      clearTimeout(editor.timer);
    } finally {
      editor.leaving = false;
    }
  }
  if (close) window.closePostSession();
  else if (session) await showDrafts(session);
}

$('#draft-new').onclick = () => openDraft(postSession);
$('#draft-previous').onclick = () => { postSession.page--; showDrafts(postSession); };
$('#draft-next').onclick = () => { postSession.page++; showDrafts(postSession); };
$('#draft-back').onclick = () => leaveDraft(false);
$('#posts-close').onclick = () => leaveDraft(true);
postsDialog.addEventListener('cancel', event => { event.preventDefault(); leaveDraft(true); });
$('#draft-preview-channel').onchange = () => renderDraftPreview(postSession.editor);
$('#draft-title').oninput = $('#draft-caption').oninput = () => {
  const session = postSession;
  const editor = session.editor;
  editor.content.title = $('#draft-title').value || null;
  editor.content.base_caption = $('#draft-caption').value || null;
  for (const field of draftEditor.querySelectorAll('textarea[data-inherited="true"]')) {
    field.value = editor.content.base_caption ?? '';
  }
  draftChanged(session, editor);
};
draftEditor.onsubmit = event => {
  event.preventDefault();
  saveDraft(postSession, postSession.editor, true);
};
window.addEventListener('beforeunload', event => {
  if (postSession?.editor?.dirty) event.preventDefault();
});
