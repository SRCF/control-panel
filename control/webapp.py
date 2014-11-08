from flask import Flask, Request, render_template, send_from_directory
from raven.flask_glue import AuthDecorator
from srcf.database.queries import get_member, get_society, _sess

import glob, os

app = Flask(__name__)

auth_decorator = AuthDecorator(desc="SRCF control panel")
app.before_request(auth_decorator.before_request)

sess = _sess()

def lookup_pgdbs(prefix):
    params = {'prefix': prefix, 'prefixfilter': '%s-%%' % prefix}
    q = sess.execute('SELECT datname FROM pg_database ' \
                     'JOIN pg_roles ON datdba=pg_roles.oid ' \
                     'WHERE rolname=:prefix OR rolname LIKE :prefixfilter',
                      params)
    return q.fetchall()


def lookup_lists(prefix):
    patterns = "/var/lib/mailman/lists/%s-*" % prefix
    return [os.path.basename(ldir) for ldir in glob.iglob(patterns)]

@app.route('/')
def home():
    crsid = auth_decorator.principal
    mem = get_member(crsid)
    mem.pgdbs = lookup_pgdbs(crsid)
    mem.lists = lookup_lists(crsid)
    for soc in mem.societies:
        soc.pgdbs = lookup_pgdbs(soc.society)
        soc.lists = lookup_lists(soc.society)

    return render_template("home.html", member=mem)

if __name__ == '__main__':
    app.run()
