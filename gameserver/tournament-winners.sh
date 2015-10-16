#!/bin/bash

# query tournament winners, send prizes, record results to file, and upload/broadcast results.

. /etc/spinpunch

if [ $# -ne 4 ]; then
    echo "Usage: tournament-winners.sh END_TIME SEASON# WEEK# STAT"
    exit 1
fi

END_TIME=$1
SEASON=$2
WEEK=$3
TOURNAMENT_STAT=$4

DROPBOX_ACCESS_TOKEN=`cat ${HOME}/.ssh/dropbox-access-token`
GAME_ID_UPPER=`echo ${GAME_ID} | tr a-z A-Z`
GAME_TOURNAMENT_CONTINENTS=`./SpinConfig.py --getvar tournament_continents | python -c 'import json, sys; print " ".join(json.load(sys.stdin))'`

declare -A PLATFORM_UI_NAMES
PLATFORM_UI_NAMES[fb]=Facebook
PLATFORM_UI_NAMES[ag]=ArmorGames
PLATFORM_UI_NAMES[kg]=Kongregate

sleep `python -c "import time; print int(${END_TIME}-time.time());"`
for CONT in $GAME_TOURNAMENT_CONTINENTS; do
    NUMERIC_DATE=`date +%Y%m%d`
    LOGFILE="/var/tmp/`date +%s`-winners-s${SEASON}-wk${WEEK}-${CONT}.txt"
    UI_PLATFORM="${PLATFORM_UI_NAMES[$CONT]}"

    # get winner list and award prizes
    ./SpinNoSQL.py --winners --season ${SEASON} --week ${WEEK} --tournament-stat ${TOURNAMENT_STAT} --score-scope continent --score-loc $CONT --send-prizes > $LOGFILE

    # upload to dropbox
    DROPBOX_FILENAME="${NUMERIC_DATE}-${GAME_ID_UPPER}-winners-week${WEEK}-${UI_PLATFORM}.txt"
    DROPBOX_PATH="/tournament_winners/${DROPBOX_FILENAME}"

    curl -s -X POST https://content.dropboxapi.com/2-beta-2/files/upload \
     --header "Authorization: Bearer ${DROPBOX_ACCESS_TOKEN}" \
     --header "Content-Type: application/octet-stream" \
     --header "Dropbox-API-Arg: {\"path\": \"${DROPBOX_PATH}\",\"mode\": \"overwrite\",\"autorename\": false,\"mute\": false}" \
     --data-binary "@${LOGFILE}" > /dev/null

    # get dropbox shared link
    SHARED_LINK_RESULT=`curl -s -X POST https://api.dropboxapi.com/2-beta-2/sharing/create_shared_link \
     --header "Authorization: Bearer ${DROPBOX_ACCESS_TOKEN}" \
     --header "Content-Type: application/json" \
     --data "{\"path\": \"${DROPBOX_PATH}\",\"short_url\": false}"`
    SHARED_LINK_URL=`echo $SHARED_LINK_RESULT | python -c 'import json, sys; print json.load(sys.stdin)["url"];'`

    # compile notification
    NOTIFICATION_SUBJECT="${NUMERIC_DATE} ${GAME_ID_UPPER} Tournament Winners in ${UI_PLATFORM}"
    NOTIFICATION_MESSAGE_BRIEF="Prizes have been sent. Winner list at: ${SHARED_LINK_URL}"
    NEWLINE=$'\n'
    NOTIFICATION_MESSAGE_FULL="${NOTIFICATION_MESSAGE_BRIEF}${NEWLINE}`cat ${LOGFILE}`"

    # send SNS notification
    /usr/bin/aws sns publish --topic-arn `./SpinConfig.py --getvar tournament_winners_sns_topic` --subject "${NOTIFICATION_SUBJECT}" --message "${NOTIFICATION_MESSAGE_FULL}" > /dev/null

    # send SpinReminder notification
    ./SpinReminders.py --from "tournament-winners.sh" --subject "${NOTIFICATION_SUBJECT}" --body "${NOTIFICATION_MESSAGE_BRIEF}" \
               --recipients "`./SpinConfig.py --getvar tournament_winners_recipients`"
done


