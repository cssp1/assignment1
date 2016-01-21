#!/bin/sh

exit 0 # XXX disabled by default

(cd ${HOME}/daysofvalor/gameserver && ./all-to-mysql.sh -f hourly)
(cd ${HOME}/daysofvalor/gameserver && ./report_mysql_alarms.py -q)
