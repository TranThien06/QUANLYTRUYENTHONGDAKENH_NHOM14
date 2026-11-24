'use strict';

const publishDialog = $('#publish-dialog');
const publishResultDialog = $('#publish-result-dialog');
const publishPost = $('#publish-post');
const publishChannels = $('#publish-channels');
const publishNow = $('#publish-now');
const channelStatus = {
  draft: 'Chưa đăng', scheduled: 'Đã lên lịch', publishing: 'Đang xử lý',
  published: 'Đăng thành công', failed: 'Đăng thất bại', cancelled: 'Đã hủy',
};
let publication;
let publicationTimer;

function showPublicationError(message = '') {
  const box = $('#publish-error');
  box.textContent = message;
  box.hidden = !message;
}

function updatePublishButton() {
  publishNow.disabled = !publication || publication.sending ||
    !publishChannels.querySelector('input:checked:not(:disabled)');
}

function showPublishResult(title, message, button, failed = false) {
  $('#publish-result-title').textContent = title;
  const box = $('#publish-result-message');
  box.textContent = message;
  box.className = failed ? 'form-error' : 'notice';
  $('#close-publish-result').textContent = button;
  if (!publishResultDialog.open) publishResultDialog.showModal();
}

function showPublishSuccess(session) {
  session.attempt = null;
  showPostList();
  publishPost.value = '';
  publishPost.disabled = false;
  publishChannels.disabled = false;
  publishChannels.replaceChildren();
  $('#publish-caption').hidden = true;
  showPublicationError();
  $('#publish-status').textContent = 'Đăng bài thành công.';
  updatePublishButton();
  showPublishResult('Đăng bài thành công', 'Bài đã đăng lên tất cả kênh bạn chọn.', 'Về Bài đăng');
}

function showPublishFailure(session, total, published, detail) {
  session.attempt = null;
  const summary = published
    ? `Đã đăng thành công trên ${published}/${total} kênh. Các kênh còn lại đăng thất bại.`
    : 'Không đăng được lên các kênh đã chọn.';
  showPublishResult(
    published ? 'Đăng bài thành công một phần' : 'Đăng bài thất bại',
    detail ? summary + ' ' + detail : summary,
    'Xem kết quả theo kênh',
    true,
  );
}

async function openPublishDialog(workspaceId, permissions) {
  const session = {
    base: '/workspaces/' + workspaceId,
    canPublish: permissions.includes('post.publish'),
    canCreate: permissions.includes('post.create'),
    canUpload: permissions.includes('media.manage'),
    results: {},
  };
  publication = session;
  showPostList();
  publishPost.replaceChildren(new Option('Chọn bài đăng', ''));
  publishNow.hidden = !session.canPublish;
  $('#new-post').hidden = !session.canCreate;
  prefetchOnIntent($('#new-post'), () => ['social-accounts', 'media'].map(
    resource => session.base + '/' + resource + '?limit=100&page=1',
  ));
  publishChannels.replaceChildren();
  $('#publish-caption').hidden = true;
  $('#publish-status').textContent = 'Đang tải danh sách bài…';
  showPublicationError();
  updatePublishButton();
  publishDialog.showModal();
  try {
    for (let page = 1; publication === session; page++) {
      const posts = await readPrefetched(session.base + '/posts?limit=100&page=' + page);
      if (publication !== session) return;
      const listed = new Set([...publishPost.options].map(option => option.value));
      for (const post of posts) {
        if (!listed.has(post.post_id)) {
          publishPost.add(new Option(post.title || 'Bài #' + post.post_id, post.post_id));
          listed.add(post.post_id);
        }
      }
      if (posts.length < 100) break;
    }
    if (publication === session && $('#publish-status').textContent === 'Đang tải danh sách bài…') {
      $('#publish-status').textContent = publishPost.options.length > 1 ? '' : 'Workspace chưa có bài đăng.';
    }
  } catch (error) {
    if (publication === session) {
      showPublicationError(error.message);
      $('#publish-status').textContent = '';
    }
  }
}

