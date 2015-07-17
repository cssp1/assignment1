#!/bin/sh

exit 0 # XXX disabled by default

(cd ${HOME}/thunderrun/gameserver && ./all-to-mysql.sh -f daily)
