#!/bin/sh

(cd ${HOME}/battlefrontmars/gameserver && ./all-to-mysql.sh -f hourly)
(cd ${HOME}/battlefrontmars/gameserver && ./report_mysql_alarms.py -q)
