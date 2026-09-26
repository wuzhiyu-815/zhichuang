"""Private provider configuration. Never fall back to another account's endpoints."""
import copy
import json

CONNECTION_KEYS = set('''llm_mode local_llm_url local_llm_model custom_base_url custom_api_key custom_model llm_profiles active_llm_profile_id
comfyui_url comfyui_servers media_provider jimeng_base_url jimeng_api_key jimeng_image_model jimeng_video_model jimeng_image_resolution jimeng_ratio exclusive_mode'''.split())


class UserConfig:
    def __init__(self, platform):
        self.platform = platform
        self.store = platform.store
        # One-time migration: the existing platform credentials belong to the initial admin only.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM settings WHERE key='private_api_migrated'").fetchone():
                if platform.default_owner:
                    cfg = copy.deepcopy(platform.ns.get('CONFIG', {}))
                    cfg.update(platform.preferences(platform.default_owner))
                    db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)',
                               ('user_config:'+platform.default_owner, json.dumps(cfg)))
                db.execute("INSERT INTO settings(key,value) VALUES ('private_api_migrated','1')")

            if not db.execute("SELECT 1 FROM settings WHERE key='node_assignments_migrated'").fetchone():
                for user in db.execute("SELECT id FROM users WHERE role='member'").fetchall():
                    row=db.execute('SELECT value FROM settings WHERE key=?',('user_config:'+user['id'],)).fetchone()
                    old=json.loads(row[0]) if row else {}
                    nodes=old.get('comfyui_servers') or []
                    db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)',('assigned_nodes:'+user['id'],json.dumps(nodes)))
                db.execute("INSERT INTO settings(key,value) VALUES ('node_assignments_migrated','1')")

    def nodes(self, uid):
        with self.store.connect() as db:
            row=db.execute('SELECT value FROM settings WHERE key=?',('assigned_nodes:'+uid,)).fetchone()
        return json.loads(row[0]) if row else []

    def assign_nodes(self, uid, nodes):
        from urllib.parse import urlsplit
        import uuid
        if not self.store.user(uid):
            raise ValueError('账号不存在')
        if not isinstance(nodes,list) or len(nodes)>50:
            raise ValueError('节点必须是列表，最多 50 个')
        clean=[]; seen=set(); ids=set()
        for node in nodes:
            if not isinstance(node,dict):
                raise ValueError('节点格式无效')
            url=str(node.get('url') or '').strip().rstrip('/')
            parsed=urlsplit(url)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('节点地址须为不含密码的 HTTP 或 HTTPS 地址')
            if url in seen:
                raise ValueError('节点地址不能重复')
            enabled=node.get('enabled',True)
            if not isinstance(enabled,bool):
                raise ValueError('节点启用状态无效')
            nid=str(node.get('id') or uuid.uuid4().hex[:12])
            if nid in ids or len(nid)>64:
                raise ValueError('节点 ID 重复或过长')
            seen.add(url);ids.add(nid)
            clean.append(dict(id=nid,name=str(node.get('name') or 'ComfyUI')[:100],url=url,enabled=enabled))
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)',('assigned_nodes:'+uid,json.dumps(clean)))
        return clean

    def get(self, uid):
        cfg = copy.deepcopy(self.platform.ns.get('DEFAULT_CONFIG', {}))
        cfg.update(llm_mode='custom',local_llm_url='',custom_base_url='',custom_api_key='',custom_model='',
                   llm_profiles=[],active_llm_profile_id='',comfyui_url='',comfyui_servers=[],
                   jimeng_base_url='',jimeng_api_key='',exclusive_mode=False)
        if uid:
            with self.store.connect() as db:
                row = db.execute('SELECT value FROM settings WHERE key=?', ('user_config:'+uid,)).fetchone()
            if row:
                cfg.update(json.loads(row[0]))
            else:
                # Older member settings contained creative options only.
                cfg.update({k:v for k,v in self.platform.preferences(uid).items() if k not in CONNECTION_KEYS})
        user=self.store.user(uid) if uid else None
        if user and user['role']=='member':
            cfg['comfyui_servers']=self.nodes(uid)
            first=next((s for s in cfg['comfyui_servers'] if s.get('enabled') and s.get('url')),None)
            cfg['comfyui_url']=first['url'] if first else ''
        cfg['_owner_id'] = uid
        return cfg

    def save(self, uid, cfg):
        if not uid:
            raise ValueError('配置缺少用户归属')
        cfg = {k:v for k,v in cfg.items() if not k.startswith('_')}
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)', ('user_config:'+uid,json.dumps(cfg)))

    def project(self, project):
        uid = self.store.owner('project', (project or {}).get('id'))
        uid = uid or self.platform.actor_id()
        if not uid:
            raise ValueError('项目缺少用户归属，不能选择 API 配置')
        cfg = self.get(uid)
        saved = (project or {}).get('render_config')
        if isinstance(saved,dict):
            cfg.update({k:v for k,v in saved.items() if k not in CONNECTION_KEYS and not k.startswith('_')})
        cfg['_owner_id'] = uid
        return cfg

    def worker_count(self, items):
        owners = {self.store.owner('project',i.get('pid')) for i in items if i.get('status') in ('queued','retry','running')}
        count = 0
        for uid in owners - {None}:
            cfg = self.get(uid)
            count += 1 if cfg.get('media_provider') == 'jimeng' else max(1,len([s for s in cfg.get('comfyui_servers',[]) if s.get('enabled') and s.get('url')]))
        return max(1,min(32,count))
