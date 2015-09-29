from werkzeug.exceptions import NotFound
from flask import Blueprint, render_template, request, redirect, url_for

from .utils import srcf_db_sess as sess
from . import utils, inspect_services
from .. import jobs

import re

def find_member():
    """ Gets a CRSID and member object from the Raven authentication data """
    crsid = utils.raven.principal
    try:
        mem = utils.get_member(crsid)
    except KeyError:
        raise NotFound

    return crsid, mem

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
        email = request.form.get("email")
        if not email:
            error = "Please enter your email address."
        elif mem.email == email:
            error = "That's the address we already have."
        elif not utils.email_re.match(email):
            error = "That address doesn't look valid."

    if request.method == "POST" and not error:
        j = jobs.UpdateEmailAddress.new(member=mem, email=email)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for("jobs.status", id=j.job_id))
    else:
        return render_template("member/update_email_address.html", member=mem, email=email, error=error)

@bp.route("/member/mailinglist", methods=["GET", "POST"])
def create_mailing_list():
    crsid, mem = find_member()

    listname = ""
    error = None
    if request.method == "POST":
        listname = request.form.get("listname")
        if not listname:
            error = "Please enter a list name."
        elif re.search(r"[^a-z0-9_-]", listname):
            error = "List names can only contain letters, numbers, hyphens and underscores."

    if request.method == "POST" and not error:
        j = jobs.CreateUserMailingList.new(member=mem, listname=request.form["listname"])
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('jobs.status', id=j.job_id))
    else:
        return render_template("member/create_mailing_list.html", member=mem, listname=listname, error=error)

@bp.route("/member/mailinglist/<listname>/password", methods=["GET", "POST"])
def reset_mailing_list_password(listname):
    crsid, mem = find_member()

    if request.method == "POST":
        j = jobs.ResetUserMailingListPassword.new(member=mem, listname=listname)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('jobs.status', id=j.job_id))
    else:
        return render_template("member/reset_mailing_list_password.html", member=mem, listname=listname)

@bp.route("/member/srcf/password", methods=["GET", "POST"], defaults={"type": "srcf"})
@bp.route("/member/mysql/password", methods=["GET", "POST"], defaults={"type": "mysql"})
@bp.route("/member/postgres/password", methods=["GET", "POST"], defaults={"type": "postgres"})
def reset_password(type):
    crsid, mem = find_member()

    if request.method == "POST":
        j = {"mysql": jobs.ResetMySQLUserPassword,
             "postgres": jobs.ResetPostgresUserPassword,
             "srcf": jobs.ResetUserPassword}[type].new(member=mem)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('jobs.status', id=j.job_id))
    else:
        formatted_name = {"mysql": "MySQL",
                          "postgres": "PostgreSQL",
                          "srcf": "SRCF"}[type]
        web_interface = {"mysql": "phpMyAdmin",
                         "postgres": "phpPgAdmin",
                         "srcf": ""}[type]

        if type == "srcf":
            affects = "password-based access to the shell service, graphical desktop and SFTP"
        else:
            affects = "access to " + web_interface + ", as well as any scripts that access databases using your account"

        return render_template("member/reset_password.html", member=mem, type=type, name=formatted_name, affects=affects)

@bp.route("/member/mysql/create",    methods=["POST"], defaults={"type": "mysql"})
@bp.route("/member/postgres/create", methods=["POST"], defaults={"type": "postgres"})
def create_database(type):
    crsid, mem = find_member()

    j = {"mysql": jobs.CreateMySQLUserDatabase,
         "postgres": jobs.CreatePostgresUserDatabase}[type].new(member=mem)
    sess.add(j.row)
    sess.commit()
    return redirect(url_for('jobs.status', id=j.job_id))
