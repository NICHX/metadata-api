#!/usr/bin/env python3
"""
Metadata API 调用示例
"""

import requests
import json
from typing import Optional, List

# 默认服务器地址（局域网访问）
BASE_URL = "http://192.168.31.252:8000"


class MetadataAPIClient:
    def __init__(self, base_url: str = BASE_URL, auth_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.auth_key = auth_key

    @property
    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.auth_key:
            headers["Authorization"] = self.auth_key
        return headers

    def _get(self, path: str) -> requests.Response:
        return requests.get(f"{self.base_url}{path}", headers=self._headers)

    def _post(self, path: str, json_data: dict = None) -> requests.Response:
        return requests.post(f"{self.base_url}{path}", json=json_data, headers=self._headers)

    def _put(self, path: str, json_data: dict = None) -> requests.Response:
        return requests.put(f"{self.base_url}{path}", json=json_data, headers=self._headers)

    def health_check(self) -> dict:
        """健康检查"""
        response = self._get("/health")
        return response.json()

    def parse_filename(self, filename: str) -> dict:
        """解析文件名"""
        response = self._post("/api/v1/recognition/parse", json_data=filename)
        return response.json()

    def recognize_media(
        self,
        filename: str,
        source: str = "siliconflow_tmdb",
        media_type_override: Optional[str] = None,
    ) -> dict:
        """识别单个媒体文件"""
        payload = {
            "filename": filename,
            "source": source,
            "media_type_override": media_type_override,
        }
        response = self._post("/api/v1/recognition/recognize", json_data=payload)
        return response.json()

    def batch_recognize(
        self,
        filenames: List[str],
        source: str = "siliconflow_tmdb"
    ) -> dict:
        """批量识别媒体文件"""
        files = [{"filename": f} for f in filenames]
        payload = {"files": files, "source": source}
        response = self._post("/api/v1/recognition/batch-recognize", json_data=payload)
        return response.json()

    def preview_rename(self, file_info: List[dict]) -> dict:
        """预览重命名"""
        payload = {"files": file_info}
        response = self._post("/api/v1/media/preview-rename", json_data=payload)
        return response.json()

    def scrape_metadata(
        self,
        files: List[dict],
        source: str = "siliconflow_tmdb",
        download_images: bool = True,
        write_nfo: bool = True
    ) -> dict:
        """刮削元数据"""
        payload = {
            "files": files,
            "download_images": download_images,
            "write_nfo": write_nfo
        }
        response = requests.post(
            f"{self.base_url}/api/v1/media/scrape",
            json=payload,
            params={"source": source},
            headers=self._headers,
        )
        return response.json()

    def get_config(self) -> dict:
        """获取配置"""
        response = self._get("/api/v1/config")
        return response.json()

    def update_config(self, **kwargs) -> dict:
        """更新配置"""
        response = self._put("/api/v1/config", json_data=kwargs)
        return response.json()

    def clear_cache(self) -> dict:
        """清除 API 缓存"""
        response = self._post("/api/v1/config/clear-cache")
        return response.json()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Metadata API 客户端示例")
    parser.add_argument("server", nargs="?", default=BASE_URL,
                        help=f"API 服务器地址（默认: {BASE_URL}）")
    parser.add_argument("--auth", type=str, default="",
                        help="API 认证密钥，请求时在 Authorization 头中携带")
    args = parser.parse_args()

    client = MetadataAPIClient(base_url=args.server, auth_key=args.auth)

    if args.auth:
        print(f"Auth: 已启用（使用 Authorization 头认证）")
    else:
        print(f"Auth: 未启用")

    print("=" * 60)
    print(f"Metadata API 调用示例 (服务器: {args.server})")
    print("=" * 60)

    # 1. 健康检查
    print("\n1. 健康检查...")
    try:
        result = client.health_check()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"  连接失败: {e}")
        print("  请确保 API 服务已启动: python main_api.py")
        return

    # 2. 获取/显示当前配置
    print("\n2. 检查当前配置...")
    try:
        config = client.get_config()
        print(json.dumps(config, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"  获取配置失败（可能是认证未通过）: {e}")
        return

    if not config.get("tmdb_api_key_set"):
        print("\n⚠️  未设置 TMDb API 密钥，部分功能将无法使用")
        print("   可通过 PUT /api/v1/config 接口或 Web UI 配置")
        print("\n   如需获取 TMDb API 密钥，请访问:")
        print("   https://www.themoviedb.org/settings/api")

    # 3. 解析文件名
    print("\n3. 解析文件名示例:")
    filename = "[捕风追影].The.Shadow's.Edge.2025.2160p.60fps.HQ.WEB-DL.HEVC.10bit.DV.AV3A7.1.4.14Audios-QHstudIo.mp4"
    result = client.parse_filename(filename)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # 4. 识别单个媒体文件（指定电影类型）
    if config.get("tmdb_api_key_set"):
        print(f"\n4. 识别媒体文件（指定电影类型）: {filename}")
        result = client.recognize_media(
            filename,
            media_type_override="movie"
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if result.get("success"):
            print(f"\n   ✅ 成功识别: {result.get('recognized_title')}")
            print(f"   📎 TMDb ID: {result.get('match_id')}")
            print(f"   📝 建议名称: {result.get('suggested_new_name')}")

            # 获取海报
            metadata = result.get("metadata", {})
            poster_path = metadata.get("poster")
            fanart_path = metadata.get("fanart")
            if poster_path:
                # 方式一：通过代理获取图片数据
                print(f"\n5. 获取海报（方式一：API 代理）...")
                poster_url = f"{args.server}/api/v1/media/image?path={poster_path}&size=w500"
                print(f"   GET {poster_url}")
                print(f"   （浏览器打开即可看到海报图片）")

                # 方式二：获取完整 URL
                print(f"\n6. 获取海报 URL（方式二：直接 URL）...")
                img_resp = requests.get(
                    f"{args.server}/api/v1/media/image-url",
                    params={"path": poster_path, "size": "w500"},
                    headers=client._headers,
                )
                img_data = img_resp.json()
                print(f"   完整 URL: {img_data['url']}")
                print(f"   （浏览器打开即可看到海报图片）")

            # 下载海报到本地
            if poster_path:
                print(f"\n7. 下载海报到本地...")
                img_resp = requests.get(
                    f"{args.server}/api/v1/media/image",
                    params={"path": poster_path, "size": "w500"},
                    headers=client._headers,
                )
                if img_resp.status_code == 200:
                    save_path = "poster_sample.jpg"
                    with open(save_path, "wb") as f:
                        f.write(img_resp.content)
                    print(f"   已保存到: {save_path}")
        else:
            print(f"\n   ❌ 识别失败: {result.get('status')}")


if __name__ == "__main__":
    main()