#!/bin/bash

# run all MongoDB/upcache-to-MySQL ETL scripts for one game title

GAME_ID=`grep '"game_id":' config.json  | cut -d\" -f4 | sed 's/test//'`
FREQ="unknown"
LOG="/var/tmp/etl-${GAME_ID}.txt"
RUN_ID=`date +%Y%m%d%H%M%S`

while getopts "f:" flag
do
  case $flag in
    f)
      FREQ="$OPTARG"
      ;;
  esac
done

if [[ "$FREQ" == "hourly" ]] && [ -e /tmp/spin-singleton-backup-mysql-${GAME_ID}*.pid ]; then
    echo `date` "${GAME_ID} === ${FREQ} ETL run ${RUN_ID} skipped because MySQL backup is in progress ===" >> ${LOG}
    echo "MySQL backup in progress - skipping hourly ETL run"
    exit 0
fi

RUN_START_TS=`date +%s`

echo `date` "${GAME_ID} === ${FREQ} ETL run ${RUN_ID} start ===" >> ${LOG}

# run a command, writing the time it took to the log as well as the command name
function run_it {
    TIME_TEMPFILE="/var/tmp/etl-${GAME_ID}-${RUN_ID}-time.txt"
    TIME_FMT="%Uuser %Ssystem %Eelapsed %PCPU %Mk max"
    UI_CMD=`basename $1`
    echo `date` "${GAME_ID} run ${RUN_ID} ${UI_CMD} START" >> ${LOG}
    /usr/bin/time -f "${TIME_FMT}" -o "${TIME_TEMPFILE}" "$@" > /dev/null
    echo `date` "${GAME_ID} run ${RUN_ID} ${UI_CMD} DONE:" `cat ${TIME_TEMPFILE}` >> ${LOG}
    /bin/rm -f "${TIME_TEMPFILE}"
}

if [[ "$FREQ" == "daily" ]]; then

  # BEGIN daily

  # things needed for battles and battles_risk_reward
  run_it ./stats_to_sql.py -q

  # credits - done hourly
  # gamebucks - done hourly

  run_it ./ai_bases_to_mysql.py -q
  run_it ./battles_to_mysql.py -q --prune
  run_it ./battle_risk_reward_to_sql.py -q # requires battles, store (gamebucks), stats

  # things needed for analytics-views, with sessions last
  run_it ./metrics_to_mysql.py -q --prune

  # fb_notifications - done hourly
  run_it ./fb_requests_to_sql.py -q --prune
  run_it ./fb_sharing_to_sql.py -q --prune
  run_it ./fb_permissions_to_sql.py -q --prune
  run_it ./fb_open_graph_to_sql.py -q --prune

  # sessions - done hourly

  # analytics-views
  run_it ./update-analytics-views.sh # requires sessions, metrics, facebook_campaign_map (currently from upcache), fb_notifications, fb_permissions, credits, battles, battle_risk_reward

  run_it ./map_to_mysql.py -q
  run_it ./damage_protection_to_sql.py -q --prune
  run_it ./ladder_pvp_to_sql.py -q --prune
  run_it ./chat_to_sql.py -q --prune
  run_it ./chat_reports_to_sql.py -q --prune
  run_it ./inventory_to_sql.py -q --prune
  run_it ./unit_donation_to_sql.py -q --prune
  run_it ./fishing_to_sql.py -q --prune
  run_it ./quests_to_sql.py -q --prune
  run_it ./achievements_to_sql.py -q --prune
  run_it ./login_flow_to_sql.py -q --prune
  run_it ./login_sources_to_sql.py -q --prune
  run_it ./activity_to_sql.py -q --prune
  run_it ./alliance_events_to_sql.py -q --prune
  run_it ./alliance_state_to_sql.py -q
  run_it ./skynet_conversion_pixels_to_sql.py -q
  run_it ./schedule_to_sql.py --workspace 'spinpunch.com' --project 'SHIP Schedule' --project 'Market Research' -q

  # upcache is slowest

  UPCACHE_FLAGS=""
  if [[ "$GAME_ID" == "mf" ]]; then
    UPCACHE_FLAGS+=" --lite"
  fi

  run_it ./upcache_to_mysql.py -q --parallel 8 $UPCACHE_FLAGS
  run_it ./cur_levels_to_sql.py -q # requires upcache
  run_it ./acquisitions_to_sql.py -q # requires upcache and analytics-views

  # END daily

elif [[ "$FREQ" == "hourly" ]]; then

  # BEGIN hourly

  run_it ./abtests_to_sql.py -q
  run_it ./credits_to_mysql.py -q
  run_it ./client_trouble_to_sql.py -q --prune --optimize
  run_it ./econ_res_to_sql.py -q --prune
  run_it ./gamebucks_to_mysql.py -q --unit-cost --prune
  run_it ./fb_notifications_to_sql.py -q --prune
  run_it ./policy_bot_to_sql.py -q --prune
  run_it ./sessions_to_sql.py -q --prune
  run_it ./purchase_ui_to_sql.py -q
  run_it ./lottery_to_sql.py -q --prune

  # END hourly

else
    echo 'unknown frequency: specify "-f hourly" or "-f daily"'
    exit 1
fi

RUN_END_TS=`date +%s`
RUN_SEC=$((RUN_END_TS - RUN_START_TS))
echo `date` "${GAME_ID} === ${FREQ} ETL run ${RUN_ID} done (${RUN_SEC} sec) ===" >> ${LOG}
