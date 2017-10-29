from contextlib import contextmanager
import subprocess
import sys
import re
import logging

from flask import url_for
from jinja2 import Environment, FileSystemLoader

from srcf import database, pwgen
from srcf.database import queries, Job as db_Job
from srcf.database.schema import Member, Society
from srcf.mail import send_mail
import os
import pwd, grp
import psycopg2
import pymysql

from . import utils


emails = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "emails")))
email_headers = {k: emails.get_template("common/header-{0}.txt".format(k)) for k in ("member", "society")}
email_footer = emails.get_template("common/footer.txt").render()


@contextmanager
def mysql_context(job):
    with open("/root/mysql-root-password", "r") as pwfh:
        rootpw = pwfh.readline().rstrip()
    job.log("Connect to MySQL db")
    conn = pymysql.connect(user="root", host="mysql.internal", passwd=rootpw, db="mysql")
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()

@contextmanager
def pgsql_context(job):
    job.log("Connect to PostgreSQL db")
    # TODO: don't connect to the sysadmins database this way -- it can deadlock with SQLAlchemy.
    # Either allow connections to an alternate database, or connect in a safer way.
    conn = psycopg2.connect(host="postgres.internal", database="sysadmins")
    try:
        yield conn, conn.cursor()
        conn.commit()
    finally:
        conn.close()

def sql_exec(job, cur, desc, sql, *vals):
    job.log(desc)
    try:
        cur.execute(sql, vals)
    except (pymysql.MySQLError, psycopg2.Error) as e:
        raise JobFailed(desc, str(e))


# Borrowed from srcf-memberdb-cli
def find_admins(admin_crsids, sess):
    admins = sess.query(Member)\
            .filter(Member.crsid.in_(admin_crsids))\
            .all()
    found = {x.crsid for x in admins}
    missing = set(admin_crsids) - found
    if missing:
        raise KeyError(list(missing)[0])
    return set(admins)

