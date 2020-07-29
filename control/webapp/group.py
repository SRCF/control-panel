import re
from urllib.parse import urlparse

from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template, request, redirect, url_for 

from .utils import srcf_db_sess as sess
from .utils import parse_domain_name, create_job_maybe_email_and_redirect, find_mem_group
from . import utils
from srcf.controllib import jobs
from srcf.controllib.jobs import Job
from srcf.database import Domain
from srcf import domains

from . import utils, inspect_services

import string

bp = Blueprint("group", __name__)


def validate_grp_role_email(email):
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


@bp.route('/groups/<group>')
def home(group):
    mem, grp = find_mem_group(group)

    inspect_services.lookup_all(mem)
    inspect_services.lookup_all(grp)

    return render_template("group/home.html", member=mem, group=grp)

@bp.route("/groups/<group>/roleemail", methods=["GET", "POST"])
def update_role_email(group):
    mem, grp = find_mem_group(group)

    email = grp.role_email
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip() or None
        if grp.role_email != email:
            error = validate_grp_role_email(email)
        elif email:
            error = "That's the address we have already."
        else:
            error = "No address is currently set."

    if request.method == "POST" and not error:
        return create_job_maybe_email_and_redirect(
            jobs.UpdateSocietyRoleEmail, # TODO s/society/group/
            requesting_member=mem,
            group=grp,
            email=email
        )
    else:
        return render_template("group/update_role_email.html", group=grp, email=email, error=error)

@bp.route("/groups/<group>/admins/add", methods=["GET", "POST"])
def add_admin(group):
    mem, grp = find_mem_group(group)

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
            if tgt in grp.admins:
                raise ValueError("{0} is already an administrator.".format(crsid))
        except ValueError as e:
            error = e.args[0]

    if request.method == "POST" and not error:
        return create_job_maybe_email_and_redirect(
            jobs.ChangeSocietyAdmin, # TODO s/society/group/
            requesting_member=mem,
            group=grp,
            target_member=tgt,
            action="add"
        )
    else:
        return render_template("group/add_admin.html", group=grp, crsid=crsid, error=error)

@bp.route("/groups/<group>/admins/<target_crsid>/remove", methods=["GET", "POST"])
def remove_admin(group, target_crsid):
    mem, grp = find_mem_group(group)

    try:
        tgt = utils.get_member(target_crsid)
    except KeyError:
        raise NotFound
    if tgt not in grp.admins:
        raise NotFound

    if request.method == "POST":
        return create_job_maybe_email_and_redirect(
            jobs.ChangeSocietyAdmin, # TODO s/society/group/
            requesting_member=mem,
            group=grp,
            target_member=tgt,
            action="remove"
        )
    else:
        return render_template("group/remove_admin.html", member=mem, group=grp, target=tgt)

@bp.route("/groups/<group>/mailinglist", methods=["GET", "POST"])
def create_mailing_list(group):
    mem, grp = find_mem_group(group)

    listname = ""
    error = None
    if request.method == "POST":
        listname = request.form.get("listname", "").strip()
        if not listname:
            error = "Please enter a list name."
        elif re.search(r"[^a-z0-9_-]", listname):
            error = "List names can only contain letters, numbers, hyphens and underscores."
        else:
            lists = inspect_services.lookup_mailinglists(group)
            if "{}-{}".format(group, listname) in lists:
                error = "This mailing list already exists."

    if request.method == "POST" and not error:
        return create_job_maybe_email_and_redirect(
            jobs.CreateSocietyMailingList, # TODO s/society/group/
            member=mem, group=grp, listname=listname
        )
    else:
        return render_template("group/create_mailing_list.html", group=grp, listname=listname, error=error)

@bp.route("/groups/<group>/mailinglist/<listname>/password", methods=["GET", "POST"])
def reset_mailing_list_password(group, listname):
    mem, grp = find_mem_group(group)

    lists = inspect_services.lookup_mailinglists(group)
    if listname not in lists:
        raise NotFound

    if request.method == "POST":
        return create_job_maybe_email_and_redirect(
            jobs.ResetSocietyMailingListPassword, # TODO s/society/group/
            member=mem, group=grp, listname=listname
        )
    else:
        return render_template("group/reset_mailing_list_password.html", member=mem, group=grp, listname=listname)

