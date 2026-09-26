"""Mount the same application at /admin with an independent browser session."""
import re
from flask import request
from flask.sessions import SecureCookieSessionInterface

PREFIX = '/admin'


class PortalSessions(SecureCookieSessionInterface):
    def get_cookie_name(self, app):
        name = super().get_cookie_name(app)
        return name + '_admin' if request.environ.get('drama.admin_portal') else name

    def get_cookie_path(self, app):
        return PREFIX if request.environ.get('drama.admin_portal') else '/'


class AdminListener:
    """Dedicated listener uses the admin namespace and its isolated cookie."""
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '/')
        if path != PREFIX and not path.startswith(PREFIX + '/'):
            location = PREFIX + path
            if environ.get('QUERY_STRING'):
                location += '?' + environ['QUERY_STRING']
            start_response('307 Temporary Redirect', [('Location', location), ('Content-Length', '0')])
            return [b'']
        return self.application(environ, start_response)


class AdminMount:
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path == PREFIX or path.startswith(PREFIX + '/'):
            environ = environ.copy()
            environ['drama.admin_portal'] = True
            environ['SCRIPT_NAME'] = environ.get('SCRIPT_NAME', '') + PREFIX
            environ['PATH_INFO'] = path[len(PREFIX):] or '/'
        return self.application(environ, start_response)


# Existing pages use root-relative URLs. Keep their links, scripts, API calls,
# redirects and media in the same portal, without a second worker/application.
ROOT_URL = re.compile(r'''(["'`])/(api|static|file|login|register|team|account|manage)(?=[/"'`?#])''')
ROOT_ONLY = re.compile(r'''(["'`])/(\1)''')


def install(app):
    app.session_interface = PortalSessions()
    app.wsgi_app = AdminMount(app.wsgi_app)

    @app.after_request
    def scope_response(response):
        if not request.environ.get('drama.admin_portal'):
            return response
        location = response.headers.get('Location', '')
        if location.startswith('/') and not location.startswith('//') and not location.startswith(PREFIX + '/'):
            response.headers['Location'] = PREFIX + location
        if response.status_code == 200 and response.mimetype in ('text/html', 'text/javascript', 'application/javascript', 'application/json'):
            response.direct_passthrough = False
            body = response.get_data(as_text=True)
            if response.mimetype == 'application/json':
                body = body.replace('"/file/', '"/admin/file/').replace('"/api/episode-exports/', '"/admin/api/episode-exports/')
            else:
                body = ROOT_URL.sub(lambda m: m[1] + PREFIX + '/' + m[2], body)
                body = ROOT_ONLY.sub(lambda m: m[1] + PREFIX + '/' + m[2], body)
            response.set_data(body)
            response.headers.pop('ETag', None)
            response.headers['Cache-Control'] = 'private, no-store'
        return response
