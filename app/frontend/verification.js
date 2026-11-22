"use strict";
(() => {
  const dialog = $('#verification-dialog'), form = $('#verify-code-form'), status = $('#verification-status');
  let busy = false;
  window.openEmailVerification = (email = '') => {
    $('#auth-dialog').close(); $('#register-dialog').close(); form.reset(); form.hidden = false;
    form.elements.email.value = email;
    status.className = 'notice'; status.textContent = 'Nhập mã 6 chữ số được gửi tới email của bạn. Mã có hiệu lực 10 phút. Kiểm tra cả mục Spam.';
    $('#resend-status').hidden = true; dialog.showModal();
  };
  $('#open-resend-button').textContent = 'Xác minh email';
  $('#open-resend-button').onclick = () => window.openEmailVerification($('#auth-form').elements.email.value);
  $('#close-verification').onclick = () => { if (!busy) dialog.close(); };
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  $('#verification-login').onclick = () => {
    if (busy) return;
    $('#auth-form').elements.email.value = form.elements.email.value;
    dialog.close(); $('#auth-dialog').showModal();
  };
  function lock(value) {
    busy = value;
    for (const id of ['close-verification', 'verification-login', 'verify-code-submit', 'resend-submit']) $('#' + id).disabled = value;
    form.elements.email.disabled = value; form.elements.code.disabled = value;
  }
  async function verify(payload) {
    lock(true); status.className = 'notice'; status.textContent = 'Đang xác minh…';
    try {
      await api('/auth/verify-email', { method: 'POST', body: JSON.stringify(payload) });
      form.elements.code.value = ''; form.hidden = true;
      status.textContent = 'Email đã xác minh thành công. Bạn có thể đăng nhập ngay.';
      $('#resend-status').hidden = true;
    } catch (error) { status.className = 'form-error'; status.textContent = error.message; }
    finally { lock(false); }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    await verify({ email: form.elements.email.value.trim(), code: form.elements.code.value.trim() });
  });
  $('#resend-submit').onclick = async () => {
    if (busy || !form.elements.email.reportValidity()) return;
    const email = form.elements.email.value.trim(); lock(true);
    const result = $('#resend-status'); result.hidden = true;
    try {
      await api('/auth/resend-verification', { method: 'POST', body: JSON.stringify({ email }) });
      form.elements.code.value = ''; result.className = 'notice';
      result.textContent = 'Nếu tài khoản đang chờ xác minh, mã sẽ được gửi qua email. Mỗi lần gửi cách nhau ít nhất 60 giây; khi có mã mới, mã cũ hết hiệu lực.';
    } catch (error) { result.className = 'form-error'; result.textContent = error.message; }
    finally { result.hidden = false; lock(false); }
  };
  if (window.location.pathname === '/verify-email') {
    const token = new URLSearchParams(window.location.search).get('token');
    window.history.replaceState(null, '', '/verify-email');
    window.openEmailVerification();
    if (token) verify({ token });
  }
})();
