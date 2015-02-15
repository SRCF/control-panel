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

@bp.route("/member/password", methods=["GET", "POST"])
def reset_password():
    crsid, mem = find_member()

    if request.method == "POST":
        j = jobs.ResetUserPassword.new(member=mem)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('job_status.status', id=j.job_id))
    else:
        return render_template("member/reset_password.html", member=mem)

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
    return redirect(url_for('job_status.status', id=j.job_id))

@bp.route("/member/mysql/password", methods=["GET", "POST"])
def reset_mysql_password():
    crsid, mem = find_member()

    if request.method == "POST":
        j = jobs.ResetMySQLUserPassword.new(member=mem)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('job_status.status', id=j.job_id))
    else:
        return render_template("member/reset_mysql_password.html", member=mem)

@bp.route("/member/postgres/password", methods=["GET", "POST"])
def reset_postgres_password():
    crsid, mem = find_member()

    if request.method == "POST":
        j = jobs.ResetPostgresUserPassword.new(member=mem)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('job_status.status', id=j.job_id))
    else:
        return render_template("member/reset_postgres_password.html", member=mem)
