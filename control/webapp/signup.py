import functools
import operator
import re

from flask import Blueprint, render_template, redirect, url_for, request

from srcf.database import Member, Society

from .utils import srcf_db_sess as sess
from . import utils
from .. import jobs

SOC_DESC_RE = re.compile(r'^[\w\s]*$')
SOC_SOCIETY_RE = re.compile(r'^[a-z]*$')
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
        for key in ("society", "description"):
            values[key] = request.form.get(key, "")
        for key in ("admins", "mailinglists"):
            values[key] = request.form.get(key, "").splitlines()
        for key in ("mysql", "postgres"):
            values[key] = bool(request.form.get(key, False))

        errors = {
            "description": SOC_DESC_RE.match(values["description"]) == None,
            "society": SOC_SOCIETY_RE.match(values["society"]) == None,
            "admins": False,
            "mailinglists": False
        }

        expect_admins = len(values["admins"])
        values["admins"] = \
            sess.query(Member) \
                .filter(Member.crsid.in_(values["admins"])) \
                .all()

        if len(values["admins"]) != expect_admins:
            errors["admins"] = True

        if mem not in values["admins"]:
            errors["admins"] = True

        for mailing_list in values["mailinglists"]:
            if not MAILING_LIST_RE.match(mailing_list):
                errors["mailinglists"] = True
                break

        any_error = functools.reduce(operator.or_, errors.values())

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
            "mailinglists": [],
            "mysql": False,
            "postgres": False
        }

        return render_template("newsoc.html", errors={}, **values)
