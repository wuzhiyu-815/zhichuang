"""OpenAI 兼容接口客户端。"""

import re
import time

import requests


class LLM客户端:
    def __init__(self, endpoint_provider, ensure_local=None, logger=print):
        self.endpoint_provider = endpoint_provider
        self.ensure_local = ensure_local
        self.logger = logger

    def 检查(self, timeout=10):
        base, key, mode = self.endpoint_provider()
        try:
            response = requests.get(
                f"{base.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key}"} if key else {},
                timeout=timeout,
            )
            if response.status_code == 200:
                return True, None
            detail = response.text[:240].strip()
            return False, f"服务返回 HTTP {response.status_code}" + (f": {detail}" if detail else "")
        except Exception as exc:
            return False, str(exc)

    def 对话(self, messages, max_tokens=4096, temperature=0.7,
             retries=1, timeout=180, local_mode=False, response_format=None,
             model=None):
        base, key, endpoint_model = self.endpoint_provider()
        from urllib.parse import urlsplit
        parsed = urlsplit(base or '')
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return None, '当前任务未取得有效的大语言模型服务地址，请检查账号配置与任务配置传递'
        payload = {
            "model": model or endpoint_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if "deepseek" in (model or endpoint_model or "").lower():
            payload["reasoning_effort"] = "none"
        if response_format is not None:
            payload['response_format'] = response_format
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        last_error = None
        attempts = max(0, int(retries)) + 1
        for attempt in range(attempts):
            try:
                response = requests.post(
                    f"{base.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()
                if data['choices'][0].get('finish_reason') == 'length':
                    return None, '模型输出达到长度上限，内容不完整，请缩短请求或提高输出上限'
                content = data["choices"][0]["message"].get("content", "") or ""
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
                if content:
                    return content, None
                last_error = "模型返回空内容"
            except requests.exceptions.HTTPError as exc:
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                detail = (getattr(response, "text", "") or "")[:240].strip()
                last_error = f"LLM服务返回 HTTP {status}" if status else str(exc)
                if detail:
                    last_error += f": {detail}"
                # 认证、请求格式和模型名错误重试没有意义；仅对限流/服务端错误重试。
                if status is not None and status < 500 and status != 429:
                    break
                self.logger(f"[LLM] 第{attempt + 1}次调用失败: {last_error}")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = str(exc)
                self.logger(f"[LLM] 第{attempt + 1}次调用失败: {exc}")
                if (
                    local_mode
                    and isinstance(exc, requests.exceptions.ConnectionError)
                    and self.ensure_local
                ):
                    ok, boot_error = self.ensure_local()
                    if ok:
                        continue
                    last_error = f"本地LLM连接失败，自动重启也失败: {boot_error}; 原始错误: {exc}"
            except Exception as exc:
                last_error = str(exc)
                self.logger(f"[LLM] 第{attempt + 1}次调用失败: {exc}")
                break
            if attempt < attempts - 1:
                time.sleep(min(8, 1.5 * (2 ** attempt)))
        return None, last_error