@bp.route("/groups/<group>/mysql/password", methods=["GET", "POST"], defaults={"type": "mysql"})
@bp.route("/groups/<group>/postgres/password", methods=["GET", "POST"], defaults={"type": "postgres"})
def reset_database_password(group, type):
    mem, grp = find_mem_group(group)

    if request.method == "POST":
        cls = {"mysql": jobs.ResetMySQLSocietyPassword, # TODO s/society/group/
               "postgres": jobs.ResetPostgresSocietyPassword}[type] # TODO s/society/group/
        return create_job_maybe_email_and_redirect(cls, group=grp, member=mem)
    else:
        formatted_name = {"mysql": "MySQL",
                          "postgres": "PostgreSQL"}[type]
        web_interface = {"mysql": "phpMyAdmin",
                         "postgres": "phpPgAdmin"}[type]

        return render_template("group/reset_database_password.html", group=grp, member=mem, type=type, name=formatted_name, web_interface=web_interface)

@bp.route("/groups/<group>/mysql/create",    methods=["GET", "POST"], defaults={"type": "mysql"})
@bp.route("/groups/<group>/postgres/create", methods=["GET", "POST"], defaults={"type": "postgres"})
def create_database(group, type):
    mem, grp = find_mem_group(group)

    if request.method == "POST":
        cls = {"mysql": jobs.CreateMySQLSocietyDatabase, # TODO s/society/group/
               "postgres": jobs.CreatePostgresSocietyDatabase}[type] # TODO s/society/group/
        return create_job_maybe_email_and_redirect(cls, member=mem, group=grp)
    else:
        formatted_name = {"mysql": "MySQL",
                          "postgres": "PostgreSQL"}[type]
        inspect = {"mysql": inspect_services.lookup_mysqluser,
                   "postgres": inspect_services.lookup_pguser}[type]
        has_mem_user = inspect(mem.crsid)
        has_grp_user = inspect(grp.society) # TODO s/society/group/
        return render_template("group/create_database.html", group=grp, member=mem, type=type, name=formatted_name, mem_user=has_mem_user, grp_user=has_grp_user)

@bp.route("/groups/<group>/domains/add", methods=["GET", "POST"])
def add_vhost(group):
    mem, grp = find_mem_group(group)

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
            elif domain.endswith("." + grp.society + ".soc.srcf.net"): # TODO s/society/group/
                pass
            elif domain.endswith(".user.srcf.net") or domain.endswith(".soc.srcf.net"): # TODO s/society/group/
                errors["domain"] = "SRCF domains can't be registered here."
            elif sess.query(Domain).filter(Domain.domain == domain).count():
                errors["domain"] = "This domain is already registered."
        else:
            errors["domain"] = "Please enter a domain or subdomain."

        if request.form.get("edit") or errors:
            return render_template("group/add_vhost.html", group=grp, member=mem, domain=domain, root=root, errors=errors)

        confirm = True
        if request.form.get("confirm"):
            confirm = False
        else:
            valid = {}
            prefixed = "www.{}".format(domain)
            for d in (domain, prefixed):
                valid[d] = domains.verify(d)
            if all(v == (True, True) for v in valid.values()):
                confirm = False

        if confirm:
            return render_template("group/add_vhost_test.html", group=grp, member=mem, domain=domain, root=root, valid=valid)
        else:
            return create_job_maybe_email_and_redirect(
                        jobs.AddSocietyVhost, member=mem, group=grp, # TODO s/society/group/
                        domain=domain, root=root)

    else:
        return render_template("group/add_vhost.html", group=grp, member=mem, domain=domain, root=root, errors=errors)

@bp.route("/groups/<group>/domains/<domain>/changedocroot", methods=["GET", "POST"])
def change_vhost_docroot(group, domain):
    mem, grp = find_mem_group(group)

    errors = {}

    try:
        record = sess.query(Domain).filter(Domain.domain == domain, Domain.owner == grp.society)[0] # TODO s/society/group/
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
                    jobs.ChangeSocietyVhostDocroot, member=mem, group=grp, # TODO s/society/group/
                    domain=domain, root=root)
    else:
        return render_template("group/change_vhost_docroot.html", group=grp, member=mem, domain=domain, root=root, errors=errors)

@bp.route("/groups/<group>/domains/<domain>/remove", methods=["GET", "POST"])
def remove_vhost(group, domain):
    mem, grp = find_mem_group(group)

    try:
        record = sess.query(Domain).filter(Domain.domain == domain)[0]
    except IndexError:
        raise NotFound
    if not record.owner == grp.society: # TODO s/society/group/
        raise Forbidden

    if request.method == "POST":
        return create_job_maybe_email_and_redirect(
                    jobs.RemoveSocietyVhost, member=mem, group=grp, # TODO s/society/group/
                    domain=domain)
    else:
        return render_template("group/remove_vhost.html", group=grp, member=mem, domain=domain)
