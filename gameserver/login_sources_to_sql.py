#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_login_flow" from MongoDB to a MySQL database for analytics

import sys, time, getopt, re, urlparse
import SpinConfig
import SpinSQLUtil
import SpinETL
import MySQLdb

time_now = int(time.time())
def login_sources_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('event_name', 'VARCHAR(128) NOT NULL'),
               ('user_id', 'INT4'),
               ('social_id', 'VARCHAR(128)'),
               ('frame_platform', 'CHAR(2)'),
               ('country', 'VARCHAR(2)'),
               ('country_tier', 'CHAR(1)'),
               ('ip', 'VARCHAR(16)'),
               ('browser_name', 'VARCHAR(16)'),
               ('browser_os', 'VARCHAR(16)'),
               ('browser_version', 'FLOAT4'),
               ('browser_hardware', 'VARCHAR(16)'),
               ('query_string', 'VARCHAR(1024)'),
               ('referer', 'VARCHAR(1024)'),
               ('acquisition_campaign', 'VARCHAR(128)'),
               ('ad_skynet', 'VARCHAR(256)'),
               ('fb_source', 'VARCHAR(128)'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }
#def login_sources_summary_schema(sql_util): return {
#    'fields': [('day', 'INT8 NOT NULL'),
#               ('event_name', 'VARCHAR(128) NOT NULL'),
#               ('count', 'INT4'),
#               ('unique_players', 'INT4')],
#    'indices': {'by_day': {'keys': [('day','ASC')]}}
#    }

# referer URL that looks like a "refresh your page" redirect from the game itself - not useful for analytics
reload_referer_re = re.compile('^http[s]?://.+prod.spinpunch.com/')

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    do_prune = False
    do_optimize = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    login_sources_table = cfg['table_prefix']+game_id+'_login_sources'
    login_sources_summary_table = cfg['table_prefix']+game_id+'_login_sources_daily_summary'

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    sql_util.ensure_table(cur, login_sources_table, login_sources_schema(sql_util))
#    sql_util.ensure_table(cur, login_sources_summary_table, login_sources_summary_schema(sql_util))
    con.commit()

    # find most recent already-converted action
    start_time = -1
    end_time = time_now - 30  # skip entries too close to "now" to ensure all events for a given second have all arrived

    cur.execute("SELECT time FROM "+sql_util.sym(login_sources_table)+" ORDER BY time DESC LIMIT 1")
    rows = cur.fetchall()
    if rows:
        start_time = max(start_time, rows[0]['time'])
    con.commit()

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    batch = 0
    total = 0
    affected_days = set()

    for row in SpinETL.iterate_from_mongodb(game_id, 'log_login_sources', start_time, end_time):
        keyvals = [('time',row['time']),
                   ('event_name',row['event_name'])]

        if ('country' in row) and row['country'] == 'unknown':
            del row['country'] # do not record "unknown" countries

        # write "unknown" browser info as NULLs to save space
        if 'browser_hardware' in row and row['browser_hardware'] == 'unknown':
            del row['browser_hardware']

        # append country_tier if necessary
        if ('country_tier' not in row) and ('country' in row):
            row['country_tier'] = SpinConfig.country_tier_map.get(row['country'], 4)

        if 'browser_OS' in row: # MongoDB log uses uppercase here for historical reasons, SQL uses lowercase
            row['browser_os'] = row['browser_OS']

        # don't bother writing apps.facebook.com or Kongregate iframe referers, since all info is redundant with query_string
        if 'referer' in row and \
           (row['referer'].startswith('https://apps.facebook.com/') or \
            ('kongregate_game_url=' in row['referer']) or \
            reload_referer_re.search(row['referer'])):
            del row['referer']

        # get rid of not-useful kongregate query string
        if 'query_string' in row and \
           ('kongregate_game_url=' in row['query_string']):
            del row['query_string']

        # fill in missing fb_source
        if ('query_string' in row) and \
           (not ('fb_source' in row)) and \
           ('fb_source=' in row['query_string']):
            q = urlparse.parse_qs(row['query_string'])
            if 'fb_source' in q:
                row['fb_source'] = q['fb_source'][-1]

        for FIELD in ('user_id','social_id','frame_platform','country','country_tier','ip',
                      'browser_name','browser_os','browser_version','browser_hardware','query_string','referer',
                      'acquisition_campaign','ad_skynet','fb_source'):
            if FIELD in row:
                keyvals.append((FIELD, row[FIELD]))

        sql_util.do_insert(cur, login_sources_table, keyvals)

        batch += 1
        total += 1
        affected_days.add(86400*(row['time']//86400))

        if commit_interval > 0 and batch >= commit_interval:
            batch = 0
            con.commit()
            if verbose: print total, 'inserted'

    con.commit()
    if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)'

    # XXX no summary yet

    if do_prune:
        # drop old data
        KEEP_DAYS = 60
        old_limit = time_now - KEEP_DAYS * 86400

        if verbose: print 'pruning', login_sources_table
        cur = con.cursor()
        cur.execute("DELETE FROM "+sql_util.sym(login_sources_table)+" WHERE time < %s", old_limit)
        if do_optimize:
            if verbose: print 'optimizing', login_sources_table
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(login_sources_table))
        con.commit()
