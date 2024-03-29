from datetime import datetime
import math

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import NotFound

from srcf.controllib.jobs import Job, JobAction, JobActionInvalid, Signup, SocietyJob
from srcf.database import JobLog

from . import utils
from .utils import srcf_db_sess as sess


bp = Blueprint("jobs", __name__)

per_page = 25


@bp.route('/jobs')
def home():
    # Best-effort parsing of ?page= falling back to 1 in all error cases
    page = 1
    try:
        page = int(request.args["page"])
    except (KeyError, ValueError):
        pass

    crsid = utils.effective_crsid()
    jobs = Job.find_by_user(sess, crsid)
    max_pages = int(math.ceil(len(jobs) / float(per_page)))
    jobs = jobs[min(len(jobs), per_page * (page - 1)):min(len(jobs), per_page * page)]
    for job in jobs:
        job.resolve_references(sess)
    return render_template("jobs/home.html", owner_in_context=crsid, jobs=jobs, pages=utils.Pagination(page, max_pages), for_society=False)


@bp.route('/jobs/<name>')
def society_home(name):
    utils.find_mem_society(name)

    # Best-effort parsing of ?page= falling back to 1 in all error cases
    page = 1
    try:
        page = int(request.args["page"])
    except (KeyError, ValueError):
        pass

    jobs = Job.find_by_society(sess, name)
    max_pages = int(math.ceil(len(jobs) / float(per_page)))
    jobs = jobs[min(len(jobs), per_page * (page - 1)):min(len(jobs), per_page * page)]
    for job in jobs:
        job.resolve_references(sess)
    return render_template("jobs/home.html", owner_in_context=name, jobs=jobs, pages=utils.Pagination(page, max_pages), for_society=True)


@bp.route('/jobs/<int:id>')
def status(id):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)

    crsid = utils.effective_crsid()
    if not job.visible_to(crsid):
        raise NotFound(id)

    for_society = isinstance(job, SocietyJob) and job.society is not None
    if job.owner is None:
        owner_in_context = None
        job_home_url = None
    elif for_society:
        owner_in_context = job.society
        job_home_url = url_for('jobs.society_home', name=owner_in_context)
    else:
        owner_in_context = job.owner.crsid
        job_home_url = url_for('jobs.home')

    if not isinstance(job, Signup):
        mem = utils.get_member(crsid)
    else:
        # Signup jobs might be viewed by the new member, who doesn't yet have a
        # DB entry, so get_member(crsid) could fail.  The purpose of this
        # lookup (i.e. to decide whether to show the 'jump to admin view'
        # button) doesn't make sense anyway for a signup job, so just pass None
        # to the template
        mem = None

    return render_template("jobs/status.html", job=job, for_society=for_society, owner_in_context=owner_in_context, job_home_url=job_home_url, member=mem)


@bp.route('/jobs/<int:id>.json')
def status_json(id):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)
    if not job.visible_to(utils.effective_crsid()):
        raise NotFound(id)
    return jsonify({"state": job.state})


@bp.route('/jobs/<int:id>/withdraw')
def withdraw(id):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)

    crsid = utils.effective_crsid()
    if not job.visible_to(crsid):
        raise NotFound(id)

    try:
        job.transition(JobAction.reject, "Job withdrawn by {}".format(crsid))
    except JobActionInvalid:
        flash("Sorry, this job cannot be withdrawn now.", "raw")
        return redirect(url_for("jobs.status", id=id))

    sess.add(JobLog(job_id=id, type="progress", level="info", time=datetime.now(),
                    message="User state change: job withdrawn by {}".format(crsid)))

    if isinstance(job, SocietyJob) and job.society_society is not None:
        return redirect(url_for("jobs.society_home", name=job.society_society))
    else:
        return redirect(url_for("jobs.home"))
