from datetime import datetime
from functools import partial
import os
import sys
import traceback
from urllib.parse import urlparse

import flask
import jinja2
import sqlalchemy.orm
import werkzeug.exceptions
from werkzeug.exceptions import BadRequest, Forbidden, HTTPException, NotFound
from werkzeug.middleware.proxy_fix import ProxyFix
import yaml

from srcf.controllib.jobs import CreateSociety, Reactivate, Signup, SocietyJob
from srcf.controllib.utils import email_re, is_admin, ldapsearch, mysql_conn
from srcf.database import JobLog, queries, Session
from srcf.mail import mail_sysadmins
import ucam_webauth
import ucam_webauth.flask_glue
import ucam_webauth.raven.demoserver as raven_demoserver
import ucam_webauth.raven.flask_glue
import ucam_webauth.rsa

__all__ = ["email_re", "auth", "raven", "srcf_db_sess", "get_member", "get_society",
           "temp_mysql_conn", "setup_app", "ldapsearch", "auth_admin", "DOMAIN_WEB"]


DOMAIN_WEB = os.getenv("DOMAIN_WEB", "https://www.srcf.net")


class WLSRequest(ucam_webauth.Request):
    def __str__(self):
        query_string = ucam_webauth.Request.__str__(self)
        return "https://auth.srcf.net/wls/authenticate?" + query_string


class WLSResponse(ucam_webauth.Response):
    keys = dict()
    for kid in (2, 500):
        with open('/etc/apache2/ucam_webauth_keys/pubkey{}'.format(kid), 'rb') as f:
            keys[str(kid)] = ucam_webauth.rsa.load_key(f.read())


class WLSAuthDecorator(ucam_webauth.flask_glue.AuthDecorator):
    request_class = WLSRequest
    response_class = WLSResponse
    logout_url = "https://auth.srcf.net/logout"


auth = WLSAuthDecorator(desc="Control Panel", require_ptags=None)
raven = ucam_webauth.raven.flask_glue.AuthDecorator(desc="SRCF control panel",
                                                    require_ptags=None)


# A session to use with the main srcf admin database (PostGres)
srcf_db_sess = sqlalchemy.orm.scoped_session(
    Session,
    scopefunc=flask._request_ctx_stack.__ident_func__
)
queries.disable_automatic_session(and_use_this_one_instead=srcf_db_sess)


class InactiveUser(NotFound):
    pass


# Use the request session in srcf.database.queries
get_member = partial(queries.get_member, session=srcf_db_sess)
get_society = partial(queries.get_society, session=srcf_db_sess)


# We occasionally need a temporary MySQL connection
def temp_mysql_conn():
    if not hasattr(flask.g, "mysql"):
        # A throwaway connection
        flask.g.mysql = mysql_conn()
    return flask.g.mysql


def parse_domain_name(domain):
    parsed = urlparse(domain.lower())
    domain = parsed.netloc or parsed.path.split("/", 1)[0]
    while domain.startswith("www."):
        domain = domain[4:]
    if all(ord(char) < 128 for char in domain):
        return domain
    else:
        # convert to punycode
        return domain.encode("idna").decode("ascii")


# Template helpers
def sif(variable, val):
    """"string if": `val` if `variable` is defined and truthy, else ''"""
    if not jinja2.is_undefined(variable) and variable:
        return val
    else:
        return ""


class Pagination(object):

    context = 3

    def __init__(self, current, total):
        self.current = current
        self.total = total

    @property
    def show(self):
        return self.total > 1

    def _range(self, x, y):
        return range(x + 1, y + 1)

    @property
    def pages(self):
        pages = set(self._range(max(0, self.current - self.context),
                                min(self.current + self.context - 1, self.total)))
        pages.update(self._range(0, self.context))
        pages.update(self._range(self.total - self.context, self.total))
        return sorted(pages)

    def __iter__(self):
        return iter(self.pages)


def generic_error_handler(error):
    if isinstance(error, HTTPException):
        return flask.render_template("error.html", error=error), error.code
    else:
        tb = traceback.format_exception(*sys.exc_info())
        return flask.render_template("error_tb.html", error=error, tb=tb), 500


def _get_supported_http_codes():
    codes = set()
    for exc in vars(werkzeug.exceptions).values():
        if isinstance(exc, type) and issubclass(exc, HTTPException) and exc.code:
            codes.add(exc.code)
    return codes


def setup_app(app):
    for error in _get_supported_http_codes():
        app.errorhandler(error)(generic_error_handler)

    @app.before_request
    def before_request():
        if getattr(app, "deploy_config", {}).get("test_raven", False):
            auth.request_class = raven_demoserver.Request
            auth.response_class = raven_demoserver.Response

    @app.before_request
    def auth_mux():
        if flask.request.url_rule and flask.request.url_rule.rule == '/signup':
            return raven.before_request()
        else:
            return auth.before_request()

    @app.after_request
    def after_request(res):
        srcf_db_sess.commit()
        return res

    @app.teardown_request
    def teardown_request(res):
        srcf_db_sess.remove()
        if hasattr(flask.g, "mysql"):
            flask.g.mysql.close()
        return res

    app.jinja_env.globals["sif"] = sif
    app.jinja_env.globals["DOMAIN_WEB"] = DOMAIN_WEB
    app.jinja_env.globals["auth"] = auth
    app.jinja_env.globals["effective_crsid"] = effective_crsid
    app.jinja_env.tests["admin"] = is_admin
    app.jinja_env.undefined = jinja2.StrictUndefined

    if not app.secret_key and 'FLASK_SECRET_KEY' in os.environ:
        app.secret_key = os.environ['FLASK_SECRET_KEY']

    if not app.request_class.trusted_hosts and 'FLASK_TRUSTED_HOSTS' in os.environ:
        app.request_class.trusted_hosts = os.environ['FLASK_TRUSTED_HOSTS'].split(",")

    # Make request.remote_addr work etc. (only safe if we are behind a proxy, which we always should be)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_host=1)


