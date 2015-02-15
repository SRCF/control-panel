from werkzeug.exceptions import NotFound
from flask import Blueprint, render_template

from . import utils, inspect_services


bp = Blueprint("member", __name__)


@bp.route('/member')
def home():
    crsid = utils.raven.principal
    try:
        mem = utils.get_member(crsid)
    except KeyError:
        raise NotFound

    inspect_services.lookup_all(mem)

    return render_template("member.html", member=mem)
