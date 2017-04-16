#!/usr/bin/env python

# this script should be invoked by adding the -m option to crond
# it receives any errors from cron jobs and transmits them as SNS notifications.
# e.g.: in /etc/sysconfig/crond:
# CRONDARGS=" -m '/usr/local/bin/cron-mail-to-sns.py arn:aws:sns:us-east-1:147976285850:spinpunch-technical'"
# (specify Topic ARN as first argument. Reads cron output as UNIX mail on stdin.)
# NOTE: requires python-boto package to be installed!

import sys, os, pwd, traceback

# for debugging
# import logging; logging.basicConfig(filename="/tmp/boto.log", level=logging.DEBUG)

try:
    import email.parser, boto.sns

    msg = None
    subject = None
    body = None

    # cron runs this in the same context as the job that produced the error messages.
    # It doesn't set the environment variables USER, HOME, etc to match the effective UID.
    # We have to do this manually so that boto will find the credentials.

    euid = os.geteuid()
    user_info = pwd.getpwuid(euid)
    os.environ['USER'] = os.environ['USERNAME'] = user_info.pw_name
    os.environ['HOME'] = user_info.pw_dir

    topic_arn = sys.argv[1]

    if 1:
        region = topic_arn.split(':')[3] # is this consistently the region?
    else:
        import boto.utils
        region = boto.utils.get_instance_metadata()['placement']['availability-zone'][0:-1]

    p = email.parser.FeedParser()
    p.feed(sys.stdin.read())
    msg = p.close()
    subject = msg.get('Subject', 'Cron error')
    body = msg.get_payload().strip()

    subject = subject.decode('utf-8').encode('ascii') # note: subject must be ASCII!
    body = body.decode('utf-8').encode('utf-8')

    # obey message limits:
    if len(body) > 262144:
        body = body[:200000]
    if len(subject) > 100:
        subject = subject[:100]

    con = boto.sns.connect_to_region(region)
    con.publish(topic = topic_arn, message = body, subject = subject)

# fallback error catcher
except Exception as e:
    err_fd = open('/tmp/cron-mail-to-sns-error.txt', 'a')
    if body and len(body) > 100:
        ui_body = body[0:16]+'...'+body[-16:]
    else:
        ui_body = body
    err_fd.write('USER %s ENV %r MSG %r SUBJECT %r BODY %r\n' % \
                 (os.getenv('USER'), os.environ, msg, subject, ui_body))
    err_fd.write(traceback.format_exc()+'\n')

# example="""From: root (Cron Daemon)
# To: ec2-user
# Subject: Cron <ec2-user@gamemaster> /home/ec2-user/cron-fail-simulator.sh
# Content-Type: text/plain; charset=UTF-8
# Auto-Submitted: auto-generated
# X-Cron-Env: <LANG=en_US.UTF-8>
# X-Cron-Env: <SHELL=/bin/sh>
# X-Cron-Env: <HOME=/home/ec2-user>
# X-Cron-Env: <PATH=/usr/bin:/bin>
# X-Cron-Env: <LOGNAME=ec2-user>
# X-Cron-Env: <USER=ec2-user>

# This is some error
# """
