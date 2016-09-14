#!/bin/sh

. /etc/spinpunch

if [ -e "/home/ec2-user/.ssh/hipchat.token" ]; then
    export HIPCHAT_TOKEN=`cat /home/ec2-user/.ssh/hipchat.token`
fi

(cd $GAME_DIR/gameserver && ./dev_reminders.py > /dev/null)
