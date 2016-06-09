#!/bin/bash

# query tournament winners, send prizes, record results to file, and upload/broadcast results.

. /etc/spinpunch

# check for various files in the environment that we'll need to run all steps
for VITAL_FILE in "${HOME}/.aws/credentials" "${HOME}/.aws/config" "${HOME}/.ssh/dropbox-access-token"; do
    if [ ! -r "${VITAL_FILE}" ]; then
        echo "Credential file missing: ${VITAL_FILE}"
        exit 1
    fi
done

if [ $# -ne 5 ]; then
    echo "Usage: tournament-winners.sh END_TIME SEASON# WEEK# STAT TIME_SCOPE"
    exit 1
fi

END_TIME=$1
SEASON=$2
WEEK=$3
TOURNAMENT_STAT=$4
TIME_SCOPE=$5

DROPBOX_ACCESS_TOKEN=`cat ${HOME}/.ssh/dropbox-access-token`
GAME_ID_UPPER=`echo ${GAME_ID} | tr a-z A-Z`
GAME_TOURNAMENT_CONTINENTS=`./SpinConfig.py --getvar tournament_continents | python -c 'import json, sys; print " ".join(json.load(sys.stdin))'`

declare -A PLATFORM_UI_NAMES
PLATFORM_UI_NAMES[fb]=Facebook
PLATFORM_UI_NAMES[ag]=ArmorGames
PLATFORM_UI_NAMES[kg]=Kongregate

# wait for end time to come
WAIT_SECONDS=`python -c "import time; print int(${END_TIME}-time.time());"`
if [[ $WAIT_SECONDS -gt 0 ]]; then
    sleep $WAIT_SECONDS
fi

for CONT in $GAME_TOURNAMENT_CONTINENTS; do
    NUMERIC_DATE=`date +%Y%m%d`
    LOGFILE="/var/tmp/`date +%s`-winners-s${SEASON}-wk${WEEK}-${CONT}.txt"
    UI_PLATFORM="${PLATFORM_UI_NAMES[$CONT]}"

    # get winner list and award prizes
    ./SpinNoSQL.py --winners --season ${SEASON} --week ${WEEK} --tournament-stat ${TOURNAMENT_STAT} \
           --score-time-scope ${TIME_SCOPE} \
           --score-space-scope continent --score-space-loc $CONT \
           --send-prizes > $LOGFILE

    # upload to dropbox
    DROPBOX_FILENAME="${NUMERIC_DATE}-${GAME_ID_UPPER}-winners-week${WEEK}-${UI_PLATFORM}.txt"
    DROPBOX_PATH="/tournament_winners/${DROPBOX_FILENAME}"
    echo "DROPBOX_PATH=${DROPBOX_PATH}" >> $LOGFILE

    UPLOAD_RESULT=`curl -s -X POST https://content.dropboxapi.com/2/files/upload \
     --header "Authorization: Bearer ${DROPBOX_ACCESS_TOKEN}" \
     --header "Content-Type: application/octet-stream" \
     --header "Dropbox-API-Arg: {\"path\": \"${DROPBOX_PATH}\",\"mode\": \"overwrite\",\"autorename\": false,\"mute\": false}" \
     --data-binary "@${LOGFILE}"`
    echo "UPLOAD_RESULT=${UPLOAD_RESULT}" >> $LOGFILE

    # check for validity by parsing returned JSON
    UPLOAD_PATH=`echo $UPLOAD_RESULT | python -c 'import json, sys; ret = json.load(sys.stdin); "name" in ret or sys.exit(1); print ret["name"];'`
    if [[ $? -ne 0 ]]; then
        # Dropbox upload seems to have failed
        SHARED_LINK_URL='(Dropbox upload failed! - Follow up with dev)'
    else
        # get dropbox shared link
        SHARED_LINK_RESULT=`curl -s -X POST https://api.dropboxapi.com/2/sharing/create_shared_link \
         --header "Authorization: Bearer ${DROPBOX_ACCESS_TOKEN}" \
         --header "Content-Type: application/json" \
         --data "{\"path\": \"${DROPBOX_PATH}\",\"short_url\": false,\"pending_upload\":\"file\"}"`
        echo "SHARED_LINK_RESULT=${SHARED_LINK_RESULT}" >> $LOGFILE
        SHARED_LINK_URL=`echo $SHARED_LINK_RESULT | python -c 'import json, sys; ret = json.load(sys.stdin); "url" in ret or sys.exit(1); print ret["url"];'`
        if [[ $? -ne 0 ]]; then
            SHARED_LINK_URL='(Dropbox upload succeeded, but shared link creation failed! - Follow up with dev)'
        fi
    fi
    echo "SHARED_LINK_URL=${SHARED_LINK_URL}" >> $LOGFILE

    # compile notification
    NOTIFICATION_SUBJECT="${NUMERIC_DATE} ${GAME_ID_UPPER} Tournament Winners in ${UI_PLATFORM}"
    NOTIFICATION_MESSAGE_BRIEF="Prizes have been sent. Winner list at: ${SHARED_LINK_URL}"
    NEWLINE=$'\n'
    NOTIFICATION_MESSAGE_FULL="${NOTIFICATION_MESSAGE_BRIEF}${NEWLINE}`cat ${LOGFILE}`"

    # send SNS notification
    /usr/bin/aws sns publish --topic-arn "`./SpinConfig.py --getvar tournament_winners_sns_topic --getvar-format raw`" --subject "${NOTIFICATION_SUBJECT}" --message "${NOTIFICATION_MESSAGE_FULL}" > /dev/null

    # send SpinReminder notification
    ./SpinReminders.py --from "tournament-winners.sh" --subject "${NOTIFICATION_SUBJECT}" --body "${NOTIFICATION_MESSAGE_BRIEF}" \
               --recipients "`./SpinConfig.py --getvar tournament_winners_recipients`"
done


