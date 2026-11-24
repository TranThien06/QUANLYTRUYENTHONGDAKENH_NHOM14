import argparse
import os

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Chạy máy chủ Orbitspace")
    parser.add_argument("--demo", action="store_true", help="Chạy kết nối kênh demo trên máy cục bộ")
    args = parser.parse_args()
    if args.demo:
        os.environ["SOCIAL_MODE"] = "mock"
        os.environ["SOCIAL_OAUTH_PLATFORMS"] = "facebook,instagram,tiktok"
        os.environ["SOCIAL_OAUTH_REQUIRE_LIVE"] = "false"

    from app.config import settings

    if args.demo:
        if settings.env == "production":
            parser.error("--demo chỉ dùng ngoài production")
        os.environ["APP_URL"] = f"http://localhost:{settings.port}"
        os.environ["FRONTEND_URL"] = os.environ["APP_URL"]
        settings.app_url = settings.frontend_url = os.environ["APP_URL"]

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1" if args.demo else "0.0.0.0",
        port=settings.port,
        reload=settings.env == "development",
        access_log=False,
    )


if __name__ == "__main__":
    main()
