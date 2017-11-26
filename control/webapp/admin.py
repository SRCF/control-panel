from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template, request, redirect, url_for

from sqlalchemy import func as sql_func

import srcf.database

import math

from .utils import srcf_db_sess as sess
from . import utils
from srcf.controllib.jobs import Job


bp = Blueprint("admin", __name__)

@bp.before_request
def before_request():
    utils.auth_admin()

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
                    .order_by(job_row.job_id.desc())
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

@bp.route('/admin/jobs/<int:id>/approve', defaults={"state": "unapproved", "approved": True})
@bp.route('/admin/jobs/<int:id>/reject',  defaults={"state": "unapproved", "approved": False})
@bp.route('/admin/jobs/<int:id>/cancel',  defaults={"state": "queued"})
@bp.route('/admin/jobs/<int:id>/abort',   defaults={"state": "running"})
def set_state(id, state, approved=False):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)
    if not job.state == state:
        raise Forbidden(id)

    if approved:
        job.set_state("queued")
    else:
        msg = job.state_message or "Job {0} by sysadmin".format({"unapproved": "rejected",
                                                                 "queued": "cancelled",
                                                                 "running": "aborted"}[state])
        job.set_state("failed", msg)

    sess.add(job.row)

    return redirect(url_for("admin.view_jobs", state=state))
