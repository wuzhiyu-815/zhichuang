import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from infrastructure.system_update import GitUpdates, UpdateError, active_work, register_system_update, source_path


class WindowsBundlePathTests(unittest.TestCase):
    def test_css_mask_names_are_not_api_keys(self):
        service = GitUpdates('.')
        service.inspect_blob('static/tailwindcss.js', b'"mask-box-image-outset", "mask-box-image-repeat"', [])
        with self.assertRaises(UpdateError):
            service.inspect_blob('app.py', b'KEY="sk-' + b'a' * 32 + b'"', [])

    def test_only_named_runtime_packages_are_allowed(self):
        for name in ('python.zip', 'ffmpeg.zip', 'ffprobe.zip', 'manifest.json', 'README.md', 'requirements-lock.txt'):
            self.assertTrue(source_path('vendor/windows-x64/' + name))
        for name in ('vendor/windows-x64/private.zip', 'vendor/windows-x64/../python.zip',
                     'vendor/windows-x64/config.json', 'vendor/windows-x64/python.exe',
                     'outputs/python.zip', 'runtime/windows/python.exe', '.venv/python.exe'):
            self.assertFalse(source_path(name))


class GitUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.remote = root / 'remote.git'
        self.local = root / 'local'
        self.other = root / 'other'
        self.run_git(root, 'init', '--bare', str(self.remote))
        self.run_git(root, 'clone', str(self.remote), str(self.local))
        self.run_git(self.local, 'checkout', '-b', 'main')
        for name, value in [('user.name', 'Test'), ('user.email', 'test@example.invalid')]:
            self.run_git(self.local, 'config', name, value)
        (self.local / '.gitignore').write_text('config.json\noutputs/\n')
        (self.local / 'app.py').write_text('VALUE = 1\n')
        self.run_git(self.local, 'add', '.')
        self.run_git(self.local, 'commit', '-m', 'initial')
        self.run_git(self.local, 'push', '-u', 'origin', 'main')
        self.run_git(root, 'clone', '-b', 'main', str(self.remote), str(self.other))
        for name, value in [('user.name', 'Test'), ('user.email', 'test@example.invalid')]:
            self.run_git(self.other, 'config', name, value)
        self.service = GitUpdates(self.local)
        # Production accepts only the configured GitHub repository. Tests use a
        # local bare remote to exercise actual Git without credentials/network.
        self.service.context = lambda: 'main'

    def run_git(self, root, *args):
        return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()

    def remote_commit(self, name='app.py', content='VALUE = 2\n'):
        (self.other / name).write_text(content)
        self.run_git(self.other, 'add', '-f', name)
        self.run_git(self.other, 'commit', '-m', 'remote update')
        self.run_git(self.other, 'push', 'origin', 'main')

    def test_update_preserves_config_and_media_and_saves_backup(self):
        (self.local / 'config.json').write_text('{"custom_api_key":"private-test-value"}')
        (self.local / 'outputs').mkdir()
        (self.local / 'outputs/video.mp4').write_bytes(b'private-video')
        previous = self.run_git(self.local, 'rev-parse', 'HEAD')
        self.remote_commit()
        result = self.service.update()
        self.assertTrue(result['restart_required'])
        self.assertEqual((self.local / 'app.py').read_text(), 'VALUE = 2\n')
        self.assertIn('private-test-value', (self.local / 'config.json').read_text())
        self.assertEqual((self.local / 'outputs/video.mp4').read_bytes(), b'private-video')
        self.assertIn(previous, self.run_git(self.local, 'show-ref'))

    def test_dirty_update_refused(self):
        self.remote_commit()
        (self.local / 'app.py').write_text('VALUE = 3\n')
        with self.assertRaises(UpdateError): self.service.update()
        self.assertEqual((self.local / 'app.py').read_text(), 'VALUE = 3\n')

    def test_diverged_update_refused(self):
        self.remote_commit()
        (self.local / 'app.py').write_text('VALUE = 3\n')
        self.run_git(self.local, 'commit', '-am', 'local change')
        with self.assertRaises(UpdateError): self.service.update()

    def test_remote_private_file_refused(self):
        self.remote_commit('config.json', '{}')
        with self.assertRaises(UpdateError): self.service.update()
        self.assertFalse((self.local / 'config.json').exists())

    def test_push_only_source(self):
        (self.local / 'config.json').write_text('{}')
        (self.local / 'app.py').write_text('VALUE = 4\n')
        self.service.push('test push')
        self.run_git(self.other, 'pull', '--ff-only')
        self.assertEqual((self.other / 'app.py').read_text(), 'VALUE = 4\n')
        self.assertFalse((self.other / 'config.json').exists())

    def test_secret_rejected_before_commit(self):
        key = 'sk-' + 'abc123' * 6
        (self.local / 'app.py').write_text('KEY = ' + repr(key))
        before = self.run_git(self.local, 'rev-parse', 'HEAD')
        with self.assertRaises(UpdateError): self.service.push('secret')
        self.assertEqual(before, self.run_git(self.local, 'rev-parse', 'HEAD'))

    def test_deleted_secret_in_outgoing_history_rejected(self):
        key = 'sk-' + 'abc123' * 6
        (self.local / 'app.py').write_text('KEY = ' + repr(key))
        self.run_git(self.local, 'commit', '-am', 'accidental secret')
        (self.local / 'app.py').write_text('VALUE = 1\n')
        self.run_git(self.local, 'commit', '-am', 'remove secret')
        with self.assertRaises(UpdateError): self.service.push('history')


