"""Administrator console: real usage, production-start limits and system backups."""
import json
import os
from pathlib import Path
import tarfile
import time
import uuid
from flask import Response, abort, jsonify, request, send_file


class QuotaExceeded(ValueError):
    pass


def policy(platform, uid):
    with platform.store.connect() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', ('quota:' + str(uid),)).fetchone()
    return json.loads(row['value']) if row else dict(parallel=0, daily=0, storage_gb=0)


def usage(platform, uid):
    with platform.store.connect() as db:
        projects = [r['key'] for r in db.execute("SELECT key FROM resources WHERE kind='project' AND owner_id=?", (uid,))]
        row = db.execute('SELECT value FROM settings WHERE key=?', ('starts:' + str(uid) + ':' + time.strftime('%Y-%m-%d', time.gmtime()),)).fetchone()
    paths = set()
    completed = 0
    for pid in projects:
        path = platform.base / 'projects' / pid / 'project.json'
        if not path.is_file():
            path = platform.base / 'projects' / (pid + '.json')
        if not path.is_file():
            continue
        paths.add(path)
        project_folder = platform.base / 'projects' / pid
        if project_folder.is_dir():
            paths.update(p.resolve() for p in project_folder.rglob('*')
                         if p.is_file() and p.resolve().is_relative_to(platform.base))
        try:
            project = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        completed += bool(project.get('final'))
        for item in (project.get('assets') or {}).values():
            candidate = Path(item.get('path') or '')
            if not candidate.is_absolute():
                candidate = platform.base / candidate
            candidate = candidate.resolve()
            if candidate.is_relative_to(platform.base) and candidate.is_file():
                paths.add(candidate)
        folder = platform.base / 'outputs' / pid
        if folder.is_dir():
            paths.update(p.resolve() for p in folder.rglob('*') if p.is_file() and p.resolve().is_relative_to(platform.base))
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    active = sum(platform.store.owner('project', pid) == uid for pid in list(platform.ns.get('PIPELINE_CANCEL_EVENTS', {})))
    return dict(projects=len(projects), completed=completed, bytes=total, active=active, daily=int(row['value']) if row else 0)


def reserve_start(platform, pid):
    uid = platform.store.owner('project', pid)
    if not uid:
        return
    limits = policy(platform, uid)
    # Runs under the engine pipeline registration lock; parallel starts cannot race.
    active = sum(platform.store.owner('project', key) == uid for key in platform.ns.get('PIPELINE_CANCEL_EVENTS', {}))
    if limits['parallel'] and active >= limits['parallel']:
        raise QuotaExceeded('已达到整集制作并发上限，请等待运行中的任务完成')
    if limits['storage_gb'] and usage(platform, uid)['bytes'] >= limits['storage_gb'] * 1024 ** 3:
        raise QuotaExceeded('作品存储已达到启动阈值，请清理作品或联系管理员调整额度')
    key = 'starts:' + uid + ':' + time.strftime('%Y-%m-%d', time.gmtime())
    with platform.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        count = int(row['value']) if row else 0
        if limits['daily'] and count >= limits['daily']:
            raise QuotaExceeded('今日整集制作启动次数已用完，请联系管理员调整额度')
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)', (key, str(count + 1)))


def register_console(platform):
    app = platform.app
    backup_dir = platform.base / 'runtime' / 'admin-backups'

    @app.get('/manage/workspace', endpoint='team_console_workspace')
    def workspace():
        page = (platform.base / 'index.html').read_text()
        return Response(page.replace('<!-- PLATFORM_BOOTSTRAP -->', platform.bootstrap_html()), mimetype='text/html')

    @app.get('/api/manage/overview', endpoint='team_console_overview')
    def overview():
        users = platform.store.users()
        rows = [dict(user=platform.store.public(user), usage=usage(platform, user['id']), limits=policy(platform, user['id'])) for user in users]
        queue = platform.ns['load_render_queue']()
        return jsonify(ok=True, users=rows, queue={status:sum(item.get('status') == status for item in queue.get('items', [])) for status in ['running','queued','error','done']}, admin_port=int(os.environ.get('SHORT_DRAMA_ADMIN_PORT', '7861')), member_port=int(os.environ.get('SHORT_DRAMA_PORT', '7860')))

    @app.get('/api/auth/usage', endpoint='team_usage')
    def own_usage():
        return jsonify(ok=True, usage=usage(platform, platform.actor_id()), limits=policy(platform, platform.actor_id()))

    @app.post('/api/manage/users/<uid>/quota', endpoint='team_console_quota')
    def save_quota(uid):
        if not platform.store.user(uid):
            abort(404)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {'parallel','daily','storage_gb'}:
            return jsonify(ok=False,msg='配额字段无效'),400
        limits = {}
        for key in data:
            value = data[key]
            if isinstance(value, bool) or not isinstance(value, (int,float)) or value < 0 or value > 1000000 or (key != 'storage_gb' and int(value) != value):
                return jsonify(ok=False,msg='额度须为非负数字，并发与次数须为整数；0 表示不限'),400
            limits[key] = value
        with platform.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)', ('quota:' + uid,json.dumps(limits)))
        platform.store.audit(platform.actor_id(),'set_user_quota',uid)
        return jsonify(ok=True,limits=limits)

    @app.route('/api/manage/backups', methods=['GET','POST'], endpoint='team_console_backups')
    def backups():
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if request.method == 'POST':
            filename = time.strftime('system-%Y%m%dT%H%M%SZ',time.gmtime()) + '-' + uuid.uuid4().hex[:8] + '.tar.gz'
            target = backup_dir / filename
            roots = ['static','core','infrastructure','agents','skills','team','workflows','tests']
            files = [p for p in platform.base.iterdir() if p.is_file() and (p.suffix in ('.py','.html','.md','.sh','.bat','.txt') or p.name == 'config.json')]
            for root in roots:
                folder = platform.base / root
                if folder.is_dir():
                    files.extend(p for p in folder.rglob('*') if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts and p.suffix != '.pyc')
            try:
                with open(target, 'xb') as stream:
                    os.chmod(target,0o600)
                    with tarfile.open(fileobj=stream,mode='w:gz') as archive:
                        for path in files:
                            archive.add(path,arcname=str(path.relative_to(platform.base)),recursive=False)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            platform.store.audit(platform.actor_id(),'system_backup',filename)
        items = [dict(name=p.name,bytes=p.stat().st_size,created=p.stat().st_mtime) for p in sorted(backup_dir.glob('system-*.tar.gz'),reverse=True)]
        return jsonify(ok=True,items=items)

    @app.get('/api/manage/backups/<name>', endpoint='team_console_backup_download')
    def download_backup(name):
        if not name.startswith('system-') or '/' in name or '\\' in name or not name.endswith('.tar.gz'):
            abort(404)
        target = backup_dir / name
        if not target.is_file():
            abort(404)
        platform.store.audit(platform.actor_id(),'download_system_backup',name)
        return send_file(target,as_attachment=True,download_name=name)
