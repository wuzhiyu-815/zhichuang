import ast
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from infrastructure.render_executor import 渲染执行器
from core.rerender_state import recover, recoverable, store


class RecoveryTests(unittest.TestCase):
    def test_502_then_success_submits_only_once(self):
        client = Mock()
        client.提交.return_value = 'original'
        result = {'status': {'completed': True, 'status_str': 'success'}}
        client.历史.side_effect = [(None, 'HTTP 502'), (result, None)]
        with patch('infrastructure.render_executor.time.time', side_effect=range(0, 1000, 10)), \
                patch('infrastructure.render_executor.time.sleep'):
            history, error = 渲染执行器(client).执行({}, timeout=500, use_websocket=False)
        self.assertEqual(history, result)
        self.assertIsNone(error)
        client.提交.assert_called_once()
        self.assertEqual(client.历史.call_args.args, ('original',))

    def test_real_execution_error_is_terminal_even_if_completed(self):
        client = Mock()
        client.历史.return_value = ({'status': {'completed': True, 'status_str': 'error'}}, None)
        history, error = 渲染执行器(client).执行({}, use_websocket=False)
        self.assertIsNone(history)
        self.assertIn('执行错误', error)

    def test_only_submitted_transport_failures_recover(self):
        base = dict(status='error', prompt_id='p', node_url='http://node')
        self.assertTrue(recoverable(dict(base, msg='渲染失败: ComfyUI历史接口返回 HTTP 502')))
        self.assertFalse(recoverable(dict(base, msg='ComfyUI执行错误: out of memory')))
        self.assertFalse(recoverable(dict(base, prompt_id='', msg='HTTP 502')))

    def test_missing_history_remains_pending(self):
        with patch('core.rerender_state.Comfy客户端') as client:
            client.return_value.历史.return_value = (None, 'HTTP 502')
            task = recover(dict(status='error', prompt_id='p', node_url='http://node'), Mock())
        self.assertEqual(task['status'], 'running')

    def test_recovery_archives_old_video_before_replacing_it(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'out'; canonical = output / 'p' / 'shot_01.mp4'
            canonical.parent.mkdir(parents=True); canonical.write_bytes(b'old')
            task = dict(id='batch_1', pid='p', index=1, kind='batch', status='running',
                        prompt_id='original', node_url='http://node', created=1)
            project = {'shots': [{'index': 1, 'video_url': 'old'}]}
            engine = SimpleNamespace(OUTPUTS_DIR=output, PROJECTS_DIR=Path(root) / 'projects',
                PROJECT_IO_LOCK=threading.RLock(), load_project=lambda _: project,
                _archive_before_overwrite=Mock(side_effect=lambda *_: self.assertEqual(canonical.read_bytes(), b'old')),
                invalidate_final=Mock(), save_project=Mock())
            with patch('core.rerender_state.Comfy客户端') as factory, patch('core.rerender_state.subprocess.run'):
                client = factory.return_value
                client.历史.return_value = ({'status': {'completed': True},
                    'outputs': {'1': {'images': [{'filename': 'new.mp4'}]}}}, None)
                client.下载.side_effect = lambda _, path: Path(path).write_bytes(b'new')
                result = recover(task, engine)
            self.assertEqual(result['status'], 'done')
            self.assertEqual(canonical.read_bytes(), b'new')
            engine.save_project.assert_called_once()

    def test_restart_rebuilds_batch_and_clears_false_failure(self):
        with tempfile.TemporaryDirectory() as root:
            store(root, 'p').save('batch_21', dict(id='batch_21', kind='batch', pid='p', index=21, status='done'))
            ns = dict(Path=Path, json=json, time=time, PROJECTS_DIR=root, RERENDER_TASKS={},
                BATCH_RENDER_TASKS={}, SUBMITTED_RENDER_RECEIPTS=set(),
                SUBMITTED_RENDER_RECEIPTS_LOCK=threading.RLock(), recoverable_receipt=recoverable)
            tree = ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_sync_render_receipt_tasks')
            exec(compile(ast.Module(body=[fn], type_ignores=[]), 'app.py', 'exec'), ns)
            ns['_sync_render_receipt_tasks']()
            self.assertEqual(ns['BATCH_RENDER_TASKS']['batch']['status'], 'done')


if __name__ == '__main__':
    unittest.main()
