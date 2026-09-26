"""即梦局域网 API 客户端。

服务端提供 OpenAI 风格的图片接口，以及同项目约定的视频接口。
参考图在客户端进程中读取并编码为 data URL，避免把本机路径传给远端服务。
"""

import base64
import mimetypes
import os
from urllib.parse import urlparse

import requests


class 即梦客户端:
    def __init__(self, base_url_provider, api_key_provider, logger=print):
        self.base_url_provider = base_url_provider
        self.api_key_provider = api_key_provider
        self.logger = logger

    def 地址(self):
        value = str(self.base_url_provider() or "").rstrip("/")
        return value[:-3] if value.lower().endswith("/v1") else value

    def _headers(self):
        key = str(self.api_key_provider() or "").strip()
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def 检查(self, timeout=5):
        try:
            response = requests.get(f"{self.地址()}/ping", timeout=timeout)
            return response.status_code == 200, None if response.status_code == 200 else response.text[:240]
        except Exception as exc:
            return False, str(exc)

    def 模型(self, model_type=None, timeout=30):
        params = {"type": model_type} if model_type else {}
        response = requests.get(
            f"{self.地址()}/v1/models",
            params=params,
            headers=self._headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]

    @staticmethod
    def 图片数据(path):
        with open(path, "rb") as source:
            encoded = base64.b64encode(source.read()).decode("ascii")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{encoded}"

    def _结果地址(self, data, media_name):
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            raise RuntimeError(f"即梦{media_name}接口未返回 data")
        item = items[0] or {}
        url = item.get("url") or item.get("uri")
        if not url:
            raise RuntimeError(f"即梦{media_name}接口未返回媒体地址: {str(data)[:500]}")
        return str(url)

    def 生成图片(self, prompt, model, ratio, resolution, count=1, timeout=1800):
        payload = {
            "model": model,
            "prompt": prompt,
            "ratio": ratio,
            "resolution": resolution,
            "n": count,
            "response_format": "url",
        }
        response = requests.post(
            f"{self.地址()}/v1/images/generations",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return self._结果地址(response.json(), "图片")

    def 生成视频(self, prompt, model, ratio, duration, file_paths=None, timeout=1800):
        payload = {
            "model": model,
            "prompt": prompt,
            "ratio": ratio,
            "duration": int(duration),
            "response_format": "url",
        }
        refs = [path for path in (file_paths or []) if path and os.path.isfile(path)]
        if refs:
            refs = refs[:10]
            self.logger(f"[即梦] 视频参考图 {len(refs)} 张: {', '.join(os.path.basename(p) for p in refs)}")
            payload["file_paths"] = [self.图片数据(path) for path in refs]
        response = requests.post(
            f"{self.地址()}/v1/videos/generations",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return self._结果地址(response.json(), "视频")

    def 下载(self, url, save_path, timeout=1800):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise RuntimeError("即梦返回了无效的媒体地址")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with open(save_path, "wb") as target:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        target.write(chunk)
        if not os.path.isfile(save_path) or os.path.getsize(save_path) <= 0:
            raise RuntimeError("即梦媒体下载结果为空")
        return save_path