def subproc_call(job, desc, cmd, stdin=None):
    job.log(desc)
    pipe = subprocess.Popen(cmd, stdin=(subprocess.PIPE if stdin else None), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = pipe.communicate(stdin)
    if pipe.returncode:
        raise JobFailed(desc, out or None)
    if out:
        job.log(desc, "output", raw=out)

def mail_users(target, subject, template, **kwargs):
    target_type = "member" if isinstance(target, Member) else "society"
    to = (target.name if target_type == "member" else target.description, target.email)
    subject = "[SRCF] " + (target.society + ": " if target_type == "society" else "") + subject
    content = "\n\n".join([
        email_headers[target_type].render(target=target),
        emails.get_template(target_type + "/" + template + ".txt").render(target=target, **kwargs),
        email_footer])
    send_mail(to, subject, content, copy_sysadmins=False)

all_jobs = {}

def add_job(cls):
    all_jobs[cls.JOB_TYPE] = cls
    return cls

class JobFailed(Exception):
    def __init__(self, message=None, raw=None):
        self.message = message
        self.raw = raw


class Job(object):
    @staticmethod
    def of_row(row):
        return all_jobs[row.type](row)

    @classmethod
    def find_by_user(cls, sess, crsid):
        job_row = db_Job
        jobs = sess.query(job_row) \
                    .filter(job_row.owner_crsid == crsid) \
                    .order_by(job_row.job_id.desc())
        return [Job.of_row(r) for r in jobs]

    @classmethod
    def find_by_society(cls, sess, name):
        job_row = db_Job
        jobs = sess.query(job_row) \
                    .filter(db_Job.args["society"] == name) \
                    .order_by(job_row.job_id.desc())
        return [Job.of_row(r) for r in jobs]

    @classmethod
    def find(cls, sess, id):
        job = sess.query(database.Job).get(id)
        if not job:
            return None
        else:
            job = cls.of_row(job)
            job.resolve_references(sess)
            return job

    def resolve_references(self, sess):
        """
        Due to jobs having a varying number of arguments, and hstore columns
        mapping strings to strings, sometimes we'll store (say) a string crsid
        for the target of a job (say, adding an admin).

        This function uses `sess` to look up those Members/Societies and
        populate attributes with `srcf.database.*` objects.

        It would be far nice if SQLAlchemy could handle this, even using a JOIN
        where possible, but this sounds like a lot of work.
        """
        pass

    @classmethod
    def create(cls, owner, args, require_approval):
        return cls(database.Job(
            type=cls.JOB_TYPE,
            owner=owner,
            state="unapproved" if require_approval else "queued",
            args=args
        ))

    def log(self, msg="", type="progress", level=logging.DEBUG, raw=None, **kwargs):
        self.logger.log(level, msg, extra={"task": "{0}/{1} {2}".format(self.job_id, self.JOB_TYPE, type),
                                           "job_id": self.job_id, "type": type, "raw": raw}, **kwargs)

    def run(self, sess):
        """Run the job. `self.state` will be set to `done` or `failed`."""
        raise JobFailed("not implemented")

    job_id = property(lambda s: s.row.job_id)
    owner = property(lambda s: s.row.owner)
    owner_crsid = property(lambda s: s.row.owner_crsid)
    state = property(lambda s: s.row.state)
    state_message = property(lambda s: s.row.state_message)

    @state.setter
    def state(s, n): s.row.state = n
    @state_message.setter
    def state_message(s, n): s.row.state_message = n

    def set_state(self, state, message=None):
        self.state = state
        self.state_message = message


@add_job
class Signup(Job):
    JOB_TYPE = 'signup'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, crsid, preferred_name, surname, email, social):
        args = {
            "crsid": crsid,
            "preferred_name": preferred_name,
            "surname": surname,
            "email": email,
            "social": "y" if social else "n"
        }
        try:
            utils.ldapsearch(crsid)
        except KeyError:
            require_approval = True
        else:
            require_approval = False
        return cls.create(None, args, require_approval)

    crsid          = property(lambda s: s.row.args["crsid"])
    preferred_name = property(lambda s: s.row.args["preferred_name"])
    surname        = property(lambda s: s.row.args["surname"])
    email          = property(lambda s: s.row.args["email"])
    social         = property(lambda s: s.row.args["social"] == "y")

    def run(self, sess):
        crsid = self.crsid

        self.log("Sanity check for an existing account for {0}".format(crsid))
        if queries.list_members().get(crsid):
            raise JobFailed(crsid + " is already a user")

        name = (self.preferred_name + " " + self.surname).strip()

        self.log("Create memberdb entry")
        sess.add(Member(crsid=self.crsid,
                        preferred_name=self.preferred_name,
                        surname=self.surname,
                        email=self.email,
                        member=True,
                        user=True))

        sess.commit()

        subproc_call(self, "Add UNIX user", ["adduser", "--disabled-password", "--gecos", name, crsid])
        subproc_call(self, "Set quota", ["set_quota", crsid])

        self.log("Create default .forward file")
        path = "/home/" + crsid + "/.forward"
        f = open(path, "w")
        f.write(self.email + "\n")
        f.close()

        self.log("Set correct permissions on .forward file")
        uid = pwd.getpwnam(crsid).pw_uid
        gid = grp.getgrnam(crsid).gr_gid
        os.chown(path, uid, gid)

        subproc_call(self, "Update Apache groups", ["/usr/local/sbin/srcf-updateapachegroups"])
        ml_entry = '"{name}" <{email}>'.format(name=name, email=self.email)
        subproc_call(self, "Queue mail subscriptions", ["/usr/local/sbin/srcf-enqueue-mlsub",
                                                        "soc-srcf-maintenance:" + ml_entry,
                                                        ("soc-srcf-social:" + ml_entry) if self.social else ""])
        subproc_call(self, "Export memberdb", ["/usr/local/sbin/srcf-memberdb-export"])

    def __repr__(self): return "<Signup {0.crsid}>".format(self)
    def __str__(self): return "Signup: {0.crsid} ({0.preferred_name} {0.surname}, {0.email})".format(self)

