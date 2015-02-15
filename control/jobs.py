from srcf import database
from srcf.mail import mail_sysadmins


__all__ = ["Job", "Signup"]


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
            return cls.of_row(job)

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
        row = database.Job(type=cls.JOB_TYPE, state="unapproved", args=args)
        return cls(row)

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
class ChangeSocietyAdmin(Job):
    JOB_TYPE = 'change_society_admin'

    def __init__(self, row):
        self.row = row

    @classmethod
    def new(cls, requesting_member, society, member, action):
        if action not in {"add", "remove"}:
            raise ValueError("action should be 'add' or 'remove'", action)
        args = {
            "society": society.society,
            "member": member.crsid,
            "action": action
        }
        require_approval = \
                society.danger \
             or member.danger \
             or requesting_member.danger

        row = database.Job(
            type=cls.JOB_TYPE,
            state="unapproved" if require_approval else "queued",
            args=args
        )
        return cls(row)

    society_crsid = property(lambda s: s.row.args["society"])
    member_crsid  = property(lambda s: s.row.args["crsid"])
