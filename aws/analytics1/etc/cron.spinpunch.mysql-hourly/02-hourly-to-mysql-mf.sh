#!/bin/sh

(cd ${HOME}/marsfrontier/gameserver && ./all-to-mysql.sh -f hourly)
(cd ${HOME}/marsfrontier/gameserver && ./report_mysql_alarms.py -q)
