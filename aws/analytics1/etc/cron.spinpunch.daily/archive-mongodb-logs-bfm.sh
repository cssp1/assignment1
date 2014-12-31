#!/bin/sh

exit 0 # XXX disabled by default

GAME_DIR=/home/ec2-user/battlefrontmars
export TMPDIR=/media/ephemeral1b/backup-scratch

(cd $GAME_DIR/gameserver && nice ./archive_mongodb_logs.py --quiet --parallel 1) > /dev/null

