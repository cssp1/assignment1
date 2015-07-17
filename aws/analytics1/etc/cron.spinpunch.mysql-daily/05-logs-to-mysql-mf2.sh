#!/bin/sh

exit 0 # XXX disabled by default

(cd ${HOME}/marsfrontier2/gameserver && ./all-to-mysql.sh -f daily)
