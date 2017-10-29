#!/usr/bin/python3
from wsgiref.handlers import CGIHandler
from werkzeug.debug import DebuggedApplication
from flask import Request

import sys
from os import path
import json

with open(path.join(path.dirname(__file__), 'deploy_config.json')) as f:
    deploy_config = json.load(f)

sys.path.insert(0, deploy_config["pythonpath"])

from control.webapp import app

class R(Request):
    trusted_hosts = deploy_config["hostname"]
app.request_class = R 

assert len(deploy_config["secret"])
app.secret_key = deploy_config["secret"].encode("ascii")

app.deploy_config = deploy_config

class AppRootFixer(object):
    def __init__(self, app):
        self.app = app 

    def __call__(self, environ, start_reponse):
        environ['SCRIPT_NAME'] = deploy_config["web_directory"]
        return self.app(environ, start_reponse)

app.debug = True
app = DebuggedApplication(app, evalex=False)
app = AppRootFixer(app)
CGIHandler().run(app)
