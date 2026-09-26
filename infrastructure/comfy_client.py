"""ComfyUI HTTP 客户端。

进度监控和业务工作流仍由 app.py 管理，本客户端只负责通用 HTTP 操作。
"""

import json
import os
import tempfile
import time

import requests


class Comfy客户端:
    def __init__(self, url_provider, logger=print):
        self.url_provider = url_provider
        self.logger = logger

    def 地址(self):
        return str(self.url_provider()).rstrip("/")

    def 检查(self, timeout=5):
        try:
            response = requests.get(f"{self.地址()}/system_stats", timeout=timeout)
            return response.status_code == 200
        except Exception:
            return False

    def 提交(self, workflow, client_id=None, timeout=30):
        payload = {"prompt": workflow}
        if client_id:
            payload["client_id"] = client_id
        response = requests.post(
            f"{self.地址()}/prompt",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise RuntimeError("ComfyUI未返回prompt_id" + (f": {payload}" if payload else ""))
        return prompt_id

    def 队列(self, timeout=2):
        response = requests.get(
            f"{self.地址()}/queue", timeout=timeout, allow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
        if (not isinstance(payload, dict)
                or not isinstance(payload.get('queue_running'), list)
                or not isinstance(payload.get('queue_pending'), list)):
            raise ValueError('ComfyUI 队列响应格式错误')
        return {'running': len(payload['queue_running']),
                'pending': len(payload['queue_pending'])}

    def 等待(self, prompt_id, timeout=1200, interval=3):
        start = time.time()
        while time.time() - start < timeout:
            try:
                response = requests.get(
                    f"{self.地址()}/history/{prompt_id}",
                    timeout=15,
                )
                if response.status_code == 200:
                    history = response.json()
                    if prompt_id in history and history[prompt_id].get("status", {}).get("completed"):
                        return history[prompt_id], None
                    if prompt_id in history:
                        status = history[prompt_id].get("status", {})
                        if status.get("status_str") == "error":
                            return None, (
                                "ComfyUI执行错误: "
                                + json.dumps(status.get("messages", []), ensure_ascii=False)[:300]
                            )
            except Exception as exc:
                self.logger(f"[ComfyUI] 轮询异常: {exc}")
            time.sleep(interval)
        return None, f"ComfyUI生成超时({timeout}秒)"

    def 历史(self, prompt_id, timeout=15):
        try:
            response = requests.get(
                f"{self.地址()}/history/{prompt_id}",
                timeout=timeout,
            )
            if response.status_code != 200:
                return None, f"ComfyUI历史接口返回 HTTP {response.status_code}"
            history = response.json()
            if prompt_id not in history:
                return None, None
            return history[prompt_id], None
        except Exception as exc:
            self.logger(f"[ComfyUI] 历史轮询异常: {exc}")
            return None, None

    def 下载(self, file_info, save_path, timeout=120):
        params = {
            "filename": file_info["filename"],
            "subfolder": file_info.get("subfolder", ""),
            "type": file_info.get("type", "output"),
        }
        response = requests.get(f"{self.地址()}/view", params=params, timeout=timeout)
        response.raise_for_status()
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix='.download-', suffix='.part',
                                          dir=os.path.dirname(os.path.abspath(save_path)))
        try:
            with os.fdopen(fd, "wb") as file:
                if not response.content:
                    raise RuntimeError('ComfyUI下载返回空文件')
                file.write(response.content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, save_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        return save_path

    def 上传图片(self, file_path, timeout=60):
        with open(file_path, "rb") as file:
            response = requests.post(
                f"{self.地址()}/upload/image",
                files={"image": (os.path.basename(file_path), file, "image/png")},
                data={"overwrite": "true"},
                timeout=timeout,
            )
        response.raise_for_status()
        return response.json()
