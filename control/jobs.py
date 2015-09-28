import subprocess
import sys

from flask import url_for

from srcf import database, pwgen
from srcf.database import queries
from srcf.mail import mail_sysadmins, send_mail, template
import os
import srcf.database
import pgdb

def parse_mail_template(temp, obj):
    f = open(temp, "r")
    text = f.read()
    f.close()

    keys = template.substitutions(obj)
    return template.replace(text, keys)

all_jobs = {}

def add_job(cls):
    all_jobs[cls.JOB_TYPE] = cls
    return cls

class JobDone(object):
    def __init__(self, message=None):
        self.state = "done"
        self.message = message

class JobFailed(object):
    def __init__(self, message=None):
        self.state = "failed"
        self.message = message


class Job(object):
    @staticmethod
    def of_row(row):
        return all_jobs[row.type](row)

    @classmethod
    def of_user(cls, sess, crsid):
        job_row = srcf.database.Job
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
            mail_sysadmins("Job pending approval: {0}".format(job),
               "You can approve or reject the job here: {0}".format(url_for("admin.view_jobs", state="unapproved", _external=True)))
            if old_LOGNAME:
                os.environ["LOGNAME"] = old_LOGNAME
            else:
                del os.environ["LOGNAME"]

        return job

    def run(self, sess):
        """Run the job. `self.state` will be set to `done` or `failed`."""
        return JobFailed("not implemented")

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
        # note that we can't set owner because the Member doesn't exist yet
        return cls.store(None, args)

    crsid          = property(lambda s: s.row.args["crsid"])
    preferred_name = property(lambda s: s.row.args["preferred_name"])
    surname        = property(lambda s: s.row.args["surname"])
    email          = property(lambda s: s.row.args["email"])
    social         = property(lambda s: s.row.args["social"] == "y")

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

    def __repr__(self): return "<ResetUserPassword {0.owner_crsid}>".format(self)
    def __str__(self): return "Reset User Password: {0.owner.crsid} ({0.owner.name})".format(self)

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

    def __str__(self): return "Update Email Address: {0.owner.crsid} ({0.owner.email} to {0.email})".format(self)
    def __repr__(self): return "<UpdateEmailAddress {0.owner_crsid}>".format(self)

    def run(self, sess):
        crsid = self.owner.crsid
        old_email = self.owner.email

        # Connect to database
        db = pgdb.connect(database="sysadmins")
        cursor = db.cursor()

        cursor.execute("UPDATE members SET email = %s WHERE crsid = '" + crsid + "'", (self.email,))

        mail_sysadmins("SRCF User Email Address Update",
                       "Email address for {0.owner.crsid} changed from {1} to {0.email}"
                       .format(self, old_email))

        return JobDone()

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
    def __str__(self): return "Create User Mailing List: {0.owner_crsid}-{0.listname}".format(self)

    def run(self, sess):

        full_listname = "{}-{}".format(self.owner, self.listname)

        import re
        if not re.match("^[A-Za-z0-9\-]+$", self.listname) \
        or self.listname.split("-")[-1] in ("admin", "bounces", "confirm", "join", "leave",
                                            "owner", "request", "subscribe", "unsubscribe"):
            return JobFailed("Invalid list name {}".format(full_listname))

        if "/usr/lib/mailman" not in sys.path:
            sys.path.append("/usr/lib/mailman")
        import Mailman.Utils
        newlist = subprocess.Popen('/usr/local/bin/local_pwgen | sshpass newlist "%s" "%s" '
                        '| grep -v "Hit enter to notify.*"'
                        % (full_listname, self.owner.crsid + "@srcf.net"), shell=True)
        newlist.wait()
        if newlist.returncode != 0:
            return JobFailed("Failed at newlist")
        configlist = subprocess.Popen(["/usr/sbin/config_list", "-i", "/root/mailman-newlist-defaults",
                            full_listname])
        configlist.wait()
        if configlist.returncode != 0:
            return JobFailed("Failed at configlist")
        genalias = subprocess.Popen(["gen_alias", full_listname])
        genalias.wait()
        if genalias.returncode != 0:
            return JobFailed("Failed at genalias")

        mail_sysadmins("SRCF User List Creation",
                       "{0} created for {1.owner.crsid} ({1.owner.name})"
                       .format(full_listname, self))

        return JobDone()

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

    def __repr__(self): return "<ResetUserMailingListPassword {0.owner_crsid} {0.listname}>".format(self)
    def __str__(self): return "Reset User Mailing List Password: {0.owner_crsid} {0.listname}".format(self)

    def run(self, sess):

        resetadmins = subprocess.check_output(["/usr/sbin/config_list", "-o", "-", self.listname])
        if "owner =" not in resetadmins:
            return JobFailed("Failed at reset admins")
        newpasswd = subprocess.check_output(["/usr/lib/mailman/bin/change_pw", "-l", self.listname])
        if "New {} password".format(self.listname) not in newpasswd:
            return JobFailed("Failed at new password")

        mail_sysadmins("SRCF User List Password Reset",
                       "{0.listname} password reset for {0.owner.crsid} ({0.owner.name})"
                       .format(self))

        return JobDone()

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
    def new(cls, member, society, description, admins,
            mysql, postgres):
        args = {
            "society": society,
            "description": description,
            "admins": ",".join(a.crsid for a in admins),
            "mysql": "y" if mysql else "n",
            "postgres": "y" if postgres else "n"
        }
        return cls.store(member, args)

    society      = property(lambda s: s.row.args["society"])
    description  = property(lambda s: s.row.args["description"])
    admin_crsids = property(lambda s: s.row.args["admins"].split(","))
    mysql        = property(lambda s: s.row.args["mysql"] == "y")
    postgres     = property(lambda s: s.row.args["postgres"] == "y")

    def __repr__(self): return "<CreateSociety {0.society}>".format(self)
    def __str__(self): return "Create Society: {0.society} ({0.description})".format(self)

