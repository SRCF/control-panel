from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template, request, redirect, url_for 

from .utils import srcf_db_sess as sess
from . import utils, inspect_services
from .. import jobs

import re

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

@bp.route("/societies/<society>/admins/add", methods=["GET", "POST"])
def add_admin(society):
    mem, soc = find_mem_society(society)

    crsid = ""
    tgt = None
    error = None

    if request.method == "POST":
        crsid = request.form["crsid"]
        if not crsid:
            error = "Please enter the new administrator's CRSid."
        else:
            try:
                tgt = utils.get_member(crsid)
            except KeyError:
                error = "{0} doesn't appear to be a current user.".format(crsid)
            if tgt in soc.admins:
                error = "{0} is already an administrator.".format(crsid)

    if request.method == "POST" and not error:
        j = jobs.ChangeSocietyAdmin.new(
            requesting_member=mem,
            society=soc,
            target_member=tgt,
            action="add"
        )
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('jobs.status', id=j.job_id))
    else:
        return render_template("society/add_admin.html", society=soc, crsid=crsid, error=error)

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
        return redirect(url_for('jobs.status', id=j.job_id))
    else:
        return render_template("society/remove_admin.html", society=soc, target=tgt)

@bp.route("/societies/<society>/mailinglist", methods=["GET", "POST"])
def create_mailing_list(society):
    mem, soc = find_mem_society(society)

    listname = ""
    error = None
    if request.method == "POST":
        listname = request.form.get("listname")
        if not listname:
            error = "Please enter a list name."
        elif re.search(r"[^a-z0-9_-]", listname):
            error = "List names can only contain letters, numbers, hyphens and underscores."

    if request.method == "POST" and not error:
        j = jobs.CreateSocietyMailingList.new(member=mem, society=soc, listname=listname)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('jobs.status', id=j.job_id))
    else:
        args = {"society": soc, "listname": listname, "error": error}
        return render_template("society/create_mailing_list.html", **args)

@bp.route("/societies/<society>/mailinglist/<listname>/password", methods=["GET", "POST"])
def reset_mailing_list_password(society, listname):
    mem, soc = find_mem_society(society)

    kwargs = { "society": soc,
               "member": mem,
               "listname": listname,
               }

    if request.method == "POST":
        j = jobs.ResetSocietyMailingListPassword.new(**kwargs)
        sess.add(j.row)
        sess.commit()
        return redirect(url_for('jobs.status', id=j.job_id))
    else:
        return render_template("society/reset_mailing_list_password.html", **kwargs)

@bp.route("/societies/<society>/mysql/password", methods=["GET", "POST"], defaults={"type": "mysql"})
@bp.route("/societies/<society>/postgres/password", methods=["GET", "POST"], defaults={"type": "postgres"})
def reset_database_password(society, type):
    mem, soc = find_mem_society(society)

    if request.method == "POST":
        j = {"mysql": jobs.ResetMySQLSocietyPassword,
         "postgres": jobs.ResetPostgresSocietyPassword,
         }[type].new(society=soc, member=mem)

        sess.add(j.row)
        sess.commit()
        return redirect(url_for('jobs.status', id=j.job_id))
    else:
        formatted_name = {"mysql": "MySQL",
                          "postgres": "PostgreSQL"}[type]
        web_interface = {"mysql": "phpMyAdmin",
                         "postgres": "phpPgAdmin"}[type]

        args = { "item": formatted_name,
                 "web_interface": web_interface,
                 "action": url_for('society.reset_database_password', society=society, type=type)
                 }

        return render_template("society/reset_database_password.html", society=soc, member=mem, **args)

@bp.route("/societies/<society>/mysql/create",    methods=["POST"], defaults={"type": "mysql"})
@bp.route("/societies/<society>/postgres/create", methods=["POST"], defaults={"type": "postgres"})
def create_database(society, type):
    mem, soc = find_mem_society(society)

    j = {"mysql": jobs.CreateMySQLSocietyDatabase,
         "postgres": jobs.CreatePostgresSocietyDatabase,
         }[type].new(member=mem, society=soc)

    sess.add(j.row)
    sess.commit()
    return redirect(url_for('jobs.status', id=j.job_id))