@add_job
class ResetUserPassword(Job):
    JOB_TYPE = 'reset_user_password'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.create(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid
        password = pwgen(8)

        subproc_call(self, "Change UNIX password for {0}".format(crsid), ["/usr/sbin/chpasswd"], (crsid + ":").encode("utf-8") + password)
        subproc_call(self, "Rebuild /var/yp", ["make", "-C", "/var/yp"])
        subproc_call(self, "Run descrypt", ["/usr/local/sbin/srcf-descrypt-cron"])

        self.log("Send new password")
        mail_users(self.owner, "SRCF account password reset", "srcf-password", password=password.decode("utf-8"))

    def __repr__(self): return "<ResetUserPassword {0.owner_crsid}>".format(self)
    def __str__(self): return "Reset user password: {0.owner.crsid} ({0.owner.name})".format(self)

@add_job
class UpdateEmailAddress(Job):
    JOB_TYPE = 'update_email_address'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member, email):
        args = {"email": email}
        require_approval = member.danger
        return cls.create(member, args, require_approval)

    email = property(lambda s: s.row.args["email"])

    def __repr__(self): return "<UpdateEmailAddress {0.owner_crsid}>".format(self)
    def __str__(self): return "Update email address: {0.owner.crsid} ({0.owner.email} to {0.email})".format(self)

    def run(self, sess):
        old_email = self.owner.email
        self.log("Update email address")
        self.owner.email = self.email

        self.log("Send confirmation")
        mail_users(self.owner, "Email address updated", "email", old_email=old_email, new_email=self.email)

@add_job
class CreateUserMailingList(Job):
    JOB_TYPE = 'create_user_mailing_list'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member, listname):
        args = {"listname": listname}
        require_approval = member.danger
        return cls.create(member, args, require_approval)

    listname = property(lambda s: s.row.args["listname"])

    def __repr__(self): return "<CreateUserMailingList {0.owner_crsid}-{0.listname}>".format(self)
    def __str__(self): return "Create user mailing list: {0.owner_crsid}-{0.listname}".format(self)

    def run(self, sess):
        full_listname = "{}-{}".format(self.owner, self.listname)
        password = pwgen(8)

        self.log("Sanity check list name")
        if not re.match("^[A-Za-z0-9\-]+$", self.listname) \
        or self.listname.split("-")[-1] in ("admin", "bounces", "confirm", "join", "leave",
                                            "owner", "request", "subscribe", "unsubscribe"):
            raise JobFailed("Invalid list name {}".format(full_listname))

        subproc_call(self, "Create mailing list {0}".format(full_listname),
                     ["sshpass", "newlist", full_listname, self.owner.crsid + "@srcf.net"], password)
        subproc_call(self, "Configure list", ["/usr/sbin/config_list", "-i", "/root/mailman-newlist-defaults", full_listname])
        subproc_call(self, "Generate aliases", ["gen_alias", full_listname])

@add_job
class ResetUserMailingListPassword(Job):
    JOB_TYPE = 'reset_user_mailing_list_password'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member, listname):
        args = {"listname": listname}
        require_approval = member.danger
        return cls.create(member, args, require_approval)

    listname = property(lambda s: s.row.args["listname"])

    def __repr__(self): return "<ResetUserMailingListPassword {0.listname}>".format(self)
    def __str__(self): return "Reset user mailing list password: {0.listname}".format(self)

    def run(self, sess):
        subproc_call(self, "Reset list admins", ["/usr/sbin/config_list", "-v", "-i", "/dev/stdin", self.listname],
                     "owner = ['{0}@srcf.net']".format(self.owner))
        subproc_call(self, "Reset list password", ["/usr/lib/mailman/bin/change_pw", "-l", self.listname])

