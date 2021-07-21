#!/bin/bash

set -e

if [ -z $ENVKEY ]; then
    echo "ENVKEY is not set"
    exit 1
fi

eval "$(envkey-source --no-cache --force)"

# set up MySQL tunnel via SSH_JUMP_HOST using the private key ANALYTICS_SSH_KEY
mkdir -p ~/.ssh
echo "${ANALYTICS_SSH_KEY}" > ~/.ssh/id_rsa
chmod og-rwx ~/.ssh/id_rsa

# set up AWS credentials from envkey
export AWS_ACCESS_KEY_ID="${BATCH_TASKS_AWS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${BATCH_TASKS_AWS_SECRET_KEY}"
export AWS_REGION="us-east-1"

ssh -i ~/.ssh/id_rsa -o StrictHostKeyChecking=no -f -N -L 3306:${ANALYTICS_MYSQL_ENDPOINT}:3306 "spanalytics@${SSH_JUMP_HOST}"

# and now use localhost for the database connection
export ANALYTICS_MYSQL_ENDPOINT="127.0.0.1:3306"

exec "$@"
