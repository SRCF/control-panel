#!/usr/bin/python
from wsgiref.handlers import CGIHandler
from werkzeug.debug import DebuggedApplication
from flask import Request

import sys
from os import path

sys.path.insert(0, "/societies/srcf-admin/control-hackday")

from control.webapp import app

class R(Request):
    trusted_hosts = {'srcf-admin.soc.srcf.net'}
app.request_class = R 

with open(path.join(path.dirname(__file__), 'secret')) as f:
    app.secret_key = f.read()

class AppRootFixer(object):
    def __init__(self, app):
        self.app = app 

    def __call__(self, environ, start_reponse):
        environ['SCRIPT_NAME'] = '/control-hackday'
        return self.app(environ, start_reponse)

app.debug = True
app = DebuggedApplication(app, evalex=False)
app = AppRootFixer(app)
CGIHandler().run(app)
