# Hướng dẫn sử dụng REST API

Base URL: `http://localhost:3000/api/v1`. Thành công trả `{ "data": ... }`; lỗi trả `{ "error": { "code", "message", "request_id", "details"? } }`. ID là chuỗi. Danh sách hỗ trợ `page=1&limit=20` (tối đa 100). Mỗi trang là mảng trong `data`; chưa có tổng số trang.

Backend hiện dùng Python + FastAPI. Chạy `python -m app.server` và terminal riêng `python -m app.worker` sau khi cài requirements trong venv. Swagger có sẵn tại `/docs`; xem README để gọi đúng Python trong venv trên Windows.

Tải file trả binary. `201` là tạo thành công, `202` là tác vụ đã nhận, chưa phải đăng/xuất thành công. Không tự gửi trường status, created_by, owner_id hoặc quyền hệ thống trong payload ngoài các API chuyên biệt.

## 1. Xác thực

```http
POST /auth/register
Content-Type: application/json

{"email":"thien@example.com","password":"Password123!","full_name":"Thiện"}
```

Chạy worker để gửi email chứa mã xác minh 6 chữ số. Với `MAIL_MODE=smtp`, mã gửi vào hộp thư thật; với `MAIL_MODE=file`, mã nằm trong trường `text` của `storage/mail/*.json`. Mã hết hạn sau 10 phút, dùng một lần; nhập sai 5 lần cần yêu cầu mã mới. `POST /auth/resend-verification` nhận email, cách nhau ít nhất 60 giây; mã mới vô hiệu mã cũ. Gửi mã kèm email:

```http
POST /auth/verify-email

{"email":"thien@example.com","code":"012345"}
```

```http
POST /auth/login

{"email":"thien@example.com","password":"Password123!"}
```

Dùng `data.access_token` cho các request tiếp theo:

```http
Authorization: Bearer TOKEN_DANG_NHAP
```

Mật khẩu bcrypt cost 12, tối thiểu 8 ký tự, tối đa 72 byte UTF-8. Phiên hết hạn sau 30 phút không hoạt động hoặc tối đa 7 ngày; logout thu hồi ngay. Sai 5 lần liên tiếp khóa đăng nhập 15 phút. Các giới hạn này hiện là hằng số trong service, không chỉnh qua endpoint cấu hình hệ thống.

API bổ sung: `POST /auth/resend-verification`, `/auth/forgot-password`, `/auth/reset-password`, `/auth/logout`; `GET/PATCH /me`; `POST /me/change-password`, `/me/deletion-requests`. Quên mật khẩu trả thông báo chung, token dùng một lần trong 30 phút. Yêu cầu xóa tài khoản vô hiệu hóa và ghi yêu cầu xử lý dữ liệu, không tự xóa dữ liệu dùng chung.

## 2. Workspace và thành viên

`POST /workspaces`:

```json
{ "name": "Nhóm 14", "slug": "nhom-14", "timezone": "Asia/Ho_Chi_Minh" }
```

Lấy workspace_id trả về làm `W=/workspaces/{workspaceId}`. Tất cả ID trong request phải thuộc workspace đó; đổi workspace dùng workspaceId trên URL, không dùng biến global của server.

`DELETE W` với body `{"confirm":true}` xóa mềm workspace, thu hồi token kênh và hủy lịch chưa chạy; chặn nếu có worker đang gửi.

| API                                                    | Quyền                                          |
| ------------------------------------------------------ | ---------------------------------------------- |
| GET /workspaces; GET W; GET /roles                     | Đã đăng nhập / là thành viên                   |
| PATCH W; POST W/transfer-owner                         | workspace.manage; chuyển owner cần chính owner |
| GET W/members                                          | Thành viên active                              |
| PATCH/DELETE W/members/{memberId}                      | member.manage; chỉ Admin quản lý Admin         |
| GET/POST W/invitations; POST W/invitations/{id}/revoke | member.manage                                  |
| POST /invitations/accept                               | Người nhận đã xác minh, email khớp             |
| GET W/settings; PATCH W/settings                       | Xem: thành viên; sửa: workspace.manage         |

