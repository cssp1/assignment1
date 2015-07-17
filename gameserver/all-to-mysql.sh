#!/bin/sh

# run all MongoDB/upcache-to-MySQL ETL scripts for one game title

GAME_ID=`grep '"game_id":' config.json  | cut -d\" -f4 | sed 's/test//'`
LOG=/var/tmp/etl.txt

echo `date` "${GAME_ID} === ETL run start ===" >> ${LOG}

# things needed for battles and battles_risk_reward
./stats_to_sql.py -q > /dev/null
echo `date` "${GAME_ID} stats done" >> ${LOG}
./credits_to_mysql.py -q > /dev/null
echo `date` "${GAME_ID} credits done" >> ${LOG}
./gamebucks_to_mysql.py -q --unit-cost --prune > /dev/null
echo `date` "${GAME_ID} gamebucks done" >> ${LOG}
./battles_to_mysql.py -q --prune > /dev/null
echo `date` "${GAME_ID} battles done" >> ${LOG}
./battle_risk_reward_to_sql.py -q > /dev/null # requires battles, store (gamebucks), stats
echo `date` "${GAME_ID} battle_risk_reward done" >> ${LOG}

# things needed for analytics-views, with sessions last
./metrics_to_mysql.py -q --prune > /dev/null
echo `date` "${GAME_ID} metrics done" >> ${LOG}
./fb_notifications_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} fb_notifications done" >> ${LOG}
./fb_requests_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} fb_requests done" >> ${LOG}
./fb_sharing_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} fb_sharing done" >> ${LOG}
./fb_permissions_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} fb_permissions done" >> ${LOG}
./fb_open_graph_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} fb_open_graph done" >> ${LOG}

./sessions_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} sessions done" >> ${LOG}

# analytics-views
./update-analytics-views.sh > /dev/null # requires sessions, metrics, facebook_campaign_map (currently from upcache), fb_notifications, fb_permissions, credits, battles, battle_risk_reward
echo `date` "${GAME_ID} analytics-views done" >> ${LOG}

./map_to_mysql.py -q > /dev/null
echo `date` "${GAME_ID} map done" >> ${LOG}
./purchase_ui_to_sql.py -q > /dev/null
echo `date` "${GAME_ID} purchase_ui done" >> ${LOG}
./damage_protection_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} damage_protection done" >> ${LOG}
./ladder_pvp_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} ladder_pvp done" >> ${LOG}
./client_trouble_to_sql.py -q --prune --optimize > /dev/null
echo `date` "${GAME_ID} client_trouble done" >> ${LOG}
./chat_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} chat done" >> ${LOG}
./econ_res_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} econ_res done" >> ${LOG}
./inventory_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} inventory done" >> ${LOG}
./unit_donation_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} unit_donation done" >> ${LOG}
./fishing_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} fishing done" >> ${LOG}
./quests_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} quests done" >> ${LOG}
./lottery_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} lottery done" >> ${LOG}
./achievements_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} achievements done" >> ${LOG}
./login_flow_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} login_flow done" >> ${LOG}
./login_sources_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} login_sources done" >> ${LOG}
./activity_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} activity done" >> ${LOG}
./alliance_events_to_sql.py -q --prune > /dev/null
echo `date` "${GAME_ID} alliance_events done" >> ${LOG}
./alliance_state_to_sql.py -q > /dev/null
echo `date` "${GAME_ID} alliance_state done" >> ${LOG}
./skynet_conversion_pixels_to_sql.py -q
echo `date` "${GAME_ID} skynet_conversion_pixels done" >> ${LOG}
./schedule_to_sql.py --workspace 'spinpunch.com' --project 'SHIP Schedule' --project 'Market Research' -q > /dev/null
echo `date` "${GAME_ID} schedule done" >> ${LOG}

# upcache is slowest

UPCACHE_FLAGS=""
if [[ "$GAME_ID" == "mf" ]]; then
    UPCACHE_FLAGS+=" --lite"
fi    

./upcache_to_mysql.py -q --parallel 8 $UPCACHE_FLAGS > /dev/null
echo `date` "${GAME_ID} UPCACHE done" >> ${LOG}
./cur_levels_to_sql.py -q > /dev/null # requires upcache
echo `date` "${GAME_ID} cur_levels done" >> ${LOG}
./acquisitions_to_sql.py -q > /dev/null # requires upcache and analytics-views
echo `date` "${GAME_ID} acquisitions done" >> ${LOG}

echo `date` "${GAME_ID} === ETL run done ===" >> ${LOG}
