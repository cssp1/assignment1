#!/bin/sh

exit 0 # XXX disabled by default

(cd ${HOME}/battlefrontmars/gameserver && ./all-to-mysql.sh -f hourly)
