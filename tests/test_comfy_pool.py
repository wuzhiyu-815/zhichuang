import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from comfy_pool import ComfyPool
from infrastructure.comfy_client import Comfy客户端


NODES = [{'id': str(i), 'url': f'http://node{i}', 'enabled': True} for i in range(3)]
EMPTY = {'running': 0, 'pending': 0}


class PoolTests(unittest.TestCase):
    def pool(self, probe):
        return ComfyPool(queue_probe=probe, poll_interval=0.001, offline_timeout=0.01)

    def test_external_running_and_pending_are_skipped(self):
        loads = [{'running': 1, 'pending': 0}, {'running': 0, 'pending': 2}, EMPTY]
        pool = self.pool(lambda url: loads[int(url[-1])])
        with pool.acquire(NODES) as node:
            self.assertEqual(node['id'], '2')

    def test_rotation_with_fresh_queue_check(self):
        probe = Mock(return_value=EMPTY)
        pool = self.pool(probe)
        picked = []
        for _ in range(6):
            with pool.acquire(NODES) as node:
                picked.append(node['id'])
        self.assertEqual(picked, ['0', '1', '2', '0', '1', '2'])
        self.assertEqual(probe.call_count, 18)

    def test_wait_until_remote_queue_drains(self):
        probe = Mock(side_effect=[{'running': 1, 'pending': 2}, EMPTY])
        with self.pool(probe).acquire(NODES[:1]) as node:
            self.assertEqual(node['id'], '0')
        self.assertEqual(probe.call_count, 2)

    def test_failed_queue_is_skipped(self):
        def probe(url):
            if url.endswith('0'):
                raise TimeoutError()
            return EMPTY
        with self.pool(probe).acquire(NODES[:2]) as node:
            self.assertEqual(node['id'], '1')

    def test_all_failed_queues_timeout(self):
        pool = self.pool(Mock(side_effect=TimeoutError()))
        with self.assertRaisesRegex(RuntimeError, '队列查询恢复超时'):
            with pool.acquire(NODES):
                self.fail('Unknown queue was allocated')
        self.assertEqual(pool.busy_urls(), [])

    def test_concurrent_jobs_reserve_distinct_nodes(self):
        pool = self.pool(lambda url: EMPTY)
        barrier = threading.Barrier(3)
        def work():
            with pool.acquire(NODES) as node:
                barrier.wait(timeout=3)
                return node['id']
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda _: work(), range(3)))
        self.assertEqual(set(results), {'0', '1', '2'})
        self.assertEqual(pool.busy_urls(), [])

    def test_cancel_during_probe(self):
        cancel = threading.Event()
        def probe(url):
            cancel.set()
            return EMPTY
        pool = self.pool(probe)
        with self.assertRaisesRegex(RuntimeError, '已停止'):
            with pool.acquire(NODES[:1], cancel):
                self.fail('Cancelled task was allocated')
        self.assertFalse(pool.probing)
        self.assertEqual(pool.busy_urls(), [])

    def test_authorization_rechecked_after_probe(self):
        nodes = list(NODES[:1])
        def probe(url):
            nodes.clear()
            return EMPTY
        pool = self.pool(probe)
        with self.assertRaisesRegex(RuntimeError, '没有已启用'):
            with pool.acquire(lambda: nodes):
                self.fail('Removed node was allocated')

    def test_release_after_work_failure(self):
        pool = self.pool(lambda url: EMPTY)
        with self.assertRaises(ValueError):
            with pool.acquire(NODES):
                raise ValueError('work failed')
        self.assertEqual(pool.busy_urls(), [])

    def test_jimeng_does_not_probe_http(self):
        probe = Mock(side_effect=AssertionError('HTTP probe'))
        with self.pool(probe).acquire([{'url': 'jimeng://api'}]):
            pass
        probe.assert_not_called()


class QueueClientTests(unittest.TestCase):
    @patch('infrastructure.comfy_client.requests.get')
    def test_queue_counts_and_validation(self, get):
        client = Comfy客户端(lambda: 'http://node0/')
        get.return_value.json.return_value = {'queue_running': [[1]], 'queue_pending': [[2], [3]]}
        self.assertEqual(client.队列(), {'running': 1, 'pending': 2})
        get.assert_called_with('http://node0/queue', timeout=2, allow_redirects=False)
        for malformed in ({}, {'queue_running': [], 'queue_pending': None}, []):
            get.return_value.json.return_value = malformed
            with self.assertRaises(ValueError):
                client.队列()


if __name__ == '__main__':
    unittest.main()
