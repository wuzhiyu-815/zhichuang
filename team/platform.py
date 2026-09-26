"""Central authorization for the existing single-process production service."""
import copy
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import unquote, urlsplit

from flask import Response, abort, g, has_request_context, jsonify, redirect, request, session, send_file
from .store import TeamStore
from .user_config import UserConfig, CONNECTION_KEYS

CREATIVE_KEYS = set('style aspect_ratio megapixels h3_steps shot_duration shot_count prompt_skill_mode video_skill_id script_skill_id subtitle_enabled manual_mode batch_prompt_mode script_review_mode agent_pipeline_enabled'.split())
MEMBER_ENDPOINTS = set('''api_comfy_nodes_status api_llm_test api_llm_models api_llm_available_models api_jimeng_test api_jimeng_models api_comfy_test api_comfy_server_toggle api_image_models index serve_static serve_file api_config api_status api_health api_skills api_custom_skills api_agents_capabilities api_director_match
single_shot_upload single_shot_prompt single_shot_generate single_shot_status
project_shot_references project_shot_reference_image_upload project_shot_bridge project_shot_replace project_shot_versions project_shot_select_version project_shot_confirm project_shot_confirm_all api_batch_update_shots api_render_selected_stream project_shot_rerender project_shot_prompt_chat project_asset_prompt_chat project_rerender_status project_resynth
api_generation_reference_upload api_project_generation_reference api_image_inspiration api_script_import_text api_novel_viewer_books api_novel_viewer_book api_novel_viewer_chapter api_tomato_downloader_status api_tomato_downloader_start api_pipeline_run api_pipeline_cancel api_render_queue api_render_queue_add api_render_queue_remove api_render_queue_start api_render_queue_pause api_archive_project api_archive_series api_projects api_project_remake api_project api_project_rename api_project_script_confirm api_project_script_regenerate api_project_script_chat api_agent_next api_delete_project api_asset_regenerate api_asset_versions api_asset_select_version api_asset_confirm api_asset_confirm_all api_upload_asset api_upload_role_audio api_confirm_assets
reference_sync
api_series_list api_series_create api_series_get api_series_remake api_series_update api_series_episode_rename api_series_episode_register api_series_delete api_series_plan api_series_episode_idea api_series_batch_run api_project_reviews api_review_one_shot
start status download jianying_export_start jianying_export_status jianying_export_download'''.split())
MUTATING_GETS = set('api_pipeline_run project_resynth api_render_selected_stream api_series_batch_run'.split())
RESOURCE_KEYS = {'pid':'project','project_id':'project','pids':'project','project_ids':'project',
                 'series_id':'series','template_series_id':'series','source_series_id':'series'}


