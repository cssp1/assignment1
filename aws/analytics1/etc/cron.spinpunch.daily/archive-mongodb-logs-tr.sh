#!/bin/sh

exit 0 # XXX disabled by default

GAME_DIR=/home/ec2-user/thunderrun
export TMPDIR=/media/aux2/tmp

(cd $GAME_DIR/gameserver && nice ./archive_mongodb_logs.py --quiet --parallel 1) > /dev/null

