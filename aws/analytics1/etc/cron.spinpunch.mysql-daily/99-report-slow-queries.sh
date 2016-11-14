#!/bin/sh

GAME_DIR=/home/ec2-user/thunderrun
(cd $GAME_DIR/gameserver && ./report_slow_mysql.py --min-sec 250 analytics1_root --prune) > /dev/null
