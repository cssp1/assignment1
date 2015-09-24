#!/bin/bash

# query tournament winners, send prizes, record results to file, and SNS broadcast result.

. /etc/spinpunch

if [ $# -ne 4 ]; then
    echo "Usage: tournament-winners.sh END_TIME SEASON# WEEK# STAT"
    exit 1
fi

END_TIME=$1
SEASON=$2
WEEK=$3
TOURNAMENT_STAT=$4

sleep `python -c "import time; print int(${END_TIME}-time.time());"`
for CONT in $GAME_TOURNAMENT_CONTINENTS; do
    LOGFILE="/var/tmp/`date +%s`-winners-s${SEASON}-wk${WEEK}-${CONT}.txt"
    ./SpinNoSQL.py --winners --season ${SEASON} --week ${WEEK} --tournament-stat ${TOURNAMENT_STAT} --score-scope continent --score-loc $CONT --send-prizes > $LOGFILE
    /usr/bin/aws sns publish --topic-arn ${GAME_TOURNAMENT_WINNERS_SNS_TOPIC} --subject "${GAME_ID} ${CONT} Winners" --message "`cat ${LOGFILE}`" > /dev/null
done


