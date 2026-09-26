"""Bounded background probes; health state never grants node authorization."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests


class NodeMonitor:
    def __init__(self, interval=5, timeout=2, probe=None):
        self.interval, self.timeout = interval, timeout
        self.probe = probe or self._probe
        self.lock = threading.RLock()
        self.states = {}
        self.pending = set()
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix='node-probe')
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.provider = None
        self.provider_due = 0

    def _probe(self, url):
        try:
            response = requests.get(url+'/system_stats', timeout=self.timeout, allow_redirects=False)
            if response.status_code != 200:
                return False
            payload = response.json()
            return isinstance(payload,dict) and ('system' in payload or 'devices' in payload)
        except (requests.RequestException, ValueError):
            return False

    def start(self, provider=None):
        with self.lock:
            if provider is not None:
                self.provider = provider
            if self.thread is None:
                self.thread = threading.Thread(target=self._loop,daemon=True,name='node-health')
                self.thread.start()

    def observe(self, servers):
        now=time.monotonic()
        with self.lock:
            for server in servers:
                url=str(server.get('url') or '').rstrip('/')
                if url.startswith(('http://','https://')):
                    self.states.setdefault(url,dict(online=None,checked_at=0,due=0))['seen']=now
        self.start()
        self.wake.set()

    def snapshot(self, url):
        with self.lock:
            state=self.states.get(url.rstrip('/'),{})
            return dict(online=state.get('online'),checked_at=state.get('checked_at',0))

    def online(self, url):
        if url.startswith('jimeng://'):
            return True
        return self.snapshot(url)['online'] is True

    def _check(self, url):
        try:
            online=bool(self.probe(url))
        except Exception:
            online=False
        with self.lock:
            state=self.states.get(url)
            if state is not None:
                state.update(online=online,checked_at=time.time(),due=time.monotonic()+self.interval)
            self.pending.discard(url)

    def _loop(self):
        while not self.stop_event.is_set():
            if self.provider and time.monotonic() >= self.provider_due:
                self.provider_due=time.monotonic()+self.interval
                try:
                    servers=self.provider()
                    now=time.monotonic()
                    with self.lock:
                        for s in servers:
                            url=str(s.get('url') or '').rstrip('/')
                            if url.startswith(('http://','https://')):
                                self.states.setdefault(url,dict(online=None,checked_at=0,due=0))['seen']=now
                except Exception:
                    pass  # A configuration read failure must not terminate monitoring.
            now=time.monotonic()
            with self.lock:
                for url,state in list(self.states.items()):
                    if now-state.get('seen',now)>60 and url not in self.pending:
                        del self.states[url]
                        continue
                    if state['due']<=now and url not in self.pending and len(self.pending)<8:
                        self.pending.add(url)
                        self.executor.submit(self._check,url)
            self.wake.wait(0.5)
            self.wake.clear()

    def close(self):
        self.stop_event.set();self.wake.set()
        if self.thread:self.thread.join(timeout=3)
        self.executor.shutdown(wait=True,cancel_futures=True)
