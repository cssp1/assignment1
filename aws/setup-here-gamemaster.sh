#!/bin/bash

. ./config.sh

# run on mothership machine

SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Building overlay tarball..."
(cd gamemaster && sudo tar zcvf ../overlay-gamemaster.tar.gz .)

# bash conveniences
FILESTOGO="$HOME/.bashrc \
           $HOME/.bash_profile \
           $HOME/.dir_colors"

# remote setup scripts
FILESTOGO+=" setup-there-common.sh setup-there-gamemaster.sh fix-ec2-mail.py"

# overlay
FILESTOGO+=" overlay-gamemaster.tar.gz"

echo "Copying files to cloud host..."
scp $SSHARGS $FILESTOGO $SSHDEST:/home/ec2-user

echo "Running setup script on cloud host..."
ssh $SSHARGS -t $SSHDEST /home/ec2-user/setup-there-gamemaster.sh
