#!/bin/bash

exit 0 # XXX disabled by default - make executable

# note: skynet queries should be run from the thunderrun sandbox
GAME_DIR=/home/ec2-user/thunderrun

(cd $GAME_DIR && ./scmtool.sh force-up > /dev/null)

#(cd $GAME_DIR/gameserver && \
#    ./skynet.py --mode adcampaigns-pull > /dev/null && \
#    ./skynet.py --mode adgroups-pull > /dev/null )

# update SQL views
(cd $GAME_DIR/gameserver && ./mysql.py skynet < skynet_views.sql > /dev/null)
(cd $GAME_DIR/gameserver && ./skynet_summary_to_sql.py -q > /dev/null)
#(cd $GAME_DIR/gameserver && ./mysql.py skynet < cross_promo_views.sql > /dev/null)
(cd $GAME_DIR/gameserver && ./cross_promo_summary_to_sql.py -q > /dev/null)

QUERY_DATE_RANGE=`date +%m/%d/%Y -d "today -7 days"`-`date +%m/%d/%Y -d "today"`
FILENAME_DATE_RANGE=`date +%Y%m%d -d "today -7 days"`-`date +%Y%m%d -d "today - 1 day"`

for GAME_ID in mf2 tr bfm sg; do
    GAME_ID_UPPER=`echo $GAME_ID | tr a-z A-Z`
    FILE_NAME=skynet-${GAME_ID}-${FILENAME_DATE_RANGE}.csv
    FILE_PATH=/tmp/$FILE_NAME
#    if [ "$GAME_ID" = "tr" ]; then
#    GAME_FILTER="aMISSING"
#    else
    GAME_FILTER="a${GAME_ID}"
#    fi

    if false; then
    (cd $GAME_DIR/gameserver && \
        ./skynet.py --mode adstats-analyze --filter $GAME_FILTER --date-range $QUERY_DATE_RANGE --output-format csv --output-frequency day --quiet --use-record a > $FILE_PATH && \
        ../aws/text-message.py \
        --sender-name "Skynet ${GAME_ID_UPPER}" --recipient "asdf@example.com" \
        --subject "Skynet ${GAME_ID_UPPER} `date +%m/%d/%Y`" \
        --body "Attached" \
        --attach $FILE_PATH \
        )
    fi
#    rm -f $FILE_PATH
done
