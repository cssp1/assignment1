#!/bin/sh

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# SVN post-commit hook to send notifications to HipChat or Slack

REPOS="$1"
REV="$2"
HIPCHAT_AUTH_TOKEN=`cat /var/svn/hipchat.token`
SLACK_AUTH_TOKEN=`cat /var/svn/slack.token`
COMMENT=`svnlook log -r $REV $REPOS`
AUTHOR=`svnlook author -r $REV $REPOS`
CHANGED_FILES=`svnlook changed -r $REV $REPOS`

# use a different background color for commits by different authors
declare -A COLORS
COLORS[ec2-user]="purple"

if [ ${COLORS[${AUTHOR}]+_} ]; then
        COLOR=${COLORS[${AUTHOR}]}
else
        COLOR="red"
fi

# HIPCHAT

#HIPCHAT_JSON_BODY=`echo "SVN ${REV} (${AUTHOR}): <b>${COMMENT}</b>" | /usr/bin/python -c "import json, sys; print json.dumps({'message':sys.stdin.read().strip(), 'color':'${COLOR}', 'notify':True, 'message_format':'html'});"`
#/usr/bin/curl --cipher rsa_rc4_128_sha "https://api.hipchat.com/v2/room/Checkins/notification?auth_token=${HIPCHAT_AUTH_TOKEN}" \
#--connect-timeout 5 --max-time 10 \
#-H "Content-Type: application/json" -d "$HIPCHAT_JSON_BODY"

# SLACK
SLACK_JSON_BODY=`echo "SVN r${REV} (${AUTHOR}): ${COMMENT}" | /usr/bin/python -c "import json, sys; print json.dumps({'channel':'#checkins','username':'gamemaster','text':sys.stdin.read().strip()});"`
/usr/bin/curl -X POST "https://YOUR-DOMAIN.slack.com/services/hooks/incoming-webhook?token=${SLACK_AUTH_TOKEN}" --data-urlencode "payload=${SLACK_JSON_BODY}"
