#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump Asana calendar to SQL for analytics use

import sys, getopt, calendar, re
import SpinConfig
import SpinSQLUtil
import SpinSingletonProcess
import asana

schedule_schema = {
    'fields': [('id', 'VARCHAR(16)'), # Asana task ID, if present
               ('start_time', 'INT8 NOT NULL'),
               ('end_time', 'INT8'),
               ('game_id', 'VARCHAR(16)'),
               ('description', 'VARCHAR(256) NOT NULL')],
    'indices': {'by_start_time': {'keys': [('start_time','ASC')]}}
    }

# look for "TR/MF2: " etc
game_re = re.compile('^.*([A-Z0-9/]+):(?!$)')
game_delimiters = re.compile('\W+|/|\+')

if __name__ == '__main__':
    commit_interval = 1000
    verbose = True
    dry_run = False
    workspaces = []
    projects = []

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'c:q', ['dry-run','workspace=','project='])

    for key, val in opts:
        if key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--workspace': workspaces.append(val)
        elif key == '--project': projects.append(val)

    # query Asana API for workspaces -> projects -> tasks
    asc = asana.client.Client.basic_auth(SpinConfig.config['asana_api_key'])
    asworklist = [w for w in asc.workspaces.find_all() if w['name'] in workspaces]
    if not asworklist:
        raise Exception('Asana workspace(s) not found: %r' % workspaces)
    asprojlist = [p for aswork in asworklist for p in asc.projects.find_all({'workspace': aswork['id']}) if p['name'] in projects]
    if not asprojlist:
        raise Exception('Asana projects(s) not found: %r' % projects)

    astasklist = [t for asproj in asprojlist for t in asc.tasks.find_all({'project': asproj['id']}, fields=['id','name','due_on'])]

    # connect to database
    sql_util = SpinSQLUtil.MySQLUtil()
    game_id = SpinConfig.game()

    with SpinSingletonProcess.SingletonProcess('schedule_to_sql-%s' % game_id):

        if not dry_run:
            import MySQLdb
            cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
            con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
            cur = con.cursor(MySQLdb.cursors.DictCursor)
            sql_util.disable_warnings()
        else:
            cur = None
            cfg = {'table_prefix':''}

        schedule_table = cfg['table_prefix']+game_id+'_ship_schedule'

        if not dry_run:
            for tbl, schema in ((schedule_table, schedule_schema),):
                cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(tbl+'_temp'))
                sql_util.ensure_table(cur, tbl, schema)
                sql_util.ensure_table(cur, tbl+'_temp', schema)
            con.commit()

        total = 0
        for astask in astasklist:
            if astask['name'].startswith('[Duplicate]'): continue

            # parse due date
            if not astask.get('due_on'): continue
            y, m, d = map(int, astask['due_on'].split('-'))
            # convert to UNIX timestamp
            start_time = calendar.timegm([y, m, d, 0, 0, 0])

            # parse game ID: "TR/SG: whatever" -> ["tr","sg"]
            applicable_games = [None]

            match = game_re.search(astask['name'])
            if match:
                temp = match.group(0)
                temp = game_delimiters.split(temp)

                # make lowercase
                temp = map(lambda x: x.lower(), temp)

                # get rid of empty/irrelevant strings
                temp = filter(lambda x: x not in ('', 'pcheck', 'skynet', 'dev', 'okr', 'aoh', 'jb'), temp)
                temp = filter(lambda x: len(x) in (2,3), temp)
                temp = filter(lambda x: not x.isdigit(), temp)

                # map wse->mf2
                temp = map(lambda x: {'wse':'mf2'}.get(x,x), temp)

                if verbose:
                    print match.group(0), '->', temp

                if temp: # replace [None] with actual list
                    applicable_games = temp


            keyvals = [(('id', str(astask['id'])),
                        ('description', astask['name']),
                        ('start_time', start_time),
                        ('game_id', applicable_game)) \
                       for applicable_game in applicable_games]

            if not dry_run:
                sql_util.do_insert_batch(cur, schedule_table+'_temp', keyvals)
            total += 1

        if not dry_run: con.commit()
        if verbose: print 'total', total, 'events inserted'

        if not dry_run:
            for tbl in (schedule_table,):
                cur.execute("RENAME TABLE "+\
                            sql_util.sym(tbl)+" TO "+sql_util.sym(tbl+'_old')+","+\
                            sql_util.sym(tbl+'_temp')+" TO "+sql_util.sym(tbl))
                cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(tbl+'_old'))
            con.commit()
