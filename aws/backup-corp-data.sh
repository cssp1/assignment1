#!/bin/bash

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# basic script to back up mutable data on the company AWS server
# note: the user running this script must have read permission on /var/svn and /var/www

SCRIPT_DIR=`dirname $0`
SAVE_DIR=/media/aux2/tmp
ERROR=0
TARFILE=spinpunch-svn-backup-`date +%Y%m%d`.tar.gz
S3_DEST="spinpunch-backups/spinpunch-svn/$TARFILE"

echo "backing up SVN repository..."
(cd / && tar cf $SAVE_DIR/backup-svn.tar var/svn)

echo "creating $SAVE_DIR/$TARFILE..."
(cd $SAVE_DIR && tar zcvf $TARFILE backup-svn.tar) # backup-*.sql)

# remove temporary files
echo "removing temp files..."
(cd $SAVE_DIR && rm -f backup-svn.tar backup-*.sql)

echo "uploading $SAVE_DIR/$TARFILE to S3 spinpunch-backups..."
$SCRIPT_DIR/aws --secrets-file="/home/ec2-user/.ssh/gamemaster-backups-awssecret" --md5 put "$S3_DEST" "$SAVE_DIR/$TARFILE"
if [[ $? != 0 ]]; then
    echo "S3 upload error!"
    ERROR=1
else
    echo "done!"
fi

rm -f $SAVE_DIR/$TARFILE

exit $ERROR
