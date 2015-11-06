#!/bin/sh

if [ $# -ne 2 ]; then
    echo "Usage: unlock-root.sh IP.amazon.com KEY.pem"
    exit 1
fi

SCRIPT_DIR=`dirname $0`
AWSHOST="$1"
AWSKEY="$2"
SSHDEST="ec2-user@$AWSHOST"
SSHARGS="-i $AWSKEY"

echo "Copying unlock script to cloud host..."
scp $SSHARGS ${SCRIPT_DIR}/unlock-root-there.sh $SSHDEST:/home/ec2-user

echo "Running unlock script on cloud host..."
ssh $SSHARGS -t $SSHDEST /home/ec2-user/unlock-root-there.sh

echo "Root login unlocked for $AWSHOST!"
