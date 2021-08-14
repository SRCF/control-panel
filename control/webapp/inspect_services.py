"""
inspect_services: look up accounts, mailing lists, etc. that a User or
Group has on the SRCF
"""

import os

import requests

import srcf.database

from . import utils
from .utils import srcf_db_sess as sess


def lookup_pgdbs(prefix):
    """Return a list of PostgreSQL databases owned by `prefix` (a user or soc)"""
    # we can borrow the postgres connection we already have
    q = sess.execute('SELECT datname FROM pg_database '
                     'JOIN pg_user ON datdba = pg_user.usesysid '
                     'WHERE usename = :prefix', {'prefix': prefix})
    return [row[0] for row in q.fetchall()]


def lookup_mysqldbs(prefix):
    """Return a list of MySQL databases owned by `prefix` (a user or soc)"""
    cur = utils.temp_mysql_conn().cursor()
    try:
        prefix = prefix.replace("-", "_")
        q = "SELECT SCHEMA_NAME FROM information_schema.schemata WHERE " \
            "SCHEMA_NAME = %s OR SCHEMA_NAME LIKE %s"
        cur.execute(q, (prefix, prefix + '/%'))
        return [row[0] for row in cur]
    finally:
        cur.close()


def lookup_pguser(prefix):
    """Does this PostgreSQL user exist?"""
    q = sess.execute('SELECT rolname FROM pg_roles WHERE rolname = :user AND rolcanlogin',
                     {"user": prefix})
    assert q.rowcount in {0, 1}
    q.fetchall()
    if q.rowcount:
        return prefix
    else:
        return None


def lookup_mysqluser(prefix):
    """Does this MySQL user exist?"""
    cur = utils.temp_mysql_conn().cursor()
    try:
        prefix = prefix.replace("-", "_")
        q = "SELECT User from mysql.user WHERE User = %s"
        cur.execute(q, (prefix, ))
        assert cur.rowcount in {0, 1}
        if cur.rowcount:
            return prefix
        else:
            return None
    finally:
        cur.close()


def lookup_mailinglists(prefix):
    """Find all mailing lists owned by `prefix`"""
    req = requests.get("https://lists.srcf.net/getlists.cgi", params={'prefix': prefix})
    req.raise_for_status()
    assert req.headers['content-type'].split(';')[0] == 'text/plain'
    return [listname for listname in req.text.split("\n") if listname]


def lookup_website(prefix, is_member):
    """Detect if a website exists for the given user."""
    path = os.path.join("/public", "home" if is_member else "societies", prefix, "public_html")
    web = {"vhosts": list(sess.query(srcf.database.Domain).filter(srcf.database.Domain.owner == prefix)), "state": None}
    if web["vhosts"]:
        domains = []
        for domain in web["vhosts"]:
            domains += [domain.domain, "www.{}".format(domain.domain)]
        cert_records = sess.query(srcf.database.HTTPSCert.domain).filter(srcf.database.HTTPSCert.domain.in_(domains))
        certs = set()
        for record in cert_records:
            name = record[0]
            while name.startswith("www."):
                name = name[4:]
            certs.add(name)
        web["certs"] = list(certs)
    else:
        web["certs"] = []
    try:
        web["exists"] = os.path.exists(path) and len(os.listdir(path)) > 0
    except OSError:
        # May exist, but we can't read it -- assume active as users may have hidden the contents.
        web["exists"] = True
    if web["exists"]:
        with open("/societies/srcf-admin/{0}webstatus".format("member" if is_member else "soc")) as f:
            for line in f:
                username, state = line.strip().split(":")
                if username == prefix:
                    web["state"] = state
                    break
    return web


def lookup_all(obj, fast=False):
    """
    Augment `obj` (a :cls:`srcf.database.Member` or
    :cls:`srcf.database.Society`) with several properties

    * mysqluser : string | None
    * mysqldbs : string list
    * pguser : string | None
    * pgdbs : string list
    * mailinglists : string list
    * website: {exists: bool[, state: str]}

    If fast==True, omit properties which are slow to
    retrieve -- currently just mailinglists
    """
    if isinstance(obj, srcf.database.Member):
        prefix = obj.crsid
    elif isinstance(obj, srcf.database.Society):
        prefix = obj.society
    else:
        raise TypeError(obj)

    obj.mysqluser = lookup_mysqluser(prefix)
    obj.mysqldbs = lookup_mysqldbs(prefix)
    obj.pguser = lookup_pguser(prefix)
    obj.pgdbs = lookup_pgdbs(prefix)
    obj.website = lookup_website(prefix, isinstance(obj, srcf.database.Member))

    if not fast:
        obj.mailinglists = lookup_mailinglists(prefix)
