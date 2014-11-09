from srcf import database
from srcf.mail import mail_sysadmins


all_jobs = {}

def add_job(cls):
    all_jobs[cls.JOB_TYPE] = cls
    return cls


class Job:
    def to_row(self):
        return database.Job(type=self.JOB_TYPE, args=self.args)

    @classmethod
    def of_row(cls, row):
        if cls == Job:
            return all_jobs[row.type].from_args(row.args)
        else:
            assert cls.JOB_TYPE == row.type
            return cls.from_args(row.args)

    def run(self):
        body = "\n".join("{0}: {1}".format(k, v) for k, v in self.args.items())
        subject = "Control panel job: {0}".format(self.JOB_TYPE)
        mail_sysadmins(subject, body)


@add_job
class Signup(Job):
    JOB_TYPE = 'signup'

    def __init__(self, crsid, preferred_name, surname, email, social):
        self.crsid = crsid
        self.preferred_name = preferred_name
        self.surname = surname
        self.email = email
        self.social = social

    def __repr__(self):
        return "<Signup {0}>".format(self.crsid)

    @classmethod
    def from_args(cls, args):
        args = args.copy()
        if args["social"] not in ("y", "n"):
            raise ValueError("Signup arg social wasn't y or n")
        args["social"] = (args["social"] == "y")
        return cls(**args)

    @property
    def args(self):
        return {
            "crsid": self.crsid,
            "preferred_name": self.preferred_name,
            "surname": self.surname,
            "email": self.email,
            "social": "y" if self.social else "n"
        }
