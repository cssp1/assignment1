#!/bin/bash

# note: skynet queries should be run from the thunderrun sandbox
GAME_DIR=/home/ec2-user/thunderrun

(cd $GAME_DIR/gameserver && ./bh_import_user_data.py -q)
