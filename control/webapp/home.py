from flask import Blueprint, render_template, redirect, url_for

from . import utils, inspect_services


bp = Blueprint("home", __name__)


@bp.route('/')
def home():
    crsid = utils.raven.principal

    try:
        mem = utils.get_member(crsid)
    except KeyError:
        return redirect(url_for('signup.signup'))

    inspect_services.lookup_all(mem, fast=True)
    for soc in mem.societies:
        inspect_services.lookup_all(soc, fast=True)

    return render_template("home.html", member=mem)
