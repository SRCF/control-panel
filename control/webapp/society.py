from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template

from . import utils, inspect_services


bp = Blueprint("society", __name__)


@bp.route('/societies/<society>')
def society(society):
    crsid = utils.raven.principal
    try:
        mem = utils.get_member(crsid)
        soc = utils.get_society(society)
    except KeyError:
        raise NotFound
    if mem not in soc.admins:
        raise Forbidden

    inspect_services.lookup_all(mem)
    inspect_services.lookup_all(soc)

    return render_template("society.html", member=mem, society=soc)
