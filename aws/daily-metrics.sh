#!/bin/bash

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# script to upload metrics/log data to S3 and perform analytics
# this processes the previous (UTC) day's metrics and uploads JSON, CSV, and text files to S3

SCRIPT_DIR=`dirname $0`

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
