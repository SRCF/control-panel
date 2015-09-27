from werkzeug.exceptions import NotFound
from flask import Blueprint, render_template, request, redirect, url_for

from .utils import srcf_db_sess as sess
from . import utils, inspect_services
from .. import jobs

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
    crsid = utils.raven.principal
    try:
        mem = utils.get_member(crsid)
    except KeyError:
        raise NotFound

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
        args = {"crsid": crsid, "email": email, "error": error}
        return render_template("member/update_email_address.html", **args)

@bp.route("/member/mailinglist", methods=["POST"])
def create_mailing_list():
    crsid = utils.raven.principal
    try:
        mem = utils.get_member(crsid)
    except KeyError:
        raise NotFound

    j = jobs.CreateUserMailingList.new(member=mem, listname=request.form["listname"])
    sess.add(j.row)
    sess.commit()
    return redirect(url_for('jobs.status', id=j.job_id))

@bp.route("/member/mailinglist/<listname>/password", methods=["GET", "POST"])
def reset_mailing_list_password(listname):
    crsid, mem = find_member()

    kwargs = {"member": mem,
              "listname": listname,
              }

    if request.method == "POST":
        j = jobs.ResetUserMailingListPassword.new(**kwargs)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('jobs.status', id=j.job_id))
    else:
        args = {"crsid": crsid, "mailing_list": listname,
                "action": url_for('member.reset_mailing_list_password', listname=listname)}
        return render_template("member/reset_mailing_list_password.html", **args)

@bp.route("/member/srcf/password", methods=["GET", "POST"], defaults={"type": "srcf"})
@bp.route("/member/mysql/password", methods=["GET", "POST"], defaults={"type": "mysql"})
@bp.route("/member/postgres/password", methods=["GET", "POST"], defaults={"type": "postgres"})
def reset_password(type):
    crsid, mem = find_member()

    if request.method == "POST":
        j = {"mysql": jobs.ResetMySQLUserPassword.new(member=mem),
             "postgres": jobs.ResetPostgresUserPassword.new(member=mem),
             "srcf": jobs.ResetUserPassword.new(member=mem)
             }[type].new(member=mem)
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

        args = { "crsid": crsid, "item": formatted_name,
                 "action": url_for('member.reset_password', type=type) }

        if type == "srcf":
            args["affects"] = "password-based access to the shell service, graphical desktop and SFTP"
        else:
            args["affects"] = "access to " + web_interface + ", as well as any scripts that access databases using your account"

        return render_template("member/reset_password.html", **args)

@bp.route("/member/mysql/create",    methods=["POST"], defaults={"type": "mysql"})
@bp.route("/member/postgres/create", methods=["POST"], defaults={"type": "postgres"})
def create_database(type):
    crsid, mem = find_member()

    j = {"mysql": jobs.CreateMySQLUserDatabase,
         "postgres": jobs.CreatePostgresUserDatabase,
         }[type].new(member=mem)

    sess.add(j.row)
    sess.commit()
    return redirect(url_for('jobs.status', id=j.job_id))
