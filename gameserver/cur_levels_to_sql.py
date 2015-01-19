#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# AFTER dumping "sessions", "stats", and upcache ("level_at_time") tables,
# compute summary of players who have achieved each level of each possible building/tech upgrade

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinSQLUtil
import SpinETL
import MySQLdb

time_now = int(time.time())

# temporary table holding users who logged in that day
def logins_schema(sql_util): return {
    'fields':  [('user_id', 'INT4 NOT NULL')] + \
               sql_util.summary_out_dimensions(),
    'indices': {'by_user_id': {'unique': True, 'keys': [('user_id','ASC')]}}
    }

# temporary table holding the current levels of units/buildings owned by all players who logged in that day
def cur_levels_schema(sql_util): return {
    'fields': [('user_id', 'INT4 NOT NULL')] + \
              [
               ('kind', 'VARCHAR(16) NOT NULL'),
               ('spec', 'VARCHAR(64) NOT NULL'),
               ('level', 'INT1'),
               ],
    'indices': {}
    }

def cur_levels_summary_schema(sql_util, interval_name): return {
    'fields': [(interval_name, 'INT8 NOT NULL')] + \
               sql_util.summary_out_dimensions()  + \
              [('kind', 'VARCHAR(16) NOT NULL'),
               ('spec', 'VARCHAR(64) NOT NULL'),
               ('level', 'INT1'),
               ('is_maxed', 'TINYINT(1) NOT NULL'), # flag that this is the max level of the spec
               # OUTPUT
               ('num_players', 'INT8 NOT NULL')
               ],
    'indices': {'by_interval': {'unique': False, 'keys': [(interval_name,'ASC')]}}
    }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 100
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

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    stats_table = cfg['table_prefix']+game_id+'_stats'
    sessions_table = cfg['table_prefix']+game_id+'_sessions'
    logins_table = cfg['table_prefix']+game_id+'_logins_temp'
    cur_levels_table = cfg['table_prefix']+game_id+'_cur_levels_temp'
    cur_levels_daily_summary_table = cfg['table_prefix']+game_id+'_cur_levels_daily_summary'
    cur = con.cursor(MySQLdb.cursors.DictCursor)

    for table, schema in ((cur_levels_daily_summary_table, cur_levels_summary_schema(sql_util, 'day')),):
        sql_util.ensure_table(cur, table, schema)
    con.commit()

    # find range of session data available
    start_time = -1
    end_time = time_now - SpinETL.MAX_SESSION_LENGTH

    cur.execute("SELECT MIN(start) AS start, MAX(start) AS end FROM "+sql_util.sym(sessions_table))
    rows = cur.fetchall()
    if rows:
        start_time = rows[0]['start']
        end_time = min(end_time, rows[0]['end'])

    if start_time < 0:
        print 'no sessions data to work with'
        sys.exit(0)

    if verbose: print 'start_time', start_time, 'end_time', end_time

    def update_cur_levels_summary(cur, table, interval, day_start, dt):
        # temporary table setup
        temp_tables = (logins_table, cur_levels_table)
        for t in temp_tables: cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(t))
        try:
            sql_util.ensure_table(cur, logins_table, logins_schema(sql_util), temporary = False)
            sql_util.ensure_table(cur, cur_levels_table, cur_levels_schema(sql_util), temporary = False)

            # accumulate list of players who logged in this day, with summary info
            cur.execute("INSERT INTO "+sql_util.sym(logins_table) + " " + \
                        "SELECT s.user_id AS user_id," + \
                        "       s.frame_platform AS frame_platform," + \
                        "       s.country_tier AS country_tier," + \
                        "       MAX(s.townhall_level) AS townhall_level," + \
                        "       "+sql_util.encode_spend_bracket("MIN(IFNULL(s.prev_receipts,0))")+" AS spend_bracket " + \
                        "FROM "+sql_util.sym(sessions_table)+" s " + \
                        "WHERE s.end >= %s AND s.start < %s " + \
                        "GROUP BY s.user_id",
                        [day_start, day_start+dt])

            # figure out current levels of each player's tech and buildings
            for kind, series_table, series_spec, series_level in (('tech', cfg['table_prefix']+game_id+'_tech_at_time', 'tech_name', 'level'),
                                                   ('building', cfg['table_prefix']+game_id+'_building_levels_at_time', 'building', 'max_level')):
                cur.execute("INSERT INTO "+sql_util.sym(cur_levels_table) + " " + \
                            "SELECT g.user_id AS user_id," + \
                            "       %s AS kind," + \
                            "       t."+sql_util.sym(series_spec)+" AS spec," + \
                            "       MAX(t."+sql_util.sym(series_level)+") AS level " + \
                            "FROM "+sql_util.sym(logins_table)+" g CROSS JOIN "+sql_util.sym(series_table)+" t "+ \
                            "WHERE t.user_id = g.user_id AND t.time < %s " + \
                            "GROUP BY user_id, kind, spec",
                            [kind, day_start+dt])

            # now count players at each level of each tech and building
            # note: this query can use SUM(1) instead of COUNT(DISTINCT(user_id)), it's the same result
            cur.execute("INSERT INTO "+sql_util.sym(cur_levels_daily_summary_table) + " " + \
                        "SELECT %s AS "+sql_util.sym(interval) + ", " + \
                        "       g.frame_platform AS frame_platform, " + \
                        "       g.country_tier AS country_tier, " + \
                        "       g.townhall_level AS townhall_level, " + \
                        "       g.spend_bracket AS spend_bracket, " + \
                        "       c.kind AS kind, " + \
                        "       c.spec AS spec, " + \
                        "       c.level AS level, " + \
                        "       IF(c.level = IFNULL((SELECT value_num FROM "+sql_util.sym(stats_table)+" stats WHERE stats.kind=c.kind AND stats.spec=c.spec AND stats.stat=%s),1),1,0) AS is_maxed, " + \
                        "       SUM(1) AS num_players " + \
                        "FROM "+sql_util.sym(cur_levels_table)+" c, "+sql_util.sym(logins_table)+" g " + \
                        "WHERE g.user_id = c.user_id " + \
                        "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, kind, spec, level",
                        [day_start, 'max_level'])

            # also add rows with spec = 'ANY' meaning "any building or tech"
            # note: this query needs COUNT(DISTINCT(user_id)), it's missing something from the WHERE or GROUP BY that would exclude duplicate rows
            cur.execute("INSERT INTO "+sql_util.sym(cur_levels_daily_summary_table) + " " + \
                        "SELECT %s AS "+sql_util.sym(interval) + ", " + \
                        "       g.frame_platform AS frame_platform, " + \
                        "       g.country_tier AS country_tier, " + \
                        "       g.townhall_level AS townhall_level, " + \
                        "       g.spend_bracket AS spend_bracket, " + \
                        "       c.kind AS kind, " + \
                        "       %s AS spec, " + \
                        "       NULL AS level, " + \
                        "       1 AS is_maxed, " + \
                        "       COUNT(DISTINCT(g.user_id)) AS num_players " + \
                        "FROM "+sql_util.sym(cur_levels_table)+" c, "+sql_util.sym(logins_table)+" g " + \
                        "WHERE g.user_id = c.user_id AND " + \
                        "c.level > 1 AND " + \
                        "c.level = (SELECT value_num FROM "+sql_util.sym(stats_table)+" stats WHERE stats.kind=c.kind AND stats.spec=c.spec AND stats.stat=%s) " + \
                        "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, kind",
                        [day_start, 'ANY', 'max_level'])

        finally:
            for t in temp_tables: cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(t))


    SpinETL.update_summary(sql_util, con, cur, cur_levels_daily_summary_table,
                           set(), [start_time, end_time], 'day', 86400,
                           verbose = verbose, execute_func = update_cur_levels_summary, resummarize_tail = 86400)
