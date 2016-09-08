#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# create a small JSON file for uploading to the battlehouse.com "news feed" system

import SpinJSON
import SpinNoSQL
import SpinConfig
from Scores2 import MongoScores2, make_point, FREQ_WEEK, SPACE_ALL, SPACE_ALL_LOC
import SpinS3
import sys, time



if __name__ == '__main__':
    server_time = int(time.time())
    client = None

    s3_bucket = SpinConfig.config.get('battlehouse_newsfeed_s3_bucket')
    if not s3_bucket: sys.exit(0)

    s3_con = SpinS3.S3(SpinConfig.aws_key_file(), use_ssl=True)

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

    pvp_day = SpinConfig.get_pvp_day(gamedata['matchmaking']['week_origin'], server_time)
    pvp_week = SpinConfig.get_pvp_week(gamedata['matchmaking']['week_origin'], server_time)

    # connect to database
    client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    client.set_time(server_time)
    api = MongoScores2(client)

    # get global stats
    # number of battles within last 24hrs
    battle_count = client.battles_table().find({'time': {'$gte': server_time - 86400}}).count()
    # number of players online right now
    online_count = client.sessions_table().count()

    news = {'time': server_time,
            'game_id': gamedata['game_id'],
            'ui_game': gamedata['strings']['game_name'],
            'battles_last_24h': battle_count,
            'online_count': online_count}

    # score leaders
    news['score_leaders'] = {}
    for category in ('xp', 'resources_looted', 'damage_inflicted', 'trophies_pvp', 'hive_kill_points', 'tokens_looted'):
        leaders_list = api.player_scores2_get_leaders([(category, make_point(FREQ_WEEK, pvp_week, SPACE_ALL, SPACE_ALL_LOC))], 1)[0]
        if not leaders_list: continue
        leader = leaders_list[0]
        pcache = client.player_cache().find_one({'_id':leader['user_id']}, {'ui_name':1, 'player_level':1})
        leader['ui_name'] = pcache['ui_name']
        leader['player_level'] = pcache['player_level']
        news['score_leaders'][category] = [leader,]

    # detect current event
    event = None
    event_end_time = None
    event_ui_title = None

    for entry in gamedata['event_schedule']:
        if entry['name'].endswith('_preannounce'): continue
        if entry['start_time'] >= server_time: continue
        if 'repeat_interval' in entry:
            delta = (server_time - entry['start_time']) % entry['repeat_interval']
            if delta >= (entry['end_time'] - entry['start_time']): continue # we are between runs
            end_time = server_time + (entry['end_time'] - entry['start_time']) - delta
        else:
            if entry['end_time'] <= server_time: continue # event is in the past
            end_time = entry['end_time']

        ev = gamedata['events'][entry['name']]
        if ev['kind'] != 'current_event': continue
        if 'ui_title' in ev:
            ui_title = ev['ui_title']
        elif 'chain' in ev:
            ui_title = ev['chain'][0][1]['ui_title']
        else:
            continue # no idea how to get title

        event = ev
        event_end_time = end_time
        event_ui_title = ui_title

    if event:
        news['event'] = {'ui_name': event_ui_title,
                         'end_time': event_end_time}

    news_str = SpinJSON.dumps(news, pretty = True, newline = True)
    s3_con.put_buffer(SpinConfig.config['battlehouse_newsfeed_s3_bucket'], SpinConfig.game()+'-news.json', news_str)

