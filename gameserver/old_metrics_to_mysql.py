#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump ONP purchases via 5120_buy_item metrics (where price_currency = 'item:token') from old S3 metrics logs to MySQL "store" table for analysis
# use only for getting access to old data before the MongoDB bridge was set up.

# note: data between 20140111 and 20140130 is lost because we stopped
# putting buy_item into metrics logs on 20140111 and didn't start
# putting it into gamebucks logs until 20140130.

import sys, time, getopt, subprocess, tempfile
import SpinConfig
import SpinJSON
import SpinS3
import SpinParallel
import SpinNoSQLId
import SpinMySQLdb
from warnings import filterwarnings

id_generator = SpinNoSQLId.Generator()

def field_column(key, val):
    return "`%s` %s" % (key, val)

def get_store_items(STORE, sku):
    if 'skus' in sku:
        [get_store_items(STORE, subsku) for subsku in sku['skus']]
    else:
        if sku.get('price_currency','fbcredits') != 'item:token':
            return
        STORE[sku['item']] = sku['price']

def do_slave(task):
    date = task['date']
    game_id = task['game_id']
    verbose = task['verbose']
    dry_run = task['dry_run']
    commit_interval = task['commit_interval']

    start_time = SpinConfig.cal_to_unix((int(date[0:4]),int(date[4:6]),int(date[6:8])))
    end_time = start_time + 86400

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id=game_id)))
    STORE = {}
    [get_store_items(STORE, sku) for sku in gamedata['store']['catalog']]

    if verbose:
        print >> sys.stderr, 'converting date', date, 'start_time', start_time, 'end_time', end_time, '...'

    if not verbose: filterwarnings('ignore', category = SpinMySQLdb.Warning)

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = SpinMySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    store_table = cfg['table_prefix']+game_id+'_store'

    s3 = SpinS3.S3(SpinConfig.aws_key_file())
    bucket = 'spinpunch-logs'

    batch = 0
    total = 0
    cur = con.cursor()

    for entry in s3.list_bucket(bucket, prefix='%s/%s-%s-metrics.json' % (date[0:6], SpinConfig.game_id_long(override_game_id=game_id), date)):
        filename = entry['name'].split('/')[-1]

        if verbose: print >> sys.stderr, 'reading', filename

        if entry['name'].endswith('.zip'):
            tf = tempfile.NamedTemporaryFile(prefix='old_metrics_to_mysql-'+filename, suffix='.zip')
            s3.get_file(bucket, entry['name'], tf.name)
            unzipper = subprocess.Popen(['unzip', '-q', '-p', tf.name],
                                        stdout = subprocess.PIPE)

        elif entry['name'].endswith('.gz'):
            fd = s3.get_open(bucket, entry['name'], allow_keepalive = False)
            unzipper = subprocess.Popen(['gunzip', '-c', '-'],
                                        stdin = fd.fileno(),
                                        stdout = subprocess.PIPE)

        for line in unzipper.stdout.xreadlines():
            if '5120_buy_item' in line:
                #and ('item:token' in line):
                entry = SpinJSON.loads(line)
                if entry['event_name'] != '5120_buy_item': continue

                if 'price_currency' not in entry:
                    # old metric, need to fill in manually
                    if entry['items'][0]['spec'] in STORE:
                        entry['price_currency'] = 'item:token'
                        entry['price'] = STORE[entry['items'][0]['spec']]

                if verbose: print >> sys.stderr, SpinJSON.dumps(entry)

                if entry.get('price_currency','unknown') != 'item:token': continue


                if '_id' in entry:
                    entry_id = entry['_id']
                else:
                    id_generator.set_time(int(time.time()))
                    entry_id = id_generator.generate() # arbitrary

                assert len(entry['items']) == 1
                item = entry['items'][0]
                keyvals = [('_id', entry_id),
                           ('time', entry['time']),
                           ('user_id', entry['user_id']),
                           ('price', entry['price']),
                           ('currency', entry['price_currency']),
                           ('item', item['spec']),
                           ('stack', item.get('stack',1))]

                query = "INSERT INTO " + store_table + \
                            "("+', '.join(['`'+k+'`' for k,v in keyvals])+")"+ \
                            " VALUES ("+', '.join(['%s'] * len(keyvals)) +")"
                if dry_run:
                    print >> sys.stderr, query, [v for k,v in keyvals]
                else:
                    cur.execute(query, [v for k,v in keyvals])

                    batch += 1
                    total += 1
                    if commit_interval > 0 and batch >= commit_interval:
                        batch = 0
                        con.commit()
                        cur = con.cursor()
                        if verbose: print >> sys.stderr, total, 'inserted'

    if not dry_run:
        con.commit()



if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(do_slave)
        sys.exit(0)

    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False
    parallel = 1

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['dry-run','parallel='])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--parallel': parallel = int(val)

    if len(args) != 2:
        print 'usage: %s 20130101 20130112' % sys.argv[0]
        sys.exit(1)

    start_time, end_time = map(lambda x: SpinConfig.cal_to_unix((int(x[0:4]),int(x[4:6]),int(x[6:8]))), args[0:2])

    tasks = [{'date': '%04d%02d%02d' % SpinConfig.unix_to_cal(t),
              'game_id': game_id,
              'verbose': verbose, 'dry_run': dry_run, 'commit_interval':commit_interval,
              'commit_interval': commit_interval} for t in range(start_time, end_time+86400, 86400)]

    if parallel <= 1:
        for task in tasks:
            do_slave(task)
    else:
        SpinParallel.go(tasks, [sys.argv[0], '--slave'], on_error = 'break', nprocs=parallel, verbose = False)

