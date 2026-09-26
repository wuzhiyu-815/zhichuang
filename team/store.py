import contextlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

from werkzeug.security import generate_password_hash, check_password_hash


class TeamStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'team.sqlite3'
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE NOT NULL,
                    display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','member')),
                    enabled INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
                    must_change INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS resources (
                    kind TEXT NOT NULL, key TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES users(id),
                    created REAL NOT NULL, PRIMARY KEY(kind,key));
                CREATE INDEX IF NOT EXISTS resources_owner ON resources(owner_id,kind);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, actor_id TEXT, action TEXT NOT NULL,
                    resource TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL, address TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS login_attempts_time ON login_attempts(created);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
            if 'email' not in columns:
                db.execute('ALTER TABLE users ADD COLUMN email TEXT COLLATE NOCASE')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email)')
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def public(user):
        return {k: user[k] for k in ('id','username','display_name','role','enabled','must_change','created','email')}

    def user(self, uid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
            return dict(row) if row else None

    def users(self):
        with self.connect() as db:
            return [self.public(dict(row)) for row in db.execute('SELECT * FROM users ORDER BY created')]

    @staticmethod
    def validate_password(password):
        if not isinstance(password, str) or not 6 <= len(password) <= 256:
            raise ValueError('密码长度须为 6～256 个字符')

    def create_user(self, username, display_name, password, role='member'):
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{2,31}', username):
            raise ValueError('账号须为 3～32 位字母、数字、点、横线或下划线')
        if role not in ('member','admin'):
            raise ValueError('角色无效')
        self.validate_password(password)
        display_name = str(display_name or username).strip()[:60]
        uid = uuid.uuid4().hex
        hashed = generate_password_hash(password, method='scrypt')
        try:
            with self.connect() as db:
                db.execute('INSERT INTO users (id,username,display_name,password_hash,role,created) VALUES (?,?,?,?,?,?)',
                           (uid, username, display_name, hashed, role, time.time()))
        except sqlite3.IntegrityError as exc:
            raise ValueError('账号已存在') from exc
        return self.user(uid)

    def authenticate(self, username, password, address):
        username = str(username or '').strip()[:254].lower()
        if not isinstance(password, str) or len(password) > 256:
            return None
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM login_attempts WHERE created<?', (now-600,))
            count = db.execute('SELECT count(*) FROM login_attempts WHERE username=? OR address=?', (username,address)).fetchone()[0]
            if count >= 20:
                raise ValueError('登录尝试过多，请 10 分钟后重试')
            db.execute('INSERT INTO login_attempts(username,address,created) VALUES (?,?,?)',(username,address,now))
            row = db.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE',(username,username)).fetchone()
        if row and row['enabled'] and check_password_hash(row['password_hash'],password):
            with self.connect() as db:
                db.execute('DELETE FROM login_attempts WHERE username=? AND address=?',(username,address))
            return dict(row)
        return None

    def update_user(self, uid, data):
        hashed = None
        if data.get('password'):
            self.validate_password(data['password'])
            hashed = generate_password_hash(data['password'],method='scrypt')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            if not row:
                raise ValueError('账号不存在')
            role = data.get('role',row['role'])
            enabled = data.get('enabled',bool(row['enabled']))
            if role not in ('admin','member') or not isinstance(enabled,bool):
                raise ValueError('角色或账号状态无效')
            if row['role']=='admin' and row['enabled'] and (role!='admin' or not enabled):
                count = db.execute("SELECT count(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0]
                if count <= 1:
                    raise ValueError('至少保留一个启用的管理员账号')
            name = str(data.get('display_name') or row['display_name'])[:60]
            db.execute('UPDATE users SET role=?,enabled=?,display_name=?,version=version+1 WHERE id=?',(role,int(enabled),name,uid))
            if hashed:
                db.execute('UPDATE users SET password_hash=?,must_change=1 WHERE id=?',(hashed,uid))
        return self.user(uid)

    def change_password(self, uid, old_password, new_password):
        self.validate_password(new_password)
        user = self.user(uid)
        if not user or not isinstance(old_password,str) or not check_password_hash(user['password_hash'],old_password):
            raise ValueError('当前密码不正确')
        if old_password == new_password:
            raise ValueError('新密码不能与当前密码相同')
        hashed = generate_password_hash(new_password,method='scrypt')
        with self.connect() as db:
            updated = db.execute('UPDATE users SET password_hash=?,must_change=0,version=version+1 WHERE id=? AND version=?',
                                 (hashed,uid,user['version']))
            if updated.rowcount != 1:
                raise ValueError('账号状态已变更，请重新登录')
        return self.user(uid)

    def owner(self, kind, key):
        with self.connect() as db:
            row=db.execute('SELECT owner_id FROM resources WHERE kind=? AND key=?',(kind,str(key))).fetchone()
            return row[0] if row else None

    def claim(self, kind, key, uid):
        if not uid:
            raise ValueError('资源缺少用户归属')
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO resources(kind,key,owner_id,created) VALUES (?,?,?,?)',(kind,str(key),uid,time.time()))
            row=db.execute('SELECT owner_id FROM resources WHERE kind=? AND key=?',(kind,str(key))).fetchone()
            if row[0] != uid:
                raise PermissionError('资源属于其他用户')
        return uid

    def audit(self, uid, action, resource=''):
        with self.connect() as db:
            db.execute('INSERT INTO audit(actor_id,action,resource,created) VALUES (?,?,?,?)',(uid,action,str(resource)[:200],time.time()))

    def bootstrap(self):
        users=self.users()
        if users:
            return next((u['id'] for u in users if u['role']=='admin'),users[0]['id'])
        password=secrets.token_urlsafe(18)
        user=self.create_user('admin','管理员',password,'admin')
        path=self.directory/'initial-admin.txt'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:
            f.write(f'登录账号: admin\n初始密码：{password}\n首次登录必须修改密码，修改后可删除此文件。\n')
        return user['id']
