#!/usr/bin/python
from wsgiref.handlers import CGIHandler
from werkzeug.debug import DebuggedApplication

import sys
sys.path.insert(0, "/societies/srcf-admin/control-hackday")

from control.webapp import app

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
