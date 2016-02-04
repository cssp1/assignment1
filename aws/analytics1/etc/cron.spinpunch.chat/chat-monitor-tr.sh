#!/bin/sh

GAME_DIR=/home/ec2-user/thunderrun
(cd $GAME_DIR/gameserver && ./chat_monitor.py -q)
