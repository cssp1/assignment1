#!/bin/bash

AWSHOST="example.compute-1.amazonaws.com"
AWSKEY="$HOME/.ssh/www.pem"
AWSCRED_KEYID="host's-IAM-key-id"
AWSCRED_SECRET="host's-IAM-key-secret"
AWS_CRON_SNS_TOPIC="your-cron-SNS-topic"
KIND="www" # one of: analytics1, forums, gamemaster, mongo, prod, www
GAME_ID="eg" # only for "prod" server type
GAME_ID_LONG="example" # only for "prod" server type

# run on mothership machine

SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd "${KIND}" && sudo tar zcvf "/tmp/overlay-${KIND}.tar.gz" .)

# bash conveniences
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.screenrc \
           $HOME/.dir_colors \
           $HOME/.nanorc $HOME/.nano"

# remote setup scripts
FILESTOGO+=" setup-there-common.sh setup-there-${KIND}.sh fix-ec2-mail.py ec2-send-memory-metrics.py cron-mail-to-sns.py"

# overlay
FILESTOGO+=" /tmp/overlay-${KIND}.tar.gz"

echo "Copying files to cloud host..."
scp -r $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST "/home/ec2-user/setup-there-common.sh ${AWSCRED_KEYID} ${AWSCRED_SECRET} ${AWS_CRON_SNS_TOPIC} && /home/ec2-user/setup-there-${KIND}.sh ${GAME_ID} ${GAME_ID_LONG}"

rm -f "/tmp/overlay-${KIND}.tar.gz"