@add_job
class ChangeSocietyAdmin(Job):
    JOB_TYPE = 'change_society_admin'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = \
            queries.get_society(self.society_society,    session=sess)
        self.target_member = \
            queries.get_member(self.target_member_crsid, session=sess)

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
        fmt = "{verb} {0.target_member.crsid} ({0.target_member.name}) "\
                "{prep} {0.society.society} ({0.society.description})"
        return fmt.format(self, verb=verb, prep=prep)

    def add_admin(self, sess):
        if self.target_member in self.society.admins:
            return JobFailed("{0.target_member.crsid} is already an admin of {0.society}".format(self))

        # Get the recipient lists before adding because we are sending the new admin a separate email.
        recipients = [(x.name, x.crsid + "@srcf.net") for x in self.society.admins]

        self.society.admins.add(self.target_member)

        subprocess.check_call(["adduser", self.target_member.crsid, self.society.society])

        target_ln = "/home/{0.target_member.crsid}/{0.society.society}".format(self)
        source_ln = "/societies/{0.society.society}/".format(self)
        if not os.path.exists(target_ln):
            os.symlink(source_ln, target_ln)

        send_mail((self.target_member.name, self.target_member.crsid + "@srcf.net"),
                  "Access granted to society {0.society.society} "
                  "for {0.target_member.crsid}".format(self),
                  parse_mail_template("/usr/local/share/srcf/mailtemplates/user-added2soc", self.society),
                  copy_sysadmins=False)
                
        send_mail((self.society.description + " Admins", self.society.society + "-admins@srcf.net"), 
                  "Access granted to society {0.society.society} "
                  "for {0.target_member.crsid}".format(self),
                  "{0.target_member.crsid} ({0.target_member.name}) added to "
                  "{0.society.society} ({0.society.description}) "
                  "at request of {0.owner.crsid} ({0.owner.name})"
                  .format(self))

        return JobDone()


    def rm_admin(self, sess):
        if self.target_member not in self.society.admins:
            return JobFailed("{0.target_member.crsid} is not an admin of {0.society.society}".format(self))

        if len(self.society.admins) == 1:
            return JobFailed("removing all admins not implemented")

        # Get the recipient lists before removing because we want to notify the user removed
        recipients = [(x.name, x.crsid + "@srcf.net") for x in self.society.admins]

        self.society.admins.remove(self.target_member)
        subprocess.check_call(["deluser", self.target_member.crsid, self.society.society])

        target_ln = "/home/{0.target_member.crsid}/{0.society.society}".format(self)
        source_ln = "/societies/{0.society.society}/".format(self)
        if os.path.islink(target_ln) and os.path.samefile(target_ln, source_ln):
            os.remove(target_ln)

        send_mail([(self.society.description + " Admins", self.society.society + "-admins@srcf.net"),
                   (self.target_member.name, self.target_member.crsid + "@srcf.net")], 
                  "Access to society {0.society.society} removed "
                  "for {0.target_member.crsid}".format(self),
                  "{0.target_member.crsid} ({0.target_member.name}) removed from "
                  "{0.society.society} ({0.society.description}) "
                  "at request of {0.owner.crsid} ({0.owner.name})"
                  .format(self))

        return JobDone()

    def run(self, sess):
        if self.owner not in self.society.admins:
            return JobFailed("{0.owner.crsid} is not permitted to change the admins of {0.society.society}".format(self))

        if self.action == "add":
            return self.add_admin(sess)
        else:
            return self.rm_admin(sess)

