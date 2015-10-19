#!/bin/bash

AWSHOST="example.compute-1.amazonaws.com"
AWSKEY="$HOME/.ssh/gamemaster.pem"
AWSCRED_KEYID="host's-IAM-key-id"
AWSCRED_SECRET="host's-IAM-key-secret"
AWS_CRON_SNS_TOPIC="your-cron-SNS-topic"

SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd gamemaster && sudo tar zcvf /tmp/overlay-gamemaster.tar.gz .)

# bash conveniences
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.screenrc \
           $HOME/.dir_colors"

# remote setup scripts
FILESTOGO+=" setup-there-common.sh setup-there-gamemaster.sh fix-ec2-mail.py ec2-send-memory-metrics.py cron-mail-to-sns.py"

# overlay
FILESTOGO+=" /tmp/overlay-gamemaster.tar.gz"

echo "Copying files to cloud host..."
scp $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST "/home/ec2-user/setup-there-common.sh ${AWSCRED_KEYID} ${AWSCRED_SECRET} ${AWS_CRON_SNS_TOPIC} && /home/ec2-user/setup-there-gamemaster.sh"

rm -f /tmp/overlay-gamemaster.tar.gz