class TeamPlatform:
    def __init__(self, app, namespace, base_dir, bootstrap=True):
        self.app, self.ns = app, namespace
        self.base = Path(base_dir).resolve()
        self.store = TeamStore(self.base / 'runtime' / 'team')
        self.default_owner = self.store.bootstrap() if bootstrap else None
        self.user_config = UserConfig(self)
        self.selection_lock = threading.RLock()
        self.last_scheduled = None
        secret_path = self.store.directory / 'session-secret'
        if not secret_path.exists():
            fd = os.open(secret_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:
                f.write(secrets.token_hex(32))
        app.config.update(SECRET_KEY=secret_path.read_text(),SESSION_COOKIE_NAME='drama_team',
                          SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                          SESSION_COOKIE_SECURE=os.environ.get('SHORT_DRAMA_COOKIE_SECURE')=='1',
                          PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
        from .admin_portal import install
        install(app)
        self.register()
        from .email_signup import EmailSignup
        self.email_signup = EmailSignup(self)
        from .console import register_console
        register_console(self)

    def actor(self):
        if has_request_context():
            return getattr(g,'team_user',None)
        cfg = self.ns.get('runtime_config',lambda: {})()
        uid = cfg.get('_owner_id') if isinstance(cfg,dict) else None
        return self.store.user(uid) if uid else None

    def actor_id(self):
        return (self.actor() or {}).get('id')

    def is_admin(self):
        return (self.actor() or {}).get('role')=='admin'

    def visible(self, kind, key):
        actor = self.actor()
        if actor is None:
            # No request means an internal recovery/maintenance operation, not an anonymous API caller.
            return not has_request_context()
        return actor['role']=='admin' or self.store.owner(kind,key)==actor['id']

    def require(self, kind, key):
        if not key or not self.visible(kind,str(key)):
            abort(404,description='资源不存在或无权访问')

    def owner_for(self, kind, key, parent=None):
        existing = self.store.owner(kind,key)
        workspace = getattr(g,'team_workspace_owner',None) if has_request_context() else None
        uid = existing or (self.store.owner(*parent) if parent else None) or workspace or self.actor_id() or self.default_owner
        actor = self.actor()
        if actor and actor['role']!='admin' and uid != actor['id']:
            raise PermissionError('无权修改其他用户资源')
        return self.store.claim(kind,key,uid)

    def workspace_owner(self):
        return (getattr(g,'team_workspace_owner',None) if has_request_context() else None) or self.actor_id()

    def series_child(self, sid, pid):
        owner=self.store.owner('series',sid)
        return bool(owner and pid and self.store.owner('project',pid)==owner)

    def bind_document(self, kind, doc):
        series_id=(doc.get('series') or {}).get('id') if kind=='project' else None
        parent=('series',series_id) if series_id else None
        uid = self.owner_for(kind,doc['id'],parent)
        if parent:
            parent_owner=self.store.owner(*parent)
            if parent_owner and parent_owner != uid:
                raise PermissionError('单集与剧项目必须属于同一用户')
            if not parent_owner:
                self.store.claim(*parent,uid)
        doc['owner_id'] = uid
        if isinstance(doc.get('render_config'),dict):
            doc['render_config']={k:v for k,v in doc['render_config'].items() if k not in CONNECTION_KEYS and not k.startswith('_')}
        if kind == 'series':
            for episode in (doc.get('episodes') or {}).values():
                pid = episode.get('project_id') if isinstance(episode,dict) else None
                if pid and self.store.owner('project',pid) not in (None,uid):
                    raise PermissionError('剧集不能关联其他用户的项目')
        for path in self.media_paths(doc):
            # A referenced project directory must also belong to this owner.
            owner = self.file_owner(path)
            if owner and owner != uid:
                raise PermissionError('素材属于其他用户')
            self.store.claim('file',str(path.relative_to(self.base)),uid)

    def media_paths(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('render_config','config','运行记录','智能体通信记录','技能调用记录','智能体决策记录'):
                    continue
                yield from self.media_paths(child)
        elif isinstance(value,list):
            for child in value:
                yield from self.media_paths(child)
        elif isinstance(value,str) and (value.startswith(('/file/','assets/','outputs/')) or value.startswith(str(self.base))):
            path=self.resolve_media(value)
            if path and path.is_file():
                yield path

    def resolve_media(self, value):
        value=str(value or '')
        if value.startswith('/file/'):
            value=unquote(urlsplit(value).path[len('/file/'):])
        elif not Path(value).is_absolute():
            value=urlsplit(value).path
        path=(self.base / value).resolve()
        if any(path.is_relative_to(self.base / folder) for folder in ('assets','outputs','reviews')):
            return path
        return None

    def file_owner(self,path):
        rel=path.relative_to(self.base)
        parts=rel.parts
        if len(parts)>2 and parts[0]=='outputs':
            if parts[1]=='_episode_exports':
                return self.store.owner('merge',path.stem)
            if parts[1]=='_jianying_exports':
                return self.store.owner('draft',path.stem)
            if parts[1]=='single' and path.stem.startswith('single_'):
                return self.store.owner('single',path.stem[len('single_'):]) or self.store.owner('file',str(rel))
            owner=self.store.owner('project',parts[1])
            if owner:
                return owner
        return self.store.owner('file',str(rel))

    def require_media(self,value):
        path=self.resolve_media(value)
        if not path or not path.is_file():
            abort(404,description='素材不存在或无权访问')
        if not self.is_admin() and self.file_owner(path)!=self.actor_id():
            abort(404,description='素材不存在或无权访问')

    def migrate_existing(self):
        with self.store.connect() as db:
            if db.execute("SELECT value FROM settings WHERE key='legacy_migrated'").fetchone():
                return
        for kind,folder in [('project','projects'),('series','series')]:
            paths = list((self.base/folder).glob('*.json'))
            if kind == 'project':
                paths.extend((self.base/folder).glob('*/project.json'))
            for path in paths:
                key = path.parent.name if path.name == 'project.json' and kind == 'project' else path.stem
                if not self.store.owner(kind,key):
                    self.store.claim(kind,key,self.default_owner)
        for folder in ('assets','outputs','reviews'):
            for path in (self.base/folder).rglob('*'):
                if path.is_file() and path.resolve().is_relative_to(self.base):
                    key=str(path.relative_to(self.base))
                    if not self.store.owner('file',key):
                        self.store.claim('file',key,self.file_owner(path) or self.default_owner)
        for folder,kind in [('_episode_exports','merge'),('_jianying_exports','draft')]:
            for path in (self.base/'outputs'/folder).glob('*'):
                if path.suffix in ('.zip','.mp4') and not self.store.owner(kind,path.stem):
                    self.store.claim(kind,path.stem,self.default_owner)
        with self.store.connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES ('legacy_migrated','1')")

    def safe_config(self, data):
        if isinstance(data,list):
            return [self.safe_config(x) for x in data]
        if not isinstance(data,dict):
            return data
        blocked=('api_key','password','secret','authorization','access_token','refresh_token','_owner_id')
        return {key:({k:v for k,v in value.items() if k in CREATIVE_KEYS or k=='media_provider'}
                     if key in ('render_config','config') and isinstance(value,dict) else self.safe_config(value)) for key,value in data.items()
                if not any(part in key.lower() for part in blocked)
                and key not in ('llm_endpoint','comfyui_url','comfyui_servers','media_endpoint','base_url','jimeng_base_url','custom_base_url','local_llm_url','llm_profiles')}

    def filter_queue(self,data):
        if self.is_admin():
            return data
        result=copy.deepcopy(data)
        result['items']=[i for i in data.get('items',[]) if self.queue_item_visible(i)]
        result['running']=any(i.get('status')=='running' for i in result['items'])
        result.pop('active_nodes',None)
        result.pop('busy_nodes',None)
        result.pop('active_workers',None)
        return result

    def queue_item_visible(self,item):
        if item.get('pid'):
            return self.visible('project',item['pid'])
        if str(item.get('id','')).startswith('single_'):
            return self.visible('single',item['id'][len('single_'):])
        return self.is_admin()

    def next_queued(self,items):
        waiting=[i for i in items if i.get('status') in ('queued','retry')]
        if not waiting:
            return None
        with self.selection_lock:
            counts={}
            for item in items:
                if item.get('status')=='running':
                    owner=self.store.owner('project',item.get('pid'))
                    counts[owner]=counts.get(owner,0)+1
            from .console import policy
            waiting = [item for item in waiting if not policy(self, self.store.owner('project',item.get('pid')))['parallel'] or counts.get(self.store.owner('project',item.get('pid')),0) < policy(self,self.store.owner('project',item.get('pid')))['parallel']]
            if not waiting:
                return None
            waiting.sort(key=lambda item:(counts.get(self.store.owner('project',item.get('pid')),0),
                                          self.store.owner('project',item.get('pid'))==self.last_scheduled))
            chosen=waiting[0]
            self.last_scheduled=self.store.owner('project',chosen.get('pid'))
            return chosen

    def check_inputs(self):
        payload=request.get_json(silent=True) if request.is_json else request.form.to_dict(flat=True)
        if payload is not None and not isinstance(payload,dict):
            abort(400,description='请求参数必须是对象')
        values=[request.args.to_dict(flat=True),payload or {},request.view_args or {}]
        for data in values:
            for key,kind in RESOURCE_KEYS.items():
                for value in (data.get(key) if isinstance(data.get(key),list) else [data.get(key)]):
                    if not value:
                        continue
                    if request.endpoint=='api_pipeline_run' and key=='pid' and not self.store.owner('project',value):
                        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',str(value)):
                            abort(400,description='项目ID无效')
                        self.store.claim('project',value,self.actor_id())
                    else:
                        self.require(kind,value)
            for key in ('ref_paths','ref_image_paths','image_path','video_path','audio_path','ref_path','src_path'):
                refs=data.get(key)
                for ref in refs if isinstance(refs,list) else [refs]:
                    if ref:
                        self.require_media(ref)
        if request.endpoint=='api_pipeline_run':
            for sid in re.findall(r'系列ID[：:]\s*([^\s；]+)',request.args.get('idea','')):
                self.require('series',sid)

    def register(self):
        app=self.app

        @app.before_request
        def team_guard():
            g.team_user=None
            uid=session.get('uid')
            if uid:
                user=self.store.user(uid)
                if user and user['enabled'] and user['version']==session.get('version'):
                    g.team_user=user
                else:
                    session.clear()
            endpoint=request.endpoint or ''
            public=endpoint in ('team_login_page','team_session','team_login','team_signup_page','team_signup_status','team_signup_code','team_signup_register') or endpoint=='serve_static'
            if public:
                return
            if not g.team_user:
                if request.path.startswith(('/api/','/file/')):
                    return jsonify(ok=False,msg='请先登录'),401
                return redirect('/login')
            if g.team_user['must_change'] and endpoint not in ('team_password_page','team_password','team_session','team_logout'):
                if request.path.startswith('/api/'):
                    return jsonify(ok=False,msg='首次登录请先修改密码'),428
                return redirect('/account/password')
            if request.method not in ('GET','HEAD','OPTIONS') or endpoint in MUTATING_GETS:
                self.check_csrf()
            cfg = self.user_config.get(g.team_user['id'])
            cfg['_owner_id'] = g.team_user['id']
            self.ns.get('set_runtime_config',lambda value:None)(cfg)
            if request.environ.get('drama.admin_portal') and not self.is_admin():
                abort(403, description='此入口仅供管理员使用')
            if endpoint.startswith('team_console_') and not self.is_admin():
                abort(403, description='仅管理员可操作')
            if endpoint.startswith('team_'):
                if endpoint in ('team_users','team_update_user','team_admin_page','team_audit','team_mail_settings','team_mail_test','team_user_nodes') and not self.is_admin():
                    abort(403,description='仅管理员可操作')
                return
            if self.is_admin() and endpoint in {
                'api_generation_reference_upload', 'api_project_generation_reference', 'api_image_inspiration', 'api_pipeline_run', 'api_director_match', 'single_shot_upload',
                'single_shot_prompt', 'single_shot_generate', 'project_shot_bridge',
                'project_shot_replace', 'project_shot_select_version', 'project_shot_confirm',
                'project_shot_confirm_all', 'api_batch_update_shots', 'api_render_selected_stream',
                'project_shot_rerender', 'project_shot_prompt_chat', 'project_resynth',
                'api_novel_viewer_queue_series', 'api_novel_viewer_highlights',
                'api_novel_viewer_trailer_script', 'api_novel_viewer_excerpt_script',
                'api_project_remake', 'api_project_script_confirm', 'api_project_script_regenerate',
                'api_project_script_chat', 'api_agent_next', 'api_dispatch_agent',
                'api_asset_regenerate', 'api_asset_select_version', 'api_asset_confirm',
                'api_asset_confirm_all', 'api_upload_asset', 'api_upload_role_audio', 'project_shot_reference_image_upload',
                'api_confirm_assets', 'api_series_create', 'api_series_remake',
                'api_series_episode_register', 'api_series_plan', 'api_series_episode_idea',
                'api_series_batch_run', 'api_review_one_shot'
            }:
                abort(403, description='管理员仅管理作品和系统，请使用成员账号进行创作')
            if not self.is_admin():
                if endpoint in ('api_comfy_test','api_comfy_server_toggle'):
                    abort(403,description='ComfyUI 节点由管理员分配和管理')
                if endpoint not in MEMBER_ENDPOINTS:
                    abort(403,description='此功能由管理员统一管理')
                if endpoint in ('api_skills','api_custom_skills') and request.method!='GET':
                    abort(403,description='平台技能由管理员统一管理')
            if endpoint=='api_config' and request.method=='POST':
                data=request.get_json(silent=True)
                allowed=set(self.ns.get('DEFAULT_CONFIG',{})) | CREATIVE_KEYS | CONNECTION_KEYS | {'single_shot_prompt'}
                if not isinstance(data,dict) or not set(data).issubset(allowed):
                    abort(403,description='配置包含不支持的字段')
                if not self.is_admin() and any(key in data for key in ('comfyui_url','comfyui_servers')):
                    abort(403,description='ComfyUI 节点由管理员分配，不能自行修改')
            if endpoint in ('api_comfy_start','api_comfy_stop','api_comfy_monitor'):
                abort(403,description='节点按用户独立配置，请在个人设置中管理节点；进程启停请在节点服务器上操作')
            if endpoint=='serve_file':
                folder=(request.view_args or {}).get('folder')
                filename=(request.view_args or {}).get('filename','')
                if Path(filename).suffix.lower() not in ('.mp4','.mov','.webm','.png','.jpg','.jpeg','.webp','.wav','.mp3','.m4a','.aac','.ogg','.flac','.srt','.zip'):
                    abort(404)
                self.require_media(f'/file/{folder}/{filename}')
            self.check_inputs()
            args=request.view_args or {}
            if self.is_admin():
                for key,kind in RESOURCE_KEYS.items():
                    value=args.get(key)
                    if isinstance(value,str) and self.store.owner(kind,value):
                        g.team_workspace_owner=self.store.owner(kind,value)
                        self.ns.get('set_runtime_config',lambda value:None)(self.user_config.get(g.team_workspace_owner))
                        break
            if endpoint=='single_shot_status':
                self.require('single',args.get('task_id'))
            if endpoint in ('status','download'):
                self.require('merge',args.get('token'))
            if endpoint in ('jianying_export_status','jianying_export_download'):
                self.require('draft',args.get('token'))
            if endpoint=='project_rerender_status':
                task=self.ns.get('RERENDER_TASKS',{}).get(args.get('task_id'),{})
                if task.get('pid')!=args.get('pid'):
                    abort(404)
            if endpoint=='api_render_queue_remove':
                items=self.ns['render_queue_snapshot']().get('items',[])
                item=next((i for i in items if i.get('id')==args.get('item_id')),None)
                if not item or not self.queue_item_visible(item):
                    abort(404)

        @app.after_request
        def team_response(response):
            response.headers['X-Content-Type-Options']='nosniff'
            response.headers['X-Frame-Options']='SAMEORIGIN'
            response.headers['Referrer-Policy']='same-origin'
            if request.path.startswith(('/api/','/file/')) or request.path in ('/','/login','/register','/team','/account/password'):
                response.headers['Cache-Control']='private, no-store'
            actor=getattr(g,'team_user',None)
            if not actor:
                return response
            endpoint=request.endpoint
            if response.is_json and response.status_code<400:
                data=response.get_json()
                if endpoint in ('single_shot_upload','api_upload_role_audio','api_upload_asset','api_image_inspiration','api_generation_reference_upload'):
                    for path in self.media_paths(data):
                        self.store.claim('file',str(path.relative_to(self.base)),(self.file_owner(path) if actor['role']=='admin' else None) or actor['id'])
                if endpoint=='single_shot_generate' and data.get('task_id'):
                    self.store.claim('single',data['task_id'],actor['id'])
                if endpoint in ('start','jianying_export_start') and data.get('job_id'):
                    self.store.claim('merge' if endpoint=='start' else 'draft',data['job_id'],getattr(g,'team_workspace_owner',None) or actor['id'])
                if endpoint in ('api_projects','api_series_list'):
                    kind='project' if endpoint=='api_projects' else 'series'
                    data=[item for item in data if self.visible(kind,item.get('id'))]
                if self.is_admin():
                    if endpoint in ('api_projects','api_series_list'):
                        for item in data:
                            self.annotate_owner(item,'project' if endpoint=='api_projects' else 'series')
                    elif endpoint=='api_project' and isinstance(data.get('project'),dict):
                        self.annotate_owner(data['project'],'project')
                    elif endpoint=='api_series_get' and isinstance(data.get('series'),dict):
                        self.annotate_owner(data['series'],'series')
                if endpoint in ('api_render_queue','api_render_queue_add','api_render_queue_start','api_render_queue_pause','api_render_queue_remove'):
                    data=self.filter_queue(data)
                if endpoint not in ('api_config','api_comfy_nodes_status') and not endpoint.startswith('team_'):
                    # Project snapshots never expose provider credentials, even to an administrator.
                    data=self.safe_config(data)
                response.set_data(app.json.dumps(data))
            if self.is_admin() and response.status_code < 400 and endpoint in ('api_project','api_series_get','serve_file','download','jianying_export_download'):
                self.store.audit(actor['id'], 'admin_read:' + endpoint, json.dumps(request.view_args or {},ensure_ascii=False))
            if response.status_code<400 and (request.method not in ('GET','HEAD','OPTIONS') or endpoint in MUTATING_GETS):
                self.store.audit(actor['id'],endpoint or request.path,json.dumps(request.view_args or {},ensure_ascii=False))
            return response

        @app.teardown_request
        def clear_team_runtime(error):
            self.ns.get('clear_runtime_config',lambda:None)()

        @app.errorhandler(PermissionError)
        def ownership_error(error):
            return jsonify(ok=False,msg='资源不存在或无权访问'),404

        @app.errorhandler(403)
        @app.errorhandler(401)
        @app.errorhandler(428)
        def team_error(error):
            return jsonify(ok=False,msg=error.description),error.code

        @app.get('/login',endpoint='team_login_page')
        def login_page():
            page=(self.base/'static'/'team-login.html').read_text()
            port=int(os.environ.get('SHORT_DRAMA_ADMIN_PORT','7861'))
            page=page.replace('<body>',f'<body data-admin-port="{port}">')
            return Response(page,mimetype='text/html')

        @app.get('/account/password',endpoint='team_password_page')
        def password_page():
            return send_file(self.base/'static'/'team-login.html')

        @app.get('/team',endpoint='team_admin_page')
        def admin_page():
            return send_file(self.base/'static'/'team-admin.html')

        @app.get('/api/auth/session',endpoint='team_session')
        def current_session():
            if 'csrf' not in session:
                session['csrf']=secrets.token_urlsafe(32)
            actor=getattr(g,'team_user',None)
            return jsonify(ok=True,user=self.store.public(actor) if actor else None,csrf=session['csrf'])

        @app.post('/api/auth/login',endpoint='team_login')
        def login():
            self.check_csrf()
            data=request.get_json(silent=True) or {}
            if not isinstance(data,dict):
                return jsonify(ok=False,msg='登录参数无效'),400
            try:
                user=self.store.authenticate(data.get('username'),data.get('password'),request.remote_addr or '')
            except ValueError as exc:
                return jsonify(ok=False,msg=str(exc)),429
            if not user:
                return jsonify(ok=False,msg='账号或密码不正确'),401
            if request.environ.get('drama.admin_portal') and user['role'] != 'admin':
                return jsonify(ok=False,msg='此入口仅供管理员登录，请在成员入口登录'),403
            self.set_session(user)
            self.store.audit(user['id'],'login')
            return jsonify(ok=True,user=self.store.public(user),csrf=session['csrf'])

        @app.post('/api/auth/logout',endpoint='team_logout')
        def logout():
            session.clear()
            return jsonify(ok=True)

        @app.post('/api/auth/password',endpoint='team_password')
        def password():
            data=request.get_json(silent=True) or {}
            if not isinstance(data,dict):
                return jsonify(ok=False,msg='参数无效'),400
            try:
                user=self.store.change_password(self.actor_id(),data.get('old_password'),data.get('new_password'))
            except ValueError as exc:
                return jsonify(ok=False,msg=str(exc)),400
            self.set_session(user)
            return jsonify(ok=True,csrf=session['csrf'])

        @app.route('/api/team/users',methods=['GET','POST'],endpoint='team_users')
        def users():
            if request.method=='GET':
                return jsonify(ok=True,users=self.store.users())
            data=request.get_json(silent=True) or {}
            try:
                user=self.store.create_user(data.get('username'),data.get('display_name'),data.get('password'),data.get('role','member'))
            except (ValueError,AttributeError) as exc:
                return jsonify(ok=False,msg=str(exc)),400
            return jsonify(ok=True,user=self.store.public(user))

        @app.route('/api/team/users/<uid>/nodes',methods=['GET','PUT'],endpoint='team_user_nodes')
        def user_nodes(uid):
            user=self.store.user(uid)
            if not user:
                abort(404)
            if user['role']!='member':
                return jsonify(ok=False,msg='管理员请在自己的设置中管理节点'),400
            if request.method=='PUT':
                data=request.get_json(silent=True)
                if not isinstance(data,dict) or set(data)!={'nodes'}:
                    return jsonify(ok=False,msg='请提交节点列表'),400
                try:
                    self.user_config.assign_nodes(uid,data['nodes'])
                except ValueError as exc:
                    return jsonify(ok=False,msg=str(exc)),400
            nodes=self.user_config.nodes(uid)
            statuses=self.ns.get('node_statuses',lambda nodes:nodes)(nodes) if request.method=='GET' else nodes
            return jsonify(ok=True,nodes=nodes,node_statuses=statuses,user=self.store.public(user))

        @app.patch('/api/team/users/<uid>',endpoint='team_update_user')
        def update_user(uid):
            data=request.get_json(silent=True) or {}
            if not isinstance(data,dict):
                return jsonify(ok=False,msg='参数无效'),400
            try:
                user=self.store.update_user(uid,data)
            except ValueError as exc:
                return jsonify(ok=False,msg=str(exc)),400
            if uid==self.actor_id():
                self.set_session(user)
            self.store.audit(self.actor_id(),'update_user',uid)
            return jsonify(ok=True,user=self.store.public(user))

        @app.get('/api/team/audit',endpoint='team_audit')
        def audit():
            with self.store.connect() as db:
                rows=db.execute('SELECT audit.*,users.username FROM audit LEFT JOIN users ON audit.actor_id=users.id ORDER BY audit.id DESC LIMIT 200').fetchall()
            return jsonify(ok=True,items=[dict(row) for row in rows])

    def annotate_owner(self,item,kind):
        uid=self.store.owner(kind,item.get('id'))
        user=self.store.user(uid) if uid else None
        if user:
            item.update(owner_id=uid,owner_name=user['display_name'],owner_username=user['username'])

    def preferences(self,actor_id):
        with self.store.connect() as db:
            row=db.execute('SELECT value FROM settings WHERE key=?',('preferences:'+actor_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_preferences(self,actor_id,data):
        # Values are only creative options; credentials and resource ownership never come from a browser.
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)',('preferences:'+actor_id,json.dumps(data)))

    def check_csrf(self):
        expected=session.get('csrf')
        actual=request.headers.get('X-CSRF-Token') or request.args.get('_csrf')
        if not expected or not actual or not secrets.compare_digest(str(expected),str(actual)):
            abort(403,description='会话校验失败，请刷新页面重试')

    def set_session(self,user):
        session.clear()
        session.update(uid=user['id'],version=user['version'],csrf=secrets.token_urlsafe(32))
        session.permanent=True

    def bootstrap_html(self):
        if 'csrf' not in session:
            session['csrf']=secrets.token_urlsafe(32)
        value={'user':self.store.public(self.actor()),'csrf':session['csrf']}
        return '<script>window.PLATFORM='+json.dumps(value,ensure_ascii=False).replace('<','\\u003c')+';</script>'