@add_job
class CreateSociety(Job):
    JOB_TYPE = 'create_society'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.admins = \
                sess.query(database.Member) \
                .filter(database.Member.crsid.in_(self.admin_crsids)) \
                .all()
        if len(self.admins) != len(self.admin_crsids):
            raise KeyError("CreateSociety references admins")

    @classmethod
    def new(cls, member, society, description, admins):
        args = {
            "society": society,
            "description": description,
            "admins": ",".join(a for a in admins),
        }
        return cls.create(member, args, True)

    society      = property(lambda s: s.row.args["society"])
    description  = property(lambda s: s.row.args["description"])
    admin_crsids = property(lambda s: s.row.args["admins"].split(","))

    def run(self, sess):
        self.log("Create memberdb entry")
        sess.add(Society(society=self.society,
                         description=self.description,
                         admins=find_admins(self.admin_crsids, sess)))

        subproc_call(self, "Add group", ["/usr/sbin/addgroup", "--force-badname", self.society])

        for admin in self.admin_crsids:
            subproc_call(self, "Add user {0} to group".format(admin), ["/usr/sbin/adduser", admin, self.society])

            self.log("Create society home symlink for {0}".format(admin))
            try:
                os.symlink("/societies/" + self.society, "/home/" + admin + "/" + self.society)
            except:
                pass

        gid = grp.getgrnam(self.society).gr_gid
        uid = gid + 50000

        subproc_call(self, "Add society user", ["/usr/sbin/adduser", "--force-badname", "--no-create-home",
                                                "--uid", str(uid), "--gid", str(gid), "--gecos", self.description,
                                                "--disabled-password", "--system", self.society])
        subproc_call(self, "Set home directory", ["/usr/sbin/usermod", "-d", "/societies/" + self.society, self.society])

        self.log("Create default directories")
        os.makedirs("/societies/" + self.society + "/public_html", 0o775)
        os.makedirs("/societies/" + self.society + "/cgi-bin", 0o775)

        self.log("Set default directory owners")
        os.chown("/societies/" + self.society + "/public_html", -1, gid)
        os.chown("/societies/" + self.society + "/cgi-bin", -1, gid)

        subproc_call(self, "Update home permissions", ["chmod", "-R", "2775", "/societies/" + self.society])

        self.log("Write subdomain status")
        with open("/societies/srcf-admin/socwebstatus", "a") as myfile:
            myfile.write(self.society + ":subdomain\n")

        subproc_call(self, "Set quota", ["/usr/local/sbin/set_quota", self.society])
        subproc_call(self, "Generate sudoers", ["/usr/local/sbin/srcf-generate-society-sudoers"])
        subproc_call(self, "Export memberdb", ["/usr/local/sbin/srcf-memberdb-export"])

        self.log("Send welcome email")
        newsoc = queries.get_society(self.society)
        mail_users(newsoc, "New shared account created", "signup")

    def __repr__(self): return "<CreateSociety {0.society}>".format(self)
    def __str__(self): return "Create society: {0.society} ({0.description})".format(self)

