from flask import Flask, Request, render_template, send_from_directory
from raven.flask_glue import AuthDecorator
from srcf.database.queries import get_member, get_society, _sess

import glob, os

class R(Request):
    trusted_hosts = {'localhost'}

app = Flask(__name__)
app.debug = True
app.request_class = R
app.secret_key = "aVw9OormkPyuliR2LVoIq5IQJPK9GznZOT54kP65SeK8QeZrfC"

auth_decorator = AuthDecorator(desc="SRCF control panel")
app.before_request(auth_decorator.before_request)

sess = _sess()

@app.route('/')
def home():
    crsid = auth_decorator.principal
    mem = get_member(crsid)
    params = {'crsid': crsid, 'crsidfilter': '%s-%%' % crsid}
    mem.pgdbs = sess.execute('SELECT datname FROM pg_database JOIN pg_roles ON datdba=pg_roles.oid WHERE rolname=:crsid OR rolname LIKE :crsidfilter', params).fetchall()
    mem.lists = [os.path.basename(ldir) for ldir in glob.iglob("/var/lib/mailman/lists/%s-*" % crsid)]
    for soc in mem.societies:
        socid = soc.name
        params = {'socid': socid, 'socidfilter': '%s-%%' % socid}
        soc.pgdbs = sess.execute('SELECT datname FROM pg_database JOIN pg_roles ON datdba=pg_roles.oid WHERE rolname=:crsid OR rolname LIKE :crsidfilter', params).fetchall()
        soc.lists = [os.path.basename(ldir) for ldir in glob.iglob("/var/lib/mailman/lists/%s-*" % socid)]
    return render_template("home.jinja2", member=mem)

if __name__ == '__main__':
    app.run()