async function refreshPublication() {
  clearTimeout(publicationTimer);
  const session = publication;
  const postId = publishPost.value;
  if (!session || !postId || session.sending || session.composer || session.loading) return;
  const request = {};
  session.loading = request;
  const isCurrent = () => publication === session && session.loading === request;
  const selected = new Set([...publishChannels.querySelectorAll('input:checked')].map(input => input.value));
  publishPost.disabled = true;
  publishChannels.disabled = true;
  publishNow.disabled = true;
  try {
    const post = await api(session.base + '/posts/' + postId);
    if (!isCurrent()) return;
    if (session.attempt?.postId === postId) {
      const results = session.attempt.variantIds.map(id => {
        const variant = post.variants.find(item => item.variant_id === id);
        return variant?.status === 'published' ? variant : session.results[id]?.status === 'failed'
          ? session.results[id] : variant;
      });
      const published = results.filter(result => result?.status === 'published').length;
      if (published === results.length) {
        showPublishSuccess(session);
        return;
      }
      if (results.every(result => ['published', 'failed', 'cancelled'].includes(result?.status))) {
        showPublishFailure(session, results.length, published, results.find(result => result.error_message)?.error_message);
      }
    }
    const caption = $('#publish-caption');
    caption.textContent = post.base_caption || '';
    caption.hidden = !caption.textContent;
    const blocked = ['pending_approval', 'rejected', 'cancelled'].includes(post.status);
    publishChannels.replaceChildren();
    for (const variant of post.variants) {
      const row = element('div', 'publish-channel');
      const label = element('label', '');
      const status = element('small', '', channelStatus[variant.status] || variant.status);
      if (session.canPublish) {
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.value = variant.variant_id;
        input.disabled = blocked || ['published', 'publishing', 'scheduled'].includes(variant.status) ||
          Boolean(variant.needs_reconciliation);
        input.checked = !input.disabled && selected.has(input.value);
        label.append(input);
      }
      label.append(document.createTextNode(variant.account_name + ' · ' + variant.platform));
      const result = session.results[variant.variant_id];
      const error = result?.status === 'failed' && variant.status !== 'published'
        ? result : variant;
      if (error?.error_message) status.textContent += ' — ' + error.error_message + ' (' + error.error_code + ')';
      row.append(label, status);
      if (variant.status === 'published') {
        const details = document.createElement('div');
        if (variant.external_post_id) {
          details.append(element('small', '', 'Mã bài: ' + variant.external_post_id));
        }
        if (/^https?:\/\//i.test(variant.external_post_url || '')) {
          const link = element('a', '', 'Mở bài đã đăng');
          link.href = variant.external_post_url;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.setAttribute('aria-label', 'Mở bài đã đăng trên ' + variant.account_name + ' · ' + variant.platform);
          details.append(document.createTextNode(' '), link);
        } else {
          details.append(document.createTextNode(' '), element('small', '', 'Chưa có liên kết từ nền tảng'));
        }
        row.append(details);
      }
      publishChannels.append(row);
    }
    const pending = post.variants.some(variant => variant.status === 'publishing');
    $('#publish-status').textContent = pending ? 'Đang chờ kết quả theo kênh…' : '';
    if (pending) publicationTimer = setTimeout(refreshPublication, 3000);
  } catch (error) {
    if (isCurrent()) {
      showPublicationError(error.message);
      $('#publish-status').textContent = 'Có thể tải lại để xem trạng thái mới nhất.';
    }
  } finally {
    if (isCurrent()) {
      session.loading = null;
      publishPost.disabled = false;
      publishChannels.disabled = false;
      updatePublishButton();
    }
  }
}

const createPostForm = $('#create-post-form');
const createPostFields = $('#create-post-fields');
const saveNewPost = $('#save-new-post');

function showPostList() {
  $('#publish-title').textContent = 'Bài đăng';
  $('#publish-form').hidden = false;
  createPostForm.hidden = true;
  if (publication) publication.composer = null;
}

function showCreatePostError(message = '') {
  const error = $('#create-post-error');
  error.textContent = message;
  error.hidden = !message;
}

async function readComposerOptions(base, resource, append, isCurrent) {
  for (let page = 1; isCurrent(); page++) {
    const items = await readPrefetched(base + '/' + resource + '?limit=100&page=' + page);
    if (!isCurrent()) return;
    for (const item of items) append(item);
    if (items.length < 100) return;
  }
}

function addComposerMedia(media, selected = false) {
  const option = new Option(media.file_name, media.media_id, false, selected);
  createPostForm.elements.media.add(option, selected ? 0 : null);
  $('#post-media-library').hidden = false;
  $('#post-media-empty').hidden = true;
}

