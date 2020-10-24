#!/usr/bin/env python

import getopt
import boto.sns
import sys
import os

topic = os.getenv('BATCH_TASKS_SNS_TOPIC') or ''
subject = 'sns-publish.py'

opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['topic=','subject='])
for key, val in opts:
    if key == '--topic': topic = val
    elif key == '--subject': subject = val

if not topic:
    print('SNS topic not specified')
    sys.exit(1)

body = sys.stdin.read()

region = topic.split(':')[3]
con = boto.sns.connect_to_region(region)
con.publish(topic = topic, message = body, subject = subject)
