#!/bin/sh

exit 0 # XXX disabled by default

GAME_DIR=/home/ec2-user/thunderrun
(cd $GAME_DIR/gameserver && nice ./stats_to_sql.py -q) > /dev/null
(cd $GAME_DIR/gameserver && nice ./map_to_mysql.py -q) > /dev/null
(cd $GAME_DIR/gameserver && nice ./purchase_ui_to_sql.py -q) > /dev/null
(cd $GAME_DIR/gameserver && nice ./battles_to_mysql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./credits_to_mysql.py -q) > /dev/null
(cd $GAME_DIR/gameserver && nice ./gamebucks_to_mysql.py -q --unit-cost --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./metrics_to_mysql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./damage_protection_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./ladder_pvp_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./client_trouble_to_sql.py -q --prune --optimize) > /dev/null
(cd $GAME_DIR/gameserver && nice ./chat_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./econ_res_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./inventory_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./unit_donation_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./fishing_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./quests_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./achievements_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./fb_notifications_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./fb_requests_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./fb_permissions_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./fb_open_graph_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./sessions_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./login_flow_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./login_sources_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./activity_to_sql.py -q --prune) > /dev/null
(cd $GAME_DIR/gameserver && nice ./skynet_conversion_pixels_to_sql.py -q)

