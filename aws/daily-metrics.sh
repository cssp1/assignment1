#!/bin/bash

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# script to upload metrics/log data to S3 and perform analytics
# this processes the previous (UTC) day's metrics and uploads JSON, CSV, and text files to S3

SCRIPT_DIR=`dirname $0`
HOST=`hostname | sed 's/.spinpunch.com//'`
S3_KEYFILE=/home/ec2-user/.ssh/${HOST}-awssecret

while getopts "s:d:m:" flag
do
    case $flag in
    s)
        UI_MAIL_SENDER="$OPTARG"
        ;;
    d)
        GAME_DIR="$OPTARG"
        ;;
    m)
        UNUSED_MAIL_RECIPIENTS="$OPTARG" # replaced by SpinConfig heartbeat_recipients
        ;;
    esac
done


# put temporary files in this directory
SAVE_DIR=/tmp

ERROR=0

if [ ! -e "$GAME_DIR" ]; then
    echo "usage: $0 -d GAME_DIR"
    exit 1
fi

if [ -f "$GAME_DIR/gameserver/logs/ZZZ_DISABLE_METRICS" ]; then
    echo "metrics disabled manually" 1>&2
    exit 0
fi

# shut up aws script sanity-check warnings
touch $HOME/.awsrc

GAME_NAME=`basename $GAME_DIR`
GAME_ID=`(cd $GAME_DIR/gameserver && ./SpinConfig.py --getvar game_id --getvar-format raw)`
GAME_ID_UPPER=`echo ${GAME_ID} | tr [a-z] [A-Z]`

TODAY=`date +%Y%m%d`
# process both yesterday and today's logs, to ensure nothing is missed
if [[ `uname` == "Darwin" ]]; then
    # OSX
    YESTERDAY=`date -v-1d +%Y%m%d`
else
    # GNU
    YESTERDAY=`date +%Y%m%d -d yesterday`
fi

SMS_DAY="$YESTERDAY"

SMSFILE=$SAVE_DIR/sms.$$
echo -n "$GAME_NAME " > $SMSFILE
#date '+%b %d %H:%MUTC ' | tr -d '\n' >> $SMSFILE

for DAY in $YESTERDAY; do
    MONTH=${DAY:0:6}

    # gzip and upload raw logs - replaced by archive_mongodb_logs.py
    # credits.json and fbrtapi.txt also replaced by archive_mongodb_logs.py
#    for NAME in metrics.json gamebucks.json; do
#    INPUT=$GAME_DIR/gameserver/logs/$DAY-$NAME
#    if [ ! -f "$INPUT" ]; then
#        # skip missing files
#        continue
#    fi
#
#    ZIPFILE=$GAME_NAME-$DAY-$NAME.gz
#    gzip -c $INPUT > $SAVE_DIR/$ZIPFILE
#
#    echo "uploading $ZIPFILE to S3..."
#    aws s3 cp $SAVE_DIR/$ZIPFILE s3://spinpunch-logs/$MONTH/$ZIPFILE
#    if [[ $? != 0 ]]; then
#        echo "S3 upload error!"
#        ERROR=1
#    fi
#
#    rm -f $SAVE_DIR/$ZIPFILE
#   done

    # zip and upload raw logs - replaced by archive_mongodb_logs.py
#    for NAME in pcheck.json adotomi.json dauup.json dauup2.json adparlor.json liniad.json fb_conversion_pixels.json; do
#    INPUT=$GAME_DIR/gameserver/logs/$DAY-$NAME
#    if [ ! -f "$INPUT" ]; then
#        # skip missing files
#        continue
#    fi
#
#    SRCFILE=$GAME_NAME-$DAY-$NAME
#    ZIP=$SRCFILE.zip
#    echo "uploading $ZIP to S3..."
#    cp $INPUT $SAVE_DIR/$SRCFILE
#    (cd $SAVE_DIR && zip $ZIP $SRCFILE && rm -f $SRCFILE)
#    aws s3 cp $SAVE_DIR/$ZIP s3://spinpunch-logs/$MONTH/$ZIP
#    if [[ $? != 0 ]]; then
#        echo "S3 upload error!"
#        ERROR=1
#    fi
#    rm -f $SAVE_DIR/$ZIP
#   done

    # run JSON-to-CSV conversion on metrics and machine logs only

    # file to store conversion output
#    TOTALSFILE=$GAME_NAME-$DAY-totals.txt
#    echo -n "" > $SAVE_DIR/$TOTALSFILE
#
#    for NAME in metrics credits; do
#    INPUT=$DAY-$NAME.json
#    if [ ! -f "$GAME_DIR/gameserver/logs/$INPUT" ]; then
#        # skip missing files
#        continue
#    fi
#
#    echo "getting totals from $INPUT..."
#    echo "$INPUT" >> $SAVE_DIR/$TOTALSFILE
#    (cd $GAME_DIR/gameserver && ./json_to_csv.py --totals-only --categories --mode $NAME logs/$INPUT > /dev/null 2>> $SAVE_DIR/$TOTALSFILE)
#    done
#
#    echo "uploading $TOTALSFILE to S3..."
#    aws s3 cp $SAVE_DIR/$TOTALSFILE s3://spinpunch-logs/$MONTH/$TOTALSFILE
#    if [[ $? != 0 ]]; then
#    echo "S3 upload error!"
#    ERROR=1
#    fi
#    rm -f $SAVE_DIR/$TOTALSFILE

    if [ "$DAY" == "$SMS_DAY" ]; then
    (cd $GAME_DIR/gameserver && ./get_heartbeat.py --date $SMS_DAY >> $SMSFILE)
    fi

done

# send SMS update
echo "sending SMS message..."
(cd $GAME_DIR/gameserver && \
    ./SpinReminders.py \
        --body-from "$SMSFILE" --from "$UI_MAIL_SENDER" --subject "${GAME_ID_UPPER} Heartbeat" \
        --recipients "`(cd ${GAME_DIR}/gameserver && ./SpinConfig.py --getvar heartbeat_recipients)`")
rm -f "$SMSFILE"

exit $ERROR
