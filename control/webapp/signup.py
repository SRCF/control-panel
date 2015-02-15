import functools
import operator
import re

from flask import Blueprint, render_template, redirect, url_for, request

from srcf.database import Member, Society

from .utils import srcf_db_sess as sess
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
    else:
        #        return redirect(url_for('home.home'))
        pass

    if request.method == 'POST':
        values = {}
        for key in ("preferred_name", "surname", "email"):
            values[key] = request.form.get(key, "")
        for key in ("dpa", "tos", "social"):
            values[key] = bool(request.form.get(key, False))

        errors = {
            "preferred_name": "Preferred name must be non-empty" if \
                    values["preferred_name"] == "" else False,
            "surname": "Surname must be non-empty" if \
                    values["surname"] == "" else False,
            "email": False if utils.email_re.match(values["email"]) \
                    else "Invalid email address",
            "dpa": not values["dpa"],
            "tos": not values["tos"],
            "social": False
        }

        any_error = False
        for i in errors:
            if i:
                any_error = True
                break

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
        for key in ("society", "description"):
            values[key] = request.form.get(key, "").strip()
        for key in ("mysql", "postgres"):
            values[key] = bool(request.form.get(key, False))
        values["admins"] = request.form.get("admins", "").splitlines()

        errors = {}

        expect_admins = len(values["admins"])
        values["admins"] = [ x.strip() for x in values["admins"] ]

        values["admins"] = \
            sess.query(Member) \
                .filter(Member.crsid.in_(values["admins"])) \
                .all()

        # Check admin list
        if mem not in values["admins"]:
            errors["admins"] = "You must be an admin yourself"

        if len(values["admins"]) != expect_admins:
            errors["admins"] = "Some admins listed are not users of SRCF"

        # Check society
        try:
            soc = utils.get_society(values["society"])
        except KeyError:
            pass
        else:
            errors["society"] = "Society name already taken"

        if len(values["society"]) == 0 or len(values["society"]) > 16:
            errors["society"] = "Society name must be 0 to 16 characters long"
        elif not SOC_SOCIETY_RE.match(values["society"]):
            errors["society"] = "Society must consist of lower case letters only"

        # Check description
        if len(values["description"]) == 0:
            errors["description"] = "Society full name must be non-empty"

        any_error = False
        for i in errors:
            if i:
                any_error = True
                break

        if any_error:
            return render_template("newsoc.html", errors=errors, **values)
        else:
            j = jobs.CreateSociety.new(member=mem, **values)
            sess.add(j.row)
            sess.commit()
            return redirect(url_for('job_status.status', id=j.row.job_id))

    else:
        # defaults
        values = {
            "description": "",
            "society": "",
            "admins": [mem],
            "mysql": False,
            "postgres": False
        }

        return render_template("newsoc.html", errors={}, **values)
