import re
import ConfigParser
from functools import partial

import flask
import jinja2
import sqlalchemy.orm
import MySQLdb
import ldap
import raven.flask_glue

import srcf.database
import srcf.database.queries


__all__ = ["email_re", "raven", "srcf_db_sess", "get_member", "get_society",
           "temp_mysql_conn", "setup_app"]


# yeah whatever.
email_re = re.compile(b"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z][A-Za-z]+$")


raven = raven.flask_glue.AuthDecorator(desc="SRCF control panel")


# A session to use with the main srcf admin database (PostGres)
srcf_db_sess = sqlalchemy.orm.scoped_session(
    srcf.database.Session,
    scopefunc=flask._request_ctx_stack.__ident_func__
)

# Use the request session in srcf.database.queries
get_member  = partial(srcf.database.queries.get_member,  session=srcf_db_sess)
get_society = partial(srcf.database.queries.get_society, session=srcf_db_sess)

# We occasionally need a temporary MySQL connection
my_cnf = ConfigParser.ConfigParser()
my_cnf.read("/societies/srcf-admin/.my.cnf")
mysql_passwd = my_cnf.get('client', 'password')
def temp_mysql_conn():
    if not hasattr(flask.g, "mysql"):
        # A throwaway connection
        flask.g.mysql = \
            MySQLdb.connect(user="srcf_admin", db="srcf_admin",
                            passwd=mysql_passwd)
        flask.g.mysql.autocommit = True
    return flask.g.mysql


# Template helpers
def sif(variable, val):
    """"string if": `val` if `variable` is defined and truthy, else ''"""
    if not jinja2.is_undefined(variable) and variable:
        return val
    else:    
        return ""


def setup_app(app):
    app.before_request(raven.before_request)

    @app.teardown_request
    def teardown_request(res):
        srcf_db_sess.remove()
        return res

    @app.teardown_request
    def teardown_request(res):
        if hasattr(flask.g, "mysql"):
            flask.g.mysql.close()

    app.jinja_env.globals["sif"] = sif
