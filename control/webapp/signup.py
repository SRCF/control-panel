import functools
import operator
import re

from flask import Blueprint, render_template, redirect, url_for, request

from .utils import srcf_db_sess as sess
from . import utils
from .. import jobs

FULL_NAME_RE = re.compile(r'^[\w\s]*$')
SHORT_NAME_RE = re.compile(r'^[a-z]*$')
MAILING_LIST_RE = re.compile(r'^[-\w]*$')

bp = Blueprint("signup", __name__)

@bp.route("/signup", methods=["get", "post"])
def signup():
    crsid = utils.raven.principal

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        pass
    else:
        return redirect(url_for('home.home'))

    if request.method == 'POST':
        values = {}
        for key in ("", "surname", "email"):
            values[key] = request.form.get(key, "")
        for key in ("dpa", "tos", "social"):
            values[key] = bool(request.form.get(key, False))

        errors = {
            "preferred_name": values["preferred_name"] == "",
            "surname": values["surname"] == "",
            "email": not utils.email_re.match(values["email"]),
            "dpa": not values["dpa"],
            "tos": not values["tos"],
            "social": False
        }

        any_error = functools.reduce(operator.or_, errors.values())

        if any_error:
            return render_template("signup.html", crsid=crsid, errors=errors, **values)
        else:
            del values["dpa"], values["tos"]
            j = jobs.Signup.new(crsid=crsid, **values)
            sess.add(j.row)
            sess.commit()
            return redirect(url_for('job_status.status', id=j.job_id))

    else:
        try:
            surname = utils.ldapsearch(crsid)["sn"][0]
        except KeyError:
            surname = ""

        # defaults
        values = {
            "preferred_name": "",
            "surname": surname,
            "email": crsid + "@cam.ac.uk",
            "dpa": False,
            "tos": False,
            "social": True }

        return render_template("signup.html", crsid=crsid, errors={}, **values)

@bp.route("/newsoc", methods=["get", "post"])
def newsoc():
    crsid = utils.raven.principal

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        return redirect(url_for('signup.signup'))

    if request.method == 'POST':
        values = {}
        for key in ("full_name", "short_name"):
            values[key] = request.form.get(key, "")
        for key in ("admins", "lists"):
            values[key] = request.form.get(key, "").splitlines()
        for key in ("mysql", "postgres"):
            values[key] = bool(request.form.get(key, False))

        errors = {
            "full_name": FULL_NAME_RE.match(values["full_name"]) == None,
            "short_name": SHORT_NAME_RE.match(values["short_name"]) == None,
            "admins": False,
            "lists": False
        }

        for admin in values["admins"]:
            try:
                utils.get_member(admin)
            except KeyError:
                errors["admins"] = True
                break

        if crsid not in values["admins"]:
            errors["admins"] = True

        for mailing_list in values["lists"]:
            if not MAILING_LIST_RE.match(mailing_list):
                errors["lists"] = True
                break

        any_error = functools.reduce(operator.or_, errors.values())

        if any_error:
            values["admins"] = "\n".join(values["admins"])
            values["lists"] = "\n".join(values["lists"])
            return render_template("newsoc.html", errors=errors, **values)
        else:
            j = jobs.CreateSociety.new(requesting_member=mem, **values)
            sess.add(j.row)
            sess.commit()
            return redirect(url_for('job_status.status', id=j.row.job_id))

    else:
        # defaults
        values = {
            "full_name": "",
            "short_name": "",
            "admins": mem,
            "lists": "",
            "mysql": False,
            "postgres": False
        }

        return render_template("newsoc.html", errors={}, **values)
