#!/bin/bash

AWSHOST="example.compute-1.amazonaws.com"
AWSKEY="$HOME/.ssh/www.pem"
AWSCRED_KEYID="host's-IAM-key-id"
AWSCRED_SECRET="host's-IAM-key-secret"
AWS_CRON_SNS_TOPIC="your-cron-SNS-topic"

# run on mothership machine

SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd www && sudo tar zcvf /tmp/overlay-www.tar.gz .)

# bash conveniences
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.screenrc \
           $HOME/.dir_colors"

# remote setup scripts
FILESTOGO+=" setup-there-common.sh setup-there-www.sh fix-ec2-mail.py ec2-send-memory-metrics.py cron-mail-to-sns.py"

# overlay
FILESTOGO+=" /tmp/overlay-www.tar.gz"

echo "Copying files to cloud host..."
scp $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST "/home/ec2-user/setup-there-common.sh ${AWSCRED_KEYID} ${AWSCRED_SECRET} ${AWS_CRON_SNS_TOPIC} && /home/ec2-user/setup-there-www.sh"

rm -f /tmp/overlay-www.tar.gz
