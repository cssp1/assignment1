#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# utility to dump user metrics history in graphical form

# get fast JSON library if available
try: import simplejson as json
except: import json

import sys, time, string, glob
import datetime
import SpinConfig
import pysvg.structure, pysvg.text, pysvg.builders

verbose = True
gamedata = json.load(open(SpinConfig.gamedata_filename()))
WIDTH=900
HEIGHT=400
SESSION_HEIGHT=200
SESSION_SPACE=90
MIN_SPACE=16

# XXX add chat, spying, gifting, production/research/upgrade queueing
IMPORTANT = set(['0115_logged_in', '0900_logged_out', '0910_logged_out',
                 '4040_harvest', '0970_client_exception',
                 '3800_produce_unit', '4060_order_prompt',
                 '4025_construct_building',
                 '4030_upgrade_building',
                 '3080_research_tech',
                 '3820_battle_start', '3830_battle_end',
                 '4010_mission_complete', '4011_mission_complete_repeatable',
                 '1000_billed'])

def read_log_file(fname, user_id):
    ret = []
    quick_str = '"user_id":%d' % user_id
    for line in open(fname).xreadlines():
        if quick_str not in line:
            continue
        event = json.loads(line)
        if event.get('user_id',-1) == user_id:
            evname = event.get('event_name', '')
            if evname in IMPORTANT or 'tutorial' in evname:
                ret.append(event)
    return ret

def read_log_files(pattern, user_id):
    ret = sum(map(lambda fn: read_log_file(fn, user_id), sorted(glob.glob(pattern))), [])
    ret.sort(key = lambda ev: ev['time'])
    return ret


def pretty_time(t):
    return datetime.datetime.utcfromtimestamp(t).isoformat(' ')

def shorten_description(desc):
    fields = desc.split(',')
    return string.join([f[0:5] for f in fields],'.')

def slanted_text(s, x, y, angle, **kwargs):
    group = pysvg.structure.g()
    group.set_transform('rotate(%g %g %g)'%(angle,x,y))
    t = pysvg.text.text(s, x, y, **kwargs)
    group.addElement(t)
    return group


