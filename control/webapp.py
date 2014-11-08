from flask import Flask, render_template
app = Flask(__name__)
app.debug = True
# import jinja2

@app.route('/')
def hello_world():
    return render_template("home.jinja2")

if __name__ == '__main__':
    app.run()
