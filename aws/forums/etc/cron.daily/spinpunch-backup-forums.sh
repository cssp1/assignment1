#!/bin/bash

AWS_USER=ec2-user

# shut up aws script sanity-check warnings
touch /home/$AWS_USER/.awsrc

SAVE_DIR=/tmp
ERROR=0
TARFILE=spinpunch-forums-backup-`date +%Y%m%d`.tar.gz

# back up SQL databases
(cd $SAVE_DIR && mysqldump --events '-uroot' -p`cat /home/$AWS_USER/.ssh/forums-mysql-root-password` mysql > backup-mysql.sql)
(cd $SAVE_DIR && mysqldump --events '-uroot' -p`cat /home/$AWS_USER/.ssh/forums-mysql-root-password` vbulletin > backup-vbulletin.sql)

# back up website files
(cd / && tar cf $SAVE_DIR/backup-www.tar var/www)

# stuff everything in one .tar.gz file
(cd $SAVE_DIR && tar zcf $TARFILE backup-www.tar backup-*.sql)

# upload to AWS
/home/$AWS_USER/aws --secrets-file="/home/$AWS_USER/.ssh/forums-awssecret" --md5 put spinpunch-forums/$TARFILE $SAVE_DIR/$TARFILE
if [[ $? != 0 ]]; then
    echo "S3 upload error!"
    ERROR=1
fi

# remove all files
(cd $SAVE_DIR && rm -f backup-www.tar backup-*.sql $TARFILE)

exit $ERROR