def create_job_maybe_email_and_redirect(cls, *args, **kwargs):
    j = cls.new(*args, **kwargs)
    srcf_db_sess.add(j.row)
    srcf_db_sess.flush()  # so that job_id is filled out
    j.resolve_references(srcf_db_sess)
    if j.owner is not None:
        source_info = "Job submitted by " + repr(j.owner)
    else:
        source_info = "Job submitted"
    source_info += " from {0.remote_addr} via {0.host}{0.script_root}.".format(flask.request)
    srcf_db_sess.add(JobLog(job_id=j.job_id, type="created", time=datetime.now(), message=source_info))
    srcf_db_sess.flush()

    if j.state == "unapproved":
        body = source_info + "\n\nYou can approve or reject the job here: {0}" \
                .format(flask.url_for("admin.status", id=j.job_id, _external=True))
        if j.row.args:
            body = yaml.dump(dict(j.row.args), default_flow_style=False) + "\n" + body
        if isinstance(j, SocietyJob) and j.society is not None and j.society.danger:
            body = "WARNING: The target group account has its danger flag set.\n\n" + body
        if j.owner is not None and j.owner.danger:
            body = "WARNING: The job owner has their danger flag set.\n\n" + body
        subject = "[SRCF Control Panel] Job #{0.job_id} {0.state} -- {0}".format(j)
        if isinstance(j, SocietyJob) and j.society is not None:
            reply_to = ("{} Admins".format(j.society.description), j.society.email)
        elif j.owner is not None:
            reply_to = (j.owner.name, j.owner.email)
        else:
            reply_to = None
        mail_sysadmins(subject, body, reply_to=reply_to)

    notify = True
    if isinstance(j, CreateSociety):
        # Society doesn't exist yet -- take the user back to where they pressed "Create society".
        url = flask.url_for("home.home")
    elif isinstance(j, SocietyJob):
        url = flask.url_for("society.home", society=j.society_society)
    elif isinstance(j, (Reactivate, Signup)):
        # User doesn't exist or has no access to control -- just take them straight to the job page.
        url = flask.url_for("jobs.status", id=j.job_id)
        notify = False
    else:
        url = flask.url_for("member.home")
    if notify:
        flask.flash((j.job_id, str(j)), "job-created")

    return flask.redirect(url)


def effective_crsid():
    """
    Return the CRSid of the authenticated user from their Raven or Goose authentication data.

    If the `SRCF-Principal-Override` header is set, admins may override the authentication data in
    order to impersonate another user.
    """
    assert auth.principal
    crsid = auth.principal
    try:
        mem = get_member(crsid)
    except KeyError:
        return crsid
    if not is_admin(mem):
        return crsid
    override = flask.request.headers.get("SRCF-Principal-Override")
    return override or crsid


def effective_member(allow_inactive=False, allow_unregistered=False):
    """
    Lookup a Member record from the user's Raven or Goose authentication data, if one exists.

    Raises `NotFound` if the CRSid is not registered yet, unless `allow_unregistered` is set.

    Raises `InactiveUser` if the corresponding member is not a user, unless `allow_inactive` is set.

    If the `SRCF-Principal-Override` header is set, admins may override the authentication data in
    order to impersonate another user.
    """
    assert auth.principal
    crsid = auth.principal
    try:
        mem = get_member(crsid)
        if not mem.member:
            raise KeyError(crsid)
    except KeyError:
        if allow_unregistered:
            return None
        else:
            raise NotFound
    if not mem.user and not allow_inactive:
        raise InactiveUser
    if not is_admin(mem):
        return mem
    override = flask.request.headers.get("SRCF-Principal-Override")
    if not override:
        return mem
    try:
        alt = get_member(override)
        if not alt.member:
            raise KeyError(crsid)
    except KeyError:
        if allow_unregistered:
            return None
        else:
            raise BadRequest
    if not alt.user and not allow_inactive:
        raise InactiveUser
    else:
        return alt


def find_mem_society(society):
    try:
        mem = effective_member()
        soc = get_society(society)
    except KeyError:
        raise NotFound
    if not mem.user:
        raise InactiveUser

    if mem not in soc.admins:
        raise Forbidden

    return mem, soc


def auth_admin():
    mem = effective_member()
    if not is_admin(mem):
        raise Forbidden


def validate_member_email(crsid, email):
    """
    Validate an email address destined to be a member's registered address.

    Does sane checks like preventing SRCF addresses (which defeat the point of
    the registered address), and preventing email addresses that we know don't
    belong to the member (e.g. @cam.ac.uk addresses with a different CRSid).

    Returns None if valid, or a user-friendly error message otherwise.
    """
    if isinstance(email, str):
        email = email.lower()

    if not email:
        return "Please enter your email address."
    elif not email_re.match(email):
        return "That address doesn't look valid."
    elif email.endswith(("@srcf.net", "@srcf.ucam.org", "@hades.srcf.net")):
        return "This should be an external email address."
    elif email.endswith(("@cam.ac.uk", "@hermes.cam.ac.uk", "@o365.cam.ac.uk",
                         "@universityofcambridgecloud.onmicrosoft.com")):
        named = email.split("@")[0].split("+")[0]
        if named != crsid:
            return "You should use only your own University email address."

    return None
