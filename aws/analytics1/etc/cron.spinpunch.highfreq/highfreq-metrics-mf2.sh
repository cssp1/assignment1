#!/bin/sh

GAME_DIR=/home/ec2-user/marsfrontier2
HOST=`hostname | sed 's/.spinpunch.com//'`
AWSSECRET=/home/ec2-user/.ssh/${HOST}-awssecret

(cd $GAME_DIR && ./scmtool.sh force-up > /dev/null)

(cd $GAME_DIR/gameserver && ./make-gamedata.sh -n -u > /dev/null)

(cd $GAME_DIR/gameserver && nice ./dump_userdb.py --cache-only \
    --cache-segments 64 --parallel 16 --s3-userdb \
    --cache-read logs/marsfrontier2-upcache --from-s3-bucket spinpunch-upcache --from-s3-keyfile $AWSSECRET \
    --cache-write logs/marsfrontier2-upcache --to-s3-bucket spinpunch-upcache --to-s3-keyfile $AWSSECRET) > /dev/null

