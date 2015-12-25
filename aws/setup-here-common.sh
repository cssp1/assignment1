#!/bin/bash

AWSHOST="ec2-54-80-125-20.compute-1.amazonaws.com"
AWSKEY="$HOME/.ssh/bfmprod.pem"
AWSCRED_KEYID="none" # optional: for per-host IAM keys
AWSCRED_SECRET="none"
AWS_CRON_SNS_TOPIC="arn:aws:sns:us-east-1:147976285850:spinpunch-technical"
KIND="prod-haproxy" # one of: analytics1, forums, gamemaster, mongo, prod, prod-haproxy, www
GAME_ID="" # only for "prod" server type
GAME_ID_LONG="" # only for "prod" server type

# run on mothership machine

SCRIPT_DIR=`dirname $0`
SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd "${SCRIPT_DIR}/${KIND}" && sudo tar zcvf "/tmp/overlay-${KIND}.tar.gz" .)

# bash conveniences
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.screenrc \
           $HOME/.dir_colors \
           $HOME/.nanorc $HOME/.nano"

# remote setup scripts
FILESTOGO+=" ${SCRIPT_DIR}/setup-there-common.sh \
             ${SCRIPT_DIR}/setup-there-${KIND}.sh \
             ${SCRIPT_DIR}/fix-ec2-mail.py \
             ${SCRIPT_DIR}/ec2-send-memory-metrics.py \
             ${SCRIPT_DIR}/cron-mail-to-sns.py"

# overlay
FILESTOGO+=" /tmp/overlay-${KIND}.tar.gz"

echo "Copying files to cloud host..."
scp -r $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

# fix some permissions
sudo sh -c 'chmod 0600 /etc/ssh/ssh_host_*_key'

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST "/home/ec2-user/setup-there-common.sh ${AWSCRED_KEYID} ${AWSCRED_SECRET} ${AWS_CRON_SNS_TOPIC} && chmod +x /home/ec2-user/setup-there-${KIND}.sh && /home/ec2-user/setup-there-${KIND}.sh ${GAME_ID} ${GAME_ID_LONG} ${ART_CDN_HOST}"

sudo rm -f "/tmp/overlay-${KIND}.tar.gz"
