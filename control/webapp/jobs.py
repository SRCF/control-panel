from werkzeug.exceptions import NotFound
from flask import Blueprint, render_template, request

from .utils import srcf_db_sess as sess
from . import utils
from ..jobs import Job

import math


bp = Blueprint("jobs", __name__)


per_page = 25

@bp.route('/jobs')
def home():
    page = int(request.args["page"]) if "page" in request.args else 1
    jobs = Job.of_user(sess, utils.raven.principal)
    max_pages = int(math.ceil(len(jobs) / float(per_page)))
    jobs = jobs[min(len(jobs), per_page * (page - 1)):min(len(jobs), per_page * page)]
    for job in jobs: job.resolve_references(sess)
    return render_template("jobs/home.html", crsid=utils.raven.principal, jobs=jobs, page=page, max_pages=max_pages)

@bp.route('/jobs/<int:id>')
def status(id):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)

    # as a special case, handle signup Jobs (which have no "owner")
    can_view = \
           (job.owner and job.owner.crsid == utils.raven.principal)            \
        or (job.JOB_TYPE == "signup" and job.crsid == utils.raven.principal)

    if not can_view:
        raise NotFound(id)

    return render_template("jobs/status.html", job=job)
