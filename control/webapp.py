from flask import Flask, Request, render_template, send_from_directory
from raven.flask_glue import AuthDecorator
from srcf.database.queries import get_member, get_society

app = Flask(__name__)
auth_decorator = AuthDecorator(desc="SRCF control panel")
app.before_request(auth_decorator.before_request)

@app.route('/')
def home():
    return render_template("home.html", member=get_member(auth_decorator.principal))
