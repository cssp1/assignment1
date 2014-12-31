#!/bin/sh

exit 0 # XXX disabled by default

GAME_DIR=/home/ec2-user/summonersgate
(cd $GAME_DIR/gameserver && nice ./upcache_to_mysql.py -q --parallel 8) > /dev/null
(cd $GAME_DIR/gameserver && ./update-analytics-views.sh) > /dev/null
(cd $GAME_DIR/gameserver && ./acquisitions_to_sql.py -q) > /dev/null
(cd $GAME_DIR/gameserver && ./cur_levels_to_sql.py -q) > /dev/null
(cd $GAME_DIR/gameserver && ./battle_risk_reward_to_sql.py -q) > /dev/null
