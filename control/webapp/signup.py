import functools
import operator

from flask import Blueprint, render_template, redirect, url_for, request

from .utils import srcf_db_sess as sess
from . import utils
from .. import jobs


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
        for key in ("preferred_name", "surname", "email"):
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
            return redirect(url_for('job_status.status', id=j.row.job_id))

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
            "social": True
        }

        return render_template("signup.html", crsid=crsid, errors={}, **values)
