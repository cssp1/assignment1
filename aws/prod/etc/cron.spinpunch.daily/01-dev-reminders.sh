#!/bin/sh

exit 0 # XXX disabled by default

. /etc/spinpunch

export HIPCHAT_TOKEN=`cat /home/ec2-user/.ssh/hipchat.token`

(cd $GAME_DIR/gameserver && ./dev_reminders.py > /dev/null)
