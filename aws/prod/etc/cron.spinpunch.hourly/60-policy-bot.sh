#!/bin/bash

exit 0 # XXX disabled by default

. /etc/spinpunch

cd $GAME_DIR/gameserver

./PolicyBot.py --quiet --parallel 8
