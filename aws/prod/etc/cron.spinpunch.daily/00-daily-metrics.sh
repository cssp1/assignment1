#!/bin/sh

. /etc/spinpunch

nice $GAME_DIR/aws/daily-metrics.sh -d "$GAME_DIR" -s "$GAME_MAIL_FROM" > /dev/null
