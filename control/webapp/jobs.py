from werkzeug.exceptions import NotFound
from flask import Blueprint, render_template, request, url_for

from .utils import srcf_db_sess as sess
from . import utils
from srcf.controllib.jobs import Job, Society, SocietyJob
from srcf.database import queries

import math

import sys


bp = Blueprint("jobs", __name__)


per_page = 25

@bp.route('/jobs')
def home():
    page = int(request.args["page"]) if "page" in request.args else 1
    jobs = Job.find_by_user(sess, utils.raven.principal)
    max_pages = int(math.ceil(len(jobs) / float(per_page)))
    jobs = jobs[min(len(jobs), per_page * (page - 1)):min(len(jobs), per_page * page)]
    for job in jobs: job.resolve_references(sess)
    return render_template("jobs/home.html", owner_in_context=utils.raven.principal, jobs=jobs, page=page, max_pages=max_pages, for_society=False)

@bp.route('/jobs/<name>')
def society_home(name):
    _, society = utils.find_mem_society(name)
    page = int(request.args["page"]) if "page" in request.args else 1
    jobs = Job.find_by_society(sess, name)
    max_pages = int(math.ceil(len(jobs) / float(per_page)))
    jobs = jobs[min(len(jobs), per_page * (page - 1)):min(len(jobs), per_page * page)]
    for job in jobs: job.resolve_references(sess)
    return render_template("jobs/home.html", owner_in_context=name, jobs=jobs, page=page, max_pages=max_pages, for_society=True)

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

@bp.route('/jobs/<int:id>')
def status(id):
    job = Job.find(sess, id)
    if not job:
        raise NotFound(id)

    if not job.visible_to(utils.raven.principal):
        raise NotFound(id)

    for_society = isinstance(job, SocietyJob) and job.society != None
    if job.owner is None:
        owner_in_context = None
        job_home_url = None
    elif for_society:
        owner_in_context = job.society
        job_home_url = url_for('jobs.society_home', name=owner_in_context)
    else:
        owner_in_context = job.owner.crsid
        job_home_url = url_for('jobs.home')

    return render_template("jobs/status.html", job=job, for_society=for_society, owner_in_context=owner_in_context, job_home_url=job_home_url)
