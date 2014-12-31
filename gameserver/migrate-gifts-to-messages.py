#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to convert old db/gift_table resource
# gifts to db/message_table

try: import simplejson as json
except: import json

import time, sys

time_now = int(time.time())
max_age = 2*86400



if __name__ == '__main__':
    converted = 0
    old = 0

    messages = {}

    gifts = json.load(sys.stdin)
    for r_user_id_str, gift_list in gifts.iteritems():
        r_user_id = int(r_user_id_str)

        for gift in gift_list:

            gift_time = gift.get('time',0)
            if (time_now - gift_time) >= max_age:
                old += 1
                continue
            s_name = gift.get('from_name', 'Unknown')
            s_user_id = gift.get('from', -1)
            s_fbid = gift.get('from_fbid', '-1')

            if r_user_id_str not in messages: messages[r_user_id_str] = []
            messages[r_user_id_str].append({
                'unique_per_sender': 'resource_gift',
                'from_name': s_name,
                'from': s_user_id,
                'to': [r_user_id],
                'time': gift_time,
                'type': 'resource_gift',
                'from_fbid': str(s_fbid)
                })
            converted += 1

    json.dump(messages, sys.stdout, indent=2)
    sys.stderr.write('converted %d messages, dropped %d old messages\n' % (converted, old))
