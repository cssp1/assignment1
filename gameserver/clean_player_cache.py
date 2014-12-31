#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Tool to clean up stale information in the dbserver player cache to make it more efficient
#
# This does two things:
# 1) for really old entries (players who haven't logged in for 60+ days), prune the entry
#    down to the bare minimum of useful fields (name, level, etc)
# 2) for all entries, prune away leaderboard score fields that are from seasons or weeks too
#    far in the past to matter anymore. This helps the dbserver get rid of old indexes.

import time, re
import SpinJSON, SpinConfig

time_now = int(time.time())
weekly_score_pattern = re.compile('^(score|quarry_resources|hive_kill_points|trophies|tokens_looted)_.*_wk([0-9]+)$')
season_score_pattern = re.compile('^(score|quarry_resources|hive_kill_points|trophies|tokens_looted)_.*_s([0-9]+)$')
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
cur_season = -1 # always prune
cur_week = -1 # always prune

def is_stale(entry, cur_time, stale_days):
    if (not entry) or len(entry) <= 6: return False # already pruned this
    age = cur_time - entry.get('last_login_time',-1)
    return age >= (stale_days * 24*60*60)

def pruned_stale_entry(entry):
    new_entry = {}
    for FIELD in ('ui_name', 'social_id', 'kg_avatar_url',
                  'facebook_id', 'kg_id'
                  ):
        if FIELD in entry:
            new_entry[FIELD] = entry[FIELD]
    if 'ui_name' not in entry: # fill in ui_name for legacy entries
        new_entry['ui_name'] = entry.get('facebook_name', entry.get('facebook_first_name', 'Unknown(clean)')).split(' ')[0]
    if entry.get('player_level',1) > 1:
        new_entry['player_level'] = entry['player_level']
    if entry.get('tutorial_complete', False):
        new_entry['tutorial_complete'] = 1
    return new_entry

def pruned_entry_scores(entry, max_week_age):
    new_entry = {}
    for key, val in entry.iteritems():
        week_match = weekly_score_pattern.match(key)
        if week_match:
            week_num = int(week_match.groups()[1])
            if cur_week < 0 or week_num < (cur_week - max_week_age):
                continue
        season_match = season_score_pattern.match(key)
        if season_match:
            season_num = int(season_match.groups()[1])
            if cur_season < 0 or season_num < cur_season:
                continue
        new_entry[key] = val
    return new_entry

if __name__ == '__main__':
    import sys, getopt

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['online', 'offline', 'prune-scores=', 'stale-days=', 'throttle=', 'dry-run'])
    mode = None
    prune_scores = -1
    throttle = 0.2
    stale_days = 60
    dry_run = False

    for key, val in opts:
        if key == '--online':
            mode = 'online'
        elif key == '--offline':
            mode = 'offline'
        elif key == '--prune-scores':
            prune_scores = int(val)
            sys.stderr.write('pruning trophy scores\n')
        elif key == '--throttle':
            throttle = float(val)
        elif key == '--stale-days':
            stale_days = int(val)
        elif key == '--dry-run':
            dry_run = True

    if mode is None:
        print 'usage: clean_player_cache.py OPTIONS [filename.txt if in offline mode]'
        print 'Options:'
        print '    --online          Proceed by interacting with the live dbserver'
        print '    --offline         DANGEROUS, DO NOT USE ON LIVE SERVER - work on db/player_cache.txt directly'
        print '    --stale-days N    Consider entries stale if player has not logged in for N days (default 60)'
        print '    --prune-scores N  Also prune leaderboard scores older than N weeks (disabled by default)'
        print '    --throttle SEC    Pause SEC between dbserver queries to avoid overload'
        print '    --dry-run         Do not write any changes (applies to online mode only)'
        sys.exit(1)



    count = 0
    stale = 0
    pruned = 0
    stats = ''

    if mode == 'online':
        # talk to dbserver to do the pruning
        import SpinConfig, SpinNoSQL
        db_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
        id_range = db_client.get_user_id_range()
        step = 32
        print 'ID RANGE', id_range, 'STEP', step
        for id_start in xrange(id_range[0], id_range[1]+1, step):
            id_end = min(id_start+step, id_range[1])
            id_list = range(id_start, id_end+1)
            entry_list = db_client.player_cache_lookup_batch(id_list)
            for id, entry in zip(id_list, entry_list):
                count += 1
                if entry:
                    assert entry.get('user_id',id) == id
                    entry_is_stale = is_stale(entry, time_now, stale_days)
                    #print 'STALE' if entry_is_stale else 'NOT STALE', entry
                    if entry_is_stale:
                        stale += 1
                        new_entry = pruned_stale_entry(entry)
                        if not dry_run:
                            db_client.player_cache_update(id, new_entry, overwrite = True)
                    elif prune_scores >= 2:
                        new_entry = pruned_entry_scores(entry, prune_scores)
                        if len(new_entry) < len(entry):
                            pruned += 1
                            if not dry_run:
                                db_client.player_cache_update(id, new_entry, overwrite = True)

                if count % 1000 == 0:
                    sys.stderr.write('count: %d stale: %d pruned: %d\n' % (count, stale, pruned))
            if throttle > 0:
                time.sleep(throttle)

    elif mode == 'offline':
        # process the JSON file directly (note: only works with files written with one entry per line, via SpinJSON)
        entry_pattern = re.compile('\"([0-9]+)\".*(\{.*\})')
        infile = open(args[0])
        opener = infile.readline()
        print '{'

        inbytes = 0
        outbytes = 0
        while True:
            line = infile.readline()
            if line.startswith('}'):
                break
            inbytes += len(line)
            line = line.strip()
            ends_with_comma = line.endswith(',')

            sid, str_entry = entry_pattern.search(line).groups()
            entry = SpinJSON.loads(str_entry)
            count += 1
            if is_stale(entry, time_now, stale_days):
                stale += 1
                new_entry = pruned_stale_entry(entry)
            elif prune_scores >= 2:
                new_entry = pruned_entry_scores(entry, prune_scores)
                if len(new_entry) < len(entry):
                    pruned += 1
            else:
                new_entry = entry
            new_line = '"%s":' % (sid) + SpinJSON.dumps(new_entry, pretty = False, double_precision = 5, newline = False) + (',' if ends_with_comma else '')
            outbytes += len(new_line) + 1 # +1 for the carriage return
            print new_line
            if count % 1000 == 0:
                sys.stderr.write('count: %d stale: %d pruned: %d\n' % (count, stale, pruned))
        print '}'
        stats = 'in: %.2f MB out: %.2f MB' % (inbytes/(1024.0*1024.0), outbytes/(1024.0*1024.0))

    sys.stderr.write('final count: %d stale: %d pruned: %d %s\n' % (count, stale, pruned, stats))
