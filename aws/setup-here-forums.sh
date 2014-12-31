#!/bin/bash

AWSHOST="forums.spinpunch.com"
AWSKEY="./forums.pem"

# run on mothership machine

SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd forums && sudo tar zcvf ../overlay-forums.tar.gz .)

# bash conveniences
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.dir_colors"

# remote setup scripts
FILESTOGO+=" setup-there-common.sh setup-there-forums.sh fix-ec2-mail.py"

# overlay
FILESTOGO+=" overlay-forums.tar.gz"

echo "Copying files to cloud host..."
scp $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST /home/ec2-user/setup-there-forums.sh
