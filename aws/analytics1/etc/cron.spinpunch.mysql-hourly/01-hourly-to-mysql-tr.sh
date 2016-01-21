#!/bin/sh

exit 0 # XXX disabled by default

(cd ${HOME}/thunderrun/gameserver && ./all-to-mysql.sh -f hourly)
(cd ${HOME}/thunderrun/gameserver && ./report_mysql_alarms.py -q)
