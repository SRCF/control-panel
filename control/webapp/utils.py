import os
import sys
import traceback
from functools import partial
from urllib.parse import urlparse

import flask
import jinja2
import sqlalchemy.orm
import raven.flask_glue
import raven.demoserver as raven_demoserver
from werkzeug.exceptions import NotFound, Forbidden, HTTPException

import srcf.database
import srcf.database.queries
import srcf.mail
from srcf.controllib.utils import *


__all__ = ["email_re", "raven", "srcf_db_sess", "get_member", "get_society",
           "temp_mysql_conn", "setup_app", "ldapsearch", "auth_admin"]


raven = raven.flask_glue.AuthDecorator(desc="SRCF control panel", require_ptags=None)


# A session to use with the main srcf admin database (PostGres)
srcf_db_sess = sqlalchemy.orm.scoped_session(
    srcf.database.Session,
    scopefunc=flask._request_ctx_stack.__ident_func__
)

class InactiveUser(NotFound): pass

# Use the request session in srcf.database.queries
get_member = partial(srcf.database.queries.get_member,  session=srcf_db_sess)
def get_society(name):
    soc = srcf.database.queries.get_society(name, session=srcf_db_sess)
    # Fix up pending_admins to remove already approved ones
    soc.pending_admins = [x for x in soc.pending_admins if not x.crsid in (y.crsid for y in soc.admins)]
    return soc

# We occasionally need a temporary MySQL connection
def temp_mysql_conn():
    if not hasattr(flask.g, "mysql"):
        # A throwaway connection
        flask.g.mysql = mysql_conn()
    return flask.g.mysql


def parse_domain_name(domain):
    if "//" in domain:
        parts = urlparse(domain.rstrip("/"))
        if parts.path:
            raise ValueError("Please enter the domain without including a path.")
        domain = parts.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        if not domain:
            raise ValueError("Please enter a domain or subdomain.")
    elif "/" in domain or ":" in domain:
        raise ValueError("Please enter the domain without including a path.")
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


def generic_error_handler(error):
    if isinstance(error, HTTPException):
        errorcode = error.code
        tb = None
    else:
        errorcode = 500
        tb = traceback.format_exception(*sys.exc_info())
    return flask.render_template("error.html", error=error, tb=tb), errorcode


def setup_app(app):
    app.errorhandler(400)(generic_error_handler)
    for error in range(402, 432):
        app.errorhandler(error)(generic_error_handler)
    for error in range(500, 504):
        app.errorhandler(error)(generic_error_handler)

    @app.before_request
    def before_request():
        if getattr(app, "deploy_config", {}).get("test_raven", False):
            raven.request_class = raven_demoserver.Request
            raven.response_class = raven_demoserver.Response

    app.before_request(raven.before_request)

    @app.after_request
    def after_request(res):
        srcf_db_sess.commit()
        return res

    @app.teardown_request
    def teardown_request(res):
        srcf_db_sess.remove()
        return res

    @app.teardown_request
    def teardown_request(res):
        if hasattr(flask.g, "mysql"):
            flask.g.mysql.close()

    app.jinja_env.globals["sif"] = sif
    app.jinja_env.globals["DOMAIN_WEB"] = os.getenv("DOMAIN_WEB", "https://www.srcf.net")
    app.jinja_env.tests["admin"] = is_admin
    app.jinja_env.undefined = jinja2.StrictUndefined

    if not app.secret_key and 'FLASK_SECRET_KEY' in os.environ:
        app.secret_key = os.environ['FLASK_SECRET_KEY']

    if not app.request_class.trusted_hosts and 'FLASK_TRUSTED_HOSTS' in os.environ:
        app.request_class.trusted_hosts = os.environ['FLASK_TRUSTED_HOSTS'].split(",")


def create_job_maybe_email_and_redirect(cls, *args, **kwargs):
    j = cls.new(*args, **kwargs)
    srcf_db_sess.add(j.row)
    srcf_db_sess.flush() # so that job_id is filled out
    j.resolve_references(srcf_db_sess)

    if j.state == "unapproved":
        body = "You can approve or reject the job here: {0}" \
                .format(flask.url_for("admin.view_jobs", state="unapproved", _external=True))
        if j.owner.danger:
            body = "WARNING: This user has their danger flag set.\n\n" + body
        subject = "[Control Panel] Job #{0.job_id} {0.state} -- {0}".format(j)
        srcf.mail.mail_sysadmins(subject, body)

    return flask.redirect(flask.url_for('jobs.status', id=j.job_id))

def find_member(allow_inactive=False):
    """ Gets a CRSID and member object from the Raven authentication data """
    crsid = raven.principal
    try:
        mem = get_member(crsid)
    except KeyError:
        raise NotFound
    if not mem.user and not allow_inactive:
        raise InactiveUser

    return crsid, mem

def find_mem_society(society):
    crsid = raven.principal

    try:
        mem = get_member(crsid)
        soc = get_society(society)
    except KeyError:
        raise NotFound
    if not mem.user:
        raise InactiveUser

    if mem not in soc.admins:
        raise Forbidden

    return mem, soc

def auth_admin():
    # I think the order before_request fns are run in is undefined.
    assert raven.principal

    mem = get_member(raven.principal)
    for soc in mem.societies:
        if soc.society == "srcf-admin":
            return None
    else:
        raise Forbidden
