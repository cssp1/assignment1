#!/bin/sh

GAME_DIR=/home/ec2-user/summonersgate
(cd $GAME_DIR/gameserver && ./chat_monitor.py -q)
