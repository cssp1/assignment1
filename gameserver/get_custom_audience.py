#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this script scans upcache and prints out a list of Facebook IDs for players
# who meet specific spend or churn criteria. Used for building custom audiences
# for Facebook ads.

import sys, time, getopt, copy
import SpinS3, SpinUpcacheIO, SpinConfig, SpinParallel

time_now = int(time.time())

def stream_upcache(game_id, info = None):
    bucket, name = SpinConfig.upcache_s3_location(game_id)
    return SpinUpcacheIO.S3Reader(SpinS3.S3(SpinConfig.aws_key_file()), bucket, name, verbose = False, info = info)

def open_output_fd(aud):
    if 'filename' in aud:
        filename = aud['filename']
    else:
        date_str = time.strftime('%Y%m%d',time.gmtime(time_now))
        filename = 'audience-%s-%s-%s.txt' % (aud['game_id'], aud['aud'], date_str)
    if filename == '-':
        return sys.stdout
    else:
        return open(filename, 'a')

def do_slave(input):
    cache = stream_upcache(input['game_id'], input['cache_info'])
    auds = input['auds']
    verbose = input['verbose']

    outputs = [{'aud': copy.deepcopy(aud), 'count':0} for aud in auds]
    fds = [open_output_fd(aud) for aud in auds]

    for user in cache.iter_segment(input['segnum']):
        if ('facebook_id' not in user):
            if verbose: print >> sys.stderr, user['user_id'], 'no facebook_id'
            continue

        for i, aud in enumerate(auds):
            min_spend = aud['min_spend']
            churned_for_days = aud['churned_for_days']
            fd = fds[i]

            net_spend = user.get('money_spent',0) - user.get('money_refunded',0)

            if net_spend < min_spend:
                continue

            if aud.get('country',None) and (user.get('country','unknown').lower() != aud['country'].lower()):
                if verbose: print >> sys.stderr, user['user_id'], 'country mismatch'
                continue

            lapsed = -1
            if churned_for_days > 0:
                if 'sessions' not in user or len(user['sessions']) < 2:
                    if verbose: print >> sys.stderr, user['user_id'], '<2 sessions'
                    continue

                last_login_time = max(user['sessions'][-1][0], user['sessions'][-2][0])
                lapsed = time_now - last_login_time
                if lapsed < churned_for_days*24*60*60:
                    if verbose: print >> sys.stderr, user['user_id'], 'logged in recently'
                    continue

            if verbose: print >> sys.stderr, user['user_id'], 'GOOD!', 'spent', net_spend, 'lapsed %.1f' % (lapsed/86400.0)
            print >> fd, user['facebook_id']
            outputs[i]['count'] += 1

    return {'result':outputs}

if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(do_slave)
        sys.exit(0)

    game_id = SpinConfig.game()
    min_spend = 100
    churned_for_days = -1
    country = None
    filename = '-'
    do_all = False
    parallel = 1
    verbose = True

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:q', ['min-spend=', 'churned-for=','all','quiet','parallel=','country=','filename='])
    for key, val in opts:
        if key == '--min-spend': min_spend = float(val)
        elif key == '--churned-for': churned_for_days = int(val)
        elif key == '-g': game_id = val
        elif key == '--all': do_all = True
        elif key == '-q' or key == '--quiet': verbose = False
        elif key == '--parallel': parallel = int(val)
        elif key == '--country': country = val
        elif key == '--filename': filename = val

    if do_all:

        # all-country churned-payer, ALL, and payer audiences, then country-specific payer audiences (for lookalike seeding)
        def auds_for_game(gid):
            ret = [{'game_id':gid, 'aud':'p10-c10', 'min_spend':10, 'churned_for_days':10},
                   {'game_id':gid, 'aud':'p10-c30', 'min_spend':10, 'churned_for_days':30},
                   {'game_id':gid, 'aud':'p10', 'min_spend':10, 'churned_for_days':-1},
                   ]
            if gid in ('tr','sg','dv'):
                ret.append({'game_id':gid, 'aud':'ALL', 'min_spend':-1, 'churned_for_days':-1})
            if 0:
                for country in ('us','ca','gb','au','nz','dk','nl','no','se'):
                    ret.append({'game_id':gid, 'aud':'p10-n%s' % country, 'min_spend':10, 'churned_for_days':-1, 'country':country})
            return ret
        auds = []
        for gid in ('mf','tr','mf2','bfm','sg','dv'):
            auds += auds_for_game(gid)

    else:
        auds = [{'game_id':game_id, 'filename':filename, 'min_spend':min_spend, 'churned_for_days':churned_for_days, 'country':country}]

    if verbose:
        for aud in auds: print aud

    # group auds by game so that we can run all auds from that game in one pass through upcache
    auds_by_game = dict((gid, filter(lambda aud: aud['game_id'] == gid, auds)) for gid in set([aud['game_id'] for aud in auds]))

    # get cache info per game
    caches_by_game = dict((gid, stream_upcache(gid)) for gid in auds_by_game)

    tasks = [{'game_id':gid, 'cache_info':caches_by_game[gid].info, 'verbose':verbose,
              'auds': auds_by_game[gid], 'segnum': segnum} for gid in auds_by_game
             for segnum in range(0, caches_by_game[gid].num_segments())]

    if parallel <= 1:
        outputs = [do_slave(task) for task in tasks]
    else:
        outputs = SpinParallel.go(tasks, [sys.argv[0], '--slave'], nprocs = parallel, verbose = False)

    # collapse multiple segments together
    for output in outputs:
        print >> sys.stderr, output