$('#new-post').onclick = async () => {
  const session = publication;
  if (!session?.canCreate || session.sending) return;
  const composer = { busy: false };
  session.composer = composer;
  clearTimeout(publicationTimer);
  session.loading = null;
  const isCurrent = () => publishDialog.open && publication === session && session.composer === composer;
  createPostForm.reset();
  createPostForm.elements.media.replaceChildren();
  $('#post-media-library').hidden = true;
  $('#post-media-empty').hidden = true;
  $('#post-upload-retry').hidden = true;
  const channels = $('#create-post-channels');
  channels.replaceChildren();
  createPostFields.disabled = false;
  createPostForm.elements.file.disabled = true;
  saveNewPost.disabled = true;
  $('#post-upload-section').hidden = !session.canUpload;
  $('#publish-form').hidden = true;
  $('#publish-title').textContent = 'Tạo bài mới';
  createPostForm.hidden = false;
  showCreatePostError();
  $('#create-post-status').textContent = 'Đang tải kênh…';
  const mediaNotice = $('#post-media-empty');
  mediaNotice.textContent = 'Đang tải thư viện…';
  mediaNotice.hidden = false;
  createPostForm.elements.title.focus();
  const loadChannels = async () => {
    try {
      await readComposerOptions(session.base, 'social-accounts', channel => {
        if (channel.status !== 'connected') return;
        const row = element('div', 'publish-channel');
        const label = element('label', '');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.name = 'channel';
        checkbox.value = channel.social_account_id;
        label.append(checkbox, document.createTextNode(channel.account_name + ' · ' + channel.platform));
        row.append(label);
        channels.append(row);
      }, isCurrent);
      if (!isCurrent()) return;
      composer.channelsReady = true;
      saveNewPost.disabled = composer.busy || !channels.children.length;
      $('#create-post-status').textContent = channels.children.length ? '' : 'Workspace chưa có kênh kết nối.';
    } catch (error) {
      if (!isCurrent()) return;
      $('#create-post-status').textContent = '';
      showCreatePostError(error.message);
    }
  };
  const channelLoad = loadChannels();
  try {
    await readComposerOptions(session.base, 'media', media => addComposerMedia(media), isCurrent);
    if (isCurrent() && !createPostForm.elements.media.options.length) {
      mediaNotice.textContent = session.canUpload
        ? 'Thư viện chưa có tệp. Bạn có thể chọn ảnh hoặc video từ máy bên dưới.'
        : 'Thư viện chưa có tệp. Người có quyền quản lý thư viện có thể thêm ảnh hoặc video.';
    }
  } catch (error) {
    if (isCurrent()) {
      mediaNotice.textContent = 'Không tải được đầy đủ thư viện: ' + error.message;
      mediaNotice.hidden = false;
    }
  } finally {
    if (isCurrent()) createPostForm.elements.file.disabled = false;
  }
  await channelLoad;
};

$('#cancel-new-post').onclick = () => {
  if (publication?.composer?.busy) return;
  showPostList();
  $('#new-post').focus();
  refreshPublication();
};

function setComposerBusy(composer, busy) {
  composer.busy = busy;
  createPostFields.disabled = busy;
  saveNewPost.disabled = busy || !composer.channelsReady || !$('#create-post-channels').children.length;
  $('#cancel-new-post').disabled = busy;
  $('#close-publish').disabled = busy;
}

async function uploadComposerMedia() {
  const session = publication;
  const composer = session?.composer;
  if (!session?.canUpload || !composer || composer.busy) return;
  const input = createPostForm.elements.file;
  const file = input.files[0];
  $('#post-upload-retry').hidden = true;
  if (!file) return;
  const body = new FormData();
  body.append('file', file);
  setComposerBusy(composer, true);
  showCreatePostError();
  $('#create-post-status').textContent = 'Đang tải tệp lên…';
  try {
    const media = await api(session.base + '/media', { method: 'POST', body });
    if (publication !== session || session.composer !== composer) return;
    addComposerMedia(media, true);
    input.value = '';
    $('#create-post-status').textContent = 'Đã đính kèm ' + media.file_name + '.';
  } catch (error) {
    if (publication === session && session.composer === composer) {
      showCreatePostError(error.message);
      $('#create-post-status').textContent = '';
      $('#post-upload-retry').hidden = false;
    }
  } finally {
    if (publication === session && session.composer === composer) {
      setComposerBusy(composer, false);
    }
  }
}

createPostForm.elements.file.onchange = uploadComposerMedia;
$('#upload-post-media').onclick = uploadComposerMedia;
$('#discard-post-media').onclick = () => {
  createPostForm.elements.file.value = '';
  $('#post-upload-retry').hidden = true;
  showCreatePostError();
};

