#!/bin/bash

AWS_USER=ec2-user

SAVE_DIR=/tmp
ERROR=0
TARFILE=spinpunch-www-backup-`date +%Y%m%d`.tar.gz

# back up SQL databases
(cd $SAVE_DIR && mysqldump --events '-uroot' -p`cat /home/$AWS_USER/.ssh/www-mysql-root-password` mysql > backup-mysql.sql)
(cd $SAVE_DIR && mysqldump --events '-uroot' -p`cat /home/$AWS_USER/.ssh/www-mysql-root-password` spinpunch_wordpress > backup-spinpunch_wordpress.sql)

# back up website files
(cd / && tar cf $SAVE_DIR/backup-www.tar etc/httpd/conf/httpd.conf var/www)

# stuff everything in one .tar.gz file
(cd $SAVE_DIR && tar zcf $TARFILE backup-www.tar backup-*.sql)

# upload to AWS
export AWS_SHARED_CREDENTIALS_FILE=/home/$AWS_USER/.aws/credentials
/usr/bin/aws s3 cp $SAVE_DIR/$TARFILE s3://spinpunch-www/$TARFILE --quiet
if [[ $? != 0 ]]; then
    echo "S3 upload error!"
    ERROR=1
fi

# remove all files
(cd $SAVE_DIR && rm -f backup-www.tar backup-*.sql $TARFILE)

exit $ERROR
