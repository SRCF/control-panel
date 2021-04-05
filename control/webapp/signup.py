import re

from flask import Blueprint, redirect, render_template, request, url_for
from sqlalchemy.sql.expression import func

from srcf.controllib import jobs
from srcf.database import Member, Society

from . import utils
from .utils import create_job_maybe_email_and_redirect, srcf_db_sess as sess


SOC_SOCIETY_RE = re.compile(r'^[a-z]+$')
ILLEGAL_NAME_RE = re.compile(r'[:,=\n]')
ILLEGAL_NAME_ERR = "Please do not use any of the following characters: : , = ⏎ "

bp = Blueprint("signup", __name__)


@bp.route("/signup", methods=["get", "post"])
def signup():
    crsid = utils.raven.principal
    force_signup_form = ("force-signup-form" in request.args or "force-signup-form" in request.form)

    try:
        utils.get_member(crsid)
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
        elif ILLEGAL_NAME_RE.search(values["preferred_name"]):
            errors["preferred_name"] = ILLEGAL_NAME_ERR

        if len(values["surname"]) <= 1:
            errors["surname"] = "Please tell us your surname."
        elif ILLEGAL_NAME_RE.search(values["surname"]):
            errors["surname"] = ILLEGAL_NAME_ERR

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
            email = crsid + "@cam.ac.uk"
        except KeyError:
            preferred_name = ""
            surname = ""
            email = ""

        # defaults
        values = {
            "preferred_name": preferred_name,
            "surname": surname,
            "email": email,
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
    crsid = utils.auth.principal

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        return redirect(url_for('signup.signup'))

    errors = {}

    if request.method == 'POST':
        values = {}
        for key in ("society", "description"):
            values[key] = request.form.get(key, "").strip()
        values["admins"] = re.findall(r"\w+", request.form.get("admins", ""))

        if crsid not in values["admins"]:
            errors["admins"] = "You need to add yourself as an admin."

        member_admins = (sess.query(Member)
                             .filter(Member.crsid.in_(values["admins"]))
                             .filter(Member.member == True)
                             .all())
        current_admins = [x for x in member_admins if x.user]

        if len(values["admins"]) != len(member_admins):
            errors["admins"] = ("The following admins do not have personal SRCF accounts: {0}"
                                .format(", ".join(sorted(set(values["admins"]) - set(x.crsid for x in member_admins)))))
        elif len(member_admins) != len(current_admins):
            errors["admins"] = ("The following admins do not have current SRCF accounts, and must first "
                                "reactivate their accounts by logging to the SRCF Control Panel: {0}"
                                .format(", ".join(sorted(x.crsid for x in member_admins if x not in current_admins))))

        if not values["society"]:
            errors["society"] = "Please enter a group account short name."
        elif len(values["society"]) > 16:
            errors["society"] = "Group account short names must be no longer than 16 characters."
        elif not SOC_SOCIETY_RE.match(values["society"]):
            errors["society"] = "Group account short names may only contain lowercase letters."

        keywords = make_keywords(values["description"])
        if not values["description"]:
            errors["description"] = "Please enter the full name of the group."
        elif ILLEGAL_NAME_RE.search(values["description"]):
            errors["description"] = ILLEGAL_NAME_ERR
        elif not keywords:
            errors["description"] = "Please use a more descriptive full name."

        try:
            soc = utils.get_society(values["society"])
        except KeyError:
            pass
        else:
            errors["existing"] = soc
            errors["society"] = "A group account with this short name already exists."

        soc = sess.query(Society).filter(func.lower(Society.description) == values["description"].lower()).first()
        if soc:
            if "existing" not in errors:
                errors["existing"] = soc
            errors["description"] = "A group account with this full name already exists."

        similar = []
        if "existing" not in errors:
            for soc in sess.query(Society):
                words = make_keywords(soc.description)
                if keywords == words:
                    errors["existing"] = soc
                    errors["description"] = "A group account with a matching full name already exists."
                    break
                elif keywords <= words:
                    similar.append(soc)

        if request.form.get("edit") or errors:
            return render_template("signup/newsoc.html", errors=errors, **values)

        elif not request.form.get("confirm"):
            return render_template("signup/newsoc_confirm.html", current_admins=current_admins, similar=similar, **values)

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
