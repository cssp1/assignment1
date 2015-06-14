#!/bin/sh

GAME_DIR=/home/ec2-user/thunderrun
LOG=/var/tmp/etl.txt


echo `date` "=== ETL run start ===" >> ${LOG}

# things needed for battles and battles_risk_reward
(cd $GAME_DIR/gameserver && nice ./stats_to_sql.py -q) > /dev/null
echo `date` "stats done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./credits_to_mysql.py -q) > /dev/null
echo `date` "credits done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./gamebucks_to_mysql.py -q --unit-cost --prune) > /dev/null
echo `date` "gamebucks done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./battles_to_mysql.py -q --prune) > /dev/null
echo `date` "battles done" >> ${LOG}
(cd $GAME_DIR/gameserver && ./battle_risk_reward_to_sql.py -q) > /dev/null # requires battles, store (gamebucks), stats
echo `date` "battle_risk_reward done" >> ${LOG}

# things needed for analytics-views, with sessions last
(cd $GAME_DIR/gameserver && nice ./metrics_to_mysql.py -q --prune) > /dev/null
echo `date` "metrics done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./fb_notifications_to_sql.py -q --prune) > /dev/null
echo `date` "fb_notifications done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./fb_requests_to_sql.py -q --prune) > /dev/null
echo `date` "fb_requests done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./fb_sharing_to_sql.py -q --prune) > /dev/null
echo `date` "fb_sharing done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./fb_permissions_to_sql.py -q --prune) > /dev/null
echo `date` "fb_permissions done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./fb_open_graph_to_sql.py -q --prune) > /dev/null
echo `date` "fb_open_graph done" >> ${LOG}

(cd $GAME_DIR/gameserver && nice ./sessions_to_sql.py -q --prune) > /dev/null
echo `date` "sessions done" >> ${LOG}

# analytics-views
(cd $GAME_DIR/gameserver && ./update-analytics-views.sh) > /dev/null # requires sessions, metrics, facebook_campaign_map (currently from upcache), fb_notifications, fb_permissions, credits, battles, battle_risk_reward
echo `date` "analytics-views done" >> ${LOG}

(cd $GAME_DIR/gameserver && nice ./map_to_mysql.py -q) > /dev/null
echo `date` "map done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./purchase_ui_to_sql.py -q) > /dev/null
echo `date` "purchase_ui done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./damage_protection_to_sql.py -q --prune) > /dev/null
echo `date` "damage_protection done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./ladder_pvp_to_sql.py -q --prune) > /dev/null
echo `date` "ladder_pvp done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./client_trouble_to_sql.py -q --prune --optimize) > /dev/null
echo `date` "client_trouble done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./chat_to_sql.py -q --prune) > /dev/null
echo `date` "chat done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./econ_res_to_sql.py -q --prune) > /dev/null
echo `date` "econ_res done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./inventory_to_sql.py -q --prune) > /dev/null
echo `date` "inventory done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./unit_donation_to_sql.py -q --prune) > /dev/null
echo `date` "unit_donation done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./fishing_to_sql.py -q --prune) > /dev/null
echo `date` "fishing done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./quests_to_sql.py -q --prune) > /dev/null
echo `date` "quests done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./lottery_to_sql.py -q --prune) > /dev/null
echo `date` "lottery done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./achievements_to_sql.py -q --prune) > /dev/null
echo `date` "achievements done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./login_flow_to_sql.py -q --prune) > /dev/null
echo `date` "login_flow done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./login_sources_to_sql.py -q --prune) > /dev/null
echo `date` "login_sources done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./activity_to_sql.py -q --prune) > /dev/null
echo `date` "activity done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./alliance_events_to_sql.py -q --prune) > /dev/null
echo `date` "alliance_events done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./alliance_state_to_sql.py -q) > /dev/null
echo `date` "alliance_state done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./skynet_conversion_pixels_to_sql.py -q)
echo `date` "skynet_conversion_pixels done" >> ${LOG}
(cd $GAME_DIR/gameserver && nice ./schedule_to_sql.py --workspace 'spinpunch.com' --project 'SHIP Schedule' --project 'Market Research' -q) > /dev/null
echo `date` "schedule done" >> ${LOG}

# upcache is slowest
(cd $GAME_DIR/gameserver && nice ./upcache_to_mysql.py -q --parallel 8) > /dev/null
echo `date` "UPCACHE done" >> ${LOG}
(cd $GAME_DIR/gameserver && ./cur_levels_to_sql.py -q) > /dev/null # requires upcache
echo `date` "cur_levels done" >> ${LOG}
(cd $GAME_DIR/gameserver && ./acquisitions_to_sql.py -q) > /dev/null # requires upcache and analytics-views
echo `date` "acquisitions done" >> ${LOG}

echo `date` "=== ETL run done ===" >> ${LOG}