if __name__ == "__main__":
    time_now = time.time()
    #user_id = 1112
    #logfiles = 'logs/*-metrics.json'
    logfiles = 'prodlogs/2012042*-metrics.json'
    user_id = 18523; user_note = 'Jim Josten'

    sys.stderr.write("reading metrics...")
    events = read_log_files(logfiles, user_id)
    time_range = [events[0]['time'], events[-1]['time']]
    time_len = time_range[1]-time_range[0]
    sys.stderr.write("done (%d events, covering %s sec)\n" % (len(events), time_len))


    # create list of intervals of time during which the player was logged in
    # [start_t, end_t]
    sessions = []
    for ev in events:
        if ev['event_name'] == '0115_logged_in':
            sessions.append([ev['time'],ev['time']+1])
            #sys.stderr.write('IN  %d\n' % ev['time'])
        elif ev['event_name'].endswith('logged_out'):
            sessions[-1][1] = ev['time']
            #sys.stderr.write('OUT %d\n' % ev['time'])
    sys.stderr.write('%d sessions\n' % len(sessions))

    HEIGHT = (SESSION_HEIGHT+SESSION_SPACE)*(len(sessions)+1)

    svg = pysvg.structure.svg(0, 0,
                              width=WIDTH+200, # let tags run off the right side
                              height=HEIGHT)

    t = pysvg.text.text('User '+str(user_id)+': '+user_note, x=10, y=30, font_size = 25)
    svg.addElement(t)

    sh = pysvg.builders.ShapeBuilder()

    day_count = -1
    day_start = sessions[0][0] # start of user's Day
    s = -1 # session index
    y = 0.0 # starting Y value for this session
    start = 10.0 # starting X value for this session
    time_scale = 0.0 # ratio of pixels to seconds for the current session
    battle_start_x = -1
    last_x = -1
    first_purchase = True

    bump = 0 # distort width to allow for spacing
    max_x = 0
    max_bump = 0

    for ev in events:
        if ev['event_name'] == '0115_logged_in':
            s += 1
            assert ev['time'] == sessions[s][0]

            time_scale = (WIDTH-20) / 600 # float(sessions[s][1]-sessions[s][0])

            start = 10.0
            last_x = -1
            bump = 0
            battle_start_x = -1
            y += SESSION_HEIGHT + SESSION_SPACE

            # draw day boundaries
            day_y = y-SESSION_HEIGHT/2-SESSION_SPACE/2

            while day_count < 0 or day_start < ev['time']:
                day_start += 24*60*60
                day_count += 1
                day_y += 12
                svg.addElement(sh.createLine(0, day_y, WIDTH, day_y, stroke='brown', strokewidth='3'))
                svg.addElement(pysvg.text.text('Day %d' % day_count, x=WIDTH/2, y=day_y-8, font_size='14', fill='brown'))

            # draw elapsed time
            if s > 0:
                svg.addElement(pysvg.text.text('%.2f Hours later...' % (float(sessions[s][0]-sessions[s-1][1])/3600.0),
                                               x=10, y=y-SESSION_HEIGHT/2-20, font_size='11'))

            # draw login info
            if ev.get('base_damage',0) > 0:
                svg.addElement(pysvg.text.text('Dmg %.2f%%' % (100.0*ev['base_damage']), start, y+25, font_size='12', fill='red'))


        assert ev['time'] >= sessions[s][0] and ev['time'] <= sessions[s][1]


        x = start + time_scale * (ev['time'] - sessions[s][0]) + bump

        if x-last_x < MIN_SPACE:
            bump += (last_x+MIN_SPACE)-x
            x = last_x + MIN_SPACE
            max_x = max(max_x, x)
            max_bump = max(max_bump, bump)

        if ev['event_name'].endswith('logged_out'):
            # draw session line
            assert ev['time'] == sessions[s][1]
            svg.addElement(sh.createLine(start, y-15, start, y+15, strokewidth=1))
            svg.addElement(sh.createLine(start, y, x, y, strokewidth=1))
            svg.addElement(sh.createLine(x, y-15, x, y+15, strokewidth=1))

            # box the session
            svg.addElement(pysvg.text.text('Session #%d %s   Duration %.1fmin  (Account Age %.1f hours)' % (s+1, pretty_time(ev['time']), (sessions[s][1]-sessions[s][0])/60.0 , (sessions[s][0]-sessions[0][0])/3600.0), x=10, y=y-SESSION_HEIGHT/2-6, font_size='13'))
            svg.addElement(sh.createRect(start-5, y-SESSION_HEIGHT/2, x-start+10, SESSION_HEIGHT))

        elif ev['event_name'] == '1000_billed':
            amount = ev['Billing Amount']
            descr = shorten_description(ev['Billing Description'])
            length = 10 + 10 * (amount/10.0)
            size = int(12 + 10*(amount/10.0))
            if first_purchase:
                stars = '*** '
                first_purchase = False
            else:
                stars = ''
            svg.addElement(slanted_text(stars+'$%0.2f ' % amount + descr, x, y-length, -45, fill='green', font_size=str(size)))
            svg.addElement(sh.createLine(x, y, x, y-length, strokewidth=1, stroke='green'))

        elif ev['event_name'] == '4060_order_prompt':
            color = 'rgba(0,128,128,1)'
            amount = ev['Billing Amount']
            descr = shorten_description(ev['Billing Description'])
            svg.addElement(slanted_text('Prompt $%0.2f ' % amount + descr, x, y+10, 45, fill=color, font_size='8'))
            svg.addElement(sh.createLine(x, y, x, y+10, strokewidth=1, stroke=color))


        elif ev['event_name'] == '4040_harvest':
            svg.addElement(slanted_text('harvest', x, y+10, 45, fill='blue', font_size='10'))
            svg.addElement(sh.createLine(x, y, x, y+10, stroke='blue'))
        elif ev['event_name'] == '0970_client_exception':
            svg.addElement(slanted_text('EXCEPTION', x, y-10, -45, fill='red', font_size='10'))
            svg.addElement(sh.createLine(x, y, x, y-10, stroke='red'))
        elif 'mission_complete' in ev['event_name']:
            color = 'rgba(130,50,0,1)'
            svg.addElement(slanted_text('MISSION '+ev['mission_id'], x, y-10, -45, fill=color, font_size='16'))
            svg.addElement(sh.createLine(x, y, x, y-10, stroke=color))

        elif ev['event_name'] == '3820_battle_start':
            if ev['opponent_type'] == 'ai':
                color = 'rgba(130,50,0,1)'
            else:
                color = 'red'
            svg.addElement(slanted_text('ATTACK (%d L%d %s)' % (ev['opponent_user_id'], ev['opponent_level'],ev['opponent_type']),
                                        x, y-10, -45, fill=color, font_size='16'))
            svg.addElement(sh.createLine(x, y, x, y-10, stroke=color))
            battle_start_x = x
        elif ev['event_name'] == '3830_battle_end':
            if battle_start_x > 0:
                if ev['opponent_type'] == 'ai':
                    color = 'rgba(100,50,0,1)'
                else:
                    color = 'red'
                svg.addElement(sh.createLine(battle_start_x, y-10, x, y-10, stroke=color, strokewidth='2'))
                svg.addElement(sh.createLine(x, y, x, y-10, stroke=color))
                svg.addElement(slanted_text('+%d iron +%d water -%d units' % (ev['gain_iron'],ev['gain_water'],ev['units_lost']),
                                            x, y-10, -45, fill=color, font_size='16'))
        elif 'tutorial' in ev['event_name']:
            svg.addElement(slanted_text(ev['event_name'], x, y-10, -45, fill='blue', font_size='10'))
            svg.addElement(sh.createLine(x, y, x, y-10, stroke='blue'))

        elif ev['event_name'] == '3800_produce_unit':
            svg.addElement(slanted_text('MAKE '+ev['unit_type'], x, y+10, 45, fill='blue', font_size='10'))
            svg.addElement(sh.createLine(x, y, x, y+10, stroke='blue'))
        elif ev['event_name'] == '4025_construct_building' or ev['event_name'] == '4030_upgrade_building':
            if ev['building_type'] == 'barrier': continue
            if ev['building_type'] == gamedata['townhall']:
                size = 26
            else:
                size = 12

            if ev.get('level',1) < 2:
                action = 'BUILD '
            else:
                action = 'UPGRADE '
            if 1 and ev.get('method','') == 'instant':
                color = 'green'
            else:
                color = 'black'
            svg.addElement(slanted_text(action+ev['building_type']+' L%d' % ev.get('level',1), x, y-10, -45, fill=color, font_size=size))
            svg.addElement(sh.createLine(x, y, x, y-10, stroke=color))
        elif ev['event_name'] == '3080_research_tech':
            if ev.get('level',1) == 1:
                size = 26
            else:
                size = 15
            if 1 and ev.get('method','') == 'instant':
                color = 'green'
            else:
                color = 'black'
            svg.addElement(slanted_text('UNLK '+ev['tech_type']+' L%d' % ev.get('level',1), x, y-10, -45, fill=color, font_size=size))
            svg.addElement(sh.createLine(x, y, x, y-10, stroke=color))

        last_x = x

    svg.set_width(max_x + max_bump + 20)

    # border
    svg.addElement(sh.createRect(0, 0, svg.get_width(), svg.get_height()))

    svg.saveFd(sys.stdout)
    # read all user/player data from upcache
    #metrics = json.load(FastGzipFile.Reader('logs/upcache.json.gz'))

