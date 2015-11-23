import functools
import operator
import re

from flask import Blueprint, render_template, redirect, url_for, request

from srcf.database import Member, Society

from .utils import srcf_db_sess as sess
from .utils import create_job_maybe_email_and_redirect

from . import utils
from .. import jobs

SOC_SOCIETY_RE = re.compile(r'^[a-z]+$')

bp = Blueprint("signup", __name__)

@bp.route("/signup", methods=["get", "post"])
def signup():
    crsid = utils.raven.principal

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        pass
    # else:
    #     return redirect(url_for('home.home'))

    if request.method == 'POST':
        values = {}
        for key in ("preferred_name", "surname", "email"):
            values[key] = request.form.get(key, "").strip()
        for key in ("dpa", "tos", "social"):
            values[key] = bool(request.form.get(key, False))

        errors = {
            "preferred_name": False,
            "surname": False,
            "dpa": not values["dpa"],
            "tos": not values["tos"],
            "social": False
        }

        # don't allow initials
        if len(re.sub(r"[^a-z]", "", values["preferred_name"], re.IGNORECASE)) <= 1:
            errors["preferred_name"] = "Please tell us your full preferred name."
        if len(re.sub(r"[^a-z]", "", values["surname"], re.IGNORECASE)) <= 1:
            errors["surname"] = "Please tell us your surname."

        if not values["email"]:
            errors["email"] = "Please enter your email address."
        elif not utils.email_re.match(values["email"]):
            errors["email"] = "That address doesn't look valid."

        any_error = False
        for i in errors.values():
            if i:
                any_error = True
                break

        if any_error:
            return render_template("signup/signup.html", crsid=crsid, errors=errors, **values)
        else:
            del values["dpa"], values["tos"]
            return create_job_maybe_email_and_redirect(
                        jobs.Signup, crsid=crsid, **values)

    else:
        try:
            lookup_user = utils.ldapsearch(crsid)
            surname = lookup_user["sn"][0]
            if lookup_user["cn"][0] != lookup_user["displayName"][0]:
                # user customised their name, maybe they added a first name?
                preferred_name = lookup_user["displayName"][0].replace(surname, "").strip()
        except KeyError:
            preferred_name = ""
            surname = ""

        # defaults
        values = {
            "preferred_name": preferred_name,
            "surname": surname,
            "email": crsid + "@cam.ac.uk",
            "dpa": False,
            "tos": False,
            "social": True
        }

        return render_template("signup/signup.html", crsid=crsid, errors={}, **values)

@bp.route("/signup/society", methods=["get", "post"])
def newsoc():
    crsid = utils.raven.principal

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        return redirect(url_for('signup.signup'))

    if request.method == 'POST':
        values = {}
        for key in ("society", "description"):
            values[key] = request.form.get(key, "").strip()
        values["admins"] = re.findall("\w+", request.form.get("admins", ""))

        errors = {}

        if crsid not in values["admins"]:
            errors["admins"] = "You need to add yourself as an admin."

        current_admins = sess.query(Member) \
                .filter(Member.crsid.in_(values["admins"])) \
                .all()
        current_admin_crsids = [x.crsid for x in current_admins]

        if len(values["admins"]) != len(current_admin_crsids):
            errors["admins"] = "The following admins do not have personal SRCF accounts: {0}" \
                    .format(", ".join(x for x in values["admins"] if x not in current_admin_crsids))

        try:
            soc = utils.get_society(values["society"])
        except KeyError:
            pass
        else:
            errors["society"] = "A society with this name already exists."

        if not values["society"]:
            errors["society"] = "Please enter a society short name."
        elif len(values["society"]) > 16:
            errors["society"] = "Society short names must be no longer than 16 characters."
        elif not SOC_SOCIETY_RE.match(values["society"]):
            errors["society"] = "Society short names may only contain lowercase letters."

        if not values["description"]:
            errors["description"] = "Please enter the full name of the society."

        any_error = False
        for i in errors.values():
            if i:
                any_error = True
                break

        if any_error:
            return render_template("signup/newsoc.html", errors=errors, **values)
        else:
            return create_job_maybe_email_and_redirect(
                        jobs.CreateSociety, member=mem, **values)

    else:
        # defaults
        values = {
            "description": "",
            "society": "",
            "admins": [crsid]
        }

        return render_template("signup/newsoc.html", errors={}, **values)