@add_job
class ChangeSocietyAdmin(Job):
    JOB_TYPE = 'change_society_admin'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = queries.get_society(self.society_society)
        self.target_member = queries.get_member(self.target_member_crsid)

    @classmethod
    def new(cls, requesting_member, society, target_member, action):
        if action not in {"add", "remove"}:
            raise ValueError("action should be 'add' or 'remove'", action)
        args = {
            "society": society.society,
            "target_member": target_member.crsid,
            "action": action
        }
        require_approval = \
                society.danger \
             or target_member.danger \
             or requesting_member.danger \
             or requesting_member == target_member
        return cls.create(requesting_member, args, require_approval)

    society_society     = property(lambda s: s.row.args["society"])
    target_member_crsid = property(lambda s: s.row.args["target_member"])
    action              = property(lambda s: s.row.args["action"])

    def __repr__(self):
        return "<ChangeSocietyAdmin {0.action} {0.society_society} " \
               "{0.target_member_crsid}>".format(self)

    def __str__(self):
        verb = self.action.title()
        prep = "to" if self.action == "add" else "from"
        fmt = "{verb} society admin: {0.target_member.crsid} ({0.target_member.name}) "\
                "{prep} {0.society.society} ({0.society.description})"
        return fmt.format(self, verb=verb, prep=prep)

    def add_admin(self, sess):
        if self.target_member in self.society.admins:
            raise JobFailed("{0.target_member.crsid} is already an admin of {0.society}".format(self))

        # Get the recipient lists before adding because we are sending the new admin a separate email.
        recipients = [(x.name, x.crsid + "@srcf.net") for x in self.society.admins]

        self.society.admins.add(self.target_member)

        subproc_call(self, "Add user to group", ["adduser", self.target_member.crsid, self.society.society])

        target_ln = "/home/{0.target_member.crsid}/{0.society.society}".format(self)
        source_ln = "/societies/{0.society.society}/".format(self)
        if not os.path.exists(target_ln):
            self.log("Create society home symlink")
            os.symlink(source_ln, target_ln)

        self.log("Send confirmation to new member")
        mail_users(self.target_member, "Access granted to " + self.society_society, "add-admin", society=self.society)
        self.log("Send confirmation to the rest")
        adminNames = sorted("{0.name} ({0.crsid})".format(m) for m in self.society.admins)
        mail_users(self.society, "Access granted for " + self.target_member.crsid, "add-admin",
                added=self.target_member, requester=self.owner, admins="\n".join(adminNames))


    def rm_admin(self, sess):
        if self.target_member not in self.society.admins:
            raise JobFailed("{0.target_member.crsid} is not an admin of {0.society.society}".format(self))

        if len(self.society.admins) == 1:
            raise JobFailed("Removing all admins not implemented")

        # Get the recipient lists before removing because we want to notify the user removed
        recipients = [(x.name, x.crsid + "@srcf.net") for x in self.society.admins]

        self.society.admins.remove(self.target_member)
        subproc_call(self, "Remove user from group", ["deluser", self.target_member.crsid, self.society.society])

        target_ln = "/home/{0.target_member.crsid}/{0.society.society}".format(self)
        source_ln = "/societies/{0.society.society}/".format(self)
        if os.path.islink(target_ln) and os.path.samefile(target_ln, source_ln):
            self.log("Remove society home symlink")
            os.remove(target_ln)

        self.log("Send confirmation to remaining admins")
        adminNames = sorted("{0.name} ({0.crsid})".format(m) for m in self.society.admins)
        mail_users(self.society, "Access removed for " + self.target_member.crsid, "remove-admin",
                removed=self.target_member, requester=self.owner, admins="\n".join(adminNames))

    def run(self, sess):
        if self.owner not in self.society.admins:
            raise JobFailed("{0.owner.crsid} is not permitted to change the admins of {0.society.society}".format(self))

        if self.action == "add":
            self.add_admin(sess)
        else:
            self.rm_admin(sess)

@add_job
class CreateSocietyMailingList(Job):
    JOB_TYPE = 'create_society_mailing_list'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = \
            queries.get_society(self.society_society)

    @classmethod
    def new(cls, member, society, listname):
        args = {
            "society": society.society,
            "listname": listname
        }
        require_approval = member.danger or society.danger
        return cls.create(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])
    listname = property(lambda s: s.row.args["listname"])

    def __repr__(self): return "<CreateSocietyMailingList {0.society_society}-{0.listname}>".format(self)
    def __str__(self): return "Create society mailing list: {0.society_society}-{0.listname}".format(self)

    def run(self, sess):
        full_listname = "{}-{}".format(self.society_society, self.listname)
        password = pwgen(8)

        if not re.match("^[A-Za-z0-9\-]+$", self.listname) \
        or self.listname.split("-")[-1] in ("admin", "bounces", "confirm", "join", "leave",
                                            "owner", "request", "subscribe", "unsubscribe"):
            raise JobFailed("Invalid list name {}".format(full_listname))

        subproc_call(self, "Create mailing list {0}".format(full_listname),
                     ["sshpass", "newlist", full_listname, self.owner.crsid + "-admins@srcf.net"], password)
        subproc_call(self, "Configure list", ["/usr/sbin/config_list", "-i", "/root/mailman-newlist-defaults", full_listname])
        subproc_call(self, "Generate aliases", ["gen_alias", full_listname])

@add_job
class ResetSocietyMailingListPassword(Job):
    JOB_TYPE = 'reset_society_mailing_list_password'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = \
            queries.get_society(self.society_society)

    @classmethod
    def new(cls, member, society, listname):
        args = {
            "society": society.society,
            "listname": listname,
        }
        require_approval = member.danger or society.danger
        return cls.create(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])
    listname = property(lambda s: s.row.args["listname"])

    def __repr__(self): return "<ResetSocietyMailingListPassword {0.listname}>".format(self)
    def __str__(self): return "Reset society mailing list password: {0.listname}".format(self)

    def run(self, sess):
        subproc_call(self, "Reset list admins", ["/usr/sbin/config_list", "-v", "-i", "/dev/stdin", self.listname],
                     "owner = ['{0}-admins@srcf.net']".format(self.society_society))
        subproc_call(self, "Reset list password", ["/usr/lib/mailman/bin/change_pw", "-l", self.listname])

