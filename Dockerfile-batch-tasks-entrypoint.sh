#!/bin/sh -l

if [ -z $ENVKEY ]; then
    echo "ENVKEY is not set"
    exit 1
fi

eval $(envkey-source)

# inject batch-tasks IAM service account credentials (from management ENVKEY)
export AWS_ACCESS_KEY_ID=${BATCH_TASKS_AWS_KEY_ID}
export AWS_SECRET_ACCESS_KEY=${BATCH_TASKS_AWS_SECRET_KEY}

exec "$@"
