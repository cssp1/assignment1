#!/bin/sh

. /etc/spinpunch

GAME_DIR=/home/ec2-user/summonersgate
export TMPDIR="${SPIN_TMPDIR}"

(cd $GAME_DIR/gameserver && nice ./archive_mongodb_logs.py --quiet --parallel 1) > /dev/null

