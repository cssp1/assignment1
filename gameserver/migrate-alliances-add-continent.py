#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to add "continent" field to existing alliances

import SpinConfig
import SpinUserDB
import SpinNoSQL
import SpinJSON

if __name__ == '__main__':
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

    converted = 0

    for row in nosql_client.alliance_table('alliances').find(): # {'continent':{'$exists':False}}):
        members = nosql_client.get_alliance_members(row['_id'])
        for mem in members:
            if mem['role'] == nosql_client.ROLE_LEADER:
                print 'alliance', row['_id'], 'leader', mem['user_id'], 'continent', row.get('continent', 'NONE'),
                if 'continent' not in row:
                    user = SpinJSON.loads(SpinUserDB.driver.sync_download_user(mem['user_id']))
                    if user.get('country','unknown') in gamedata['predicate_library']['eng_region_access']['countries']:
                        new_continent = 'fb_eng'
                    else:
                        new_continent = 'fb_intl'
                    if 1:
                        nosql_client.alliance_table('alliances').update_one({'_id':row['_id']}, {'$set':{'continent':new_continent}})
                    converted += 1
                    print '->', new_continent
                else:
                    print

    print 'updated', converted
