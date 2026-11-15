# Email xác minh qua Gmail

Web đã có trang `/verify-email`: mở liên kết trong email để xác minh, sau đó chọn Đăng nhập. Trong hộp thoại Đăng nhập, chọn **Gửi lại xác minh** nếu chưa nhận được thư hoặc liên kết hết hạn. Gửi lại vô hiệu hóa liên kết trước; liên kết mới dùng một lần trong 24 giờ.

## Cấu hình trên máy

1. Bật xác minh hai bước cho tài khoản Gmail dùng gửi thư.
2. Tạo Mật khẩu ứng dụng tại https://myaccount.google.com/apppasswords (tùy chính sách tài khoản).
3. Sửa `.env` tại thư mục gốc, giữ nguyên cấu hình database và TOKEN_ENCRYPTION_KEY:

```dotenv
MAIL_MODE=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=dia-chi-gui@gmail.com
SMTP_PASSWORD=mat_khau_ung_dung_16_ky_tu_khong_co_khoang_trang
MAIL_FROM=dia-chi-gui@gmail.com
FRONTEND_URL=http://localhost:3000
```

Điền Gmail gửi thư thực vào cả SMTP_USER và MAIL_FROM; không dùng mật khẩu đăng nhập Gmail. `.env` được Git bỏ qua. Chỉ chuyển MAIL_MODE sang smtp sau khi điền đủ thông tin; khi thiếu cấu hình, server/worker sẽ thông báo tên biến còn thiếu.

FRONTEND_URL phải là địa chỉ người nhận mở được. localhost chỉ phù hợp khi mở email trên chính máy chạy web. Khi triển khai, dùng domain HTTPS của web. Không dùng localhost:5173 nếu web đang phục vụ tại cổng 3000.

4. Khởi động lại API và worker trong hai terminal:

```powershell
.\.venv\Scripts\python.exe -m app.server
```

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

5. Với tài khoản đã đăng ký: Đăng nhập → Gửi lại xác minh → nhập email → kiểm tra Inbox/Spam → mở liên kết mới → Đăng nhập. Email đã ghi vào file trước khi bật SMTP không được gửi lại tự động; hãy dùng Gửi lại xác minh.

Worker gửi email từ email_outbox; thất bại được thử lại tối đa 4 lần. Nếu Gmail từ chối, kiểm tra Mật khẩu ứng dụng, xác minh hai bước và quyền tài khoản. Không cần cấu hình Facebook/TikTok live để gửi Gmail trong môi trường development.

Hiện `.env` đã chuẩn bị SMTP_HOST và địa chỉ callback; cần điền thông tin Gmail rồi bật smtp. Chưa xác nhận gửi thư thật khi chưa có thông tin tài khoản.

Tài liệu Google:
- https://support.google.com/accounts/answer/185833
- https://developers.google.com/workspace/gmail/imap/imap-smtp
