from srcf import database
from srcf.database import queries
from srcf.mail import mail_sysadmins


__all__ = ["Job", "Signup", "ChangeSocietyAdmin", \
           "CreateMySQLUserDatabase", "CreateMySQLSocietyDatabase", \
           "CreatePostgresUserDatabase", "CreatePostgresSocietyDatabase"]


all_jobs = {}

def add_job(cls):
    all_jobs[cls.JOB_TYPE] = cls
    return cls


class Job:
    @staticmethod
    def of_row(row, sess):
        return all_jobs[row.type](row, sess=sess)

    @classmethod
    def find(cls, sess, id):
        job = sess.query(database.Job).get(id)
        if not job:
            return None
        else:
            return cls.of_row(job, sess=sess)

    @classmethod
    def store(cls, owner, args, require_approval=False):
        return cls(database.Job(
            type=cls.JOB_TYPE,
            owner=owner,
            state="unapproved" if require_approval else "queued",
            args=args
        ))

    def run(self):
        body = "\n".join("{0}: {1}".format(k, v) for k, v in self.args.items())
        subject = "Control panel job: {0}".format(self.JOB_TYPE)
        mail_sysadmins(subject, body)

    job_id = property(lambda s: s.row.job_id)
    owner = property(lambda s: s.row.owner)
    owner_crsid = property(lambda s: s.row.owner_crsid)
    state = property(lambda s: s.row.state)
    state_message = property(lambda s: s.row.state_message)

    @state.setter
    def state(s, n): s.row.state = n
    @state_message.setter
    def state_message(s, n): s.row.state_message = n


@add_job
class Signup(Job):
    JOB_TYPE = 'signup'

    def __init__(self, row, sess=None):
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
        return cls.store(args, None)

    crsid          = property(lambda s: s.row.args["crsid"])
    preferred_name = property(lambda s: s.row.args["preferred_name"])
    surname        = property(lambda s: s.row.args["surname"])
    email          = property(lambda s: s.row.args["email"])
    social         = property(lambda s: s.row.args["social"] == "y")

    __repr__ = "<Signup {0.crsid}>".format
    description = \
        property("Signup: {0.crsid} ({0.preferred_name} "
                 "{0.surname}, {0.email})".format)

@add_job
class CreateSociety(Job):
    JOB_TYPE = 'create_society'

    def __init__(self, row, sess=None):
        self.row = row

    @classmethod
    def new(cls, requesting_member, short_name, full_name, admins, mysql, postgres, lists):
        args = {
            "requesting_member": requesting_member,
            "short_name": short_name,
            "full_name": full_name,
            "admins": ",".join(admins),
            "mysql": "y" if mysql else "n",
            "postgres": "y" if postgres else "n",
            "lists": ",".join(lists)
        }
        return cls.store(requesting_member, args)

    short_name = property(lambda s: s.row.args["short_name"])
    full_name  = property(lambda s: s.row.args["full_name"])
    admins     = property(lambda s: s.row.args["admins"].split(","))
    mysql      = property(lambda s: s.row.args["mysql"] == "y")
    postgres   = property(lambda s: s.row.args["postgres"] == "y")
    lists      = property(lambda s: s.row.args["lists"].split(","))

    __repr__ = "<CreateSociety {0.short_name}>".format
    description = \
        property("Create Society: {0.short_name} ({0.full_name})".format)

@add_job
class ChangeSocietyAdmin(Job):
    JOB_TYPE = 'change_society_admin'

    def __init__(self, row, sess=None):
        self.row = row
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

    society_crsid = property(lambda s: s.row.args["society"])
    member_crsid  = property(lambda s: s.row.args["crsid"])

@add_job
class CreateMySQLUserDatabase(Job):
    JOB_TYPE = 'create_mysql_user_database'

    def __init__(self, row, sess=None):
        self.row = row

    @classmethod
    def new(cls, member):
        args = {
            "member": member.crsid
        }
        require_approval = member.danger
        return cls.store(member, args, require_approval)

    member_crsid  = property(lambda s: s.row.args["crsid"])

@add_job
class CreateMySQLSocietyDatabase(Job):
    JOB_TYPE = 'create_mysql_society_database'

    def __init__(self, row, sess=None):
        self.row = row

    @classmethod
    def new(cls, requesting_member, society):
        args = {
            "society": society.society,
            "member": requesting_member.crsid
        }
        require_approval = \
                society.danger \
             or requesting_member.danger
        return cls.store(requesting_member, args, require_approval)

    society_crsid = property(lambda s: s.row.args["society"])
    member_crsid  = property(lambda s: s.row.args["crsid"])

@add_job
class CreatePostgresUserDatabase(Job):
    JOB_TYPE = 'create_postgres_user_database'

    def __init__(self, row, sess=None):
        self.row = row

    @classmethod
    def new(cls, member):
        args = {
            "member": member.crsid
        }
        require_approval = member.danger
        return cls.store(member, args, require_approval)

    member_crsid  = property(lambda s: s.row.args["crsid"])

@add_job
class CreatePostgresSocietyDatabase(Job):
    JOB_TYPE = 'create_postgres_society_database'

    def __init__(self, row, sess=None):
        self.row = row

    @classmethod
    def new(cls, requesting_member, society):
        args = {
            "society": society.society,
            "member": requesting_member.crsid
        }
        require_approval = \
                society.danger \
             or requesting_member.danger
        return cls.store(requesting_member, args, require_approval)

    society_society     = property(lambda s: s.row.args["society"])
    target_member_crsid = property(lambda s: s.row.args["target_member"])
    action              = property(lambda s: s.row.args["action"])
