"""ComfyUI 工作流执行器。

这里集中处理工作流提交、WebSocket 进度、历史轮询、超时和统一进度回调。
具体工作流内容、输出文件类型和项目存档仍由上层业务负责。
"""

import json
import re
import time
import uuid


class 渲染执行器:
    def __init__(self, comfy_client, monitor=None, logger=print):
        self.comfy_client = comfy_client
        self.monitor = monitor or {}
        self.logger = logger

    def _monitor(self, name, *args, **kwargs):
        callback = self.monitor.get(name)
        if callback:
            callback(*args, **kwargs)

    def 执行(
        self,
        workflow,
        task_label="ComfyUI工作流",
        timeout=1800,
        interval=2,
        estimated_seconds=240,
        progress_callback=None,
        use_websocket=True,
    ):
        client_id = uuid.uuid4().hex
        websocket = None
        prompt_id = None
        try:
            self._monitor("begin", workflow, task_label=task_label)
            if use_websocket:
                websocket = self._connect_websocket(client_id)
            prompt_id = self.comfy_client.提交(
                workflow,
                client_id=client_id if websocket is not None else None,
            )
            self._monitor("set_prompt", prompt_id)
            return self._wait(
                prompt_id,
                websocket,
                timeout,
                interval,
                estimated_seconds,
                progress_callback,
            )
        except Exception as exc:
            self._monitor("finish", False, exc)
            raise
        finally:
            if websocket is not None:
                try:
                    websocket.close()
                except Exception:
                    pass

    def _connect_websocket(self, client_id):
        try:
            import websocket
            ws_url = re.sub(
                r"^http",
                "ws",
                self.comfy_client.地址(),
            ) + f"/ws?clientId={client_id}"
            return websocket.create_connection(ws_url, timeout=5)
        except Exception as exc:
            self.logger(f"[ComfyUI] WebSocket进度不可用，改用估算进度: {exc}")
            return None

    def _wait(
        self,
        prompt_id,
        websocket,
        timeout,
        interval,
        estimated_seconds,
        progress_callback,
    ):
        start = time.time()
        last_emit = 0.0
        max_percent = 0
        got_real_progress = False
        if websocket is not None:
            try:
                websocket.settimeout(0.8)
            except Exception:
                pass

        def emit(percent, phase="渲染中", estimated=False, force=False):
            nonlocal last_emit, max_percent
            now = time.time()
            if not force and now - last_emit < 0.7:
                return
            percent = max(max_percent, int(max(0, min(99, percent))))
            max_percent = percent
            elapsed = max(0, int(now - start))
            if percent > 2:
                eta = int(max(0, elapsed * (100 - percent) / max(percent, 1)))
            else:
                eta = int(max(0, estimated_seconds - elapsed))
            self._monitor(
                "update",
                percent=percent,
                elapsed=elapsed,
                eta=eta,
                phase=phase,
            )
            if progress_callback:
                try:
                    progress_callback({
                        "percent": percent,
                        "elapsed": elapsed,
                        "eta": eta,
                        "estimated": bool(estimated),
                        "phase": phase,
                    })
                except Exception:
                    pass
            last_emit = now

        emit(0, "等待ComfyUI开始", estimated=websocket is None, force=True)
        next_poll = 0.0
        while time.time() - start < timeout:
            now = time.time()
            if websocket is not None:
                try:
                    message = websocket.recv()
                    if isinstance(message, str):
                        payload = json.loads(message)
                        event_type = payload.get("type")
                        data = payload.get("data") or {}
                        message_prompt_id = data.get("prompt_id")
                        if message_prompt_id and message_prompt_id != prompt_id:
                            continue
                        if event_type == "progress":
                            value = float(data.get("value", 0) or 0)
                            maximum = float(data.get("max", 0) or 0)
                            if maximum > 0:
                                got_real_progress = True
                                emit(
                                    min(95, max(1, round(value / maximum * 95))),
                                    "H3采样中",
                                    force=True,
                                )
                        elif event_type == "executing":
                            node = data.get("node")
                            if node is not None:
                                self._monitor("update", current_node=node, phase="执行节点")
                            elif data.get("prompt_id") in (None, prompt_id):
                                emit(99, "编码保存中", estimated=not got_real_progress, force=True)
                        elif event_type in ("execution_success", "executed"):
                            emit(max(max_percent, 98), "输出处理中", estimated=not got_real_progress, force=True)
                except Exception:
                    pass

            if now >= next_poll:
                next_poll = now + interval
                history, error = self.comfy_client.历史(prompt_id)
                # Transport failure does not establish failure of the submitted job.
                if error and history is None:
                    emit(max_percent, "连接暂时中断，正在查询原任务", estimated=True, force=True)
                    next_poll = time.time() + max(interval, 5)
                    continue
                if history is not None:
                    status = history.get("status", {})
                    if status.get("status_str") == "error":
                        error = "ComfyUI执行错误: " + json.dumps(status.get("messages", []), ensure_ascii=False)[:300]
                        self._monitor("finish", False, error)
                        return None, error
                    if status.get("completed"):
                        elapsed = max(0, int(time.time() - start))
                        if progress_callback:
                            try:
                                progress_callback({
                                    "percent": 100,
                                    "elapsed": elapsed,
                                    "eta": 0,
                                    "estimated": False,
                                    "phase": "完成",
                                })
                            except Exception:
                                pass
                        self._monitor("finish", True)
                        return history, None
                    if status.get("status_str") == "error":
                        error = (
                            "ComfyUI执行错误: "
                            + json.dumps(status.get("messages", []), ensure_ascii=False)[:300]
                        )
                if error:
                    self._monitor("finish", False, error)
                    return None, error
                if not got_real_progress:
                    elapsed = time.time() - start
                    ratio = min(
                        0.94,
                        elapsed / max(float(estimated_seconds), elapsed + 30.0),
                    )
                    emit(max(2, round(ratio * 100)), "渲染中（估算）", estimated=True, force=True)
            time.sleep(0.08)

        error = f"ComfyUI生成超时({timeout}秒)"
        self._monitor("finish", False, error)
        return None, error
