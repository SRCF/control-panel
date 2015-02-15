from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template, request, redirect, url_for

from .utils import srcf_db_sess as sess
from . import utils, inspect_services
from .. import jobs


bp = Blueprint("society", __name__)


def find_mem_society(society):
    crsid = utils.raven.principal

    try:
        mem = utils.get_member(crsid)
        soc = utils.get_society(society)
    except KeyError:
        raise NotFound

    if mem not in soc.admins:
        raise Forbidden

    return mem, soc

@bp.route('/societies/<society>')
def home(society):
    mem, soc = find_mem_society(society)

    inspect_services.lookup_all(mem)
    inspect_services.lookup_all(soc)

    return render_template("society/home.html", member=mem, society=soc)

@bp.route("/societies/<society>/admins/add", methods=["POST"])
def add_admin(society):
    mem, soc = find_mem_society(society)

    try:
        tgt = utils.get_member(request.form["crsid"])
    except KeyError:
        raise NotFound
    if tgt in soc.admins:
        raise Forbidden

    j = jobs.ChangeSocietyAdmin.new(
        requesting_member=mem,
        society=soc,
        target_member=tgt,
        action="add"
    )
    sess.add(j.row)
    sess.commit()
    return redirect(url_for('job_status.status', id=j.job_id))

@bp.route("/societies/<society>/admins/<target_crsid>/remove", methods=["GET", "POST"])
def remove_admin(society, target_crsid):
    mem, soc = find_mem_society(society)

    try:
        tgt = utils.get_member(target_crsid)
    except KeyError:
        raise NotFound
    if tgt not in soc.admins:
        raise NotFound
    if tgt == mem:
        raise Forbidden

    if request.method == "POST":
        j = jobs.ChangeSocietyAdmin.new(
            requesting_member=mem,
            society=soc,
            target_member=tgt,
            action="remove"
        )
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('job_status.status', id=j.job_id))
    else:
        return render_template("society/remove_admin.html", society=soc, target=tgt)

@bp.route("/societies/<society>/mailinglist", methods=["POST"])
def create_mailing_list(society):
    mem, soc = find_mem_society(society)

    j = jobs.CreateSocietyMailingList.new(member=mem, society=soc, listname=request.form["listname"])
    sess.add(j.row)
    sess.commit()
    return redirect(url_for('job_status.status', id=j.job_id))

@bp.route("/societies/<society>/mysql/password", methods=["GET", "POST"])
def reset_mysql_password(society):
    mem, soc = find_mem_society(society)

    if request.method == "POST":
        j = jobs.ResetMySQLSocietyPassword.new(society=soc, member=mem)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('job_status.status', id=j.job_id))
    else:
        return render_template("society/reset_mysql_password.html", society=soc, member=mem)

@bp.route("/societies/<society>/postgres/password", methods=["GET", "POST"])
def reset_postgres_password(society):
    mem, soc = find_mem_society(society)

    if request.method == "POST":
        j = jobs.ResetPostgresSocietyPassword.new(society=soc, member=mem)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('job_status.status', id=j.job_id))
    else:
        return render_template("society/reset_postgres_password.html", society=soc, member=mem)
