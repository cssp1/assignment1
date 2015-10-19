#!/bin/bash

AWSHOST="forums.spinpunch.com"
AWSKEY="$HOME/.ssh/forums.pem"
AWSCRED_KEYID="host's-IAM-key-id"
AWSCRED_SECRET="host's-IAM-key-secret"
AWS_CRON_SNS_TOPIC="your-cron-SNS-topic"

# run on mothership machine

SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd forums && sudo tar zcvf /tmp/overlay-forums.tar.gz .)

# bash conveniences
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.screenrc \
           $HOME/.dir_colors"

# remote setup scripts
FILESTOGO+=" setup-there-common.sh setup-there-forums.sh fix-ec2-mail.py ec2-send-memory-metrics.py cron-mail-to-sns.py"

# overlay
FILESTOGO+=" /tmp/overlay-forums.tar.gz"

echo "Copying files to cloud host..."
scp $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST "/home/ec2-user/setup-there-common.sh ${AWSCRED_KEYID} ${AWSCRED_SECRET} ${AWS_CRON_SNS_TOPIC} && /home/ec2-user/setup-there-forums.sh"

rm -f /tmp/overlay-forums.tar.gz0

