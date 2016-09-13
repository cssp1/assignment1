#!/bin/sh

(cd ${HOME}/firestrike/gameserver && ./all-to-mysql.sh -f hourly)
(cd ${HOME}/firestrike/gameserver && ./report_mysql_alarms.py -q)
