"use strict";
(() => {
  const dialog = $('#verification-dialog');
  const status = $('#verification-status');
  let verifying = false;
  function openResend() {
    $('#auth-dialog').close();
    status.textContent = 'Nhận liên kết xác minh email mới.';
    status.className = 'notice';
    $('#resend-status').hidden = true;
    $('#resend-form').elements.email.value = $('#auth-form').elements.email.value;
    dialog.showModal();
  }
  $('#open-resend-button').onclick = openResend;
  $('#close-verification').onclick = () => { if (!verifying) dialog.close(); };
  dialog.addEventListener('cancel', event => { if (verifying) event.preventDefault(); });
  $('#verification-login').onclick = () => {
    $('#auth-form').elements.email.value = $('#resend-form').elements.email.value;
    dialog.close(); $('#auth-dialog').showModal();
  };
  $('#resend-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = $('#resend-submit');
    if (button.disabled) return;
    button.disabled = true; button.textContent = 'Đang gửi…';
    const result = $('#resend-status'); result.hidden = true;
    try {
      await api('/auth/resend-verification', { method: 'POST', body: JSON.stringify({ email: event.target.elements.email.value.trim() }) });
      result.className = 'notice'; result.textContent = 'Nếu tài khoản đang chờ xác minh, email mới sẽ được gửi. Kiểm tra hộp thư và mục Spam. Liên kết cũ sẽ hết hiệu lực.';
    } catch (error) { result.className = 'form-error'; result.textContent = error.message; }
    finally { result.hidden = false; button.disabled = false; button.textContent = 'Gửi lại email xác minh'; }
  });
  async function verifyLink() {
    if (window.location.pathname !== '/verify-email') return;
    const token = new URLSearchParams(window.location.search).get('token');
    // Remove the one-use token from the address bar before making requests.
    window.history.replaceState(null, '', '/verify-email');
    dialog.showModal();
    if (!token) { status.className = 'form-error'; status.textContent = 'Thiếu mã xác minh. Hãy mở đầy đủ liên kết trong email hoặc yêu cầu gửi lại.'; return; }
    verifying = true; status.textContent = 'Đang xác minh email…';
    $('#resend-form').hidden = true; $('#close-verification').disabled = true;
    try {
      await api('/auth/verify-email', { method: 'POST', body: JSON.stringify({ token }) });
      status.className = 'notice'; status.textContent = 'Email đã được xác minh thành công. Bạn có thể đăng nhập ngay.';
      $('#resend-form').querySelector('.dialog-intro').hidden = true;
      $('#resend-form').querySelector('label').hidden = true;
      $('#resend-submit').hidden = true;
    } catch (error) { status.className = 'form-error'; status.textContent = error.message; }
    finally { verifying = false; $('#resend-form').hidden = false; $('#close-verification').disabled = false; }
  }
  verifyLink();
})();
