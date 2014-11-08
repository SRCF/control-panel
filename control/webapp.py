from flask import Flask, render_template, send_from_directory
app = Flask(__name__)
app.debug = True
# import jinja2

@app.route('/')
def hello_world():
    return render_template("home.jinja2")

@app.route('/static/<path:filename>')
def static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    app.run()
