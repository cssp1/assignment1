#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# performs two functions on MongoDB log buffers:
# 1) uploads earlier days' data to spinpunch-logs bucket in S3
# 2) deletes data older than the retention period

import sys, os, getopt, time, tempfile
import SpinS3
import SpinConfig
import SpinNoSQL
import bson.objectid
import SpinLog
import SpinParallel
import subprocess

time_now = int(time.time())

# autoconfigure based on config.json
game_id = SpinConfig.config['game_id']
log_bucket = 'spinpunch-logs'
s3_key_file_for_logs = SpinConfig.aws_key_file()

TABLES = {
    'chat': { 's3_name': 'chat',
              'table_name': 'chat_buffer',
              'compression': 'zip',
              'retain_for': 30*86400 },

    # credits log
    'credits': { 's3_name': 'credits', 'table_name': 'log_credits', 'compression': 'zip', 'retain_for': -1 },

    # ad network logs

    'fb_conversion_pixels': { 's3_name': 'fb_conversion_pixels', 'table_name': 'log_fb_conversion_pixels',
                              'compression': 'zip', 'retain_for': -1 },
    'kg_conversion_pixels': { 's3_name': 'kg_conversion_pixels', 'table_name': 'log_kg_conversion_pixels',
                              'compression': 'zip', 'retain_for': 30*86400 },
    'adotomi': { 's3_name': 'adotomi', 'table_name': 'log_adotomi', 'compression': 'zip', 'retain_for': 30*86400 },
    'dauup': { 's3_name': 'dauup', 'table_name': 'log_dauup', 'compression': 'zip', 'retain_for': 30*86400 },
    'dauup2': { 's3_name': 'dauup2', 'table_name': 'log_dauup2', 'compression': 'zip', 'retain_for': 30*86400 },
    'adparlor': { 's3_name': 'adparlor', 'table_name': 'log_adparlor', 'compression': 'zip', 'retain_for': 30*86400 },
    'liniad': { 's3_name': 'liniad', 'table_name': 'log_liniad', 'compression': 'zip', 'retain_for': 30*86400 },

    # pcheck action log
    'pcheck': { 's3_name': 'pcheck', 'table_name': 'log_pcheck', 'compression': 'zip', 'retain_for': 30*86400 },

    # fbrtapi call log
    'fbrtapi': { 's3_name': 'fbrtapi', 'table_name': 'log_fbrtapi', 'compression': 'zip', 'retain_for': 30*86400 },

    # game event logs
    'metrics': { 's3_name': 'metrics', 'table_name': 'log_metrics', 'compression': 'zip', 'retain_for': 30*86400 },
    'gamebucks': { 's3_name': 'gamebucks', 'table_name': 'log_gamebucks', 'compression': 'zip', 'retain_for': 180*86400 },
    'purchase_ui': { 's3_name': 'purchase_ui', 'table_name': 'log_purchase_ui', 'compression': 'zip', 'retain_for': 30*86400 },

    # let's try keeping these in MongoDB indefinitely - or not. TR DB size grows about 2GB/week without bound.
    'battles': { 's3_name': 'battles', 'table_name': 'battles', 'compression': 'zip', 'retain_for': 30*86400 },

    # exceptions
    'exceptions': { 's3_name': 'exceptions', 'table_name': 'log_exceptions', 'compression': 'zip', 'retain_for': 30*86400 },
    'client_exceptions': { 's3_name': None, 'table_name': 'log_client_exceptions', 'retain_for': 30*86400 },
    'client_trouble': { 's3_name': None, 'table_name': 'log_client_trouble', 'retain_for': 4*86400 },

    # economy source/sink log
    'econ_res': { 's3_name': 'econ_res', 'table_name': 'econ_res', 'compression': 'zip', 'retain_for': 1*86400 },

    # inventory source/sink log
    'inventory': { 's3_name': 'inventory', 'table_name': 'log_inventory', 'compression': 'zip', 'retain_for': 60*86400 },

    # lottery log
    'lottery': { 's3_name': 'lottery', 'table_name': 'log_lottery', 'compression': 'zip', 'retain_for': 60*86400 },

    # alliance logs
    'alliance_events': { 's3_name': 'alliance_events', 'table_name': 'log_alliances', 'compression': 'zip', 'retain_for': 14*86400 },
    'alliance_member_events': { 's3_name': 'alliance_member_events', 'table_name': 'log_alliance_members', 'compression': 'zip', 'retain_for': 14*86400 },

    # unit donation log
    'unit_donation': { 's3_name': 'unit_donation', 'table_name': 'log_unit_donation', 'compression': 'zip', 'retain_for': 7*86400 },

    # ladder PvP log
    'ladder_pvp': { 's3_name': 'ladder_pvp', 'table_name': 'log_ladder_pvp', 'compression': 'zip', 'retain_for': 10*86400 },

    # damage protection log
    'damage_protection': { 's3_name': 'damage_protection', 'table_name': 'log_damage_protection', 'compression': 'zip', 'retain_for': 30*86400 },

    # fishing log
    'fishing': { 's3_name': 'fishing', 'table_name': 'log_fishing', 'compression': 'zip', 'retain_for': 30*86400 },

    # quests and achievements logs
    'quests': { 's3_name': 'quests', 'table_name': 'log_quests', 'compression': 'zip', 'retain_for': 30*86400 },
    'achievements': { 's3_name': 'achievements', 'table_name': 'log_achievements', 'compression': 'zip', 'retain_for': 30*86400 },

    # login flow log
    'login_flow': { 's3_name': 'login_flow', 'table_name': 'log_login_flow', 'compression': 'zip', 'retain_for': 2*86400 },

    # login sources log
    'login_sources': { 's3_name': 'login_sources', 'table_name': 'log_login_sources', 'compression': 'zip', 'retain_for': 4*86400 },

    # Facebook Permissions, Notifications, Requests, and Open Graph logs
    'fb_permissions': { 's3_name': 'fb_permissions', 'table_name': 'log_fb_permissions', 'compression': 'zip', 'retain_for': 10*86400 },
    'fb_notifications': { 's3_name': 'fb_notifications', 'table_name': 'log_fb_notifications', 'compression': 'zip', 'retain_for': 30*86400 },
    'fb_requests': { 's3_name': 'fb_requests', 'table_name': 'log_fb_requests', 'compression': 'zip', 'retain_for': 30*86400 },
    'fb_open_graph': { 's3_name': 'fb_open_graph', 'table_name': 'log_fb_open_graph', 'compression': 'zip', 'retain_for': 30*86400 },

    # activity log
    'activity': { 's3_name': 'activity', 'table_name': 'activity', 'compression': 'zip', 'retain_for': 7*86400 },

    # session log
    'sessions': { 's3_name': 'sessions', 'table_name': 'log_sessions', 'compression': 'zip', 'retain_for': 7*86400 },

    # (re)acquisitions log
    'acquisitions': { 's3_name': 'acquisitions', 'table_name': 'log_acquisitions', 'compression': 'zip', 'retain_for': 90*86400 },

    }

