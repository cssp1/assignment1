#!/bin/bash

. /etc/spinpunch

cd $GAME_DIR/gameserver

./PolicyBot.py --quiet --parallel 8
