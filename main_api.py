import uvicorn
import argparse
import logging
from api.config import settings, DeploymentMode

# 配置详细日志输出
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# 抑制 httpx 的 INFO 级请求日志，避免大量并发日志导致阻塞
logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(
        description="Metadata API Server"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to listen on (default: 0.0.0.0, 允许外部访问)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["local", "remote"],
        default=settings.mode.value,
        help=f"Deployment mode (default: {settings.mode.value})",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="仅允许本地访问 (绑定到 127.0.0.1)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (for development)",
    )
    parser.add_argument(
        "--auth",
        type=str,
        default=None,
        help="API 认证密钥，请求需在 Authorization 或 Authentication 头中携带此值（留空则不启用）",
    )

    args = parser.parse_args()

    # 设置部署模式和主机地址
    if args.mode == "local":
        settings.mode = DeploymentMode.LOCAL
    else:
        settings.mode = DeploymentMode.REMOTE

    # 设置认证密钥（优先使用命令行参数，否则保持 env / config 中的值）
    if args.auth is not None:
        settings.auth_key = args.auth

    # 如果指定 --local-only，绑定到本地地址
    host = "127.0.0.1" if args.local_only else args.host

    print(f"Starting Metadata API in {settings.mode} mode...")
    base_url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{args.port}"
    print(f"API URL: {base_url}")
    print(f"Web UI:  {base_url}/web-ui")
    print(f"Swagger: {base_url}/docs")
    if settings.auth_key:
        print(f"Auth: Enabled（Authorization / Authentication header 验证已开启）")
    else:
        print(f"Auth: Disabled（无认证要求）")

    uvicorn.run(
        "api.main:app",
        host=host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
