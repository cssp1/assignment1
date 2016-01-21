#!/bin/bash

exit 0 # XXX disabled by default

. /etc/spinpunch

# vacuum only during low load time (~0300GMT)
FLAGS=""
if [ `date +%H` -eq 3 ]; then
    FLAGS+=" --optimize"
fi

cd $GAME_DIR/gameserver
./scores2_to_sql.py --mongo-drop ${FLAGS} -q
./battles_to_psql.py ${FLAGS} -q
