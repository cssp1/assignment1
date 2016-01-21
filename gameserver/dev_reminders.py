#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import sys, os, time, getopt, subprocess, re
import SpinConfig
import SpinReminders

def pretty_print_time(sec):
    ret = []
    if sec > 24*60*60:
        days = sec//(24*60*60)
        ret.append('%d day%s' % (days, 's' if days!=1 else ''))
        sec -= days*(24*60*60)
    if sec > 60*60:
        hours = sec//(60*60)
        ret.append('%d hour%s' % (hours, 's' if hours!=1 else ''))
        sec -= hours*(60*60)
    return ' '.join(ret)

time_re = re.compile('XXXXXX_?([0-9]+)') # detect comments of the form XXXXXX_UNIXTIME
def six_X_comment_is_relevant(line, time_now):
    match = time_re.search(line)
    if match:
        t = int(match.group(1))
        if (t - time_now) >= 7*86400: # too far into the future - do not report yet
            return False
    return True

def get_six_X_comments(game_id, time_now):
    cmd = 'cd ../gamedata/'+game_id+' && env grep -sn '+game_id+'X'*6+' ../*.{json,py} || env grep -sn '+'X'*6+' *.{json,py,skel}'
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
    out, err = p.communicate()
    if err:
        raise Exception(err or out)
    out = out.strip()
    if out:
        lines = out.split('\n')
        lines = filter(lambda x: six_X_comment_is_relevant(x, time_now), lines)
        if lines:
            return 'X'*6 + ' items in production that need to be fixed:\n'+('\n'.join(lines))
    return ''

def do_reminders(game_id, dry_run = False):
    filename = SpinConfig.gamedata_component_filename('dev_reminders.json', override_game_id = game_id)
    if not os.path.exists(filename): return
    data = SpinConfig.load(filename, override_game_id = game_id)

    time_now = int(time.time())
    sender_name = data['sender']

    for reminder in data['reminders']:
        subject = 'Automated reminder from %s' % sender_name
        if reminder['body'] == '$XXX': # special case for six-X comments
            body = get_six_X_comments(game_id, time_now)
        else:
            body = 'Due %s %s' % (pretty_print_time(abs(reminder['deadline']-time_now)), 'from now' if reminder['deadline']>time_now else 'ago') + '\n' + reminder['body']

        if body:
            SpinReminders.send_reminders(sender_name, reminder['notify'], subject, body, dry_run = dry_run)

if __name__ == "__main__":
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['dry-run'])
    dry_run = False
    game_id = SpinConfig.game()
    for key, val in opts:
        if key == '--dry-run': dry_run = True
        elif key == '-g': game_id = val
    do_reminders(game_id, dry_run=dry_run)
