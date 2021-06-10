from datetime import datetime
import math

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func as sql_func
from werkzeug.exceptions import Forbidden, NotFound

from srcf.controllib.jobs import Job, SocietyJob
import srcf.database
from srcf.database import JobLog

from . import utils
from .utils import srcf_db_sess as sess


bp = Blueprint("admin", __name__)

per_page = 25


@bp.before_request
def before_request():
    utils.auth_admin()


def job_counts():
    job_row = srcf.database.Job
    q = (
        sess.query(job_row.state, sql_func.count(job_row.job_id))
        .group_by(job_row.state)
        .order_by(job_row.state)  # this is the order the enum was defined in, and is what we want.
    )
    return q.all()


@bp.route('/admin')
def home():
    return render_template("admin/home.html", job_counts=job_counts())


@bp.route('/admin/jobs/unapproved', defaults={"state": "unapproved"})
@bp.route('/admin/jobs/queued',     defaults={"state": "queued"})
@bp.route('/admin/jobs/running',    defaults={"state": "running"})
@bp.route('/admin/jobs/done',       defaults={"state": "done"})
@bp.route('/admin/jobs/failed',     defaults={"state": "failed"})
@bp.route('/admin/jobs/withdrawn',  defaults={"state": "withdrawn"})
def view_jobs(state):

    # Best-effort parsing of ?page= falling back to 1 in all error cases
    page = 1
    try:
        page = int(request.args["page"])
    except (KeyError, ValueError):
        pass

    job_row = srcf.database.Job
    jobs = (
        sess.query(job_row)
        .filter(job_row.state == state)
        .order_by(job_row.job_id.desc())
    )
    jobs = [Job.of_row(r) for r in jobs]
    max_pages = int(math.ceil(len(jobs) / float(per_page)))
    jobs = jobs[min(len(jobs), per_page * (page - 1)):min(len(jobs), per_page * page)]
    note_count = dict()
    for j in jobs:
        j.resolve_references(sess)
        note_count[j.job_id] = (
            sess.query(JobLog)
            .filter(JobLog.job_id == j.job_id)
            .filter(JobLog.type == 'note').count()
        )
    return render_template("admin/view_jobs.html", job_counts=job_counts(), state=state, jobs=jobs, note_count=note_count, pages=utils.Pagination(page, max_pages))


@bp.route('/admin/jobs/<int:id>')
def status(id):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)

    log = list(sess.query(JobLog).filter(JobLog.job_id == id).order_by(JobLog.time))
    has_create_log = sess.query(JobLog).filter(JobLog.job_id == id).filter(JobLog.type == 'created').first() is not None
    notes = [x for x in log if x.type == "note"]

    job_home_url = url_for('admin.view_jobs', state=job.state)
    for_society = isinstance(job, SocietyJob)

    owner_in_context = job.owner_crsid
    if for_society:
        owner_in_context = job.society_society

    return render_template("admin/status.html", job=job, notes=notes, log=log, job_home_url=job_home_url,
                           for_society=for_society, owner_in_context=owner_in_context,
                           principal=utils.effective_crsid(), has_create_log=has_create_log)


_actions = {
    "reject": ("rejected", "unapproved", "withdrawn"),
    "approve": ("approved", "unapproved", "queued"),
    "cancel": ("cancelled", "queued", "failed"),
    "abort": ("aborted", "running", "failed"),
    "repeat": ("repeated", "done", "queued"),
    "retry": ("retried", "failed", "queued"),
}


@bp.route('/admin/jobs/<int:id>/<action>')
def set_state(id, action):
    # Move this race control logic to controllib
    try:
        display, old, new = _actions[action]
    except KeyError:
        raise NotFound(action)

    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)
    elif job.state != old:
        raise Forbidden(id)

    sess.add(JobLog(job_id=id, type="progress", level="info", time=datetime.now(),
                    message="Admin state change: job {} by {}".format(display, utils.effective_crsid())))

    message = None
    if new in ("failed", "withdrawn"):
        message = "Job {} by sysadmins".format(display)
    job.set_state(new, message or job.state_message)
    sess.add(job.row)

    return redirect(url_for("admin.view_jobs", state=new))


@bp.route('/admin/jobs/<int:job_id>/notes', methods=["POST"])
def add_note(job_id):
    text = request.form.get("text", "").strip()
    if text:
        sess.add(JobLog(job_id=job_id, type="note", level="info", time=datetime.now(),
                        message="Note added by {}".format(utils.effective_crsid()), raw=text))
        flash("Note successfully added.", "raw")
    return redirect(url_for('admin.status', id=job_id))
