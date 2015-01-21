#!/bin/bash

# Ensure the S3-backed SpinPunch docker registry service is running on localhost

if docker inspect spinpunch-docker-registry > /dev/null 2>&1; then
    echo "SpinPunch local Docker registry service appears to be running already"
    exit 0
fi

# When run manually in development, this should find the developer's S3 credentials for read/write access
# When run in production, it should fall back to the IAM Role for read-only access

# look for ~/.ssh/HOSTNAME-awssecret
SECRETNAME=`echo ${HOSTNAME} | cut -d. -f1` # before-first-dot part of hostname
SECRETFILE="${HOME}/.ssh/${SECRETNAME}-awssecret"

if [ -e "$SECRETFILE" ]; then
    # use key file
    KEY=`< ${SECRETFILE} sed -n '1p'`
    SECRET=`< ${SECRETFILE} sed -n '2p'`
    # also add sqlalchemy indexing in this mode
    CREDENTIAL_OPTS=" -e AWS_KEY=${KEY} -e AWS_SECRET=${SECRET} -e SEARCH_BACKEND=sqlalchemy"
else
    # if no hostname-awssecret file is found, use boto's default credential search
    CREDENTIAL_OPTS=""
fi

docker run -d --name spinpunch-docker-registry \
       -e SETTINGS_FLAVOR=s3 \
       -e AWS_REGION=us-east-1 \
       -e AWS_BUCKET=spinpunch-docker \
       -e STORAGE_PATH=/registry \
       -p 5000:5000 \
       ${CREDENTIAL_OPTS} \
       registry