@add_job
class CreateSocietyMailingList(Job):
    JOB_TYPE = 'create_society_mailing_list'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = \
            queries.get_society(self.society_society, session=sess)

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
    def __str__(self): return "Create Society Mailing List: {0.society_society}-{0.listname}".format(self)

    def run(self, sess):

        full_listname = "{}-{}".format(self.society_society, self.listname)

        import re
        if not re.match("^[A-Za-z0-9\-]+$", self.listname) \
        or self.listname.split("-")[-1] in ("admin", "bounces", "confirm", "join", "leave",
                                            "owner", "request", "subscribe", "unsubscribe"):
            return JobFailed("Invalid list name {}".format(full_listname))

        if "/usr/lib/mailman" not in sys.path:
            sys.path.append("/usr/lib/mailman")
        import Mailman.Utils
        newlist = subprocess.Popen('/usr/local/bin/local_pwgen | sshpass newlist "%s" "%s" '
                        '| grep -v "Hit enter to notify.*"'
                        % (full_listname, self.society_society + "-admins@srcf.net"), shell=True)
        newlist.wait()
        if newlist.returncode != 0:
            return JobFailed("Failed at newlist")
        configlist = subprocess.Popen(["/usr/sbin/config_list", "-i", "/root/mailman-newlist-defaults",
                            full_listname])
        configlist.wait()
        if configlist.returncode != 0:
            return JobFailed("Failed at configlist")
        genalias = subprocess.Popen(["gen_alias", full_listname])
        genalias.wait()
        if genalias.returncode != 0:
            return JobFailed("Failed at genalias")

        mail_sysadmins("SRCF Society List Creation",
                       "{0} created for {1.society_society} ({1.society.description})"
                       .format(full_listname, self))

        return JobDone()

@add_job
class ResetSocietyMailingListPassword(Job):
    JOB_TYPE = 'reset_society_mailing_list_password'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = \
            queries.get_society(self.society_society, session=sess)

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

    def __repr__(self): return "<ResetSocietyMailingListPassword {0.society_society} {0.listname}>".format(self)
    def __str__(self): return "Reset Society Mailing List Password: {0.society.society} {0.listname}".format(self)

    def run(self, sess):

        resetadmins = subprocess.check_output(["/usr/sbin/config_list", "-o", "-", self.listname])
        if "owner =" not in resetadmins:
            return JobFailed("Failed at reset admins")
        newpasswd = subprocess.check_output(["/usr/lib/mailman/bin/change_pw", "-l", self.listname])
        if "New {} password".format(self.listname) not in newpasswd:
            return JobFailed("Failed at new password")

        mail_sysadmins("SRCF Society List Password Reset",
                       "{0.listname} password reset for {0.society_society} ({0.society.description})"
                       .format(self))

        return JobDone()

@add_job
class CreateMySQLUserDatabase(Job):
    JOB_TYPE = 'create_mysql_user_database'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.store(member, {}, require_approval)

    def __repr__(self): return "<CreateMySQLUserDatabase {0.owner_crsid}>".format(self)
    def __str__(self): return "Create MySQL User Database: {0.owner.crsid} ({0.owner.name})".format(self)

@add_job
class ResetMySQLUserPassword(Job):
    JOB_TYPE = 'reset_mysql_user_password'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.store(member, {}, require_approval)

    def __repr__(self): return "<ResetMySQLUserPassword {0.owner_crsid}>".format(self)
    def __str__(self): return "Reset MySQL User Password: {0.owner.crsid} ({0.owner.name})".format(self)

