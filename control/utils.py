import re
import ldap
import ConfigParser
import MySQLdb


__all__ = ["email_re", "ldapsearch", "is_admin", "mysql_conn"]


# yeah whatever.
email_re = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z][A-Za-z]+$")


# LDAP helper
def ldapsearch(crsid):
    l = ldap.initialize('ldap://ldap.lookup.cam.ac.uk')
    r = l.search_s('ou=people, o=University of Cambridge,dc=cam,dc=ac,dc=uk',
                   ldap.SCOPE_SUBTREE,
                   '(uid={0})'.format(crsid))
    if len(r) != 1:
        raise KeyError(crsid)
    (dn, attrs), = r
    return attrs


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
