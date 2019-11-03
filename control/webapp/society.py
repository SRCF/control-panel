import re
from urllib.parse import urlparse

from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template, request, redirect, url_for 

from .utils import srcf_db_sess as sess
from .utils import parse_domain_name, create_job_maybe_email_and_redirect, find_mem_society
from . import utils
from srcf.controllib import jobs
from srcf.controllib.jobs import Job
from srcf.database import Domain

from . import utils, inspect_services

import string

bp = Blueprint("society", __name__)


def validate_soc_role_email(email):
    if isinstance(email, str):
        email = email.lower()

    if not email:
        return None
    elif not utils.email_re.match(email):
        return "This doesn't look like a valid email address."
    elif email.endswith(("@srcf.net", "@srcf.ucam.org", "@hades.srcf.net")):
        return "This should be an external email address, not one provided by the SRCF."
    elif (email.endswith(("@cam.ac.uk", "@cantab.net", "@alumni.cam.ac.uk"))
          or (email.endswith(("@hermes.cam.ac.uk",
                              "@universityofcambridgecloud.onmicrosoft.com"))
              # check that this isn't a shared mailbox
              and re.match(r'[0-9]$', '@'.join(email.split('@')[:-1]).split('+')[0]))):
        return "This looks like a personal email address, which isn't suitable for a role email."

    return None


@bp.route('/societies/<society>')
def home(society):
    mem, soc = find_mem_society(society)

    inspect_services.lookup_all(mem)
    inspect_services.lookup_all(soc)

    return render_template("society/home.html", member=mem, society=soc)

@bp.route("/societies/<society>/roleemail", methods=["GET", "POST"])
def update_role_email(society):
    mem, soc = find_mem_society(society)

    email = soc.role_email
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip() or None
        if soc.role_email != email:
            error = validate_soc_role_email(email)
        elif email:
            error = "That's the address we have already."
        else:
            error = "No address is currently set."

    if request.method == "POST" and not error:
        return create_job_maybe_email_and_redirect(
            jobs.UpdateSocietyRoleEmail,
            requesting_member=mem,
            society=soc,
            email=email
        )
    else:
        return render_template("society/update_role_email.html", society=soc, email=email, error=error)

@bp.route("/societies/<society>/admins/add", methods=["GET", "POST"])
def add_admin(society):
    mem, soc = find_mem_society(society)

    crsid = ""
    tgt = None
    error = None

    if request.method == "POST":
        crsid = request.form.get("crsid", "").strip().lower()
        try:
            if not crsid:
                raise ValueError("Please enter the new administrator's CRSid.")
            try:
                tgt = utils.get_member(crsid)
            except KeyError:
                if re.match("^[a-z]+[0-9]*$", crsid):
                    raise ValueError("{0} isn't a SRCF member; please ask them to join.".format(crsid))
                else:
                    raise ValueError("{0} isn't a valid CRSid.".format(crsid))
            if not tgt.member:
                raise ValueError("{0} isn't a SRCF member; please ask them to join.".format(crsid))
            if not tgt.user:
                raise ValueError("{0} doesn't have an active SRCF account; please ask them to reactivate their account by going to the SRCF Control Panel.".format(crsid))
            if tgt == mem:
                raise ValueError("You are already an administrator.")
            if tgt in soc.admins:
                raise ValueError("{0} is already an administrator.".format(crsid))
        except ValueError as e:
            error = e.args[0]

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

    if request.method == "POST":
        return create_job_maybe_email_and_redirect(
            jobs.ChangeSocietyAdmin,
            requesting_member=mem,
            society=soc,
            target_member=tgt,
            action="remove"
        )
    else:
        return render_template("society/remove_admin.html", member=mem, society=soc, target=tgt)

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
        else:
            lists = inspect_services.lookup_mailinglists(society)
            if "{}-{}".format(society, listname) in lists:
                error = "This mailing list already exists."

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

    lists = inspect_services.lookup_mailinglists(society)
    if listname not in lists:
        raise NotFound

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

@bp.route("/societies/<society>/domains/add", methods=["GET", "POST"])
def add_vhost(society):
    mem, soc = find_mem_society(society)

    domain = ""
    root = ""
    errors = {}
    if request.method == "POST":
        domain = request.form.get("domain", "").strip()
        root = request.form.get("root", "").strip()
        if domain:
            parsed = parse_domain_name(domain)
            if domain != parsed:
                domain = parsed
                errors["domain"] = "We've corrected your input to just the domain name, submit again once you've checked it's correct."
            elif domain.endswith("." + soc.society + ".soc.srcf.net"):
                pass
            elif domain.endswith(".user.srcf.net") or domain.endswith(".soc.srcf.net"):
                errors["domain"] = "SRCF domains can't be registered here."
            elif sess.query(Domain).filter(Domain.domain == domain).count():
                errors["domain"] = "This domain is already registered."
        else:
            errors["domain"] = "Please enter a domain or subdomain."

    if request.method == "POST" and not errors:
        return create_job_maybe_email_and_redirect(
                    jobs.AddSocietyVhost, member=mem, society=soc,
                    domain=domain, root=root)
    else:
        return render_template("society/add_vhost.html", society=soc, member=mem, domain=domain, root=root, errors=errors)

@bp.route("/societies/<society>/domains/<domain>/changedocroot", methods=["GET", "POST"])
def change_vhost_docroot(society, domain):
    mem, soc = find_mem_society(society)

    errors = {}

    try:
        record = sess.query(Domain).filter(Domain.domain == domain, Domain.owner == soc.society)[0]
    except IndexError:
        raise NotFound

    root = record.root.replace("public_html/", "") if record.root else ""

    if request.method == "POST":
        root = request.form.get("root", "").strip()
        if any([ch in root for ch in string.whitespace + "\\" + "\"" + "\'"]) or ".." in root:
            errors["root"] = "This document root is invalid."
        try:
            domain = parse_domain_name(domain)
        except ValueError as e:
            errors["domain"] = e.args[0]

    if request.method == "POST" and not errors:
        return create_job_maybe_email_and_redirect(
                    jobs.ChangeSocietyVhostDocroot, member=mem, society=soc,
                    domain=domain, root=root)
    else:
        return render_template("society/change_vhost_docroot.html", society=soc, member=mem, domain=domain, root=root, errors=errors)

@bp.route("/societies/<society>/domains/<domain>/remove", methods=["GET", "POST"])
def remove_vhost(society, domain):
    mem, soc = find_mem_society(society)

    try:
        record = sess.query(Domain).filter(Domain.domain == domain)[0]
    except IndexError:
        raise NotFound
    if not record.owner == soc.society:
        raise Forbidden

    if request.method == "POST":
        return create_job_maybe_email_and_redirect(
                    jobs.RemoveSocietyVhost, member=mem, society=soc,
                    domain=domain)
    else:
        return render_template("society/remove_vhost.html", society=soc, member=mem, domain=domain)