@add_job
class CreateMySQLSocietyDatabase(Job):
    JOB_TYPE = 'create_mysql_society_database'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = queries.get_society(self.society_society, session=sess)

    @classmethod
    def new(cls, member, society):
        args = {"society": society.society}
        require_approval = society.danger or member.danger
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def __repr__(self): return "<CreateMySQLSocietyDatabase {0.society_society}>".format(self)
    def __str__(self): return "Create MySQL Society Database: {0.society.society} ({0.society.description})".format(self)

@add_job
class ResetMySQLSocietyPassword(Job):
    JOB_TYPE = 'reset_mysql_society_password'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = queries.get_society(self.society_society, session=sess)

    @classmethod
    def new(cls, member, society):
        args = {"society": society.society}
        require_approval = society.danger or member.danger
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def __repr__(self): return "<ResetMySQLSocietyPassword {0.society_society}>".format(self)
    def __str__(self): return "Reset MySQL Society Password: {0.society.society} ({0.society.description})".format(self)

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
        db = pgdb.connect(database='template1')
        cursor = db.cursor()

        # Create user
        usercreated = False

        cursor.execute("SELECT usename FROM pg_shadow WHERE usename = '" + crsid + "'")
        results = cursor.fetchall()

        if len(results) == 0:
            cursor.execute("COMMIT")
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
            cursor.execute("COMMIT")
            cursor.execute("CREATE DATABASE " + crsid + " OWNER " + crsid)
            dbcreated = True

        if not dbcreated and not usercreated:
            return JobFailed(crsid + " already has a functioning database")

        # Email user
        message = ""
        if usercreated:
            message += "A postgreSQL database '" + crsid + "' has been created for you\n" \
                       "PostgreSQL username:  " + crsid + "\n" \
                       "PostgreSQl password:  " + password + "\n\n" \
                       "Do not let anyone know your password, including the system\n" \
                       "administrators (they do not need to know it to administer your\n" \
                       "account). In particular, if you reply to this message, DO NOT quote\n" \
                       "your password in the reply\n\n"

        message += "To access the database via a web interface (phpPgAdmin), visit:\n" \
                   "  https://www.srcf.net/phpgadmin\n\n" \
                   "To access the database from the shell, use the following command:\n" \
                   "  psql " + crsid + "\n" \
                   "You will be automatically identified so no password is required.\n\n" \
                   "Regards,\n\n" \
                   "The Sysadmins\n"
        send_mail((self.owner.name, crsid + "@srcf.net"), "PostgreSQL database created for " + crsid, message, copy_sysadmins=False)
        mail_sysadmins("PostgreSQL database created for " + crsid, "")


        return JobDone()



    def __repr__(self): return "<CreatePostgresUserDatabase {0.owner_crsid}>".format(self)
    def __str__(self): return "Create Postgres User Database: {0.owner.crsid} ({0.owner.name})".format(self)

@add_job
class ResetPostgresUserPassword(Job):
    JOB_TYPE = 'reset_postgres_user_password'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.store(member, {}, require_approval)

    def __repr__(self): return "<ResetPostgresUserPassword {0.owner_crsid}>".format(self)
    def __str__(self): return "Reset Postgres User Password: {0.owner.crsid} ({0.owner.name})".format(self)

@add_job
class CreatePostgresSocietyDatabase(Job):
    JOB_TYPE = 'create_postgres_society_database'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = queries.get_society(self.society_society, session=sess)

    @classmethod
    def new(cls, member, society):
        args = {"society": society.society}
        require_approval = society.danger or member.danger
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def __repr__(self): return "<CreatePostgresSocietyDatabase {0.society_society}>".format(self)
    def __str__(self): return "Create Postgres Society Database: {0.society.society} ({0.society.description})".format(self)

@add_job
class ResetPostgresSocietyPassword(Job):
    JOB_TYPE = 'reset_postgres_society_password'

    def __init__(self, row):
        self.row = row

    def resolve_references(self, sess):
        self.society = queries.get_society(self.society_society, session=sess)

    @classmethod
    def new(cls, member, society):
        args = {"society": society.society}
        require_approval = society.danger or member.danger
        return cls.store(member, args, require_approval)

    society_society = property(lambda s: s.row.args["society"])

    def __repr__(self): return "<ResetPostgresSocietyPassword {0.society_society}>".format(self)
    def __str__(self): return "Reset Postgres Society Password: {0.society.society} ({0.society.description})".format(self)
