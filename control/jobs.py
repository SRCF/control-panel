import subprocess
import sys

from flask import url_for
from jinja2 import Environment, FileSystemLoader

from srcf import database, pwgen
from srcf.database import queries, Job as db_Job
from srcf.database.schema import Member
from srcf.mail import mail_sysadmins, send_mail
import os
import pwd, grp
import MySQLdb

emails = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "emails")))
email_headers = {k: emails.get_template("common/header-{0}.txt".format(k)) for k in ("member", "society")}
email_footer = emails.get_template("common/footer.txt").render()

def mysql_conn():
    with open("/root/mysql-root-password", "r") as pwfh:
        rootpw = pwfh.readline().rstrip()
    return MySQLdb.connect(user="root", host="localhost", passwd=rootpw, db="mysql")

def postgres_conn():
    # Warning: don't connect to sysadmins database this way -- it can deadlock with SQLAlchemy.
    return pgdb.connect(database="template1")

def subproc_check_multi(*tasks):
    for desc, task in tasks:
        try:
            subprocess.check_call(task)
        except subprocess.CalledProcessError:
            raise JobFailed("Failed at " + desc)

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
    def __init__(self, message=None):
        self.message = message


class Job(object):
    @staticmethod
    def of_row(row):
        return all_jobs[row.type](row)

    @classmethod
    def of_user(cls, sess, crsid):
        job_row = db_Job
        jobs = sess.query(job_row) \
                    .filter(job_row.owner_crsid == crsid) \
                    .order_by(job_row.job_id)
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
    def store(cls, owner, args, require_approval=False):
        job = cls(database.Job(
            type=cls.JOB_TYPE,
            owner=owner,
            state="unapproved" if require_approval else "queued",
            args=args
        ))

        if require_approval:
            old_LOGNAME = os.environ.get("LOGNAME")
            os.environ["LOGNAME"] = "sysadmins" # TODO: this works for the wrong reasons
            job.mail_current_state_to_sysadmins()
            if old_LOGNAME:
                os.environ["LOGNAME"] = old_LOGNAME
            else:
                del os.environ["LOGNAME"]

        return job

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

    def mail_current_state_to_sysadmins(self):
        if self.state == "unapproved":
            body = "You can approve or reject the job here: {0}" \
                    .format(url_for("admin.view_jobs", state="unapproved", _external=True))
        elif self.state_message is not None:
            body = self.state_message
        else:
            body = "This space is intentionally left blank."

        subject = "[Control Panel] Job #{0.job_id} {0.state} -- {0}".format(self)
        mail_sysadmins(subject, body)


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
        # TODO: this check fails unsafe; what if the finger output format changes?
        res = subprocess.check_output(["finger", crsid + "@hermes.cam.ac.uk"])
        require_approval = ("no such user" in res) or ("cancelled" in res)
        return cls.store(None, args, require_approval)

    crsid          = property(lambda s: s.row.args["crsid"])
    preferred_name = property(lambda s: s.row.args["preferred_name"])
    surname        = property(lambda s: s.row.args["surname"])
    email          = property(lambda s: s.row.args["email"])
    social         = property(lambda s: s.row.args["social"] == "y")

    def run(self, sess):
        crsid = self.crsid

        if queries.list_members().get(crsid):
            raise JobFailed(crsid + " is already a user")

        name = (self.preferred_name + " " + self.surname).strip()

        # TODO: don't shell out to srcf-memberdb-cli!
        subproc_check_multi(
            ("add to memberdb", ["/usr/local/sbin/srcf-memberdb-cli", "member", crsid, "--member", "--user", preferred_name, surname, email]),
            ("add user", ["adduser", "--disabled-password", "--gecos", name, crsid]),
            ("set quota", ["set_quota", crsid]))

        path = "/home/" + crsid + "/.forward"
        f = open(path, "w")
        f.write(self.email + "\n")
        f.close()

        uid = pwd.getpwnam(crsid).pw_uid
        gid = grp.getgrnam(crsid).gr_gid
        os.chown(path, uid, gid)

        ml_entry = '"{name}" <{email}>'.format(name=name, email=self.email)
        subproc_check_multi(
            ("Apache groups", ["/usr/local/sbin/srcf-updateapachegroups"]),
            ("queue mail subscriptions", ["/usr/local/sbin/srcf-enqueue-mlsub", "soc-srcf-maintenance:" + entry, ("soc-srcf-social:" + entry) if social else ""]),
            ("export memberdb", ["/usr/local/sbin/srcf-memberdb-export"]))

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
        return cls.store(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid
        password = pwgen(8)

        pipe = subprocess.Popen(["/usr/sbin/chpasswd"], stdin=subprocess.PIPE)
        pipe.communicate(crsid + ":" + password)
        pipe.stdin.close()

        subproc_check_multi(
            ("make", ["make", "-C", "/var/yp"]),
            ("descrypt", ["/usr/local/sbin/srcf-descrypt-cron"]))

        mail_users(self.owner, "SRCF account password reset", "srcf-password", password=password)

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
        return cls.store(member, args, require_approval)

    email = property(lambda s: s.row.args["email"])

    def __repr__(self): return "<UpdateEmailAddress {0.owner_crsid}>".format(self)
    def __str__(self): return "Update email address: {0.owner.crsid} ({0.owner.email} to {0.email})".format(self)

    def run(self, sess):
        old_email = self.owner.email
        self.owner.email = self.email
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
        return cls.store(member, args, require_approval)

    listname = property(lambda s: s.row.args["listname"])

    def __repr__(self): return "<CreateUserMailingList {0.owner_crsid}-{0.listname}>".format(self)
    def __str__(self): return "Create user mailing list: {0.owner_crsid}-{0.listname}".format(self)

    def run(self, sess):

        full_listname = "{}-{}".format(self.owner, self.listname)

        import re
        if not re.match("^[A-Za-z0-9\-]+$", self.listname) \
        or self.listname.split("-")[-1] in ("admin", "bounces", "confirm", "join", "leave",
                                            "owner", "request", "subscribe", "unsubscribe"):
            raise JobFailed("Invalid list name {}".format(full_listname))

        # XXX DanielRichman: see other
        if "/usr/lib/mailman" not in sys.path:
            sys.path.append("/usr/lib/mailman")
        import Mailman.Utils
        newlist = subprocess.Popen('/usr/local/bin/local_pwgen | sshpass newlist "%s" "%s" '
                        '| grep -v "Hit enter to notify.*"'
                        % (full_listname, self.owner.crsid + "@srcf.net"), shell=True)
        newlist.wait()
        if newlist.returncode != 0:
            raise JobFailed("Failed at new list")

        subproc_check_multi(
            ("config list", ["/usr/sbin/config_list", "-i", "/root/mailman-newlist-defaults", full_listname]),
            ("generate alias", ["gen_alias", full_listname]))

@add_job
class ResetUserMailingListPassword(Job):
    JOB_TYPE = 'reset_user_mailing_list_password'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member, listname):
        args = {"listname": listname}
        require_approval = member.danger
        return cls.store(member, args, require_approval)

    listname = property(lambda s: s.row.args["listname"])

    def __repr__(self): return "<ResetUserMailingListPassword {0.listname}>".format(self)
    def __str__(self): return "Reset user mailing list password: {0.listname}".format(self)

    def run(self, sess):

        resetadmins = subprocess.check_output(["/usr/sbin/config_list", "-o", "-", self.listname])
        if "owner =" not in resetadmins:
            raise JobFailed("Failed at reset admins")
        newpasswd = subprocess.check_output(["/usr/lib/mailman/bin/change_pw", "-l", self.listname])
        if "New {} password".format(self.listname) not in newpasswd:
            raise JobFailed("Failed at new password")

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
        return cls.store(member, args)

    society      = property(lambda s: s.row.args["society"])
    description  = property(lambda s: s.row.args["description"])
    admin_crsids = property(lambda s: s.row.args["admins"].split(","))

    def run(self, sess):
        society = self.society
        description = self.description
        admin_crsids = self.admin_crsids

        # TODO: don't shell out to srcf-memberdb-cli!
        subproc_check_multi(
            ("add to memberdb", ["/usr/local/sbin/srcf-memberdb-cli", "society", society, "insert", description] + admin_crsids),
            ("add group", ["/usr/sbin/addgroup", "--force-badname", society]))

        for admin in admin_crsids:
            subproc_check_multi(("add user " + admin, ["/usr/sbin/adduser", admin, society]))

            try:
                os.symlink("/societies/" + society, "/home/" + admin + "/" + society)
            except:
                pass

        gid = grp.getgrnam(society).gr_gid
        uid = gid + 50000

        subproc_check_multi(
            ("add user", ["/usr/sbin/adduser", "--force-badname", "--no-create-home", "--uid", str(uid), "--gid", str(gid), "--gecos", description, "--disabled-password", "--system", society]),
            ("set home", ["/usr/sbin/usermod", "-d", "/societies/" + society, society]))

        os.makedirs("/societies/" + society + "/public_html", 0775)
        os.makedirs("/societies/" + society + "/cgi-bin", 0775)

        os.chown("/societies/" + society + "/public_html", -1, gid)
        os.chown("/societies/" + society + "/cgi-bin", -1, gid)

        subproc_check_multi(("chmod home", ["chmod", "-R", "2775", "/societies/" + society]))

        with open("/societies/srcf-admin/socwebstatus", "a") as myfile:
            myfile.write(society + ":subdomain\n")

        subproc_check_multi(
            ("set quota", ["/usr/local/sbin/set_quota", society]),
            ("generate sudoers", ["/usr/local/sbin/srcf-generate-society-sudoers"]),
            ("memberdb export", ["/usr/local/sbin/srcf-memberdb-export"]))

        newsoc = queries.get_society(society)
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
        return cls.store(requesting_member, args, require_approval)

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

        subproc_check_multi(("add user", ["adduser", self.target_member.crsid, self.society.society]))

        target_ln = "/home/{0.target_member.crsid}/{0.society.society}".format(self)
        source_ln = "/societies/{0.society.society}/".format(self)
        if not os.path.exists(target_ln):
            os.symlink(source_ln, target_ln)

        mail_users(self.target_member, "Access granted to " + self.society_society, "add-admin", society=self.society)
        mail_users(self.society, "Access granted for " + self.target_member.crsid, "add-admin",
                added=self.target_member, requester=self.requesting_member)


    def rm_admin(self, sess):
        if self.target_member not in self.society.admins:
            raise JobFailed("{0.target_member.crsid} is not an admin of {0.society.society}".format(self))

        if len(self.society.admins) == 1:
            raise JobFailed("removing all admins not implemented")

        # Get the recipient lists before removing because we want to notify the user removed
        recipients = [(x.name, x.crsid + "@srcf.net") for x in self.society.admins]

        self.society.admins.remove(self.target_member)
        subproc_check_multi(("del user", ["deluser", self.target_member.crsid, self.society.society]))

        target_ln = "/home/{0.target_member.crsid}/{0.society.society}".format(self)
        source_ln = "/societies/{0.society.society}/".format(self)
        if os.path.islink(target_ln) and os.path.samefile(target_ln, source_ln):
            os.remove(target_ln)

        mail_users(self.society, "Access removed for " + self.target_member.crsid, "remove-admin",
                removed=self.target_member, requester=self.requesting_member)

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
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])
    listname = property(lambda s: s.row.args["listname"])

    def __repr__(self): return "<CreateSocietyMailingList {0.society_society}-{0.listname}>".format(self)
    def __str__(self): return "Create society mailing list: {0.society_society}-{0.listname}".format(self)

    def run(self, sess):

        full_listname = "{}-{}".format(self.society_society, self.listname)

        import re
        if not re.match("^[A-Za-z0-9\-]+$", self.listname) \
        or self.listname.split("-")[-1] in ("admin", "bounces", "confirm", "join", "leave",
                                            "owner", "request", "subscribe", "unsubscribe"):
            raise JobFailed("Invalid list name {}".format(full_listname))

        # XXX DanielRichman: we import mailman, but don't use it?
        # If you wanted to use its api---which may well be nicer than shelling out---
        # It might be safer to have a small helper script and execute that, rather than importing Mailman?
        # You could feed it its arguments as JSON over stdin, to avoid having to think about escaping.
        if "/usr/lib/mailman" not in sys.path:
            sys.path.append("/usr/lib/mailman")
        import Mailman.Utils
        newlist = subprocess.Popen('/usr/local/bin/local_pwgen | sshpass newlist "%s" "%s" '
                        '| grep -v "Hit enter to notify.*"'
                        % (full_listname, self.society_society + "-admins@srcf.net"), shell=True)
        newlist.wait()
        if newlist.returncode != 0:
            raise JobFailed("Failed at newlist")

        subproc_check_multi(
            ("config list", ["/usr/sbin/config_list", "-i", "/root/mailman-newlist-defaults", full_listname]),
            ("generate alias", ["gen_alias", full_listname]))

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
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])
    listname = property(lambda s: s.row.args["listname"])

    def __repr__(self): return "<ResetSocietyMailingListPassword {0.listname}>".format(self)
    def __str__(self): return "Reset society mailing list password: {0.listname}".format(self)

    def run(self, sess):

        resetadmins = subprocess.check_output(["/usr/sbin/config_list", "-o", "-", self.listname])
        if "owner =" not in resetadmins:
            raise JobFailed("Failed at reset admins")
        newpasswd = subprocess.check_output(["/usr/lib/mailman/bin/change_pw", "-l", self.listname])
        if "New {} password".format(self.listname) not in newpasswd:
            raise JobFailed("Failed at new password")

