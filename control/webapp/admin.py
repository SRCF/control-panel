from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template, request, redirect, url_for

from sqlalchemy import func as sql_func

import srcf.database

import math

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

per_page = 25

@bp.route('/admin/jobs/unapproved', defaults={"state": "unapproved"})
@bp.route('/admin/jobs/queued',     defaults={"state": "queued"})
@bp.route('/admin/jobs/running',    defaults={"state": "running"})
@bp.route('/admin/jobs/done',       defaults={"state": "done"})
@bp.route('/admin/jobs/failed',     defaults={"state": "failed"})
def view_jobs(state):
    page = int(request.args["page"]) if "page" in request.args else 1
    job_row = srcf.database.Job
    jobs = sess.query(job_row) \
                    .filter(job_row.state == state) \
                    .order_by(job_row.job_id)
    jobs = [Job.of_row(r) for r in jobs]
    max_pages = int(math.ceil(len(jobs) / float(per_page)))
    jobs = jobs[min(len(jobs), per_page * (page - 1)):min(len(jobs), per_page * page)]
    for j in jobs: j.resolve_references(sess)
    return render_template("admin/view_jobs.html", state=state, jobs=jobs, page=page, max_pages=max_pages)

@bp.route('/admin/jobs/<int:id>')
def status(id):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)

    return render_template("jobs/status.html", job=job)

@bp.route('/admin/jobs/<int:id>/approve', defaults={"approved": True})
@bp.route('/admin/jobs/<int:id>/reject',  defaults={"approved": False})
def approve(id, approved):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)
    if not job.state == "unapproved":
        raise Forbidden(id)

    if approved:
        job.set_state("queued")
    else:
        job.set_state("failed", "Job rejected by sysadmin")

    sess.add(job.row)
    sess.commit()

    return redirect(url_for("admin.view_jobs", state="unapproved"))
