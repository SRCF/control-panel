from __future__ import print_function

import sys
import os
import select
import traceback
import logging
import platform
import subprocess

import psycopg2.extensions

import sqlalchemy.orm
import sqlalchemy.sql.expression
import sqlalchemy.ext.compiler

from srcf import database

from . import jobs
from .postgresqlhandler import PostgreSQLHandler


logger = logging.getLogger("control.job_runner")
logger.setLevel(logging.DEBUG)
logger.addHandler(PostgreSQLHandler({"database": "sysadmins"}))

runner_id_string = "{} {}".format(platform.node(), os.getpid())


RUNNER_LOCK_NUM = 0x366636F6E7472

pg_try_advisory_lock = sqlalchemy.sql.expression.func.pg_try_advisory_lock

class DatabaseLocked(Exception): pass


class Listen(sqlalchemy.sql.expression.Executable,
             sqlalchemy.sql.expression.ClauseElement):
    def __init__(self, channel):
        self.channel = channel

    def __repr__(self):
        return "<Listen {}>".format(self.channel)

@sqlalchemy.ext.compiler.compiles(Listen, 'postgresql')
def compile_listen(element, compiler, **kw):
    return "LISTEN {}".format(element.channel)


def connect():
    # By explicitly creating a connection, and not using the pool, the
    # connection should persist for the lifetime of the process (it won't
    # be closed after each .commit()), and therefore hold the session level
    # lock.
    conn = database.engine.connect()
    conn.detach()
    with conn.begin():
        row, = conn.execute(pg_try_advisory_lock(RUNNER_LOCK_NUM))
        if not row[0]: raise DatabaseLocked

        conn.execute(Listen("jobs_insert"))

    sess = sqlalchemy.orm.Session(bind=conn)
    database.queries.disable_automatic_session(and_use_this_one_instead=sess)
    return conn, sess

def notifications(conn):
    # get the underlying psycopg2 conn
    conn = conn.connection

    while True:
        if conn.status != psycopg2.extensions.STATUS_READY:
            raise RuntimeError("Notifications cannot be recieved "
                               "if a transaction is left open")

        select.select([conn], [], [], 600)
        conn.poll()

        while conn.notifies:
            notify = conn.notifies.pop()
            yield int(notify.payload)

def queued_jobs(conn, sess):
    """
    Yields a list of job ids.

    Liable to yield IDs twice.

    Does not leave a transaction open; moreover, requires that you commit
    your transactions (or notifications won't be received)
    """

    # We're using the advisory lock to protect us against other
    # job runners; not transactions (indeed, transactions would be
    # insufficient).

    # First, go through jobs added while the runner was offline

    existing = \
        sess.query(database.Job) \
        .filter(database.Job.state == "queued") \
        .all()

    existing_ids = [e.job_id for e in existing]
    del existing

    sess.commit()

    for i in existing_ids:
        yield i

    del existing_ids

    # And listen for new jobs...
    # It's possible that an ID was yielded twice; this is not a problem.

    for n in notifications(conn):
        yield n

def main():
    conn, sess = connect()
    for i in queued_jobs(conn, sess):
        job = jobs.Job.find(id=i, sess=sess)
        if job.state != "queued":
            sess.rollback()
            continue

        job.logger = logger

        job.log("Running (host: {0})".format(runner_id_string), "started", logging.INFO)
        job.set_state("running", "Running (host: {0})".format(runner_id_string))
        sess.add(job.row)
        sess.commit()

        run_state = "failed"
        run_message = None

        try:
            run_message = job.run(sess=sess) or "Completed"
            run_state = "done"
            job.log(run_message, "done", logging.INFO)

        except jobs.JobFailed as e:
            run_message = e.message or "Aborted"
            job.log(run_message, "failed", logging.WARNING, e.raw)

        except Exception as e:
            job.log("Unhandled exception", "failed", logging.ERROR, traceback.format_exc(), exc_info=1)

            # rollback
            sess.rollback()
            job = jobs.Job.find(id=i, sess=sess)

            exc = traceback.format_exception_only(*sys.exc_info()[:2])[0].strip()
            run_message = exc

        job.set_state(run_state, run_message)
#        job.mail_current_state_to_sysadmins() # need to implement this
        sess.add(job.row)
        sess.commit()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting job runner (host: {0})".format(runner_id_string))
    try:
        main()
    except KeyboardInterrupt:
        pass
    except:
        logger.exception("Unhandled exception")
        raise
