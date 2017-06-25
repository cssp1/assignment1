#!/bin/bash

# note: skynet queries should be run from the thunderrun sandbox
GAME_DIR=/home/ec2-user/thunderrun

(cd $GAME_DIR/gameserver && ./bh_import_google_analytics.py -q)
(cd $GAME_DIR/gameserver && ./bh_import_metrics.py -q)
