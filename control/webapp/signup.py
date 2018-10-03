import functools
import operator
import re

from flask import Blueprint, render_template, redirect, url_for, request
from sqlalchemy.orm.exc import NoResultFound

from srcf.database import Member, Society
from srcf.controllib import jobs

from .utils import srcf_db_sess as sess
from .utils import create_job_maybe_email_and_redirect

from . import utils

SOC_SOCIETY_RE = re.compile(r'^[a-z]+$')

bp = Blueprint("signup", __name__)


@bp.route("/signup", methods=["get", "post"])
def signup():
    crsid = utils.raven.principal
    force_signup_form = ("force-signup-form" in request.args or "force-signup-form" in request.form)

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        pass
    else:
        if force_signup_form:
            pass
        else:
            return redirect(url_for('home.home'))

    if request.method == 'POST':
        values = {}
        for key in ("preferred_name", "surname", "email", "mail_handler"):
            values[key] = request.form.get(key, "").strip()
        for key in ("dpa", "tos", "social"):
            values[key] = bool(request.form.get(key, False))

        errors = {}

        # Don't allow a single initial
        if len(values["preferred_name"]) <= 1:
            errors["preferred_name"] = "Please tell us your preferred name."
        if len(values["surname"]) <= 1:
            errors["surname"] = "Please tell us your surname."

        email_err = utils.validate_member_email(crsid, values["email"])
        if email_err is not None:
            errors["email"] = email_err

        if not values["dpa"]:
            errors["dpa"] = "Please allow us to store your information."
        if not values["tos"]:
            errors["tos"] = "Please accept the terms."

        if errors:
            return render_template("signup/signup.html", crsid=crsid, errors=errors, **values)
        else:
            del values["dpa"], values["tos"]
            return create_job_maybe_email_and_redirect(
                        jobs.Signup, crsid=crsid, **values)

    else:
        try:
            lookup_user = utils.ldapsearch(crsid)
            surname = lookup_user["sn"][0]
            preferred_name = ""
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
            "mail_handler": "forward",
            "dpa": False,
            "tos": False,
            "social": True
        }

        return render_template("signup/signup.html", crsid=crsid, errors={}, force_signup_form=force_signup_form, **values)


def make_keywords(desc):
    keywords = set()
    formatted = re.sub("[^a-z]", " ", desc.lower().replace("'", ""))
    for word in formatted.split():
        if word in ("the", "cu", "cambridge", "university", "college", "soc", "society"):
            continue
        while word.endswith("s"):
            word = word[:-1]
        keywords.add(word)
    return keywords

@bp.route("/signup/society", methods=["get", "post"])
def newsoc():
    crsid = utils.raven.principal

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        return redirect(url_for('signup.signup'))

    errors = {}

    if request.method == 'POST':
        values = {}
        for key in ("society", "description"):
            values[key] = request.form.get(key, "").strip()
        values["admins"] = re.findall("\w+", request.form.get("admins", ""))

        if crsid not in values["admins"]:
            errors["admins"] = "You need to add yourself as an admin."

        current_admins = sess.query(Member) \
                .filter(Member.crsid.in_(values["admins"])) \
                .all()
        current_admin_crsids = [x.crsid for x in current_admins]

        if len(values["admins"]) != len(current_admin_crsids):
            errors["admins"] = "The following admins do not have personal SRCF accounts: {0}" \
                    .format(", ".join(x for x in values["admins"] if x not in current_admin_crsids))

        if not values["society"]:
            errors["society"] = "Please enter a society short name."
        elif len(values["society"]) > 16:
            errors["society"] = "Society short names must be no longer than 16 characters."
        elif not SOC_SOCIETY_RE.match(values["society"]):
            errors["society"] = "Society short names may only contain lowercase letters."

        if not values["description"]:
            errors["description"] = "Please enter the full name of the society."

        try:
            soc = utils.get_society(values["society"])
        except KeyError:
            pass
        else:
            errors["existing"] = soc
            errors["society"] = "A society with this short name already exists."

        try:
            soc = sess.query(Society).filter(Society.description == values["description"]).one()
        except NoResultFound:
            pass
        else:
            if "existing" not in errors:
                errors["existing"] = soc
            errors["description"] = "A society with this full name already exists."

        if request.form.get("edit") or errors:
            return render_template("signup/newsoc.html", errors=errors, **values)

        elif not request.form.get("confirm"):
            similar = []
            keywords = make_keywords(values["description"])
            for soc in sess.query(Society):
                words = make_keywords(soc.description)
                if keywords <= words:
                    similar.append(soc)
            return render_template("signup/newsoc_confirm.html",
                    current_admins=current_admins, similar=similar, **values)

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

        return render_template("signup/newsoc.html", errors=errors, **values)
