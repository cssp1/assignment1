#!/bin/bash

exit 0 # XXX disabled by default

. /etc/spinpunch

cd $GAME_DIR/gameserver
./scores2_to_sql.py --mongo-drop -q
