#!/bin/sh

# backup script for MySQL analytics database

# to restore:
# gunzip -c ${GAME}_upcache.mysql.gz | perl -pe 's/\sDEFINER=`[^`]+`@`[^`]+`//' | mysql -u ... -p... --host ... ${GAME}_upcache
# (the Perl edit is to remove DEFINERs that refer to users that may not exist in the destination server)

GAME_ID=`grep '"game_id":' config.json  | cut -d\" -f4 | sed 's/test//'`
DBNAME=${GAME_ID}_upcache
SAVE_DIR=/media/backup-scratch
S3_PATH="spinpunch-backups/analytics"

while getopts "d:" flag
do
    case $flag in
    d)
        DBNAME="$OPTARG"
        ;;
    esac
done

TARFILE=`date +%Y%m%d`-${DBNAME}.mysql.gz
# S3_KEYFILE=${HOME}/.ssh/`echo $HOSTNAME | cut -d. -f1`-awssecret
# export AWS_ACCESS_KEY_ID=`head -n1 ${S3_KEYFILE}`
# export AWS_SECRET_ACCESS_KEY=`head -n2 ${S3_KEYFILE} | tail -n1`

tempfiles=( )
cleanup() {
    rm -f "${tempfiles[@]}"
}
trap cleanup 0

PIDFILE="/tmp/spin-singleton-backup-mysql-${DBNAME}.pid"
tempfiles+=( "${PIDFILE}" )
echo $$ > "${PIDFILE}"

tempfiles+=( "${SAVE_DIR}/${TARFILE}" )
./mysql.py "${DBNAME}" --dump "${SAVE_DIR}/${TARFILE}"
if [[ $? != 0 ]]; then
    echo "SQL dump error"
    exit $?
fi

/usr/bin/env aws s3 cp --quiet "${SAVE_DIR}/${TARFILE}" "s3://${S3_PATH}/${TARFILE}"
if [[ $? != 0 ]]; then
    echo "S3 upload error!"
    exit $?
fi
