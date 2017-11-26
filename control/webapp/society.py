from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template, request, redirect, url_for 

from .utils import srcf_db_sess as sess
from .utils import create_job_maybe_email_and_redirect, find_mem_society
from srcf.controllib import jobs
from srcf.controllib.jobs import Job

from . import utils, inspect_services

import re

bp = Blueprint("society", __name__)


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
        crsid = request.form.get("crsid", "").strip()
        if not crsid:
            error = "Please enter the new administrator's CRSid."
        else:
            try:
                tgt = utils.get_member(crsid)
            except KeyError:
                error = "{0} doesn't appear to be a current user.".format(crsid)
            if tgt == mem:
                error = "You are already an administrator."
            elif tgt in soc.admins:
                error = "{0} is already an administrator.".format(crsid)

    if request.method == "POST" and not error:
        return create_job_maybe_email_and_redirect(
            jobs.ChangeSocietyAdmin,
            requesting_member=mem,
            society=soc,
            target_member=tgt,
            action="add"
        )
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
        return create_job_maybe_email_and_redirect(
            jobs.ChangeSocietyAdmin,
            requesting_member=mem,
            society=soc,
            target_member=tgt,
            action="remove"
        )
    else:
        return render_template("society/remove_admin.html", society=soc, target=tgt)

@bp.route("/societies/<society>/mailinglist", methods=["GET", "POST"])
def create_mailing_list(society):
    mem, soc = find_mem_society(society)

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
            jobs.CreateSocietyMailingList,
            member=mem, society=soc, listname=listname
        )
    else:
        return render_template("society/create_mailing_list.html", society=soc, listname=listname, error=error)

@bp.route("/societies/<society>/mailinglist/<listname>/password", methods=["GET", "POST"])
def reset_mailing_list_password(society, listname):
    mem, soc = find_mem_society(society)

    if request.method == "POST":
        return create_job_maybe_email_and_redirect(
            jobs.ResetSocietyMailingListPassword,
            member=mem, society=soc, listname=listname
        )
    else:
        return render_template("society/reset_mailing_list_password.html", member=mem, society=soc, listname=listname)

@bp.route("/societies/<society>/mysql/password", methods=["GET", "POST"], defaults={"type": "mysql"})
@bp.route("/societies/<society>/postgres/password", methods=["GET", "POST"], defaults={"type": "postgres"})
def reset_database_password(society, type):
    mem, soc = find_mem_society(society)

    if request.method == "POST":
        cls = {"mysql": jobs.ResetMySQLSocietyPassword,
               "postgres": jobs.ResetPostgresSocietyPassword}[type]
        return create_job_maybe_email_and_redirect(cls, society=soc, member=mem)
    else:
        formatted_name = {"mysql": "MySQL",
                          "postgres": "PostgreSQL"}[type]
        web_interface = {"mysql": "phpMyAdmin",
                         "postgres": "phpPgAdmin"}[type]

        return render_template("society/reset_database_password.html", society=soc, member=mem, type=type, name=formatted_name, web_interface=web_interface)

@bp.route("/societies/<society>/mysql/create",    methods=["GET", "POST"], defaults={"type": "mysql"})
@bp.route("/societies/<society>/postgres/create", methods=["GET", "POST"], defaults={"type": "postgres"})
def create_database(society, type):
    mem, soc = find_mem_society(society)

    if request.method == "POST":
        cls = {"mysql": jobs.CreateMySQLSocietyDatabase,
               "postgres": jobs.CreatePostgresSocietyDatabase}[type]
        return create_job_maybe_email_and_redirect(cls, member=mem, society=soc)
    else:
        formatted_name = {"mysql": "MySQL",
                          "postgres": "PostgreSQL"}[type]
        inspect = {"mysql": inspect_services.lookup_mysqluser,
                   "postgres": inspect_services.lookup_pguser}[type]
        has_mem_user = inspect(mem.crsid)
        has_soc_user = inspect(soc.society)
        return render_template("society/create_database.html", society=soc, member=mem, type=type, name=formatted_name, mem_user=has_mem_user, soc_user=has_soc_user)
