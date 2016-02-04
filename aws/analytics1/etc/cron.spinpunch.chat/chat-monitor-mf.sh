#!/bin/sh

GAME_DIR=/home/ec2-user/marsfrontier
(cd $GAME_DIR/gameserver && ./chat_monitor.py -q)
