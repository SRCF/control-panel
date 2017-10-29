import re
from ldap3 import Server, Connection, ALL, ALL_ATTRIBUTES
import ConfigParser
import MySQLdb


__all__ = ["email_re", "ldapsearch", "is_admin", "mysql_conn"]


# yeah whatever.
email_re = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z][A-Za-z]+$")


# LDAP helper
def ldapsearch(crsid):

    server = Server('ldap.lookup.cam.ac.uk', get_info=ALL)
    conn = Connection(server, auto_bind=True)
    conn.search('ou=people, o=University of Cambridge,dc=cam,dc=ac,dc=uk', '(uid={0})'.format(crsid), attributes=ALL_ATTRIBUTES)
    r = conn.entries

    if len(r) != 1:
        raise KeyError(crsid)
    return r[0]


def is_admin(member):
    for soc in member.societies:
        if soc.society == "srcf-admin":
            return True
    return False


my_cnf = ConfigParser.ConfigParser()
my_cnf.read("/societies/srcf-admin/.my.cnf")
mysql_passwd = my_cnf.get('client', 'password')
def mysql_conn():
    conn = MySQLdb.connect(user="srcf_admin", db="srcf_admin",
                         passwd=mysql_passwd)
    conn.autocommit = True
    return conn


def is_valid_socname(s):
    return re.match(r'^[a-z0-9_-]+$', s)
