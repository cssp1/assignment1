#!/bin/sh

exit 0 # XXX disabled by default

GAME_DIR=/home/ec2-user/battlefrontmars
export TMPDIR=/media/ephemeral1b/backup-scratch

# perform S3 backup only, leave local backup for prod.spinpunch.com
(cd $GAME_DIR/gameserver && nice ./backup-data.py --quiet --parallel 16 --local 0 --s3 1) > /dev/null
