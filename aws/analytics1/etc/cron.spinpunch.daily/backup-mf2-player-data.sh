#!/bin/sh

. /etc/spinpunch

GAME_DIR=/home/ec2-user/marsfrontier2
export TMPDIR="${SPIN_SMALL_TMPDIR}"

# perform S3 backup only, leave local backup for prod.spinpunch.com
(cd $GAME_DIR/gameserver && nice ./backup-data.py --quiet --parallel 16 --local 0 --s3 1) > /dev/null