Mời: `{"email":"dung@example.com","role":"editor"}`. Nhận: `{"email":"thien@example.com","code":"012345"}`. Vai trò gồm admin, manager, editor, approver, viewer. Owner luôn là Admin active; phải chuyển owner trước khi hạ/xóa/tạm ngưng. Tạo workspace mặc định `require_approval=false`, `allow_self_approval=false`.

## 3. Kết nối kênh qua OAuth

Trong giao diện, mở workspace, chọn **Quản lý kênh**, bấm **+ Kết nối kênh** và chọn nền tảng. Sau khi cấp quyền, chọn tài khoản trong danh sách và xác nhận. Người có quyền `channel.manage` có thể kết nối, kiểm tra, làm mới token, yêu cầu đồng bộ và ngắt kết nối. Thành viên có quyền truy cập workspace có thể xem danh sách, quyền hiện có và lịch sử kênh.

Chạy `python -m scripts.migrate` để áp dụng migration 004 trước khi khởi động API và worker. `SOCIAL_MODE=mock` dùng cho phát triển và gắn nhãn **Kênh mẫu**. Để kiểm thử tài khoản thật, đặt `SOCIAL_MODE=live`, cấu hình thông tin ứng dụng theo nền tảng ở máy chủ và dùng chính địa chỉ HTTPS trong `APP_URL` để mở giao diện. `APP_URL` và địa chỉ callback phải cùng origin với giao diện để hệ thống quay về đúng phiên đăng nhập sau khi cấp quyền.

Cùng một tài khoản có thể liên kết với nhiều workspace nếu người thực hiện có quyền trong từng workspace và tự cấp quyền nền tảng. Trong mỗi workspace, cặp nền tảng và ID tài khoản là duy nhất. Kết nối lại cập nhật bản ghi hiện tại. Ngắt kết nối chỉ thu hồi token lưu trong workspace đó, giữ lịch sử và hủy các lịch chưa gửi của kênh.

API bài đăng kiểm tra quyền đăng khi thêm kênh mới vào bài, khi lập lịch hoặc đăng, và trước lúc worker gửi. Các kênh đã có trong bản nháp vẫn có thể được chỉnh sửa. Kênh thật cũ chưa có thông tin quyền cần được kết nối lại trước khi đăng.

Các API quản lý theo phạm vi workspace dùng đường dẫn `W/social-accounts`.

| Phương thức và đường dẫn | Dữ liệu hoặc thao tác |
| --- | --- |
| `GET W/social-accounts?q=&platform=&status=&page=1&limit=20` | Tìm theo tên/ID, lọc và phân trang |
| `GET W/social-accounts/{id}` | Chi tiết và 10 lượt đồng bộ gần nhất |
| `GET W/social-accounts/{id}/permissions` | Quyền ghi nhận lúc cấp hoặc làm mới token. Kênh cũ có thể cần kết nối lại |
| `GET W/social-accounts/{id}/activity-logs?page=1&limit=20` | Lịch sử thao tác theo kênh |
| `POST W/social-accounts/{id}/check` | Kiểm tra token và nhận dạng tài khoản qua nhà cung cấp |
| `POST W/social-accounts/{id}/refresh` | Làm mới token TikTok. Meta yêu cầu cấp quyền lại khi cần |
| `POST W/social-accounts/{id}/sync/metrics` | Yêu cầu làm mới số liệu |
| `POST W/social-accounts/{id}/sync/inbox` | Yêu cầu làm mới hộp thư Facebook |
| `POST W/social-accounts/{id}/disconnect` | Ngắt kênh và hủy lịch chưa gửi |

