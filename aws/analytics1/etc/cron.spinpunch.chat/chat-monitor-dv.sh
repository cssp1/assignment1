#!/bin/sh

exit 0 # XXX disabled by default

GAME_DIR=/home/ec2-user/daysofvalor
(cd $GAME_DIR/gameserver && ./chat_monitor.py -q)
