# Battlehouse Analytics System (2021)

This takes the form of Jupyter notebooks that connect to the MySQL analytics database.

# Interactive operation

- In `gameserver/analytics-env`, create a file `.env` containing an Envkey for the "SpinPunch Management" secrets, like the following:
```
ENVKEY=...
```

This Envkey will be used to read the MySQL server endpoint name and password.

- In `gameserver/`, run `analytics-env/start.sh` to build and run the Dockerized Jupyter server
- When Jupyter finishes launching, use the URL at the end of the console output to connect to the server (`http://127.0.0.1:8888/lab/...)

- The Jupyter file browser will display the contents of `gameserver/analyics-env/notebooks`. This is mounted from your local drive into Docker, so changes you make and save inside of Jupyter will affect the source files.

- Check in any updates to notebooks using the usual git flow. Note: Please "Clear All Outputs" before committing changes, to avoid bloating the .ipynb files.

# Automatic dashboard publishing

We have a system to evaluate notebooks and export the output to HTML for publishing on a regular basis.

The components of this are split between:
- `gameserver/analytics-env`: Dockerfile, scripts, and notebooks
- `aws/terraform/env-game-batch-tasks`: AWS and CloudFlare resources for publishing dashboards
  - * in addition to the above, ensure that the RDS database allows connections from `gamemaster.spinpunch.com`,
  and that `gamemaster.spinpunch.com` allows SSH connections from any IP using the SSH key in Envkey's `ANALYTICS_SSH_KEY` variable.
- `.github/workflows/build-jupyter-image.yml`: Github action to build and push Docker image
- `.github/workflows/publish-dashboards.yml`: Github action to run and publish notebooks

The publishing flow is as follows:
- (once-only, or whenever the Jupyer Dockerfile changes) Push to the `github-automation` branch to trigger the `build-jupyter-image` workflow to build the Docker image `ghcr.io/spinpunch/game-jupyter:latest`
- (daily) A GitHub cron schedule triggers the `publish-dashboards` workflow to execute the notebooks and publish the HTML files to the S3 bucket `dashboards.spinpunch.com`
  - This uses the `ANALYTICS_SSH_KEY` Envkey to tunnel into the RDS server via `gamemaster.spinpunch.com`
  - And also `BATCH_TASKS_AWS` credentials from Envkey
- Access to `https://dashboards.spinpunch.com/...` is guarded by CloudFlare Access which requires a Google OAuth sign-in from any `*@battlehouse.com` email address.
