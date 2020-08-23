[Live site](https://control.srcf.net) | [To-do list](https://kanboard.srcf.net/board/1)

# Components

|Component|Location|
|:--------|:------:|
|Frontend & backend (Flask webapp, unprivileged)|https://github.com/SRCF/control-panel|
|Job runner (Postgres listener, root-privileged)|srcf-scripts Python library: `srcf.controllib.job_runner`|
|Job definitions|srcf-scripts Python library: `srcf.controllib.jobs`|

Each job has an `environment` associated with it.  Jobs created by a control panel frontend with a given environment tag will only be picked up by a job runner using the corresponding tag.  The live system (https://control.srcf.net + systemd service runner) use `live` as their tag.

At most one runner per environment can run, managed by PostgreSQL advisory locks.

# Setup

## Frontend / backend

1. Set up a !GitHub account, configure SSH keys, be granted access to the SRCF group etc.
2. Clone the control panel repository into your own dev folder:
```
git clone git@github.com:SRCF/control-panel.git ~srcf-admin/control-hackday-$USER
```
3. Choose a random high-numbered port to run your frontend on, e.g.:
```
export PORT=54321  # but choose something better
```
4. Add a rewrite rule to `/public/societies/srcf-admin/public_html/.htaccess`:
```
cat >>/public/societies/srcf-admin/public_html/.htaccess_ <<EOF
RewriteRule "^control-$USER/(.*)$" "http://localhost:$PORT/\$1" [P,QSA]
EOF
```
5. Start your dev server **on sinkhole** (ssh to `webserver.srcf.net`):
```
cd ~srcf-admin/control-hackday-$USER
sudo -Hu srcf-admin env SRCF_JOB_QUEUE=$USER wsgi-proxy-run control.webapp:app $PORT \
  --debug --https --prefix /control-$USER --host srcf-admin.soc.srcf.net
```
6. Find your dev server at `https://srcf-admin.soc.srcf.net/control-$USER/` (the trailing slash is important)

# Job runner

 1. Clone the srcf-scripts SVN repository in your -adm account, if you haven't already.

 2. Prioritise the local Python lib over `/usr/local` (`$PYTHONPATH`, `.pth` file in `~./local` packages etc.).

 3. Start your job runner **on pip**:
```
sudo env SRCF_JOB_QUEUE=$NON_ADM_USER python3 -m srcf.controllib.job_runner
```


# Deployment
## Frontend

```
cd ~srcf-admin/control
git pull
```

`uwsgi` on sinkhole will automatically restart the site when `.git/HEAD` changes.

## Backend

On pip:

```
sudo update-usr-local
sudo systemctl restart control-panel-job-runner.service
```

# Docker

There is a basic `Dockerfile` to ensure dependencies are tracked and to assist (some forms) of testing and local development.

To build:

    $ docker build --tag srcf/control .

Actually running the service locally via Docker is currently experimental at best, and looks something like the following:

1. Modify `run.py` to pass `debug=False` to the `app.run` call
2. docker run --tty --interactive --env FLASK_TRUSTED_HOSTS=localhost --env FLASK_SECRET_KEY=not-a-secret --env DOMAIN_WEB=localhost --env FLASK_ENV=development -p 5000:5000 srcf/control
3. Point your browser at http://localhost:5000/
