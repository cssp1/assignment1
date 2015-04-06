#!/bin/bash

AWSHOST="example.compute-1.amazonaws.com"
AWSKEY="$HOME/.ssh/analytics1.pem"

# run on mothership machine

SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd analytics1 && find . -not -path '*.svn*' | cpio -o | gzip -c > /tmp/overlay-analytics1.cpio.gz)

# bash conveniences
FILESTOGO=$HOME/.bashrc $HOME/.bash_profile $HOME/.dir_colors

# remote setup scripts
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.dir_colors"

# remote setup scripts
FILESTOGO+=" setup-there-common.sh setup-there-analytics1.sh fix-ec2-mail.py ec2-send-memory-metrics.py"

# overlay
FILESTOGO+=" /tmp/overlay-analytics1.cpio.gz"

echo "Copying files to cloud host..."
scp $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST /home/ec2-user/setup-there-analytics1.sh

rm -f /tmp/overlay-analytics1.cpio.gz