Đồng bộ có trạng thái `pending`, `syncing`, `success` và `failed`. Số bản ghi là số dòng số liệu tài khoản hoặc số hội thoại đã xử lý, gồm bản ghi được cập nhật lại. OAuth web TikTok dùng state và callback HTTPS theo Login Kit. TikTok áp dụng PKCE cho các biến thể desktop/mobile. [TikTok Login Kit Web](https://developers.tiktok.com/docs/en/login-kit-web)

1. `POST W/social-accounts/oauth/facebook` (hoặc instagram/tiktok), lấy authorization_url.
2. Mở URL đó. Trong mock, URL đi thẳng callback nội bộ, không yêu cầu tài khoản thật.
3. Callback trả `connection_token` và danh sách tài khoản; token này hết hạn sau 10 phút, không phải OAuth access token.
4. `POST W/social-accounts/oauth/complete-selection`:

```json
{ "connection_token": "TOKEN_TU_CALLBACK", "external_account_ids": ["mock-facebook"] }
```

Kết nối lại cập nhật token trên cùng bản ghi. `GET W/social-accounts` xem trạng thái; `POST W/social-accounts/{id}/disconnect` ngắt, xóa token, hủy lịch chưa chạy. Nếu đang gửi bài, trả 409; xử lý xong rồi ngắt. `GET /platforms/{platform}/capabilities` cho biết chế độ và khả năng; live_verified hiện luôn false vì chưa chạy tài khoản thật.

### Kiểm thử Facebook Page thật

Để mở thử nghiệm chỉ cho Facebook, đặt `SOCIAL_OAUTH_PLATFORMS=facebook` và
`SOCIAL_OAUTH_REQUIRE_LIVE=true`. Giao diện chỉ mở nút kết nối Facebook khi
máy chủ đã có cấu hình OAuth live. Nếu chỉ kiểm tra kết nối và đồng bộ cơ bản,
đặt `FACEBOOK_OAUTH_SCOPES=pages_show_list,pages_read_engagement`. Cấp thêm
`pages_manage_posts` và kết nối lại nếu thử đăng trên Page có quyền tạo nội dung.

Trong Meta App Dashboard, bật sản phẩm đăng nhập phù hợp, khai báo chính sách quyền riêng tư và gửi App Review cho những quyền cần Advanced Access khi dùng với người ngoài vai trò ứng dụng. Các thao tác đăng bài và hộp thư phụ thuộc quyền đã cấp và nhiệm vụ trên Trang. [Meta Pages API](https://developers.facebook.com/docs/graph-api/reference/page/) · [Meta Insights và Advanced Access](https://developers.facebook.com/docs/insights/overview)

1. Đặt `SOCIAL_MODE=live`, `APP_URL=https://<tên-miền-API>`, `META_APP_ID`, `META_APP_SECRET` và `META_API_VERSION` trong cấu hình backend. Đăng ký chính xác `https://<tên-miền-API>/api/v1/oauth/facebook/callback` trong **Valid OAuth Redirect URIs** của Meta App.
2. Đăng nhập API bằng tài khoản có quyền `channel.manage`. Mở `authorization_url` bằng tài khoản Facebook có quyền trên Page và có thể dùng Meta App. Kiểm tra các quyền Pages được yêu cầu trong Meta App, gồm `pages_show_list` để liệt kê Page.
3. Callback trả JSON tại URL của backend. Lấy `connection_token` và ID Page từ danh sách, rồi gọi `complete-selection` với Bearer token của người đã bắt đầu OAuth trong cùng workspace.
4. Gọi `GET W/social-accounts` và đối chiếu ID Facebook, tên, ảnh (nếu Meta cung cấp) và trạng thái `connected`. Kết nối lại cùng Page và kiểm tra ID bản ghi giữ nguyên.

Backend đổi mã ủy quyền lấy user token dài hạn, dùng token đó để lấy danh sách Page và chỉ lưu Page token. Dữ liệu OAuth tạm và Page token lưu trong MySQL đều được mã hóa bằng `TOKEN_ENCRYPTION_KEY`. Callback từ chối state đã dùng hoặc hết hạn, trả `OAUTH_DENIED` nếu người dùng hủy và `NO_FACEBOOK_PAGES` nếu Meta không trả Page có token. Bắt đầu lại OAuth sau khi xử lý lỗi. Nếu chạy qua reverse proxy, cấu hình log của proxy để bỏ query string của callback.

### Kết nối Instagram Business hoặc Creator

Luồng này dùng Instagram API with Facebook Login. Tài khoản chuyên nghiệp phải liên kết với Facebook Page, và Page cần có trong cùng workspace. [Meta Instagram API](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/v21.0/)

1. Liên kết tài khoản Instagram chuyên nghiệp với Facebook Page trong Meta và kết nối Page đó vào workspace qua OAuth Facebook.
2. Trong chế độ live, đăng ký thêm `https://<tên-miền-API>/api/v1/oauth/instagram/callback` trong Meta App. Cấp `pages_show_list`, `pages_read_engagement`, `instagram_basic`, `instagram_content_publish` và `instagram_manage_insights`. Callback trả `INSTAGRAM_PERMISSIONS_MISSING` (403) nếu thiếu quyền.
3. Bắt đầu OAuth qua `POST W/social-accounts/oauth/instagram`. Callback trả tài khoản chuyên nghiệp Meta cho phép truy cập cùng `linked_page_external_id`. Nếu danh sách trống, API trả `NO_ELIGIBLE_INSTAGRAM_ACCOUNTS` (422).
4. Gửi ID Instagram vào `complete-selection`. Nếu Page chưa kết nối trong workspace, API trả `LINK_PAGE_FIRST` (422). Sau khi kết nối, `GET W/social-accounts` trả `linked_account_id` là ID nội bộ của Page. Trong mock, kết nối `mock-facebook` trước rồi chọn `mock-instagram`.

Meta trả cả Business và Creator qua trường `instagram_business_account`. Luồng Facebook Login này lưu cả hai dưới `account_type=business`.

### Kết nối TikTok qua Login Kit

Thêm Login Kit trong TikTok Developer Portal. Xin các quyền theo tính năng đã bật. Nội dung của ứng dụng chưa qua audit bị giới hạn chế độ xem riêng tư. Với `PULL_FROM_URL`, TikTok yêu cầu xác minh tên miền hoặc tiền tố URL chứa video. [TikTok Scopes](https://developers.tiktok.com/docs/en/scopes-overview) · [TikTok Direct Post](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post)

1. Đặt `SOCIAL_MODE=live`, `APP_URL=https://<tên-miền-API>`, `TIKTOK_CLIENT_KEY` và `TIKTOK_CLIENT_SECRET` ở backend. Đăng ký chính xác `https://<tên-miền-API>/api/v1/oauth/tiktok/callback` trong Login Kit.
2. Quyền mặc định là `user.info.basic`. Nếu ứng dụng đã được TikTok duyệt quyền cho các tính năng tương ứng, thêm `user.info.stats,video.publish,video.list` vào `TIKTOK_EXTRA_SCOPES` theo nhu cầu.
3. Gọi `POST W/social-accounts/oauth/tiktok` với quyền `channel.manage`, mở URL trả về và cấp quyền. Callback trả `OAUTH_DENIED` (400) khi người dùng từ chối hoặc hủy, hoặc `TIKTOK_PERMISSIONS_MISSING` (403) khi thiếu quyền đã yêu cầu. Bắt đầu lại OAuth sau khi xử lý lỗi.
4. Dùng `connection_token` và ID tài khoản từ callback để gọi `complete-selection` bằng cùng người dùng và workspace. `GET W/social-accounts` trả ID TikTok, tên hiển thị, ảnh đại diện nếu có và trạng thái `connected`. Backend lưu access token và refresh token dưới dạng mã hóa cùng hạn của access token.

`POST W/social-accounts/{id}/sync/metrics` hoặc `/sync/inbox` yêu cầu worker đồng bộ ở chu kỳ tiếp theo; cần channel.manage.

## 4. Media

`POST W/media`: multipart/form-data, field **file**, tùy chọn folder_id. Mỗi request một file; frontend có thể gửi nhiều request cho chọn nhiều tệp. Kiểm tra nội dung file thực, tạo thumbnail; JPEG/PNG/WebP và MP4. Video cần FFmpeg/FFprobe. Mặc định 50 MB/file và quota 1 GiB/workspace.

- GET W/media: q, media_type, folder_id, tag_id và phân trang.
- GET/PATCH/DELETE W/media/{id}: xem, đổi tên/di chuyển/gắn tag, xóa mềm.
- GET W/media/{id}/download-link: link ảnh và thumbnail ký số, hạn 1 giờ.
- GET W/media/usage: active_bytes và retained_bytes; quota tính cả tệp giữ cho lịch sử.
- GET/POST W/media-folders; PUT/DELETE W/media-folders/{id}.
- GET/POST W/media-tags; DELETE W/media-tags/{id}.

Xóa folder cần body `{"confirm":true}`, di chuyển tệp ra gốc; xóa thư mục con trước. Media dùng trong bài đã duyệt/chờ duyệt/có lịch/đang đăng bị chặn xóa để không làm hỏng bài. Xóa mềm không xóa tệp vật lý, nên retained_bytes chưa giảm. Chưa có API purge tệp; cần quy trình lưu trữ riêng.

## 5. Bài đăng, duyệt và lịch

`POST W/posts` và `PUT W/posts/{id}` (PUT thay toàn bộ nội dung):

```json
{
  "title": "Giới thiệu sản phẩm",
  "base_caption": "Nội dung chung",
  "media_ids": ["1"],
  "variants": [{ "social_account_id": "1", "caption": "Nội dung Facebook", "platform_options": {} }]
}
```

Caption variant null dùng base_caption. Không sửa bài pending_approval, scheduled, publishing hoặc đã đăng; hủy lịch trước khi sửa. Sửa bài approved chuyển draft và phải duyệt lại nếu bật require_approval. Bài đã có lịch sử không được xóa variant để tránh mất lịch sử; nhân bản nếu cần bộ kênh mới.

Khi tạo bài, gửi header `Idempotency-Key` (UUID hoặc chuỗi chữ/số/_/- tối đa 100 ký tự): cùng key và payload trả lại bài cũ, khác payload trả 409. Nếu không gửi key, mỗi request tạo một bài mới có chủ đích.

| API                                                  | Ý nghĩa                                                                 |
| ---------------------------------------------------- | ----------------------------------------------------------------------- |
| GET W/posts; GET W/posts/{id}                        | Danh sách, chi tiết                                                     |
| GET W/posts/{id}/preview                             | Nội dung đã ghép theo kênh cho frontend render                          |
| POST W/posts/{id}/duplicate; DELETE W/posts/{id}     | Nhân bản về draft, xóa mềm                                              |
| GET W/posts/{id}/history; GET W/posts/{id}/approvals | Lịch sử trạng thái và duyệt                                             |
| POST W/posts/{id}/approvals                          | Gửi duyệt, body note                                                    |
| POST W/posts/{id}/approvals/decision                 | decision approved/rejected; rejected bắt buộc reason                    |
| POST W/posts/{id}/approvals/withdraw                 | Rút duyệt về draft                                                      |
| GET/POST W/posts/{id}/comments                       | Bình luận nội bộ; POST có content/parent_comment_id                     |
| DELETE W/posts/{id}/comments/{commentId}             | Tác giả hoặc Admin xóa mềm                                              |
| POST W/posts/{id}/publish                            | Đăng các variant chưa thành công; cần post.publish                      |
| POST W/variants/{id}/schedules                       | Lên lịch với scheduled_at có timezone                                   |
| PATCH W/variants/{id}/schedules/{scheduleId}         | Đổi scheduled_at hoặc cancel=true                                       |
| GET W/calendar                                       | from/to có timezone; kênh/trạng thái/phân trang                         |
| GET W/variants/{id}/jobs                             | Lịch sử thử đăng theo lần mới nhất, gồm thời gian, kênh, trạng thái, kết quả và lỗi |
| POST W/variants/{id}/retry                           | Retry thủ công variant failed; cần post.publish                         |
| POST W/variants/{id}/reconcile                       | Xác minh external_post_id thuộc tài khoản để ghi nhận job mơ hồ đã đăng |

Worker lưu từng lần thử, tự retry lỗi tạm tối đa 3 lần sau lần đầu, chờ 60/120/240 giây hoặc lâu hơn theo rate limit. Không retry khi không biết nền tảng đã nhận bài hay chưa; job có needs_reconciliation=1. Xem quy trình đối soát trong PHAM_VI.md. Job từ lịch chỉ được tạo khi tới giờ. Hủy lịch trả 409 nếu worker đã bắt đầu gửi.

Đăng ngay trả 202 kèm jobs; poll GET chi tiết bài hoặc GET jobs. `published` chỉ khi mọi kênh thành công; một phần thành công là `partially_failed`. Trong mock, dùng platform_options.mock_failure bằng temporary/ambiguous để thử lỗi, chỉ sử dụng trên môi trường dev/test.

## 6. Báo cáo, hộp thư, thông báo và quản trị

| API                                                       | Nội dung                                                                              |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| GET W/reports/overview?from=2026-01-01&to=2026-12-31      | Series ngày, kênh, synced_at; thiếu dữ liệu là null                                   |
| GET W/reports/posts?from=...&to=...&metric=likes          | Xếp hạng theo snapshot mới nhất của bài đăng trong khoảng                             |
| POST W/reports/exports                                    | Body from/to, report_type channel_overview/post_performance, file_format csv/xlsx/pdf |
| GET W/reports/exports; GET W/reports/exports/{id}         | Xem tiến độ                                                                           |
| GET W/reports/exports/{id}/download                       | Tải file sau khi done; cần report.export                                              |
| GET W/conversations                                       | Lọc social_account_id/status/assigned_to                                              |
| GET W/conversations/{id}/messages                         | Lịch sử hội thoại                                                                     |
| PATCH W/conversations/{id}                                | Gán assigned_to hoặc status open/resolved/spam                                        |
| POST W/conversations/{id}/messages                        | content và request_id UUID; lặp request_id không gửi lại                              |
| GET /me/notifications; GET /me/notifications/unread-count | Thông báo còn quyền xem                                                               |
| POST /me/notifications/read                               | all=true hoặc notification_ids                                                        |
| GET/PUT W/notification-settings                           | Cấu hình type/in_app_enabled/email_enabled                                            |
| GET W/audit-logs                                          | Lọc thời gian, người, action; cần audit.view                                          |
| GET /admin/settings; PUT /admin/settings/{key}            | is_system_admin, khác Admin workspace                                                 |

Cấu hình runtime hỗ trợ media.workspace_quota_bytes, publish.max_retries và publish.retry_delays_seconds. Các khóa xác thực hiện chỉ đọc, chưa hỗ trợ thay đổi runtime. Hộp thư cần inbox.reply; viewer không đọc nội dung tin nhắn khách hàng.

Webhook Meta: GET/POST `/webhooks/meta`, xác minh verify token/chữ ký HMAC, chống xử lý trùng theo hash payload, đánh dấu kênh cần sync. Cần META_APP_SECRET và META_WEBHOOK_VERIFY_TOKEN, không dùng webhook để nhận payload không có chữ ký.
