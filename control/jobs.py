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
    def of_row(row):
        return all_jobs[row.type](row)

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
    describe = property("Signup: {0.crsid} ({0.preferred_name} "
                        "{0.surname}, {0.email})".format)

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
    describe = property("Reset User Password: {0.owner.crsid} ({0.owner.name})".format)

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
    describe = property("Create User Mailing List: {0.owner_crsid}-{0.listname}".format)

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
    describe = property("Create Society: {0.society} ({0.description})".format)

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

    @property
    def describe(self):
        verb = self.action.title()
        prep = "to" if self.action == "add" else "from"
        fmt = "{verb} {0.target_member.crsid} ({0.target_member.name}) "\
                "{prep} {0.society.society} ({0.society.description})"
        return fmt.format(self, verb=verb, prep=prep)

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

    society_society     = property(lambda s: s.row.args["society"])
    listname = property(lambda s: s.row.args["listname"])

    def __repr__(self): return "<CreateSocietyMailingList {0.society_society}-{0.listname}>".format(self)
    describe = property("Create Society Mailing List: {0.society.society}-{0.listname}".format)

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
    describe = property("Create MySQL User Database: {0.owner.crsid} ({0.owner.name})".format)

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
    describe = property("Reset MySQL User Password: {0.owner.crsid} ({0.owner.name})".format)

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
    describe = property("Create MySQL Society Database: "
                        "{0.society.society} ({0.society.description})".format)

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
    describe = property("Reset MySQL Society Password: "
                        "{0.society.society} ({0.society.description})".format)

@add_job
class CreatePostgresUserDatabase(Job):
    JOB_TYPE = 'create_postgres_user_database'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, member):
        require_approval = member.danger
        return cls.store(member, {}, require_approval)

    def __repr__(self): return "<CreatePostgresUserDatabase {0.owner_crsid}>".format(self)
    describe = property("Create Postgres User Database: "
                        "{0.owner.crsid} ({0.owner.name})".format)

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
    describe = property("Reset Postgres User Password: "
                        "{0.owner.crsid} ({0.owner.name})".format)

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
    describe = property("Create Postgres Society Database: "
                        "{0.society.society} ({0.society.description})".format)

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
    describe = property("Reset Postgres Society Password: "
                        "{0.society.society} ({0.society.description})".format)
