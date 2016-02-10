#!/bin/sh

exit 0 # obsoleted by mongodb backup (but make sure to set it up!)

. /etc/spinpunch

# this ONLY backs up the local files:
# dbserver metadata like facebook_id_map, player_cache, and map_regions
# MySQL state
# MongoDB state
# the full userdb/playerdb backup happens on a different server

export TEMP=/tmp # set this to somewhere with 10GB+ of space

(cd $GAME_DIR/gameserver && nice ./backup-data.py --quiet --parallel 1 --local 1 --s3 0) > /dev/null
