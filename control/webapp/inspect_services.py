"""
inspect_services: look up accounts, mailing lists, etc. that a Member or
Society has on the SRCF
"""

import os
import glob

import srcf.database

from .utils import srcf_db_sess as sess
from . import utils


def lookup_pgdbs(prefix):
    """Return a list of PostgreSQL databases owned by `prefix` (a user or soc)"""
    params = {'prefix': prefix, 'prefixfilter': '%s-%%' % prefix}
    # we can borrow the postgres connection we already have
    q = sess.execute('SELECT datname FROM pg_database ' \
                     'JOIN pg_roles ON datdba=pg_roles.oid ' \
                     'WHERE rolname=:prefix OR rolname LIKE :prefixfilter',
                      params)
    return [row[0] for row in q.fetchall()]

def lookup_mysqldbs(prefix):
    """Return a list of MySQL databases owned by `prefix` (a user or soc)"""
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
    """Does this PostgreSQL user exist?"""
    q = sess.execute('SELECT rolname FROM pg_roles WHERE rolname = :user',
                     {"user": crsid_or_society})
    assert q.rowcount in {0, 1}
    q.fetchall()
    if q.rowcount:
        return crsid_or_society
    else:
        return None

def lookup_mysqluser(crsid_or_society):
    """Does this MySQL user exist?"""
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

def lookup_mailinglists(prefix):
    """Find all mailing lists owned by `prefix`"""
    patterns = "/var/lib/mailman/lists/%s-*" % prefix
    return [os.path.basename(ldir) for ldir in glob.iglob(patterns)]

def lookup_website(user):
    """Detect if a website exists for the given user."""
    path = os.path.join(os.path.expanduser("~" + user), "public_html")
    return os.path.exists(path) and len(os.listdir(path)) > 0

def lookup_all(obj):
    """
    Augment `obj` (a :cls:`srcf.database.Member` or
    :cls:`srcf.database.Society`) with several properties

    * mysqluser : string | None
    * mysqldbs : string list
    * pguser : string | None
    * pgdbs : string list
    * mailinglists : string list

    """
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
    obj.mailinglists = lookup_mailinglists(prefix)
    obj.website = lookup_website(prefix)