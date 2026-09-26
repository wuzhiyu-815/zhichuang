"""Email ownership verification and member signup; existing accounts remain valid."""
from email.message import EmailMessage
import hashlib
import hmac
import json
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
import uuid

from flask import jsonify, request, send_file, session
from werkzeug.security import generate_password_hash


class SignupError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class EmailSignup:
    def __init__(self, platform):
        self.platform, self.store = platform, platform.store
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS email_codes (
                    email TEXT PRIMARY KEY, digest TEXT NOT NULL, created REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, delivered INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS email_events (
                    address TEXT NOT NULL, email TEXT NOT NULL, kind TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS email_events_time ON email_events(created);
            ''')
        self.register_routes()

    @staticmethod
    def email(value):
        value = str(value or '').strip().lower()
        if len(value) > 254 or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
            raise SignupError('请输入有效的邮箱地址')
        return value

    def config(self):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='email_signup'").fetchone()
        return json.loads(row[0]) if row else dict(enabled=False, host='', port=465, security='ssl', username='', password='', sender='')

    def public_config(self):
        cfg = self.config()
        cfg['password_set'] = bool(cfg.pop('password', ''))
        return cfg

    def save_config(self, data):
        previous = self.config()
        cfg = {key: data.get(key, previous.get(key)) for key in ('enabled','host','port','security','username','sender')}
        cfg['password'] = data.get('password') or previous.get('password', '')
        if not isinstance(cfg['enabled'], bool) or cfg['security'] not in ('ssl','starttls'):
            raise SignupError('请选择有效的注册状态和加密方式')
        try:
            cfg['port'] = int(cfg['port'])
        except (TypeError, ValueError):
            raise SignupError('SMTP 端口无效')
        if not 1 <= cfg['port'] <= 65535:
            raise SignupError('SMTP 端口无效')
        for key in ('host','username','sender','password'):
            if not isinstance(cfg[key], str) or len(cfg[key]) > 1024 or '\n' in cfg[key] or '\r' in cfg[key]:
                raise SignupError('发信配置格式无效')
            if key != 'password':
                cfg[key] = cfg[key].strip()
        if cfg['enabled'] and not cfg['host']:
            raise SignupError('开启注册前请填写 SMTP 主机和发件邮箱')
        if cfg['enabled'] or cfg['sender']:
            cfg['sender'] = self.email(cfg['sender'])
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('email_signup',?)", (json.dumps(cfg),))
            if not cfg['enabled']:
                db.execute('DELETE FROM email_codes')

    def send(self, recipient, subject, content):
        cfg = self.config()
        if not cfg['host'] or not cfg['sender']:
            raise SignupError('管理员尚未配置发信服务', 503)
        message = EmailMessage()
        message['Subject'], message['From'], message['To'] = subject, cfg['sender'], recipient
        message.set_content(content)
        context = ssl.create_default_context()
        try:
            if cfg['security'] == 'ssl':
                connection = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=15, context=context)
            else:
                connection = smtplib.SMTP(cfg['host'], cfg['port'], timeout=15)
            with connection as smtp:
                if cfg['security'] == 'starttls':
                    smtp.starttls(context=context)
                if cfg['username']:
                    smtp.login(cfg['username'], cfg['password'])
                if smtp.send_message(message):
                    raise SignupError('邮件未被服务器接受，请联系管理员检查发信配置', 503)
        except (OSError, smtplib.SMTPException):
            # SMTP error strings may include credentials or server details.
            raise SignupError('邮件发送失败，请联系管理员检查 SMTP 地址、授权码和发信权限', 503) from None

    def digest(self, email, code):
        key = self.platform.app.secret_key.encode()
        return hmac.new(key, (email+'\0'+code).encode(), hashlib.sha256).hexdigest()

    def require_enabled(self):
        if not self.config()['enabled']:
            raise SignupError('邮箱注册尚未开放，请联系管理员', 403)

    def issue(self, email, address):
        self.require_enabled()
        email = self.email(email)
        now, code = time.time(), f'{secrets.randbelow(1000000):06d}'
        digest = self.digest(email, code)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM email_events WHERE created<?', (now-3600,))
            db.execute('DELETE FROM email_codes WHERE created<?', (now-600,))
            recent = db.execute("SELECT created FROM email_events WHERE email=? AND kind='send' ORDER BY created DESC LIMIT 1", (email,)).fetchone()
            count = db.execute("SELECT count(*) FROM email_events WHERE kind='send' AND (address=? OR email=?)", (address,email)).fetchone()[0]
            total = db.execute("SELECT count(*) FROM email_events WHERE kind='send'").fetchone()[0]
            if (recent and recent[0] > now-60) or count >= 10 or total >= 100:
                raise SignupError('验证码发送过于频繁，请稍后重试（每次至少间隔 60 秒）', 429)
            db.execute("INSERT INTO email_events VALUES (?,?,'send',?)", (address,email,now))
            exists = db.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
            if not exists:
                db.execute('INSERT OR REPLACE INTO email_codes(email,digest,created) VALUES (?,?,?)', (email,digest,now))
        if exists:
            return  # Same response avoids disclosing registered email addresses.
        try:
            self.send(email, '短剧工厂 · 注册验证码', f'你的注册验证码是：{code}\n\n10 分钟内有效，请勿向他人透露。若非本人操作，请忽略此邮件。')
        except Exception:
            with self.store.connect() as db:
                db.execute('DELETE FROM email_codes WHERE email=? AND digest=?', (email,digest))
            raise
        with self.store.connect() as db:
            db.execute('UPDATE email_codes SET delivered=1 WHERE email=? AND digest=?', (email,digest))

    def signup(self, data, address):
        self.require_enabled()
        email = self.email(data.get('email'))
        password = data.get('password')
        self.store.validate_password(password)
        code = str(data.get('code', ''))
        if not re.fullmatch(r'\d{6}', code, flags=re.ASCII):
            raise SignupError('请输入六位数字验证码')
        now = time.time()
        # Commit rejected attempts too; rolling back would permit unlimited guesses.
        error, uid = None, uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute("SELECT count(*) FROM email_events WHERE kind='verify' AND address=? AND created>?", (address,now-600)).fetchone()[0]
            if count >= 30:
                raise SignupError('验证尝试过多，请 10 分钟后重试', 429)
            db.execute("INSERT INTO email_events VALUES (?,?,'verify',?)", (address,email,now))
            row = db.execute('SELECT * FROM email_codes WHERE email=?', (email,)).fetchone()
            if not row or not row['delivered'] or row['created'] < now-600 or row['attempts'] >= 5:
                error = '验证码无效或已过期，请重新获取'
            elif not hmac.compare_digest(row['digest'], self.digest(email,code)):
                db.execute('UPDATE email_codes SET attempts=attempts+1 WHERE email=?', (email,))
                error = '验证码不正确'
            else:
                try:
                    db.execute('INSERT INTO users(id,username,display_name,password_hash,role,must_change,email,created) VALUES (?,?,?,?,\'member\',0,?,?)',
                               (uid,'u_'+uid[:24],str(data.get('display_name') or email.split('@')[0]).strip()[:60],generate_password_hash(password,method='scrypt'),email,now))
                    db.execute('DELETE FROM email_codes WHERE email=?', (email,))
                except sqlite3.IntegrityError:
                    error = '该邮箱无法注册，请登录或联系管理员'
        if error:
            raise SignupError(error)
        return self.store.user(uid)

    def register_routes(self):
        app, platform = self.platform.app, self.platform

        @app.errorhandler(SignupError)
        def signup_error(error):
            return jsonify(ok=False,msg=str(error)), error.status

        def body():
            platform.check_csrf()
            data = request.get_json(silent=True)
            if not isinstance(data,dict):
                raise SignupError('请求参数无效')
            return data

        @app.get('/register', endpoint='team_signup_page')
        def page():
            return send_file(platform.base/'static'/'team-register.html')

        @app.get('/api/auth/registration', endpoint='team_signup_status')
        def status():
            return jsonify(ok=True,enabled=self.config()['enabled'])

        @app.post('/api/auth/email-code', endpoint='team_signup_code')
        def issue():
            data = body()
            self.issue(data.get('email'), request.remote_addr or '')
            return jsonify(ok=True,msg='若该邮箱可注册，验证码已发送，请检查收件箱和垃圾邮件。',retry_after=60)

        @app.post('/api/auth/register', endpoint='team_signup_register')
        def signup():
            data = body()
            try:
                user = self.signup(data, request.remote_addr or '')
            except SignupError:
                raise
            except ValueError as exc:
                raise SignupError(str(exc)) from None
            platform.set_session(user)
            self.store.audit(user['id'],'email_register')
            return jsonify(ok=True,user=self.store.public(user),csrf=session['csrf'])

        @app.route('/api/team/email-settings', methods=['GET','POST'], endpoint='team_mail_settings')
        def settings():
            if request.method == 'POST':
                self.save_config(body())
            return jsonify(ok=True,settings=self.public_config())

        @app.post('/api/team/email-test', endpoint='team_mail_test')
        def test():
            recipient = self.email(body().get('email'))
            self.send(recipient,'短剧工厂 · 发信测试','发信配置测试成功。你可以在团队管理中开启邮箱注册。')
            return jsonify(ok=True,msg='测试邮件已提交给邮件服务器，请确认收件后开启注册。')
