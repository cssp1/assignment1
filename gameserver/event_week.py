#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# print start/end times for a specific week

import SpinJSON, SpinConfig, Timezones
import time, datetime, getopt, sys

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
WEEKDAYS = {0: 'Mon', 1:'Tue', 2:'Wed', 3:'Thu', 4:'Fri', 5:'Sat', 6:'Sun'}

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['week='])

    time_now = int(time.time())
    cur_week = SpinConfig.get_pvp_week(gamedata['matchmaking']['week_origin'], time_now)

    for key, val in opts:
        if key == '--week':
            cur_week = int(val)
    print '// %s WEEK %d' % (gamedata['strings']['game_name'].upper(), cur_week)

    start_time = (cur_week+0) * (7*24*60*60) + gamedata['matchmaking']['week_origin']
    end_time   = (cur_week+1) * (7*24*60*60) + gamedata['matchmaking']['week_origin']

    def ampm(hour):
        return 'am' if hour < 12 else 'pm'

    def fmt_time(t):
        gmt = time.gmtime(t)
        pacific = datetime.datetime.fromtimestamp(t, tz=Timezones.USPacific)
        pacific_weekday = pacific.weekday()
        return '%02d:%02d%s UTC (%02d:%02d%s %sPacific) %s %2d/%-2d %04d' % (gmt.tm_hour, gmt.tm_min, ampm(gmt.tm_hour), pacific.hour, pacific.minute, ampm(pacific.hour), WEEKDAYS[pacific_weekday]+' ' if pacific_weekday!=gmt.tm_wday else '', WEEKDAYS[gmt.tm_wday], gmt.tm_mon, gmt.tm_mday, gmt.tm_year)

    print '"start_time": %d, // %s' % (start_time, fmt_time(start_time))
    print '"end_time":   %d  // %s' % (end_time, fmt_time(end_time))
