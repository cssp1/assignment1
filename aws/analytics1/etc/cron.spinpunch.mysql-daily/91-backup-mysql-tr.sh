#!/bin/sh

exit 0 # XXX disabled by default

GAME_DIR=/home/ec2-user/thunderrun
DB=tr_upcache
SAVE_DIR=/media/ephemeral0a/backup-scratch
S3_PATH="spinpunch-backups/analytics"

S3_KEYFILE=${HOME}/.ssh/`echo $HOSTNAME | cut -d. -f1`-awssecret
TARFILE=`date +%Y%m%d`-${DB}.mysql.gz
ERROR=0

cd $GAME_DIR/gameserver

./mysql.py ${DB} --dump "${SAVE_DIR}/${TARFILE}"
if [[ $? != 0 ]]; then
    echo "SQL dump error"
    exit $?
fi

$GAME_DIR/aws/aws --secrets-file=${S3_KEYFILE} --md5 put "${S3_PATH}/${TARFILE}" "${SAVE_DIR}/${TARFILE}"
if [[ $? != 0 ]]; then
    echo "S3 upload error!"
    ERROR=1
fi

rm -f "${SAVE_DIR}/${TARFILE}"

exit $ERROR
