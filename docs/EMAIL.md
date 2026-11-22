# Email xác minh qua Gmail

Sau khi đăng ký, web mở biểu mẫu xác minh. Người dùng nhận **mã 6 chữ số** qua email và nhập cùng email đã đăng ký. Mã có hiệu lực **10 phút**, dùng một lần; nhập sai **5 lần** phải gửi lại mã. Mã được lưu dưới dạng HMAC gắn với tài khoản, không lưu rõ trong bảng xác minh. Chờ ít nhất **60 giây** giữa hai lần gửi; mã mới vô hiệu mã cũ.

Tài khoản cũ chưa xác minh: Đăng nhập → Xác minh email → nhập email → Gửi lại mã. Các liên kết đã gửi trước khi đổi sang mã vẫn được hỗ trợ cho tới khi hết hạn hoặc gửi lại mã.

Chạy `.\.venv\Scripts\python.exe -m scripts.migrate` để thêm bảng `email_verification_codes` trước khi khởi động lại API/worker.

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

5. Với tài khoản đã đăng ký: Đăng nhập → Xác minh email → nhập email → Gửi lại mã → kiểm tra Inbox/Spam → nhập mã → Đăng nhập. Email đã ghi vào file trước khi bật SMTP không được gửi lại tự động; hãy dùng Gửi lại xác minh.

Worker gửi email từ email_outbox; thất bại được thử lại tối đa 4 lần. Nếu Gmail từ chối, kiểm tra Mật khẩu ứng dụng, xác minh hai bước và quyền tài khoản. Không cần cấu hình Facebook/TikTok live để gửi Gmail trong môi trường development.

Hiện `.env` đã chuẩn bị SMTP_HOST và địa chỉ callback; cần điền thông tin Gmail rồi bật smtp. Chưa xác nhận gửi thư thật khi chưa có thông tin tài khoản.

Tài liệu Google:
- https://support.google.com/accounts/answer/185833
- https://developers.google.com/workspace/gmail/imap/imap-smtp
