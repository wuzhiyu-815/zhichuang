"""ComfyUI service configuration and process-wide task allocation."""
import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from urllib.parse import urlparse, urlunparse

from infrastructure.comfy_client import Comfy客户端


def normalized_url(value):
    if not isinstance(value, str):
        raise ValueError('ComfyUI 地址必须是文本')
    parsed = urlparse(value.strip())
    try:
        port = parsed.port
    except ValueError:
        raise ValueError('ComfyUI 端口无效') from None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('ComfyUI 地址须为 http 或 https 基础地址，不含账号、查询参数或片段')
    host = parsed.hostname.lower()
    if host in ('localhost', '::1'):
        host = '127.0.0.1'
    elif ':' in host:
        host = f'[{host}]'
    if port and port != (443 if parsed.scheme == 'https' else 80):
        host += f':{port}'
    return urlunparse((parsed.scheme, host, parsed.path.rstrip('/'), '', '', ''))


def normalize_comfy_config(cfg, updates=None):
    updates = updates or {}
    servers = copy.deepcopy(cfg.get('comfyui_servers'))
    if servers is None:
        servers = [{'id': 'legacy', 'name': '默认 ComfyUI',
                    'url': cfg.get('comfyui_url', 'http://127.0.0.1:8189'), 'enabled': True}]
    elif 'comfyui_url' in updates and 'comfyui_servers' not in updates:
        target = next((s for s in servers if s.get('enabled', True)), None)
        if target is not None:
            target['url'] = updates['comfyui_url']
    if not isinstance(servers, list) or not 1 <= len(servers) <= 16:
        raise ValueError('请配置 1～16 个 ComfyUI 服务')
    ids, urls, clean = set(), set(), []
    for server in servers:
        if not isinstance(server, dict):
            raise ValueError('ComfyUI 服务配置格式错误')
        item = {}
        for field in ('id', 'name', 'url'):
            value = server.get(field, '')
            if not isinstance(value, str) or not value.strip():
                raise ValueError('请填写每个 ComfyUI 服务的名称和地址')
            item[field] = value.strip()
        item['url'] = normalized_url(item['url'])
        item['enabled'] = server.get('enabled', True)
        if not isinstance(item['enabled'], bool):
            raise ValueError('ComfyUI 启用状态必须是布尔值')
        if item['id'] in ids or item['url'] in urls:
            raise ValueError('ComfyUI 服务 ID 和地址不能重复')
        ids.add(item['id'])
        urls.add(item['url'])
        clean.append(item)
    enabled = [s for s in clean if s['enabled']]
    if not enabled:
        raise ValueError('请至少启用一个 ComfyUI 服务')
    cfg['comfyui_servers'] = clean
    cfg['comfyui_url'] = enabled[0]['url']
    return cfg


class ComfyPool:
    """One task per endpoint across pipelines and single-shot jobs."""
    def __init__(self, health=None, offline_timeout=300, poll_interval=0.5,
                 queue_probe=None, queue_timeout=2):
        self.condition = threading.Condition()
        self.busy = set()
        self.last_assigned = {}
        self.assignment_sequence = 0
        self.health = health
        self.offline_timeout = offline_timeout
        self.poll_interval = poll_interval
        self.queue_probe = queue_probe or (lambda url: Comfy客户端(lambda: url).队列(timeout=queue_timeout))
        self.probing = False
        self.queue_retry = {}

    def _queue_idle(self, server):
        if server['url'].startswith('jimeng://'):
            return True
        url = server['url']
        with self.condition:
            retry_at, previous = self.queue_retry.get(url, (0, None))
        if time.monotonic() < retry_at:
            return previous
        try:
            queue = self.queue_probe(url)
            idle = queue['running'] == 0 and queue['pending'] == 0
        except Exception:
            # Unknown queues must never be treated as empty.
            idle = None
        with self.condition:
            if idle is True:
                self.queue_retry.pop(url, None)
            else:
                # Many waiting jobs share the retry delay; empty queues are
                # always checked afresh before a new reservation.
                self.queue_retry[url] = (time.monotonic() + self.poll_interval, idle)
        return idle

    @staticmethod
    def resolve(servers):
        return [{**s, 'url': s['url'].rstrip('/')} for s in (servers() if callable(servers) else servers)
                if s.get('enabled',True) and s.get('url')]

    @contextmanager
    def acquire(self, servers, cancel_event=None):
        offline_since=None
        while True:
            if cancel_event and cancel_event.is_set():
                raise RuntimeError('任务已停止')
            candidates=self.resolve(servers)
            if not candidates:
                raise RuntimeError('没有已启用且分配给当前用户的 ComfyUI 节点')
            if self.health:self.health.observe(candidates)
            online=[s for s in candidates if not self.health or self.health.online(s['url'])]
            with self.condition:
                if self.probing:
                    self.condition.wait(self.poll_interval)
                    continue
                available = [s for s in online if s['url'] not in self.busy]
                locally_busy = any(s['url'] in self.busy for s in online)
                self.probing = True
            try:
                # Probe in parallel without holding the reservation lock. Only one
                # dispatcher probes at a time, so concurrent snapshots cannot race.
                if available:
                    with ThreadPoolExecutor(max_workers=min(16, len(available))) as executor:
                        states = list(executor.map(self._queue_idle, available))
                else:
                    states = []
                if cancel_event and cancel_event.is_set():
                    raise RuntimeError('任务已停止')
                allowed = {s['url'] for s in self.resolve(servers)}
                now = time.monotonic()
                if locally_busy or any(state is not None for state in states):
                    offline_since = None
                elif offline_since is None:
                    offline_since = now
                elif now - offline_since >= self.offline_timeout:
                    raise RuntimeError('等待 ComfyUI 节点上线或队列查询恢复超时，请检查节点后重试')
                with self.condition:
                    idle = [s for s, state in zip(available, states)
                            if state is True and s['url'] in allowed and s['url'] not in self.busy]
                    server = min(idle, key=lambda s: self.last_assigned.get(s['url'], 0), default=None)
                    if server is not None:
                        self.busy.add(server['url'])
                        self.assignment_sequence += 1
                        self.last_assigned[server['url']] = self.assignment_sequence
            finally:
                with self.condition:
                    self.probing = False
                    self.condition.notify_all()
            if server is not None:
                break
            with self.condition:
                self.condition.wait(self.poll_interval)
        try:
            yield server
        finally:
            with self.condition:
                self.busy.discard(server['url'])
                self.condition.notify_all()

    def is_busy(self, url):
        with self.condition:
            return url.rstrip('/') in self.busy

    def busy_urls(self):
        with self.condition:
            return sorted(self.busy)

    def run(self, jobs, servers, work, cancel_event=None, before_acquire=None):
        """Resolve authorization and health at dispatch; newly online nodes take pending jobs.

        Once work has started we never replay it automatically on another endpoint:
        a lost response does not prove the original render was not submitted.
        """
        def execute(job):
            try:
                if before_acquire:before_acquire(job)
                with self.acquire(servers,cancel_event=cancel_event) as server:
                    return work(job,server),None
            except Exception as exc:
                return None,str(exc)

        if not jobs:return
        capacity=32 if callable(servers) else max(1,len(servers))
        with ThreadPoolExecutor(max_workers=min(capacity,len(jobs))) as executor:
            futures={executor.submit(execute,job):job for job in jobs}
            for future in as_completed(futures):
                result,error=future.result()
                yield futures[future],result,error
