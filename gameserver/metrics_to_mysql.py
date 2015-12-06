#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_metrics" table from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

gamedata = None
time_now = int(time.time())

# this is a bit ad-hoc since the types of events we are logging can
# change as we focus on different analyses over time. Also, this means
# we don't really do summaries.

def metrics_schema(sql_util): return {
    'fields': [('_id', 'CHAR(24) NOT NULL PRIMARY KEY'),
               ('time', 'INT8 NOT NULL'),
               ('user_id', 'INT4')] + \
              sql_util.summary_in_dimensions() + \
              [('code', 'INT4 NOT NULL'),
               ('event_name', 'VARCHAR(128)'),
               ('spec', 'VARCHAR(128)'),
               ('stack', 'INT4')
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }

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

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('metrics_to_mysql-%s' % game_id):

        metrics_table = cfg['table_prefix']+game_id+'_metrics'

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, metrics_table, metrics_schema(sql_util))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(metrics_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0

        qs = {'time':{'$gt':start_time,'$lt':end_time}}

        for row in nosql_client.log_buffer_table('log_metrics').find(qs):
            if 'user_id' not in row: continue # server_restart etc

            _id = nosql_client.decode_object_id(row['_id'])

            if 'code' not in row: # fix missing codes
                row['code'] = int(row['event_name'][0:4])

            keyvals = [('_id',_id),
                       ('time',row['time']),
                       ('user_id',row['user_id']),
                       ('code',row['code']),
                       ('event_name',row['event_name'])]

            if 'sum' in row:
                if row['sum'].get('developer', False): continue
                keyvals += sql_util.parse_brief_summary(row['sum'])

            if row['event_name'] == '5130_item_activated':
                keyvals.append(('spec',row['spec']))
            elif row['event_name'] == '5131_item_trashed':
                keyvals.append(('spec',row['spec']))
                keyvals.append(('stack',row.get('stack',1)))
            elif row['event_name'] in ('7530_cross_promo_banner_seen',
                                       '7531_cross_promo_banner_clicked'):
                keyvals.append(('spec',row.get('campaign',None)))
            elif row['event_name'] in ('4010_quest_complete',
                                       '4011_quest_complete_again'):
                keyvals.append(('spec',row['quest']))
                if 'count' in row:
                    keyvals.append(('stack',row['count']))
            elif row['event_name'] == '4701_change_region_success':
                if row.get('reason',None) in ('player_request',): # only include player-initiated changes
                    keyvals.append(('spec',row.get('new_region',None))) # stick the new region name in the 'spec' column
                else:
                    continue # do not dump "involuntary" region changes to SQL
            elif row['event_name'] == '4702_region_close_notified':
                keyvals.append(('spec',row.get('region',None))) # stick the region name in the 'spec' column

            elif row['event_name'] == '4120_send_gift_completed':
                if 'recipients' in row:
                    keyvals.append(('stack', len(row['recipients'])))
                if 'reason' in row:
                    keyvals.append(('spec', row['reason']))

            elif row['event_name'] in ('7150_friendstone_generated',
                                       '7151_friendstone_opened_send_ui',
                                       '7153_friendstone_sent',
                                       '7154_friendstone_received',
                                       '7155_friendstones_redeemed'):
                for f in ('recipient_id', 'sender_id', 'num_friends'):
                    if f in row:
                        keyvals.append(('stack', row[f]))

            elif row['event_name'] == '3350_no_miss_hack':
                keyvals.append(('spec', row['spellname']))

            elif row['event_name'] == '6000_reacquisition_gift_sent':
                keyvals.append(('spec', row['gift']))

            elif row['event_name'] == '5141_dp_cancel_aura_acquired':
                keyvals.append(('spec', row['aura_name']))
                keyvals.append(('stack', int(100*row['aura_strength'])))
            elif row['event_name'] == '5142_dp_cancel_aura_ended':
                keyvals.append(('spec', row['aura_name']))
                keyvals.append(('stack', row['start_time']))

            elif row['event_name'] == '4461_promo_warehouse_upgrade':
                keyvals.append(('stack', row['level']))

            elif row['event_name'] in ('0113_account_deauthorized',
                                       '0140_tutorial_oneway_ticket',
                                       '0140_tutorial_start',
                                       '0141_tutorial_start_client',
                                       '0145_deploy_one_unit',
                                       '0150_finish_battle',
                                       '0155_reward_finish_battle',
                                       '0160_accept_barracks_mission',
                                       '0170_click_barracks_on_menu',
                                       '0180_reward_barracks_mission',
                                       '0190_one_unit_queued',
                                       '0200_full_army_queued',
                                       '0210_reward_full_army_mission',
                                       '0220_click_attack_menu',
                                       '0230_base_attack_started',
                                       '0240_win_base_attack',
                                       '0244_reward_base_attack',
                                       '0246_proceed_incoming_message',
                                       '0250_click_allandra_console',
                                       '0260_click_warehouse',
                                       '0270_activate_mana_icon',
                                       '0280_reward_activate_item_mission',
                                       '0399_tutorial_complete',
                                       '0700_login_abuse_detected',
                                       '4056_strategy_guide_opened',
                                       '5149_turret_heads_migrated',
                                       '5200_insufficient_resources_dialog',
                                       '5201_insufficient_resources_go_to_store',
                                       '5202_insufficient_resources_topup_dialog',
                                       '5203_insufficient_resources_topup_buy_now',
                                       ):
                pass # include this
            else:
                continue # skip

            sql_util.do_insert(cur, metrics_table, keyvals)

            batch += 1
            total += 1
            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted'

        if do_prune:
            # drop old data
            KEEP_DAYS = 90
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', metrics_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(metrics_table)+" WHERE time < %s", old_limit)
            if do_optimize:
                if verbose: print 'optimizing', metrics_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(metrics_table))
            con.commit()
