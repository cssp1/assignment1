#!/bin/bash

# load environment variables on legacy systems
if [ -r /etc/spinpunch ]; then
    . /etc/spinpunch
fi

cd $GAME_DIR/gameserver

TODAY=`date +%Y%m%d`
TIME=`date`
LOG=logs/$TODAY-patron-rewards.txt

echo "====== ${TIME} ======" >> $LOG
./SpinNoSQL.py --patron-rewards >> $LOG