class UpdateApiTests(unittest.TestCase):
    def setUp(self):
        from flask import Response
        from team.admin_portal import install
        self.app = Flask(__name__)
        install(self.app)
        self.app.add_url_rule('/static/update-script', view_func=lambda: Response(
            Path('static/system-update.js').read_text(encoding='utf-8'), mimetype='application/javascript'))
        self.ns = {'app': self.app, 'BASE_DIR': '.', '__name__': 'test', 'SINGLE_TASKS': {}}
        register_system_update(self.ns)
        self.client = self.app.test_client()
        self.token = self.client.get('/api/system-update/status').json['token']

    def post(self, action):
        return self.client.post('/api/system-update/' + action, json={}, headers={'X-Update-Token': self.token})

    def test_remote_single_user_denied(self):
        self.assertEqual(self.client.get('/api/system-update/status', environ_base={'REMOTE_ADDR':'192.0.2.10'}).status_code, 403)

    def test_team_admin_can_update_through_admin_namespace(self):
        self.ns['MULTIUSER'] = Mock(is_admin=Mock(return_value=True))
        response = self.client.get('/admin/api/system-update/status', environ_base={'REMOTE_ADDR': '192.0.2.10'})
        self.assertEqual(response.status_code, 200)
        with patch.object(GitUpdates, 'update', return_value={'message': 'done', 'restart_required': False}):
            response = self.client.post('/admin/api/system-update/update', json={},
                                        headers={'X-Update-Token': response.json['token']})
            self.assertEqual(response.status_code, 200)
            for _ in range(100):
                task = self.client.get('/admin/api/system-update/status').json['task']
                if task['status'] != 'running': break
                time.sleep(.01)
            self.assertEqual(task['status'], 'done')

    def test_team_member_cannot_read_or_push_even_from_localhost(self):
        self.ns['MULTIUSER'] = Mock(is_admin=Mock(return_value=False))
        self.assertEqual(self.client.get('/api/system-update/status').status_code, 403)
        self.assertEqual(self.post('push').status_code, 403)

    def test_admin_script_uses_admin_api_namespace(self):
        script = self.client.get('/admin/static/update-script').text
        self.assertIn("fetch('/admin/api/system-update/status'", script)
        self.assertIn("fetch('/admin/api/system-update/' + action", script)

    def test_csrf_required(self):
        self.assertEqual(self.client.post('/api/system-update/push').status_code, 403)

    def test_running_render_blocks_update(self):
        self.ns['SINGLE_TASKS']['one'] = {'status':'running'}
        self.assertEqual(self.post('update').status_code, 409)

    def test_update_reports_restart_for_external_server(self):
        with patch.object(GitUpdates, 'update', return_value={'message':'done','restart_required':True}):
            self.assertEqual(self.post('update').status_code, 200)
            for _ in range(100):
                task = self.client.get('/api/system-update/status').json['task']
                if task['status'] != 'running': break
                time.sleep(.01)
            self.assertEqual(task['status'], 'done')
            self.assertFalse(task['restarting'])

    def test_synth_and_queued_work_count_as_busy(self):
        self.assertTrue(active_work({'SYNTHESIZING_PROJECTS': {'a'}}))
        self.assertTrue(active_work({'render_queue_snapshot':lambda:{'items':[{'status':'queued'}]}}))


if __name__ == '__main__':
    unittest.main()
