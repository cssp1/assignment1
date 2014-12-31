#!/bin/bash

# note: all skynet queries can be run from ANY game sandbox
GAME_DIR=/home/ec2-user/thunderrun

(cd $GAME_DIR && ./scmtool.sh force-up > /dev/null)
(cd $GAME_DIR/gameserver && ./skynet.py --mode adstats-record > /dev/null)
(cd $GAME_DIR/gameserver && ./skynet_adstats_to_sql.py --fix-missing-data -q)
