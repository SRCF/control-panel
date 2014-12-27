import os
import glob

from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template, redirect, url_for

import srcf.database

from .utils import srcf_db_sess as sess
from . import utils


bp = Blueprint("home", __name__)


def lookup_pgdbs(prefix):
    params = {'prefix': prefix, 'prefixfilter': '%s-%%' % prefix}
    # we can borrow the postgres connection we already have
    q = sess.execute('SELECT datname FROM pg_database ' \
                     'JOIN pg_roles ON datdba=pg_roles.oid ' \
                     'WHERE rolname=:prefix OR rolname LIKE :prefixfilter',
                      params)
    return [row[0] for row in q.fetchall()]

def lookup_mysqldbs(prefix):
    try:
        cur = utils.temp_mysql_conn().cursor()
        prefix = prefix.replace("-", "_")
        q = "SELECT SCHEMA_NAME FROM information_schema.schemata WHERE " \
            "SCHEMA_NAME = %s OR SCHEMA_NAME LIKE %s"
        cur.execute(q, (prefix, prefix + '/%'))
        return [row[0] for row in cur]
    finally:
        cur.close()

def lookup_pguser(crsid_or_society):
    q = sess.execute('SELECT rolname FROM pg_roles WHERE rolname = :user',
                     {"user": crsid_or_society})
    assert q.rowcount in {0, 1}
    q.fetchall()
    if q.rowcount:
        return crsid_or_society
    else:
        return None

def lookup_mysqluser(crsid_or_society):
    try:
        cur = utils.temp_mysql_conn().cursor()
        crsid_or_society = crsid_or_society.replace("-", "_")
        q = "SELECT User from mysql.user WHERE User = %s"
        cur.execute(q, (crsid_or_society, ))
        assert cur.rowcount in {0, 1}
        if cur.rowcount:
            return crsid_or_society
        else:
            return None
    finally:
        cur.close()

def lookup_lists(prefix):
    patterns = "/var/lib/mailman/lists/%s-*" % prefix
    return [os.path.basename(ldir) for ldir in glob.iglob(patterns)]

def lookup_all(obj):
    if isinstance(obj, srcf.database.Member):
        prefix = obj.crsid
    elif isinstance(obj, srcf.database.Society):
        prefix = obj.society
    else:
        raise TypeError

    obj.mysqluser = lookup_mysqluser(prefix)
    obj.mysqldbs = lookup_mysqldbs(prefix)
    obj.pguser = lookup_pguser(prefix)
    obj.pgdbs = lookup_pgdbs(prefix)
    obj.lists = lookup_lists(prefix)

@bp.route('/')
def home():
    crsid = utils.raven.principal

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        return redirect(url_for('signup.signup'))

    lookup_all(mem)
    for soc in mem.societies:
        lookup_all(soc)

    return render_template("home.html", member=mem)

@bp.route('/societies/<society>')
def society(society):
    crsid = utils.raven.principal
    try:
        mem = utils.get_member(crsid)
        soc = utils.get_society(society)
    except KeyError:
        raise NotFound
    if mem not in soc.admins:
        raise Forbidden

    lookup_all(mem)
    lookup_all(soc)

    return render_template("society.html", member=mem, society=soc)