class NullFD(object):
    def write(self, stuff): pass
    def flush(self): pass

def safe_unlink(x):
    try: os.unlink(x)
    except: pass

def do_upload(nosql_client, table, verbose, dry_run, keep_local):
    if not table['s3_name']: return
    msg_fd = sys.stderr if verbose else NullFD()
    s3_logs = SpinS3.S3(s3_key_file_for_logs)
    print >> msg_fd, '%s: upload' % (table['table_name'])

    tbl = nosql_client._table(table['table_name'])
    # find earliest timestamp
    first = list(tbl.find({}, {'time':1}).sort([('time',1)]).limit(1))
    if not first:
        print >> msg_fd, 'no records'
        return
    start_time = first[0]['time']

    # snap to day boundary
    start_time = 86400*(start_time//86400)
    today_start = 86400*(time_now//86400)

    # check each full UTC day from start_time, stopping before the current day
    while start_time < today_start:
        date_str = time.strftime('%Y%m%d', time.gmtime(start_time))
        year_month = date_str[:-2]
        obj_name = '%s/%s-%s-%s.json.%s' % (year_month, SpinConfig.game_id_long(), date_str, table['s3_name'], table['compression'])
        print >> msg_fd, '  checking %s/%s...' % (log_bucket, obj_name),
        msg_fd.flush()

        if s3_logs.exists(log_bucket, obj_name, has_read_permission = False):
            print >> msg_fd, 'already exists, skipping.'
        else:
            # upload one day's data
            print >> msg_fd, 'does not exist, dumping...'

            # spit out the entries to a flat file using SpinLog
            tf_name = '%s/%s-%s-%s.json' % (tempfile.gettempdir(), SpinConfig.game_id_long(), date_str, table['s3_name'])
            try:
                target = SpinLog.SimpleJSONLog(tf_name, buffer = -1)
                cursor = tbl.find({'time':{'$gte':start_time, '$lt':start_time+86400}}).sort([('time',1)])
                total = cursor.count()
                count = 0
                for row in cursor:
                    if '_id' in row:
                        if type(row['_id']) is bson.objectid.ObjectId:
                            row['_id'] = SpinNoSQL.NoSQLClient.decode_object_id(row['_id'])
                    assert 'time' in row
                    t = row['time']; del row['time']
                    target.event(t, row)
                    count += 1
                    if count == 1 or count == total or (count%1000)==0:
                        print >> msg_fd, '\r    %d/%d %s dump' % (count,total,table['table_name']),
                print >> msg_fd, 'finished'
                target.close()

                # compress the file
                obj_file_name = os.path.basename(obj_name)
                print >> msg_fd, '  compressing', os.path.basename(tf_name), '->', os.path.basename(obj_file_name), '...',
                msg_fd.flush()
                assert table['compression'] == 'zip'
                save_cwd = os.getcwd()
                try:
                    os.chdir(os.path.dirname(tf_name))
                    args = ['/usr/bin/zip','-q',os.path.basename(obj_file_name), os.path.basename(tf_name)]
                    subprocess.check_call(args)
                    print >> msg_fd, 'done'

                    print >> msg_fd, '  uploading', obj_file_name, '->', log_bucket+':'+obj_name, '...',
                    msg_fd.flush()
                    if not dry_run:
                        s3_logs.put_file(log_bucket, obj_name, os.path.basename(obj_file_name))
                finally:
                    safe_unlink(os.path.basename(obj_file_name))
                    os.chdir(save_cwd)
            finally:
                if keep_local:
                    print >> msg_fd, '  KEEPING', tf_name
                else:
                    safe_unlink(tf_name)

            print >> msg_fd, 'done'

        start_time += 86400

def do_clean(nosql_client, table, verbose, dry_run):
    if table['retain_for'] < 0: return
    msg_fd = sys.stderr if verbose else NullFD()
    print >> msg_fd, '%s: deleting records older than %.1f days...' % (table['table_name'], table['retain_for']/86400.0),
    msg_fd.flush()
    qs = {'time':{'$lt':time_now - table['retain_for']}}
    if dry_run:
        print >> msg_fd, 'remove(%s) would affect %d' % (qs, nosql_client._table(table['table_name']).find(qs).count())
    else:
        n = nosql_client._table(table['table_name']).remove(qs)['n']
        print >> msg_fd, 'deleted %d' % n

def my_slave(input):
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    table = TABLES[input['kind']]
    do_upload(nosql_client, table, input['verbose'], input['dry_run'], input['keep_local'])
    do_clean(nosql_client, table, input['verbose'], input['dry_run'])

if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(my_slave)
        sys.exit(0)

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['parallel=', 'quiet', 'dry-run', 'table=', 'keep'])

    verbose = True
    dry_run = False
    parallel = 1
    table = 'ALL'
    keep_local = False

    for key, val in opts:
        if key == '--parallel': parallel = int(val)
        elif key == '--quiet': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--keep': keep_local = True
        elif key == '--table':
            assert val in TABLES
            table = val

    task_list = []

    # for checking if collections are present
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))

    if table == 'ALL':
        table_names = TABLES.keys()
    else:
        table_names = [table,]

    task_list += [{'kind':table_name, 'verbose':verbose, 'dry_run':dry_run, 'keep_local':keep_local} for table_name in table_names if nosql_client._table_exists(TABLES[table_name]['table_name'])]

    if parallel <= 1:
        for task in task_list:
            my_slave(task)
    else:
        SpinParallel.go(task_list, [sys.argv[0], '--slave'], on_error = 'continue', nprocs=parallel, verbose = False)

    if verbose: print 'DONE'

