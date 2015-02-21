#!/bin/sh

GAME_DIR=/home/ec2-user/thunderrun
(cd $GAME_DIR/gameserver && ./report_slow_mysql.py --min-sec 60 analytics1_root --email XXXXXX@example.com --prune) > /dev/null
