#!/bin/sh

(cd ${HOME}/marsfrontier2/gameserver && ./all-to-mysql.sh -f hourly)
(cd ${HOME}/marsfrontier2/gameserver && ./report_mysql_alarms.py -q)
