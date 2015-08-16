#!/bin/sh

exit 0 # XXX disabled by default

(cd ${HOME}/daysofvalor/gameserver && ./all-to-mysql.sh -f daily)
