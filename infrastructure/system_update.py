"""Git maintenance for the local checkout; no force pushes or destructive resets."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import sys
import threading
import time

from flask import g, jsonify, request


class UpdateError(RuntimeError):
    pass


ROOT_FILES = {
    '.gitignore', '.gitattributes', 'README.md', 'THIRD_PARTY_NOTICES.md',
    'config.example.json', 'requirements.txt', 'app.py', 'comfy_pool.py', 'index.html',
    'start_windows.bat', 'start_team.bat', 'debug_windows.bat', 'start_ubuntu.sh',
    'push_updates.bat', 'update.bat', 'push_updates.sh', 'update.sh',
}
SOURCE_DIRS = {'.github', 'agents', 'core', 'infrastructure', 'skills', 'static', 'team', 'tests', 'workflows', 'docs'}
SECRET_PATTERN = re.compile(rb'(?<![A-Za-z0-9_])(?:sk-|ghp_|gho_|github_pat_|AKIA)[A-Za-z0-9_-]{16,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')
WINDOWS_BUNDLE_FILES = {
    'vendor/windows-x64/python.zip', 'vendor/windows-x64/ffmpeg.zip',
    'vendor/windows-x64/ffprobe.zip', 'vendor/windows-x64/manifest.json',
    'vendor/windows-x64/README.md', 'vendor/windows-x64/requirements-lock.txt',
}


def source_path(name):
    if name in WINDOWS_BUNDLE_FILES:
        return True
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name:
        return False
    if name not in ROOT_FILES and (len(p.parts) < 2 or p.parts[0] not in SOURCE_DIRS):
        return False
    if any(x in {'__pycache__', '.venv', 'runtime', 'custom', '.git'} for x in p.parts):
        return False
    if p.name.startswith('.env') or p.name == 'initial-admin.txt':
        return False
    return p.suffix.lower() not in {'.db', '.sqlite', '.sqlite3', '.exe', '.dll', '.pem', '.key', '.pfx', '.pyc', '.log', '.zip', '.mp4', '.mp3', '.wav'}


class GitUpdates:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def command(self, args, timeout=120, binary=False):
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
        try:
            result = subprocess.run(args, cwd=self.root, env=env, capture_output=True,
                                    timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError('命令无法执行或超时；请检查 Git 安装、网络和本机 GitHub 登录') from exc
        if result.returncode:
            # Git output can echo credential-bearing remote URLs. Keep it local.
            raise UpdateError('操作失败：' + args[0] + ' ' + args[1] + '；请检查网络、GitHub 登录、分支权限及 Git 配置')
        return result.stdout if binary else result.stdout.decode('utf-8', errors='replace').strip()

    def git(self, *args, **kwargs):
        return self.command(['git', *args], **kwargs)

    def context(self):
        top = Path(self.git('rev-parse', '--show-toplevel')).resolve()
        if top != self.root:
            raise UpdateError('当前应用目录不是 Git 仓库根目录；请先完成首次迁移')
        branch = self.git('symbolic-ref', '--short', 'HEAD')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', branch):
            raise UpdateError('请切换到正常开发或部署分支')
        remote = self.git('remote', 'get-url', 'origin')
        push_remote = self.git('remote', 'get-url', '--push', 'origin')
        expected = {'https://github.com/wuzhiyu-815/zhichuang.git', 'https://github.com/wuzhiyu-815/zhichuang',
                    'git@github.com:wuzhiyu-815/zhichuang.git', 'ssh://git@github.com/wuzhiyu-815/zhichuang.git'}
        if remote not in expected or push_remote not in expected:
            raise UpdateError('origin 必须指向 wuzhiyu-815/zhichuang；请使用本机凭据管理器，不要在地址中放令牌')
        return branch

    def changes(self):
        raw = self.git('status', '--porcelain=v1', '-z', '--untracked-files=all', binary=True)
        records = raw.decode('utf-8').split('\0')
        result, i = [], 0
        while i < len(records):
            entry = records[i]
            i += 1
            if not entry:
                continue
            result.append({'status': entry[:2], 'path': entry[3:]})
            if 'R' in entry[:2] or 'C' in entry[:2]:
                result.append({'status': 'old', 'path': records[i]})
                i += 1
        return result

    def status(self, fetch=False):
        branch = self.context()
        if fetch:
            self.git('fetch', 'origin')
        upstream = 'refs/remotes/origin/' + branch
        try:
            ahead, behind = map(int, self.git('rev-list', '--left-right', '--count', 'HEAD...' + upstream).split())
        except UpdateError:
            ahead, behind = None, None
        return {'branch': branch, 'commit': self.git('rev-parse', '--short', 'HEAD'),
                'ahead': ahead, 'behind': behind, 'changes': self.changes(),
                'repository': 'https://github.com/wuzhiyu-815/zhichuang'}

    def known_secrets(self):
        found = []
        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if re.search('key|token|password|secret', key, re.I) and isinstance(item, str) and len(item) > 8:
                        found.append(item.encode())
                    else:
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        path = self.root / 'config.json'
        if path.exists():
            try:
                visit(json.loads(path.read_text(encoding='utf-8-sig')))
            except (ValueError, OSError) as exc:
                raise UpdateError('配置文件无法读取，无法完成敏感信息检查') from exc
        return found

    def inspect_blob(self, name, blob, known):
        if not source_path(name):
            raise UpdateError('禁止同步运行数据或私密文件：' + name)
        if SECRET_PATTERN.search(blob) or any(secret in blob for secret in known):
            raise UpdateError('发现疑似密钥，请先移入本机配置：' + name)

    def inspect_tree(self, ref):
        known = self.known_secrets()
        for record in self.git('ls-tree', '-r', '-z', ref, binary=True).split(b'\0'):
            if not record:
                continue
            meta, name = record.split(b'\t', 1)
            mode, kind, oid = meta.split()
            name = name.decode('utf-8')
            if mode in (b'120000', b'160000') or kind != b'blob':
                raise UpdateError('自动同步不接受符号链接或子模块：' + name)
            self.inspect_blob(name, self.git('cat-file', 'blob', oid.decode(), binary=True), known)

    def push(self, message):
        branch = self.context()
        self.git('fetch', 'origin')
        changes = self.changes()
        known = self.known_secrets()
        # Inspect before staging, including files accidentally force-added by hand.
        for item in changes:
            name = item['path']
            if not source_path(name):
                raise UpdateError('禁止提交：' + name)
            path = self.root / name
            if path.is_symlink():
                raise UpdateError('不提交符号链接：' + name)
            if path.is_file():
                self.inspect_blob(name, path.read_bytes(), known)
        if changes:
            self.git('add', '-A', '--', '.')
            self.inspect_tree(self.git('write-tree'))
            self.git('commit', '-m', message.strip()[:300] or 'Update Zhichuang')
        # Scan every outgoing snapshot so a removed secret in an earlier commit
        # cannot slip through merely because HEAD is clean.
        revisions = self.git('rev-list', 'HEAD', '--not', '--remotes=origin').splitlines()
        for revision in revisions:
            self.inspect_tree(revision)
        self.git('push', 'origin', 'HEAD:refs/heads/' + branch)
        return {'message': '代码已提交并推送到 ' + branch, **self.status()}

    def update(self):
        branch = self.context()
        if self.changes():
            raise UpdateError('有未提交的代码修改，请先推送或手动处理；不会覆盖本地修改')
        self.git('fetch', 'origin')
        target = 'refs/remotes/origin/' + branch
        before = self.git('rev-parse', 'HEAD')
        after = self.git('rev-parse', target)
        if before == after:
            return {'message': '已经是最新版本', 'restart_required': False, **self.status()}
        if self.git('merge-base', 'HEAD', target) != before:
            raise UpdateError('本地分支领先或与远端分叉，请先推送或手动合并；不会强制覆盖')
        self.inspect_tree(target)
        # --ff-only still protects against a concurrent checkout change.
        requirements = self.git('diff', '--name-only', before, after, '--', 'requirements.txt')
        backup = 'refs/zhichuang-backups/' + str(time.time_ns())
        self.git('update-ref', backup, before)
        self.git('merge', '--ff-only', target)
        if requirements:
            try:
                self.command([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], timeout=600)
            except UpdateError as exc:
                raise UpdateError('代码已更新，但依赖安装失败，未重启。请检查依赖；旧代码备份：' + backup) from exc
        return {'message': '更新完成；旧代码备份：' + backup, 'restart_required': True, **self.status()}


def active_work(ns):
    if ns.get('PIPELINE_CANCEL_EVENTS') or ns.get('SYNTHESIZING_PROJECTS'):
        return True
    for name in ('SINGLE_TASKS', 'RERENDER_TASKS', 'BATCH_RENDER_TASKS'):
        if any(t.get('status') in ('running', 'queued', 'pending', 'submitted') for t in list(ns.get(name, {}).values())):
            return True
    snapshot = ns.get('render_queue_snapshot', lambda: {})()
    return bool(snapshot.get('running') or snapshot.get('active_workers') or
                any(t.get('status') in ('running', 'queued', 'retry') for t in snapshot.get('items', [])))


def register_system_update(ns):
    app = ns['app']
    service = GitUpdates(ns['BASE_DIR'])
    lock = threading.RLock()
    state = {'status': 'idle', 'message': ''}
    token = secrets.token_urlsafe(32)
    maintenance = {'active': False}
    requests_in_flight = set()
    mutating_gets = {'api_pipeline_run', 'project_resynth', 'api_render_selected_stream', 'api_series_batch_run'}

    @app.before_request
    def system_update_guard():
        if request.path.startswith('/api/system-update'):
            platform = ns.get('MULTIUSER')
            if (platform and not platform.is_admin()) or (not platform and request.remote_addr not in ('127.0.0.1', '::1')):
                return jsonify(ok=False, msg='仅管理员或本机访问可以更新代码'), 403
            if request.method == 'POST' and not secrets.compare_digest(request.headers.get('X-Update-Token', ''), token):
                return jsonify(ok=False, msg='请重新检查版本后操作'), 403
        elif request.path.startswith('/api/') and (request.method not in ('GET', 'HEAD', 'OPTIONS') or request.endpoint in mutating_gets):
            with lock:
                if maintenance['active']:
                    return jsonify(ok=False, msg='系统正在更新，请稍后再试'), 503
                key = secrets.token_hex(12)
                requests_in_flight.add(key)
                g.update_request_key = key

    @app.after_request
    def system_update_request_finished(response):
        key = getattr(g, 'update_request_key', None)
        def release():
            with lock:
                requests_in_flight.discard(key)
        if key:
            if response.is_streamed:
                response.call_on_close(release)
            else:
                release()
        return response

    @app.teardown_request
    def system_update_request_failed(error):
        if error:
            with lock:
                requests_in_flight.discard(getattr(g, 'update_request_key', None))

    @app.get('/api/system-update/status')
    def system_update_status():
        with lock:
            snapshot = dict(state)
        return jsonify(ok=True, task=snapshot, token=token)

    @app.post('/api/system-update/<action>')
    def system_update_action(action):
        if action not in ('check', 'push', 'update'):
            return jsonify(ok=False, msg='不支持的更新操作'), 400
        data = request.get_json(silent=True) or {}
        with lock:
            if state['status'] == 'running' or maintenance['active']:
                return jsonify(ok=False, msg='已有更新操作在执行'), 409
            if action != 'check' and (requests_in_flight or active_work(ns)):
                return jsonify(ok=False, msg='有生成或合成任务正在运行，请完成后再操作'), 409
            maintenance['active'] = action != 'check'
            state.clear()
            state.update(status='running', action=action, message='正在检查并执行…')

        def run():
            restarting = False
            try:
                if action == 'check':
                    result = service.status(fetch=True)
                    result['message'] = '版本检查完成'
                elif action == 'push':
                    result = service.push(str(data.get('message') or 'Update Zhichuang'))
                else:
                    result = service.update()
                restarting = bool(result.get('restart_required') and ns.get('__name__') == '__main__')
                with lock:
                    state.update(status='done', result=result, restarting=restarting, message=result['message'])
                if restarting:
                    time.sleep(3)
                    os.execv(sys.executable, [sys.executable, '-u', str(service.root / 'app.py')])
            except Exception as exc:
                restarting = False
                with lock:
                    state.update(status='error', message=str(exc) if isinstance(exc, UpdateError) else '操作失败，请查看服务器日志')
            finally:
                if not restarting:
                    maintenance['active'] = False
        threading.Thread(target=run, name='system-update', daemon=True).start()
        return jsonify(ok=True)


def main():
    parser = argparse.ArgumentParser(description='智创版本管理（使用当前分支）')
    parser.add_argument('action', choices=('check', 'push', 'update'))
    parser.add_argument('--message', default='Update Zhichuang')
    parser.add_argument('--offline', action='store_true', help='确认应用已停止，直接更新 Git；不会启动服务')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.offline:
            # Require the caller to stop the application rather than racing it.
            import socket
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1', int(os.environ.get('SHORT_DRAMA_PORT', '7860')))) == 0:
                    raise UpdateError('检测到运行中的服务，请使用网页更新入口或先停止服务')
            service = GitUpdates(root)
            result = service.status(fetch=True) if args.action == 'check' else (
                service.push(args.message) if args.action == 'push' else service.update())
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            import requests
            base = 'http://127.0.0.1:' + os.environ.get('SHORT_DRAMA_PORT', '7860') + '/api/system-update'
            session = requests.Session()
            session.trust_env = False
            status = session.get(base + '/status', timeout=10)
            if status.status_code != 200:
                raise UpdateError('服务尚未加载更新功能，或需管理员登录。请在网页操作；停服后可使用 --offline')
            token = status.json()['token']
            response = session.post(base + '/' + args.action, json={'message': args.message}, headers={'X-Update-Token': token}, timeout=15)
            body = response.json()
            if not response.ok:
                raise UpdateError(body.get('msg', '无法开始操作'))
            for _ in range(900):
                task = session.get(base + '/status', timeout=10).json()['task']
                if task['status'] != 'running':
                    print(json.dumps(task, ensure_ascii=False, indent=2))
                    return 0 if task['status'] == 'done' else 1
                time.sleep(1)
            raise UpdateError('等待超时，请查看网页状态；未自动重试')
        return 0
    except Exception as exc:
        print(str(exc) if isinstance(exc, UpdateError) else '连接失败；请检查服务或先停服后使用 --offline', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
