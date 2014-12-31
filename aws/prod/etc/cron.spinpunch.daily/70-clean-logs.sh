#!/bin/sh

. /etc/spinpunch

(cd $GAME_DIR/gameserver && ./clean_logs.py --go --battle-archive-s3-bucket spinpunch-${GAME_ID}prod-battle-archive ) > /dev/null
