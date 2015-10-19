#!/bin/bash

AWSHOST="dvprod-mongo.spinpunch.com"
AWSKEY="$HOME/.ssh/dvprod.pem"
SYSTEM="mongo"
AWSCRED_KEYID="host's-IAM-key-id"
AWSCRED_SECRET="host's-IAM-key-secret"

# run on mothership machine

SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd "$SYSTEM" && find . -not -path '*.svn*' | cpio -o | gzip -c > /tmp/overlay-${SYSTEM}.cpio.gz)

# bash conveniences
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.screenrc \
           $HOME/.dir_colors"

# remote setup scripts
FILESTOGO+=" setup-there-common.sh setup-there-${SYSTEM}.sh fix-ec2-mail.py ec2-send-memory-metrics.py"

# overlay
FILESTOGO+=" /tmp/overlay-${SYSTEM}.cpio.gz"

echo "Copying files to cloud host..."
scp $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST "/home/ec2-user/setup-there-common.sh ${AWSCRED_KEYID} ${AWSCRED_SECRET} && /home/ec2-user/setup-there-${SYSTEM}.sh $SYSTEM"

rm -f /tmp/overlay-${SYSTEM}.cpio.gz
