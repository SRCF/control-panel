from flask import Flask

from . import utils, home, signup

app = Flask(__name__,
            template_folder="../templates",
            static_folder="../static")
utils.setup_app(app)
app.register_blueprint(home.bp)
app.register_blueprint(signup.bp)
