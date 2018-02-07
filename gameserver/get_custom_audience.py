#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this script scans upcache (or the Battlehouse user database from bh_import_user_data.py)
# and prints out a list of Facebook IDs for players
# who meet specific spend or churn criteria. Used for building custom audiences
# for Facebook ads.

import sys, time, getopt, copy
import SpinS3, SpinUpcacheIO, SpinConfig, SpinParallel
import SpinSQLUtil, MySQLdb

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
    if input['game_id'] == 'bh':
        return do_slave_bh(input)
    else:
        return do_slave_upcache(input)

def do_slave_bh(input):
    # scan bh.com accounts via the SQL table created by bh_import_user_data.py
    sql_util = SpinSQLUtil.MySQLUtil()
    if not input['verbose']: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config('skynet')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    bh_users_table = cfg['table_prefix']+'bh_users'
    cur = con.cursor(MySQLdb.cursors.DictCursor)

    auds = input['auds']
    outputs = [{'aud': copy.deepcopy(aud), 'count':0} for aud in auds]
    fds = [open_output_fd(aud) for aud in auds]

    # note: the money_spent calculation is a hack until we set up reporting from the game servers to loginserver

    cur.execute("SELECT user_id, facebook_id, ui_email, last_login_time," + \
                " (SELECT IFNULL(money_spent,0) FROM fs_upcache." + sql_util.sym('fs_upcache') + \
                "  WHERE fs_upcache.bh_id = bh.user_id) AS net_spend " + \
                "FROM " + sql_util.sym(bh_users_table) + " bh " + \
                "WHERE (facebook_id IS NOT NULL) OR (ui_email IS NOT NULL)")

    for user in cur.fetchall():
        for i, aud in enumerate(auds):
            min_spend = aud['min_spend']
            churned_for_days = aud['churned_for_days']
            played_within_days = aud.get('played_within_days', -1)

            fd = fds[i]

            net_spend = user.get('net_spend', 0)

            if net_spend < min_spend:
                continue

            if aud.get('country'):
                raise Exception('country is unreliable')

            if aud.get('country',None) and (user.get('country','unknown').lower() != aud['country'].lower()):
                if verbose: print >> sys.stderr, user['user_id'], 'country mismatch'
                continue

            last_login_time = user['last_login_time']
            lapsed = time_now - last_login_time
            if churned_for_days > 0:
                if lapsed < churned_for_days*24*60*60:
                    if verbose: print >> sys.stderr, user['user_id'], 'logged in recently'
                    continue
            if played_within_days > 0:
                if lapsed > played_within_days*24*60*60:
                    if verbose: print >> sys.stderr, user['user_id'], 'did not play recently'
                    continue

            if verbose: print >> sys.stderr, user['user_id'], 'GOOD!', 'spent', net_spend, 'lapsed %.1f' % (lapsed/86400.0)
            if user['facebook_id']:
                print >> fd, user['facebook_id']
            if user['ui_email']:
                print >> fd, user['ui_email']
            outputs[i]['count'] += 1

    con.commit()

    return {'result':outputs}

def do_slave_upcache(input):
    # scan game players via per-game upcache
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
            played_within_days = aud.get('played_within_days', -1)
            fd = fds[i]

            net_spend = user.get('money_spent',0) - user.get('money_refunded',0)

            if net_spend < min_spend:
                continue

            if aud.get('country',None) and (user.get('country','unknown').lower() != aud['country'].lower()):
                if verbose: print >> sys.stderr, user['user_id'], 'country mismatch'
                continue

            lapsed = -1
            if churned_for_days > 0 or played_within_days > 0:
                if 'sessions' not in user or len(user['sessions']) < 2:
                    if verbose: print >> sys.stderr, user['user_id'], '<2 sessions'
                    continue

                last_login_time = max(user['sessions'][-1][0], user['sessions'][-2][0])
                lapsed = time_now - last_login_time
                if churned_for_days > 0:
                    if lapsed < churned_for_days*24*60*60:
                        if verbose: print >> sys.stderr, user['user_id'], 'logged in recently'
                        continue
                if played_within_days > 0:
                    if lapsed > played_within_days*24*60*60:
                        if verbose: print >> sys.stderr, user['user_id'], 'did not play recently'
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
            ret = [#{'game_id':gid, 'aud':'p10-c10', 'min_spend':10, 'churned_for_days':10},
                   #{'game_id':gid, 'aud':'p10-c30', 'min_spend':10, 'churned_for_days':30},
                   #{'game_id':gid, 'aud':'p10-c90', 'min_spend':10, 'churned_for_days':90},
                   {'game_id':gid, 'aud':'p10', 'min_spend':10, 'churned_for_days':-1},
                   ]
#            if gid in ('dv','tr','fs',):
#                ret.append({'game_id':gid, 'aud':'ALL', 'min_spend':-1, 'churned_for_days':-1})
            if gid in ('dv','tr',):
                ret.append({'game_id':gid, 'aud':'a60', 'min_spend':-1, 'churned_for_days':-1, 'played_within_days': 60})
            if 0:
                for country in ('us','ca','gb','au','nz','dk','nl','no','se'):
                    ret.append({'game_id':gid, 'aud':'p10-n%s' % country, 'min_spend':10, 'churned_for_days':-1, 'country':country})
            return ret
        auds = []
        for gid in ('mf','tr','mf2','bfm','sg','dv',): # note: FS not necessary - use BH for that
            auds += auds_for_game(gid)

        auds += [#{'game_id': 'bh', 'aud': 'ALL', 'min_spend':-1, 'churned_for_days':-1},
                 {'game_id': 'bh', 'aud': 'a60', 'min_spend':-1, 'churned_for_days':-1, 'played_within_days': 60},
                 {'game_id': 'bh', 'aud': 'p10', 'min_spend':10, 'churned_for_days':-1},
                 ]

    else:
        auds = [{'game_id':game_id, 'filename':filename, 'min_spend':min_spend, 'churned_for_days':churned_for_days, 'country':country}]

    if verbose:
        for aud in auds: print aud

    # group auds by game so that we can run all auds from that game in one pass through upcache
    auds_by_game = dict((gid, filter(lambda aud: aud['game_id'] == gid, auds)) for gid in set([aud['game_id'] for aud in auds]))

    # note: 'bh' is handled as if it were a "game", but it uses a separate scan method

    # get cache info per game
    caches_by_game = dict((gid, stream_upcache(gid)) for gid in auds_by_game if gid != 'bh')

    tasks = [{'game_id':gid, 'cache_info':caches_by_game[gid].info, 'verbose':verbose,
              'auds': auds_by_game[gid], 'segnum': segnum} for gid in auds_by_game if gid != 'bh'
             for segnum in range(0, caches_by_game[gid].num_segments())]

    if 'bh' in auds_by_game:
        tasks.append({'game_id': 'bh', 'verbose': verbose,
                      'auds': auds_by_game['bh']})

    if parallel <= 1:
        outputs = [do_slave(task) for task in tasks]
    else:
        outputs = SpinParallel.go(tasks, [sys.argv[0], '--slave'], nprocs = parallel, verbose = False)

    # collapse multiple segments together
    for output in outputs:
        print >> sys.stderr, output



