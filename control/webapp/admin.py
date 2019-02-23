from werkzeug.exceptions import NotFound, Forbidden
from flask import Blueprint, render_template, request, redirect, url_for

from sqlalchemy import func as sql_func

import srcf.database

import math
from binascii import unhexlify
from datetime import datetime

from .utils import srcf_db_sess as sess
from . import utils
from srcf.controllib.jobs import Job, SocietyJob
from srcf.database import JobLog


bp = Blueprint("admin", __name__)

@bp.before_request
def before_request():
    utils.auth_admin()

def job_counts():
    job_row = srcf.database.Job
    q = sess.query(
            job_row.state,
            sql_func.count(job_row.job_id)
        ) \
        .group_by(job_row.state) \
        .order_by(job_row.state)
        # this is the order the enum was defined in, and is what we want.
    return q.all()


@bp.route('/admin')
def home():
    return render_template("admin/home.html", job_counts=job_counts())

per_page = 25

@bp.route('/admin/jobs/unapproved', defaults={"state": "unapproved"})
@bp.route('/admin/jobs/queued',     defaults={"state": "queued"})
@bp.route('/admin/jobs/running',    defaults={"state": "running"})
@bp.route('/admin/jobs/done',       defaults={"state": "done"})
@bp.route('/admin/jobs/failed',     defaults={"state": "failed"})
def view_jobs(state):

    # Best-effort parsing of ?page= falling back to 1 in all error cases
    page = 1
    try:
        page = int(request.args["page"])
    except KeyError, ValueError:
        pass

    job_row = srcf.database.Job
    jobs = sess.query(job_row) \
                    .filter(job_row.state == state) \
                    .order_by(job_row.job_id.desc())
    jobs = [Job.of_row(r) for r in jobs]
    max_pages = int(math.ceil(len(jobs) / float(per_page)))
    jobs = jobs[min(len(jobs), per_page * (page - 1)):min(len(jobs), per_page * page)]
    for j in jobs: j.resolve_references(sess)
    return render_template("admin/view_jobs.html", job_counts=job_counts(), state=state, jobs=jobs, pages=utils.Pagination(page, max_pages))

@bp.route('/admin/jobs/<int:id>')
def status(id):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)

    log = list(sess.query(JobLog).filter(JobLog.job_id == id).order_by(JobLog.time))

    job_home_url = url_for('admin.view_jobs', state=job.state)
    for_society = isinstance(job, SocietyJob) and job.owner.crsid != utils.raven.principal
    owner_in_context = job.society_society if isinstance(job, SocietyJob) else job.owner_crsid

    return render_template("admin/status.html", job=job, log=log, job_home_url=job_home_url,
                           for_society=for_society, owner_in_context=owner_in_context, unhexlify=unhexlify)

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

    log = JobLog(job_id=id, type="progress", level="info", time=datetime.now(),
                 message="Job {0} by sysadmins".format({"unapproved": "approved" if approved else "rejected",
                                                        "queued": "cancelled",
                                                        "running": "aborted"}[state]))
    if approved:
        job.set_state("queued")
    else:
        job.set_state("failed", job.state_message or log.message)

    sess.add(log)
    sess.add(job.row)

    return redirect(url_for("admin.view_jobs", state=state))
