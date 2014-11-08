from flask import Flask, Request, render_template, send_from_directory
from raven.flask_glue import AuthDecorator
from srcf.database import Member, Session

class R(Request):
    trusted_hosts = {'localhost'}

app = Flask(__name__)
app.debug = True
app.request_class = R
app.secret_key = "aVw9OormkPyuliR2LVoIq5IQJPK9GznZOT54kP65SeK8QeZrfC"
auth_decorator = AuthDecorator(desc="SRCF control panel")
app.before_request(auth_decorator.before_request)

sess = Session()	

@app.route('/')
def home():
	# auth_decorator.principal
	return render_template("home.jinja2")

@app.route('/static/<path:filename>')
def static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    app.run()
