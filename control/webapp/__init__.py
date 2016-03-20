from flask import Flask, request, redirect

from . import utils, home, member, society, signup, jobs, admin

app = Flask(__name__,
            template_folder="../templates",
            static_folder="../static")
utils.setup_app(app)
app.register_blueprint(home.bp)
app.register_blueprint(member.bp)
app.register_blueprint(society.bp)
app.register_blueprint(signup.bp)
app.register_blueprint(jobs.bp)
app.register_blueprint(admin.bp)

@app.before_request
def https():
    if not request.url.startswith("https"):
        return redirect(request.url.replace("http", "https", 1))
