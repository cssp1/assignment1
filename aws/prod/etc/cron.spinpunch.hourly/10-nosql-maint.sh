#!/bin/bash

. /etc/spinpunch

cd $GAME_DIR/gameserver

TODAY=`date +%Y%m%d`
TIME=`date`
LOG=logs/$TODAY-maint.txt

echo "====== ${TIME} ======" >> $LOG
./SpinNoSQL.py --maint >> $LOG
