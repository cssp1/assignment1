#!/bin/sh

. /etc/spinpunch

GAME_DIR=/home/ec2-user/thunderrun

cd $GAME_DIR/gameserver

for LIST_NAME in 'DV New Accounts' 'FS New Accounts' 'TR New Accounts'; do
    ./clean_mailchimp_list.py --list-name "${LIST_NAME}" -q
done
