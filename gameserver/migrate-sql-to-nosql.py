#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to move alliance/score/donation tables from MySQL to MongoDB
# OBSOLETE

import SpinConfig
import SpinSQL
import SpinNoSQL
import MySQLdb
import sys, time, getopt

time_now = int(time.time())

def migrate_alliances(sql_client, nosql_client):
    sql_cur = sql_client.con.cursor(MySQLdb.cursors.DictCursor)
    sql_cur.execute("SELECT id,ui_name,ui_description,join_type,founder_id,leader_id,logo,chat_motd,UNIX_TIMESTAMP(creation_time) AS creation_time FROM alliances")
    for row in sql_cur.fetchall():
        if row['logo'] == '0': row['logo'] = 'tetris_red'
        nosql_client.alliance_table('alliances').insert_one({'_id':int(row['id']), 'ui_name':row['ui_name'], 'ui_description':row['ui_description'],
                                                             'join_type':SpinSQL.SQLClient.ALLIANCE_JOIN_TYPES_REV[row['join_type']],
                                                             'founder_id':int(row['founder_id']),
                                                             'leader_id':int(row['leader_id']), 'logo':row['logo'], 'creation_time':int(row['creation_time']),
                                                             'chat_motd':row['chat_motd']})
    sql_client.con.commit()

def migrate_alliance_members(sql_client, nosql_client):
    sql_cur = sql_client.con.cursor(MySQLdb.cursors.DictCursor)
    sql_cur.execute("SELECT user_id,alliance_id,UNIX_TIMESTAMP(join_time) AS join_time FROM alliance_members")
    for row in sql_cur.fetchall():
        nosql_client.alliance_table('alliance_members').insert_one({'_id':int(row['user_id']), 'alliance_id':int(row['alliance_id']), 'join_time':int(row['join_time'])})
    sql_client.con.commit()

def migrate_alliance_invites(sql_client, nosql_client):
    sql_cur = sql_client.con.cursor(MySQLdb.cursors.DictCursor)
    sql_cur.execute("SELECT user_id,alliance_id,UNIX_TIMESTAMP(creation_time) AS creation_time,UNIX_TIMESTAMP(expire_time) as expire_time FROM alliance_invites")
    for row in sql_cur.fetchall():
        nosql_client.alliance_table('alliance_invites').insert_one({'user_id':int(row['user_id']), 'alliance_id':int(row['alliance_id']), 'creation_time':int(row['creation_time']), 'expire_time':int(row['expire_time'])})
    sql_client.con.commit()
def migrate_alliance_join_requests(sql_client, nosql_client):
    sql_cur = sql_client.con.cursor(MySQLdb.cursors.DictCursor)
    sql_cur.execute("SELECT user_id,alliance_id,UNIX_TIMESTAMP(creation_time) AS creation_time,UNIX_TIMESTAMP(expire_time) as expire_time FROM alliance_join_requests")
    for row in sql_cur.fetchall():
        nosql_client.alliance_table('alliance_join_requests').insert_one({'user_id':int(row['user_id']), 'alliance_id':int(row['alliance_id']), 'creation_time':int(row['creation_time']), 'expire_time':int(row['expire_time'])})
    sql_client.con.commit()

FREQ_MAP = {SpinSQL.SQLClient.SCORE_FREQ_SEASON: 'season', SpinSQL.SQLClient.SCORE_FREQ_WEEKLY: 'week'}

def migrate_player_scores(sql_client, nosql_client):
    sql_cur = sql_client.con.cursor(MySQLdb.cursors.DictCursor)
    sql_cur.execute("SELECT user_id,field_name AS field,frequency AS int_frequency,period,score FROM player_scores")
    for row in sql_cur.fetchall():
        addr = nosql_client.parse_score_addr((row['field'],FREQ_MAP[row['int_frequency']],row['period']))
        nosql_client.player_scores().insert_one({'field':addr['field'], 'frequency':addr['frequency'], 'period':int(addr['period']), 'user_id': int(row['user_id']), 'score': int(row['score'])})
    sql_client.con.commit()

def migrate_alliance_score_cache(sql_client, nosql_client):
    sql_cur = sql_client.con.cursor(MySQLdb.cursors.DictCursor)
    sql_cur.execute("SELECT alliance_id,field_name AS field,frequency AS int_frequency,period,score FROM alliance_score_cache")
    for row in sql_cur.fetchall():
        addr = nosql_client.parse_score_addr((row['field'],FREQ_MAP[row['int_frequency']],row['period']))
        nosql_client.alliance_score_cache().insert_one({'field':addr['field'], 'frequency':addr['frequency'], 'period':int(addr['period']), 'alliance_id': int(row['alliance_id']), 'score': int(row['score'])})
    sql_client.con.commit()

def migrate_unit_donation_requests(sql_client, nosql_client):
    sql_cur = sql_client.con.cursor(MySQLdb.cursors.DictCursor)
    sql_cur.execute("SELECT user_id,alliance_id,UNIX_TIMESTAMP(time) as time,tag,cur_space,max_space FROM unit_donation_requests")
    for row in sql_cur.fetchall():
        nosql_client.unit_donation_requests_table().insert_one({'_id':int(row['user_id']), 'alliance_id':int(row['alliance_id']), 'time':int(row['time']), 'tag':int(row['tag']),
                                                            'space_left': int(row['max_space']-row['cur_space']), 'max_space':int(row['max_space'])})
    sql_client.con.commit()

if __name__ == '__main__':
    yes_i_am_sure = False
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['yes-i-am-sure'])
    for key, val in opts:
        if key == '--yes-i-am-sure': yes_i_am_sure = True

    if not yes_i_am_sure:
        print 'DESTROYS data in SpinNoSQL, use --yes-i-am-sure flag to confirm.'
        sys.exit(1)

    sql_client = SpinSQL.SQLClient(SpinConfig.config['sqlserver'])
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))

    for TABLE in ('alliance_invites', 'alliance_join_requests', 'alliance_members', 'alliance_score_cache', 'alliances', 'player_scores', 'unit_donation_requests'):
        nosql_client._table(TABLE).drop()

    print 'alliances...'
    migrate_alliances(sql_client, nosql_client)
    print 'alliance_members...'
    migrate_alliance_members(sql_client, nosql_client)
    print 'alliance_invites...'
    migrate_alliance_invites(sql_client, nosql_client)
    print 'alliance_join_requests...'
    migrate_alliance_join_requests(sql_client, nosql_client)
    print 'player_scores...'
    migrate_player_scores(sql_client, nosql_client)
    print 'alliance_score_cache...'
    migrate_alliance_score_cache(sql_client, nosql_client)
    print 'unit_donation_requests...'
    migrate_unit_donation_requests(sql_client, nosql_client)

    # fix num_members_cache
    import SpinJSON
    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
    cur_season = -1
    cur_week = -1
    nosql_client.do_maint(time_now, cur_season, cur_week)