@add_job
class CreateMySQLUserDatabase(Job):
    JOB_TYPE = 'create_mysql_user_database'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.store(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid

        password = pwgen(8)

        db = mysql_conn()
        cursor = db.cursor()

        # create database for the user
        try:
            cursor.execute('create database ' + crsid)
        except Exception, e:
            raise JobFailed('Failed to create database for ' + crsid)

        # grant permissions
        sqls = (
            'grant all privileges on ' +  crsid + '.* to ' + crsid + '@localhost',
            'grant all privileges on `' +  crsid + '/%`.* to ' + crsid + '@localhost',
            'set password for ' + crsid + '@localhost = password(\'' + password + '\')')
        for sql in sqls:
            cursor.execute(sql)

        db.close()

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
        return cls.store(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid

        password = pwgen(8)

        db = mysql_conn()
        cursor = db.cursor()

        # create database for the user
        try:
            cursor.execute("set password for " + crsid + "@localhost= password('" + password + "')")
        except Exception, e:
            raise JobFailed('Failed to reset password for ' + crsid)

        db.close()

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
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def run(self, sess):
        password = pwgen(8)

        db = mysql_conn()
        cursor = db.cursor()

        # create database for the user
        try:
            cursor.execute('create database ' + self.society_society)
        except Exception, e:
            raise JobFailed('Failed to create database for ' + self.society_society)

        # set password for requesting user if no MySQL account already
        usrpassword = None
        cursor.execute('select exists (select distinct user from mysql.user where user = `' + self.owner.crsid + '`) as e')
        if cursor.fetchone()[0] == 0:
            usrpassword = pwgen(8)
            cursor.execute('set password for ' + self.owner.crsid + '@localhost = password(\'' + password + '\')')

        # grant permissions
        sqls = (
            'grant all privileges on ' +  self.society_society + '.* to ' + self.society_society + '@localhost',
            'grant all privileges on `' +  self.society_society + '/%`.* to ' + self.society_society + '@localhost',
            'grant all privileges on ' +  self.society_society + '.* to ' + self.owner.crsid + '@localhost',
            'grant all privileges on `' +  self.society_society + '/%`.* to ' + self.owner.crsid + '@localhost',
            'set password for ' + self.society_society + '@localhost = password(\'' + password + '\')')
        for sql in sqls:
            cursor.execute(sql)

        db.close()

        mail_users(self.society, "MySQL database created", "mysql-create", password=password, requester=self.owner)
        if usrpassword:
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
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def run(self, sess):
        password = pwgen(8)

        db = mysql_conn()
        cursor = db.cursor()

        # create database for the user
        try:
            cursor.execute("set password for " + self.society_society + "@localhost= password('" + password + "')")
        except Exception, e:
            raise JobFailed('Failed to reset password for ' + self.society_society)

        db.close()

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
        return cls.store(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid
        password = pwgen(8)

        # Connect to database
        db = postgres_conn()
        cursor = db.cursor()

        # Create user
        usercreated = False

        cursor.execute("SELECT usename FROM pg_shadow WHERE usename = '" + crsid + "'")
        results = cursor.fetchall()

        if len(results) == 0:
            cursor.execute("CREATE USER " + crsid + " ENCRYPTED PASSWORD '" + password + "' NOCREATEDB NOCREATEUSER")
            usercreated = True
        else:
            # Just in case the user exists but is disabled
            cursor.execute("ALTER ROLE " + crsid + " LOGIN")

        # Create database
        dbcreated = False

        cursor.execute("SELECT datname FROM pg_database WHERE datname = '" + crsid + "'")
        results = cursor.fetchall()

        if len(results) == 0:
            cursor.execute("CREATE DATABASE " + crsid + " OWNER " + crsid)
            dbcreated = True

        if not dbcreated and not usercreated:
            raise JobFailed(crsid + " already has a functioning database")

        db.commit()
        db.close()

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
        return cls.store(member, {}, require_approval)

    def run(self, sess):
        crsid = self.owner.crsid
        password = pwgen(8)

        # Connect to database
        db = postgres_conn()
        cursor = db.cursor()

        # Check if the user exists
        cursor.execute("SELECT usename FROM pg_shadow WHERE usename = '" + crsid + "'")
        results = cursor.fetchall()
        if len(results) == 0:
            raise JobFailed(crsid + " does not have a Postgres user")

        # Reset the password
        cursor.execute("ALTER USER " + crsid + " PASSWORD '" + password + "'")

        db.commit()
        db.close()

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
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def run(self, sess):
        crsid = self.owner.crsid
        socname = self.society_society
        userpassword = pwgen(8)
        socpassword = pwgen(8)

        # Connect to database
        db = postgres_conn()
        cursor = db.cursor()

        # Create user
        usercreated = False

        cursor.execute("SELECT usename FROM pg_shadow WHERE usename = '" + crsid + "'")
        results = cursor.fetchall()

        if len(results) == 0:
            cursor.execute("CREATE USER " + crsid + " ENCRYPTED PASSWORD '" + userpassword + "' NOCREATEDB NOCREATEUSER")
            usercreated = True
        else:
            # Just in case the user exists but is disabled
            cursor.execute("ALTER ROLE " + crsid + " LOGIN")

        # Create society user
        socusercreated = False

        cursor.execute("SELECT usename FROM pg_shadow WHERE usename = '" + socname + "'")
        results = cursor.fetchall()

        if len(results) == 0:
            cursor.execute("CREATE USER " + socname + " ENCRYPTED PASSWORD '" + password + "' NOCREATEDB NOCREATEUSER")
            usercreated = True
        else:
            # Just in case the user exists but is disabled
            cursor.execute("ALTER ROLE " + socname + " LOGIN")

        # Create database
        dbcreated = False

        cursor.execute("SELECT datname FROM pg_database WHERE datname = '" + socname + "'")
        results = cursor.fetchall()

        if len(results) == 0:
            cursor.execute("CREATE DATABASE " + socname + " OWNER " + socname)
            dbcreated = True

        # Grant user access to database
        cursor.execute("GRANT " + socname + " TO " + crsid)

        if not dbcreated and not usercreated and not socusercreated:
            raise JobFailed(socname + " already has a functioning database")

        db.commit()
        db.close()

        mail_users(self.society, "PostgreSQL database created", "postgres-create", password=socpassword, requester=self.owner)
        if usercreated:
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
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def run(self, sess):
        socname = self.society_society
        password = pwgen(8)

        # Connect to database
        db = postgres_conn()
        cursor = db.cursor()

        # Check if the user exists
        cursor.execute("SELECT usename FROM pg_shadow WHERE usename = '" + socname + "'")
        results = cursor.fetchall()
        if len(results) == 0:
            raise JobFailed(socname + " does not have a Postgres user")

        # Reset the password
        cursor.execute("ALTER USER " + socname + " PASSWORD '" + password + "'")

        db.commit()
        db.close()

        mail_users(self.society, "PostgreSQL database password reset", "postgres-password", password=password, requester=self.owner)

    def __repr__(self): return "<ResetPostgresSocietyPassword {0.society_society}>".format(self)
    def __str__(self): return "Reset society PostgreSQL password: {0.society.society} ({0.society.description})".format(self)
