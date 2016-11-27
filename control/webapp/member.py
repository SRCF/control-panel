from werkzeug.exceptions import NotFound
from flask import Blueprint, render_template, request, redirect, url_for

from .utils import srcf_db_sess as sess
from .utils import create_job_maybe_email_and_redirect, find_member
from . import utils, inspect_services
from .. import jobs

import re

bp = Blueprint("member", __name__)


@bp.route('/member')
def home():
    crsid, mem = find_member()

    inspect_services.lookup_all(mem)

    return render_template("member/home.html", member=mem)

@bp.route("/member/email", methods=["GET", "POST"])
def update_email_address():
    crsid, mem = find_member()

    email = mem.email
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email:
            error = "Please enter your email address."
        elif mem.email == email:
            error = "That's the address we have already."
        elif not utils.email_re.match(email):
            error = "That address doesn't look valid."

    if request.method == "POST" and not error:
        return create_job_maybe_email_and_redirect(
                    jobs.UpdateEmailAddress, member=mem, email=email)
    else:
        return render_template("member/update_email_address.html", member=mem, email=email, error=error)

@bp.route("/member/mailinglist", methods=["GET", "POST"])
def create_mailing_list():
    crsid, mem = find_member()

    listname = ""
    error = None
    if request.method == "POST":
        listname = request.form.get("listname", "").strip()
        if not listname:
            error = "Please enter a list name."
        elif re.search(r"[^a-z0-9_-]", listname):
            error = "List names can only contain letters, numbers, hyphens and underscores."

    if request.method == "POST" and not error:
        return create_job_maybe_email_and_redirect(
                    jobs.CreateUserMailingList, member=mem,
                    listname=request.form["listname"])
    else:
        return render_template("member/create_mailing_list.html", member=mem, listname=listname, error=error)

@bp.route("/member/mailinglist/<listname>/password", methods=["GET", "POST"])
def reset_mailing_list_password(listname):
    crsid, mem = find_member()

    if request.method == "POST":
        return create_job_maybe_email_and_redirect(
                    jobs.ResetUserMailingListPassword, member=mem, listname=listname)
    else:
        return render_template("member/reset_mailing_list_password.html", member=mem, listname=listname)

@bp.route("/member/srcf/password", methods=["GET", "POST"], defaults={"type": "srcf"})
@bp.route("/member/mysql/password", methods=["GET", "POST"], defaults={"type": "mysql"})
@bp.route("/member/postgres/password", methods=["GET", "POST"], defaults={"type": "postgres"})
def reset_password(type):
    crsid, mem = find_member()

    if request.method == "POST":
        cls = {"mysql": jobs.ResetMySQLUserPassword,
               "postgres": jobs.ResetPostgresUserPassword,
               "srcf": jobs.ResetUserPassword}[type]
        return create_job_maybe_email_and_redirect(cls, member=mem)
    else:
        formatted_name = {"mysql": "MySQL",
                          "postgres": "PostgreSQL",
                          "srcf": "SRCF"}[type]
        web_interface = {"mysql": "phpMyAdmin",
                         "postgres": "phpPgAdmin",
                         "srcf": None}[type]

        if type == "srcf":
            affects = "password-based access to the shell service, graphical desktop and SFTP"
        else:
            affects = "access to " + web_interface + ", as well as any scripts that access databases using your account"

        return render_template("member/reset_password.html", member=mem, type=type, name=formatted_name, affects=affects)

@bp.route("/member/mysql/create",    methods=["GET", "POST"], defaults={"type": "mysql"})
@bp.route("/member/postgres/create", methods=["GET", "POST"], defaults={"type": "postgres"})
def create_database(type):
    crsid, mem = find_member()

    if request.method == "POST":
        cls = {"mysql": jobs.CreateMySQLUserDatabase,
               "postgres": jobs.CreatePostgresUserDatabase}[type]
        return create_job_maybe_email_and_redirect(cls, member=mem)
    else:
        formatted_name = {"mysql": "MySQL",
                          "postgres": "PostgreSQL"}[type]
        inspect = {"mysql": inspect_services.lookup_mysqluser,
                   "postgres": inspect_services.lookup_pguser}[type]
        has_user = inspect(mem.crsid)
        return render_template("member/create_database.html", member=mem, type=type, name=formatted_name, user=has_user)