# Here be dragons: we trust the value of crsid a *lot* (such that it appears unescaped in SQL queries).
# Quote with backticks and ensure only valid characters (alnum for crsid, alnum + [_-] for society).

@add_job
class CreateMySQLUserDatabase(Job):
    JOB_TYPE = 'create_mysql_user_database'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.create(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid
        assert crsid.isalnum()

        password = pwgen(8)

        with mysql_context(self) as (db, cursor):
            sql_exec(self, cursor, "Create database",         "CREATE DATABASE " + crsid)
            sql_exec(self, cursor, "Grant privileges (base)", "GRANT ALL PRIVILEGES ON `" + crsid + "`.*    to '" + crsid + "'@'%%'")
            sql_exec(self, cursor, "Grant privileges (wild)", "GRANT ALL PRIVILEGES ON `" + crsid + "/%%`.* to '" + crsid + "'@'%%'")
            sql_exec(self, cursor, "Set password",            "SET PASSWORD FOR '" + crsid + "'@'%%' = %s", password)

        self.log("Send password")
        mail_users(self.owner, "MySQL database created", "mysql-create", password=password)

    def __repr__(self): return "<CreateMySQLUserDatabase {0.owner_crsid}>".format(self)
    def __str__(self): return "Create user MySQL database: {0.owner.crsid} ({0.owner.name})".format(self)

@add_job
class ResetMySQLUserPassword(Job):
    JOB_TYPE = 'reset_mysql_user_password'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.create(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid
        assert crsid.isalnum()

        password = pwgen(8)

        with mysql_context(self) as (db, cursor):
            sql_exec(self, cursor, "Reset password", "SET PASSWORD FOR '" + crsid + "'@'%%' = %s", password)

        self.log("Send new password")
        mail_users(self.owner, "MySQL database password reset", "mysql-password", password=password)

    def __repr__(self): return "<ResetMySQLUserPassword {0.owner_crsid}>".format(self)
    def __str__(self): return "Reset user MySQL password: {0.owner.crsid} ({0.owner.name})".format(self)

@add_job
class CreateMySQLSocietyDatabase(Job):
    JOB_TYPE = 'create_mysql_society_database'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = queries.get_society(self.society_society)

    @classmethod
    def new(cls, member, society):
        args = {"society": society.society}
        require_approval = society.danger or member.danger
        return cls.create(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def run(self, sess):
        crsid = self.owner.crsid
        assert crsid.isalnum()
        socname = self.society_society
        assert utils.is_valid_socname(socname)

        password = pwgen(8)
        usrpassword = None

        with mysql_context(self) as (db, cursor):
            sql_exec(self, cursor, "Create society database", "CREATE DATABASE " + socname)

            sql_exec(self, cursor, "Check for existing owner user", "SELECT EXISTS (SELECT DISTINCT User FROM mysql.user WHERE User = %s) AS e", self.owner.crsid)
            if cursor.fetchone()[0] == 0:
                usrpassword = pwgen(8)
                sql_exec(self, cursor, "Set owner user password", "SET PASSWORD FOR " + self.owner.crsid + "@%% = %s", usrpassword)

            sql_exec(self, cursor, "Grant privileges (society, base)", "GRANT ALL PRIVILEGES ON `" +  socname + "`.*   TO '" + socname + "'@'%'")
            sql_exec(self, cursor, "Grant privileges (society, wild)", "GRANT ALL PRIVILEGES ON `" +  socname + "/%`.* TO '" + socname + "'@'%'")
            sql_exec(self, cursor, "Grant privileges (user, base)",    "GRANT ALL PRIVILEGES ON `" +  socname + "`.*   TO '" + self.owner.crsid + "'@'%'")
            sql_exec(self, cursor, "Grant privileges (user, wild)",    "GRANT ALL PRIVILEGES ON `" +  socname + "/%`.* TO '" + self.owner.crsid + "'@'%'")
            sql_exec(self, cursor, "Set society user password",        "SET PASSWORD FOR '" + socname + "'@'%%' = %s", password)

        self.log("Send society password")
        mail_users(self.society, "MySQL database created", "mysql-create", password=password, requester=self.owner)
        if usrpassword:
            self.log("Send owner password")
            mail_users(self.owner, "MySQL database created", "mysql-create", password=usrpassword)

    def __repr__(self): return "<CreateMySQLSocietyDatabase {0.society_society}>".format(self)
    def __str__(self): return "Create society MySQL database: {0.society.society} ({0.society.description})".format(self)

@add_job
class ResetMySQLSocietyPassword(Job):
    JOB_TYPE = 'reset_mysql_society_password'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = queries.get_society(self.society_society)

    @classmethod
    def new(cls, member, society):
        args = {"society": society.society}
        require_approval = society.danger or member.danger
        return cls.create(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def run(self, sess):
        crsid = self.owner.crsid
        assert crsid.isalnum()
        socname = self.society_society
        assert utils.is_valid_socname(socname)

        password = pwgen(8)

        with mysql_context(self) as (db, cursor):
            sql_exec(self, cursor, "Set password", "SET PASSWORD FOR '" + socname + "'@'%%' = %s", password)

        self.log("Send new password")
        mail_users(self.society, "MySQL database password reset", "mysql-password", password=password, requester=self.owner)

    def __repr__(self): return "<ResetMySQLSocietyPassword {0.society_society}>".format(self)
    def __str__(self): return "Reset society MySQL password: {0.society.society} ({0.society.description})".format(self)

@add_job
class CreatePostgresUserDatabase(Job):
    JOB_TYPE = 'create_postgres_user_database'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.create(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid
        assert crsid.isalnum()

        usercreated = False
        password = pwgen(8)
        dbcreated = False

        with pgsql_context(self) as (db, cursor):
            sql_exec(self, cursor, "Check for existing user", "SELECT usename FROM pg_shadow WHERE usename = %s", crsid)
            results = cursor.fetchall()

            if len(results) == 0:
                sql_exec(self, cursor, "Create user", "CREATE USER " + crsid + " ENCRYPTED PASSWORD %s NOCREATEDB NOCREATEUSER", password)
                usercreated = True
            else:
                sql_exec(self, cursor, "(Re-)enable user logins", "ALTER ROLE " + crsid + " LOGIN")

            sql_exec(self, cursor, "Check for existing database", "SELECT datname FROM pg_database WHERE datname = %s", crsid)
            results = cursor.fetchall()

            if len(results) == 0:
                # CREATE DATABASE not supported inside a transaction
                cursor.execute("COMMIT")
                sql_exec(self, cursor, "Create database", "CREATE DATABASE " + crsid + " OWNER " + crsid)
                cursor.execute("BEGIN")
                dbcreated = True

            if not dbcreated and not usercreated:
                raise JobFailed(crsid + " already has a functioning database")

        self.log("Send new password")
        mail_users(self.owner, "PostgreSQL database created", "postgres-create", password=password)

    def __repr__(self): return "<CreatePostgresUserDatabase {0.owner_crsid}>".format(self)
    def __str__(self): return "Create user PostgreSQL database: {0.owner.crsid} ({0.owner.name})".format(self)

@add_job
class ResetPostgresUserPassword(Job):
    JOB_TYPE = 'reset_postgres_user_password'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.create(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid
        assert crsid.isalnum()

        password = pwgen(8)

        with pgsql_context(self) as (db, cursor):
            sql_exec(self, cursor, "Check for existing user", "SELECT usename FROM pg_shadow WHERE usename = %s", crsid)
            results = cursor.fetchall()

            if len(results) == 0:
                raise JobFailed(crsid + " does not have a Postgres user")

            sql_exec(self, cursor, "Reset password", "ALTER USER " + crsid + " PASSWORD %s", password)

        self.log("Send new password")
        mail_users(self.owner, "PostgreSQL database password reset", "postgres-password", password=password)

    def __repr__(self): return "<ResetPostgresUserPassword {0.owner_crsid}>".format(self)
    def __str__(self): return "Reset user PostgreSQL password: {0.owner.crsid} ({0.owner.name})".format(self)


@add_job
class CreatePostgresSocietyDatabase(Job):
    JOB_TYPE = 'create_postgres_society_database'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = queries.get_society(self.society_society)

    @classmethod
    def new(cls, member, society):
        args = {"society": society.society}
        require_approval = society.danger or member.danger
        return cls.create(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def run(self, sess):
        crsid = self.owner.crsid
        assert crsid.isalnum()
        socname = self.society_society
        assert utils.is_valid_socname(socname)

        usercreated = False
        userpassword = pwgen(8)
        socusercreated = False
        socpassword = pwgen(8)
        dbcreated = False

        with pgsql_context(self) as (db, cursor):
            sql_exec(self, cursor, "Check for existing owner user", "SELECT usename FROM pg_shadow WHERE usename = %s", crsid)
            results = cursor.fetchall()

            if len(results) == 0:
                sql_exec(self, cursor, "Create owner user", "CREATE USER " + crsid + " ENCRYPTED PASSWORD %s NOCREATEDB NOCREATEUSER", userpassword)
                usercreated = True
            else:
                sql_exec(self, cursor, "(Re-)enable owner user logins", "ALTER ROLE " + crsid + " LOGIN")

            sql_exec(self, cursor, "Check for existing society user", "SELECT usename FROM pg_shadow WHERE usename = '" + socname + "'")
            results = cursor.fetchall()

            if len(results) == 0:
                sql_exec(self, cursor, "Create society user", "CREATE USER " + socname + " ENCRYPTED PASSWORD %s NOCREATEDB NOCREATEUSER", socpassword)
                usercreated = True
            else:
                sql_exec(self, cursor, "(Re-)enable society user logins", "ALTER ROLE " + socname + " LOGIN")

            sql_exec(self, cursor, "Check for existing society database", "SELECT datname FROM pg_database WHERE datname = %s", socname)
            results = cursor.fetchall()

            if len(results) == 0:
                # CREATE DATABASE not supported inside a transaction
                cursor.execute("COMMIT")
                sql_exec(self, cursor, "Create society database", "CREATE DATABASE " + socname + " OWNER " + socname)
                cursor.execute("BEGIN")
                dbcreated = True

            self.log("Grant owner access")
            sql_exec(self, cursor, "Grant owner access", "GRANT " + socname + " TO " + crsid)

            if not dbcreated and not usercreated and not socusercreated:
                raise JobFailed(socname + " already has a functioning database")

        self.log("Send society password")
        mail_users(self.society, "PostgreSQL database created", "postgres-create", password=socpassword, requester=self.owner)
        if usercreated:
            self.log("Send owner password")
            mail_users(self.owner, "PostgreSQL database created", "postgres-create", password=userpassword)

    def __repr__(self): return "<CreatePostgresSocietyDatabase {0.society_society}>".format(self)
    def __str__(self): return "Create society PostgreSQL database: {0.society.society} ({0.society.description})".format(self)

@add_job
class ResetPostgresSocietyPassword(Job):
    JOB_TYPE = 'reset_postgres_society_password'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = queries.get_society(self.society_society)

    @classmethod
    def new(cls, member, society):
        args = {"society": society.society}
        require_approval = society.danger or member.danger
        return cls.create(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def run(self, sess):
        crsid = self.owner.crsid
        assert crsid.isalnum()
        socname = self.society_society
        assert utils.is_valid_socname(socname)

        password = pwgen(8)

        with pgsql_context(self) as (db, cursor):
            sql_exec(self, cursor, "Check for existing user", "SELECT usename FROM pg_shadow WHERE usename = %s", socname)
            results = cursor.fetchall()

            if len(results) == 0:
                raise JobFailed(socname + " does not have a Postgres user")

            sql_exec(self, cursor, "Reset password", "ALTER USER " + socname + " PASSWORD %s", password)

        self.log("Send new password")
        mail_users(self.society, "PostgreSQL database password reset", "postgres-password", password=password, requester=self.owner)

    def __repr__(self): return "<ResetPostgresSocietyPassword {0.society_society}>".format(self)
    def __str__(self): return "Reset society PostgreSQL password: {0.society.society} ({0.society.description})".format(self)
