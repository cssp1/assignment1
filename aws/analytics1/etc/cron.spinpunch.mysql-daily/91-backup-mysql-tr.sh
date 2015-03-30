#!/bin/sh

exit 0 # XXX disabled by default

# to restore:
# gunzip -c ${GAME}_upcache.mysql.gz | perl -pe 's/\sDEFINER=`[^`]+`@`[^`]+`//' | mysql -u ... -p... --host ... ${GAME}_upcache
# (the Perl edit is to remove DEFINERs that refer to users that may not exist in the destination server)

GAME_DIR=/home/ec2-user/thunderrun
DB=tr_upcache
SAVE_DIR=/media/ephemeral0a/backup-scratch
S3_PATH="spinpunch-backups/analytics"

TARFILE=`date +%Y%m%d`-${DB}.mysql.gz
S3_KEYFILE=${HOME}/.ssh/`echo $HOSTNAME | cut -d. -f1`-awssecret
export AWS_ACCESS_KEY_ID=`head -n1 ${S3_KEYFILE}`
export AWS_SECRET_ACCESS_KEY=`head -n2 ${S3_KEYFILE} | tail -n1`
ERROR=0

cd $GAME_DIR/gameserver

./mysql.py ${DB} --dump "${SAVE_DIR}/${TARFILE}"
if [[ $? != 0 ]]; then
    echo "SQL dump error"
    exit $?
fi

/usr/bin/env aws s3 cp --quiet "${SAVE_DIR}/${TARFILE}" "s3://${S3_PATH}/${TARFILE}"
if [[ $? != 0 ]]; then
    echo "S3 upload error!"
    ERROR=1
fi

rm -f "${SAVE_DIR}/${TARFILE}"

exit $ERROR
