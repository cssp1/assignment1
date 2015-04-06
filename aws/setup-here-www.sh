#!/bin/bash

AWSHOST="example.compute-1.amazonaws.com"
AWSKEY="www.pem"

# run on mothership machine

SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd www && sudo tar zcvf ../overlay-www.tar.gz .)

# bash conveniences
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.dir_colors"

# remote setup scripts
FILESTOGO+=" setup-there-common.sh setup-there-www.sh fix-ec2-mail.py ec2-send-memory-metrics.py"

# overlay
FILESTOGO+=" overlay-www.tar.gz"

echo "Copying files to cloud host..."
scp $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST /home/ec2-user/setup-there-www.sh
