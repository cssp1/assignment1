#!/bin/sh

(cd ${HOME}/summonersgate/gameserver && ./all-to-mysql.sh -f hourly)
(cd ${HOME}/summonersgate/gameserver && ./report_mysql_alarms.py -q)
