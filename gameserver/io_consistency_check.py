#!/usr/bin/env python

# read through a -player-io.txt log file
# (produced by the gameserver with gamedata.server.log_player_io enabled)
# and check it for lock generation violations

import sys, getopt
import ANSIColor

def week_of(ts):
    return (ts - 1337274000) // (7*86400)

player_id_to_gen = {}
player_id_to_time = {}

ai_id_to_gen = {}
ai_id_to_time = {}

count = 0
errors = 0
warnings = 0
verbose = 0

opts, args = getopt.gnu_getopt(sys.argv[1:], 'v', ['verbose'])
for key, val in opts:
    if key == '-v' or key == '--verbose': verbose += 1

last_event_time = -1

for line in sys.stdin.xreadlines():
    event_time_rounded, event_date, event_daytime, event_time, \
                        server_name, category, action, id, gen = line.strip().split(' ')
    event_time = float(event_time)
    gen = int(gen)

    # re-initialize AIs on week boundaries
    if last_event_time > 0 and week_of(event_time) != week_of(last_event_time):
        ai_id_to_gen.clear()
        ai_id_to_time.clear()

    count += 1

    if category == 'PLAYER':
        id_to_gen = player_id_to_gen
        id_to_time = player_id_to_time
    elif category == 'AI':
        id_to_gen = ai_id_to_gen
        id_to_time = ai_id_to_time

    err_list = []
    warn_list = []

    if action == 'WRITE':
        if id in id_to_gen:
            if gen <= id_to_gen[id]:
                err_list.append('wrote a generation <= stored one: (%.6f %5d %.6f %5d)' % \
                                (id_to_time[id], id_to_gen[id], event_time, gen))
        id_to_time[id] = event_time
        id_to_gen[id] = gen

    elif action == 'READ':
        if id in id_to_gen:
            if gen < id_to_gen[id]:
                err_list.append('read a generation < stored one: (%.6f %5d %.6f %5d)' % \
                                (id_to_time[id], id_to_gen[id], event_time, gen))
            elif gen > id_to_gen[id]:
                warn_list.append('read a generation > stored one (unlogged write?): (%.6f %5d %.6f %5d)' % \
                                 (id_to_time[id], id_to_gen[id], event_time, gen))

    errors += len(err_list)
    warnings += len(warn_list)

    if err_list or (warn_list and verbose):
        print line.strip()
        print ', '.join(map(ANSIColor.red, err_list) + map(ANSIColor.yellow, warn_list))
        print

    last_event_time = event_time

print count, 'actions', errors, 'errors', warnings, 'warnings'
