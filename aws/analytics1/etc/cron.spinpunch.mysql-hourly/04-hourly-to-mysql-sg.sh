#!/bin/sh

exit 0 # XXX disabled by default

(cd ${HOME}/summonersgate/gameserver && ./all-to-mysql.sh -f hourly)
