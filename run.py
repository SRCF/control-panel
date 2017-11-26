#!/usr/bin/env python3

import os
import sys

from flask import Request

from control.webapp import app


class TrustedRequest(Request):
    trusted_hosts = "srcf-admin.soc.srcf.net"


class AppRootFixer(object):

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_reponse):
        environ["SCRIPT_NAME"] = "/control-hackday-rsa33-wsgi"
        return self.app(environ, start_reponse)


if __name__ == "__main__":
    app.request_class = TrustedRequest
    app.wsgi_app = AppRootFixer(app.wsgi_app)
    app.secret_key = os.urandom(32)
    app.run(host="localhost", port=int(sys.argv[1]), debug=True)
