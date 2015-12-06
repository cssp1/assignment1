#!/bin/bash

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# run GAME_ID string replacement on analytics_views.sql and pipe it to mysql.py

GAME_ID=`grep '"game_id":' config.json  | cut -d\" -f4 | sed 's/test//'`
if [[ $GAME_ID == 'mf' ]]; then
    UPCACHE_TABLE="${GAME_ID}_upcache_lite"
else
    UPCACHE_TABLE="${GAME_ID}_upcache"
fi
LAUNCH_DATE=`./SpinConfig.py --launch-date`

< ./analytics_views.sql sed "s/\$UPCACHE_TABLE/${UPCACHE_TABLE}/g; s/\$GAME_ID/${GAME_ID}/g; s/\$LAUNCH_DATE/${LAUNCH_DATE}/g;" | ./mysql.py ${GAME_ID}_upcache
