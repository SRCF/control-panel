import os
import glob

from flask import Blueprint, render_template, redirect, url_for

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
    cur = utils.temp_mysql_conn().cursor()
    perfix = prefix.replace("-", "_")
    q = "SELECT SCHEMA_NAME FROM information_schema.schemata WHERE " \
        "SCHEMA_NAME = %s OR SCHEMA_NAME LIKE %s"
    cur.execute(q, (prefix, prefix + '/%'))
    return [row[0] for row in cur]

def lookup_lists(prefix):
    patterns = "/var/lib/mailman/lists/%s-*" % prefix
    return [os.path.basename(ldir) for ldir in glob.iglob(patterns)]


@bp.route('/')
def home():
    crsid = utils.raven.principal

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        return redirect(url_for('signup.signup'))

    mem.mysqldbs = lookup_mysqldbs(crsid)
    mem.pgdbs = lookup_pgdbs(crsid)
    mem.lists = lookup_lists(crsid)
    for soc in mem.societies:
        soc.mysqldbs = lookup_mysqldbs(soc.society)
        soc.pgdbs = lookup_pgdbs(soc.society)
        soc.lists = lookup_lists(soc.society)

    return render_template("home.html", member=mem)