createPostForm.onsubmit = async event => {
  event.preventDefault();
  const session = publication;
  const composer = session?.composer;
  if (!session?.canCreate || !composer || composer.busy || saveNewPost.disabled) return;
  if (session.canUpload && createPostForm.elements.file.files.length) {
    showCreatePostError('Tệp đang chọn chưa được đính kèm. Hãy thử tải lại hoặc bỏ chọn tệp trước khi lưu.');
    return;
  }
  const values = new FormData(createPostForm);
  const channels = values.getAll('channel');
  const caption = values.get('caption').trim();
  const mediaIds = values.getAll('media');
  if (!channels.length || channels.length > 30) {
    showCreatePostError('Chọn từ 1 đến 30 kênh đăng.');
    return;
  }
  if (!caption && !mediaIds.length) {
    showCreatePostError('Nhập nội dung hoặc chọn ảnh, video.');
    return;
  }
  if (mediaIds.length > 20) {
    showCreatePostError('Chọn tối đa 20 tệp.');
    return;
  }
  const body = JSON.stringify({
    title: values.get('title').trim() || null,
    base_caption: caption || null,
    media_ids: mediaIds,
    variants: channels.map(social_account_id => ({ social_account_id })),
  });
  if (composer.body !== body) {
    composer.body = body;
    composer.key = crypto.randomUUID();
  }
  setComposerBusy(composer, true);
  showCreatePostError();
  $('#create-post-status').textContent = 'Đang lưu bản nháp…';
  try {
    const post = await api(session.base + '/posts', {
      method: 'POST', body, headers: { 'Idempotency-Key': composer.key },
    });
    if (publication !== session || session.composer !== composer) return;
    setComposerBusy(composer, false);
    if (![...publishPost.options].some(option => option.value === post.post_id)) {
      publishPost.add(new Option(post.title || 'Bài #' + post.post_id, post.post_id), 1);
    }
    publishPost.value = post.post_id;
    showPostList();
    publishPost.onchange();
    notify('Đã lưu bản nháp.');
  } catch (error) {
    if (publication !== session || session.composer !== composer) return;
    showCreatePostError(error.message);
    setComposerBusy(composer, false);
    $('#create-post-status').textContent = '';
  }
};

publishPost.onchange = () => {
  publication.attempt = null;
  publication.results = {};
  publishChannels.replaceChildren();
  $('#publish-caption').hidden = true;
  $('#publish-status').textContent = '';
  showPublicationError();
  updatePublishButton();
  refreshPublication();
};
publishChannels.onchange = updatePublishButton;
$('#refresh-publication').onclick = () => {
  showPublicationError();
  refreshPublication();
};
$('#close-publish').onclick = () => publishDialog.close();
publishDialog.addEventListener('cancel', event => {
  if (publication?.composer?.busy) event.preventDefault();
});
publishDialog.addEventListener('close', () => {
  publishResultDialog.close();
  publication = null;
  clearTimeout(publicationTimer);
  publishPost.disabled = false;
  publishChannels.disabled = false;
  $('#close-publish').disabled = false;
  $('#cancel-new-post').disabled = false;
});

$('#publish-form').onsubmit = async event => {
  event.preventDefault();
  const session = publication;
  if (publishNow.disabled || !session?.canPublish) return;
  const variantIds = [...publishChannels.querySelectorAll('input:checked:not(:disabled)')].map(input => input.value);
  const postId = publishPost.value;
  clearTimeout(publicationTimer);
  session.sending = true;
  publishPost.disabled = true;
  publishChannels.disabled = true;
  updatePublishButton();
  showPublicationError();
  $('#publish-status').textContent = 'Đang gửi yêu cầu…';
  try {
    const response = await api(session.base + '/posts/' + postId + '/publish?finish_demo=true', {
      method: 'POST', body: JSON.stringify({ variant_ids: variantIds }),
    });
    if (publication !== session) return;
    if (response.results.length === variantIds.length && response.results.every(result => result.status === 'published')) {
      showPublishSuccess(session);
      return;
    }
    for (const result of response.results) session.results[result.variant_id] = result;
    if (response.results.some(result => result.status === 'publishing')) {
      session.attempt = { postId, variantIds };
      $('#publish-status').textContent = 'Đang chờ kết quả theo kênh…';
    } else {
      showPublishFailure(session, variantIds.length, response.results.filter(result => result.status === 'published').length,
        response.results.find(result => result.error_message)?.error_message);
    }
    publishChannels.querySelectorAll('input:checked').forEach(input => { input.checked = false; });
  } catch (error) {
    if (publication === session) {
      showPublicationError(error.message);
      showPublishResult('Chưa xác nhận được kết quả đăng bài', error.message, 'Quay lại Bài đăng', true);
    }
  } finally {
    if (publication === session) {
      session.sending = false;
      if (publishPost.value) await refreshPublication();
    }
  }
};
