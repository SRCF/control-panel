from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template

from sqlalchemy import func as sql_func

import srcf.database

from .utils import srcf_db_sess as sess
from . import utils
from ..jobs import Job


bp = Blueprint("admin", __name__)


@bp.before_request
def auth():
    # I think the order before_request fns are run in is undefined.
    assert utils.raven.principal

    mem = utils.get_member(utils.raven.principal)
    for soc in mem.societies:
        if soc.society == "srcf-admin":
            return None
    else:
        raise Forbidden

@bp.route('/admin')
@bp.route('/admin/')
def home():
    job_row = srcf.database.Job
    q = sess.query(
            job_row.state,
            sql_func.count(job_row.job_id)
        ) \
        .group_by(job_row.state) \
        .order_by(job_row.state)
        # this is the order the enum was defined in, and is what we want.
    counts = q.all()
    return render_template("admin/home.html", job_counts=counts)

@bp.route('/admin/jobs/unapproved', defaults={"state": "unapproved"})
@bp.route('/admin/jobs/queued',     defaults={"state": "queued"})
@bp.route('/admin/jobs/running',    defaults={"state": "running"})
def view_jobs(state):
    job_row = srcf.database.Job
    jobs = sess.query(job_row) \
                    .filter(job_row.state == state) \
                    .order_by(job_row.job_id)
    # XXX: it would be quite nice to load this with a JOIN, but due to
    # jobs having different arguments and relations this is harder.
    jobs = [Job.of_row(r, sess=sess) for r in jobs]
    return render_template("admin/view_jobs.html", state=state, jobs=jobs)
