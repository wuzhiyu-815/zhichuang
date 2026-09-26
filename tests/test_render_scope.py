"""Exercise the real Flask entry point without starting GPUs or background services."""
import ast
import copy
import json
from pathlib import Path
import threading
import tempfile
import time
import unittest
import uuid
from unittest.mock import Mock

from flask import Flask, Response, jsonify, request


class RenderScopeTests(unittest.TestCase):
    def setUp(self):
        project = {'id': 'test', 'script': {'shots': [{'index': i} for i in range(1, 22)]},
                   'shots': [{'index': i, 'video_url': 'saved.mp4'} for i in range(1, 14)]}
        self.project = project
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.render = Mock()
        app = Flask(__name__)
        ns = dict(app=app, request=request, jsonify=jsonify, Response=Response,
                  copy=copy, time=time, uuid=uuid, threading=threading,
                  Path=Path, json=json, PROJECTS_DIR=self.directory.name,
                  serialized_queue=lambda fn: fn,
                  load_project=lambda pid: project, project_render_config=lambda p: {},
                  _shot_has_current_video=lambda s: bool(s.get('video_url')) and not s.get('continuity_stale'),
                  BATCH_RENDER_TASKS={}, _render_selected_shots=self.render,
                  set_runtime_config=lambda cfg: None, clear_runtime_config=lambda: None,
                  sse=lambda event, data: f'event: {event}\ndata: {json.dumps(data)}\n\n')
        tree = ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'api_render_selected_stream')
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'route', 'exec'), ns)
        self.client = app.test_client()
        self.tasks = ns['BATCH_RENDER_TASKS']

    def test_reconnecting_batch_does_not_duplicate_pending_work(self):
        self.tasks['original'] = {'pid': 'test', 'status': 'running', 'indexes': [17, 18]}
        response = self.client.get('/api/project/test/shots/render_selected_stream?indexes=17,18')
        self.assertIn('already_running', response.get_data(as_text=True))
        self.render.assert_not_called()

    def test_restart_keeps_submitted_receipt_on_original_node(self):
        directory = Path(self.directory.name) / 'test' / 'rerender_tasks'
        directory.mkdir(parents=True)
        (directory / 'original.json').write_text(json.dumps({'index': 17, 'status': 'running',
            'prompt_id': 'original-prompt', 'node_url': 'http://node'}), encoding='utf-8')
        self.client.get('/api/project/test/shots/render_selected_stream?indexes=17,18,19').get_data()
        self.assertEqual(self.render.call_args.args[1], [18, 19])

    def test_all_pending_ignores_incomplete_browser_selection(self):
        response = self.client.get('/api/project/test/shots/render_selected_stream?scope=missing&indexes=1,2,3')
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.render.call_args.args[1], list(range(14, 22)))
        self.assertIn('"total": 21', body)

    def test_explicit_selection_remains_explicit(self):
        self.client.get('/api/project/test/shots/render_selected_stream?indexes=4,9').get_data()
        self.assertEqual(self.render.call_args.args[1], [4, 9])

    def test_stale_video_included(self):
        self.project['shots'][2]['continuity_stale'] = True
        self.client.get('/api/project/test/shots/render_selected_stream?scope=missing').get_data()
        self.assertEqual(self.render.call_args.args[1], [3, *range(14, 22)])

    def test_nothing_pending_does_not_render(self):
        self.project['shots'] = [{'index': i, 'video_url': 'saved.mp4'} for i in range(1, 22)]
        self.assertEqual(self.client.get('/api/project/test/shots/render_selected_stream?scope=missing').status_code, 400)
        self.render.assert_not_called()


if __name__ == '__main__':
    unittest.main()
