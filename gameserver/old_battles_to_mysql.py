#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump 3830_battle_end metrics from metrics logs to MySQL "battles" table for analytics
# use only for getting access to old data before the MongoDB bridge was set up.

import sys, time, getopt, re, subprocess
import SpinConfig
import SpinJSON
import SpinLog
import SpinS3
import SpinNoSQLId
import SpinParallel
import MySQLdb
from warnings import filterwarnings

id_generator = SpinNoSQLId.Generator()

battle_fields = {
    'battle_id': 'CHAR(24) NOT NULL PRIMARY KEY',
    'time': 'INT',
    'duration': 'INT',
    'attacker_id': 'INT',
    'attacker_level': 'INT',
    'attacker_outcome': 'VARCHAR(10)',
    'attack_type': 'VARCHAR(10)',
    'defender_id': 'INT',
    'defender_level': 'INT',
    'defender_outcome': 'VARCHAR(10)',
    'base_damage': 'FLOAT',
    'base_region':'VARCHAR(16)',
    'base_id': 'VARCHAR(16)',
    'base_type': 'VARCHAR(8)',
    'base_template': 'VARCHAR(32)',
    'home_base': 'TINYINT(1)',
    'loot:xp': 'INT',
    'loot:iron': 'INT',
    'loot:water': 'INT',
    'loot:units_lost_iron': 'INT',
    'loot:units_lost_water': 'INT',
    }

def field_column(key, val):
    return "`%s` %s" % (key, val)

log_re = re.compile('^([0-9]+)-([0-9]+)-vs-([0-9]+)-at-(.+).json.*$')
def parse_battle_log_filename(filename):
    match = log_re.match(filename)
    if match:
        event_time = int(match.groups()[0])
        attacker_id = int(match.groups()[1])
        defender_id = int(match.groups()[2])
        base_id = match.groups()[3]
        return event_time, attacker_id, defender_id, base_id
    return None, None, None, None

def find_template(spawn_list, id):
    for i in xrange(len(spawn_list)):
        spawn = spawn_list[i]
        # we've changed spawn numbers from time to time, so we can't just check
        # id >= spawn['id_start'] and id < spawn['id_start'] + spawn['num']
        # instead, assume that the spawn entries are in sorted order
        if id >= spawn['id_start'] and (i >= len(spawn_list)-1 or id < spawn_list[i+1]['id_start']):
            return spawn['template']
    return None

def do_slave(task):
    date = task['date']
    game_id = task['game_id']
    verbose = task['verbose']
    dry_run = task['dry_run']

    start_time = SpinConfig.cal_to_unix((int(date[0:4]),int(date[4:6]),int(date[6:8])))
    end_time = start_time + 86400

    if verbose:
        print >> sys.stderr, 'converting date', date, 'start_time', start_time, 'end_time', end_time, '...'

    # gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
    if not verbose: filterwarnings('ignore', category = MySQLdb.Warning)
    quarries = SpinJSON.load(SpinConfig.gamedata_component_filename('quarries_compiled.json'))
    hives = SpinJSON.load(SpinConfig.gamedata_component_filename('hives_compiled.json'))

    # ensure that the spawn list is ordered by id_start - necessary for find_template() below
    for spawn_list in quarries['spawn'], hives['spawn']:
        spawn_list.sort(key = lambda x: x['id_start'])

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    battles_table = cfg['table_prefix']+game_id+'_battles'

    if 0:
        # find any already-converted battles
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM %s WHERE time >= %%s and time < %%s" % battles_table, (start_time, end_time))
        row = cur.fetchone()
        con.commit()
        if row and row[0] > 0:
            print >> sys.stderr, 'there are already', row[0], 'entries in this time range, aborting!'
            return

    s3 = SpinS3.S3(SpinConfig.aws_key_file())
    bucket = 'spinpunch-%sprod-battle-logs' % game_id

    for entry in s3.list_bucket(bucket, prefix='%s-battles-%s/%s' % (game_id, date[0:6], date)):
        filename = entry['name'].split('/')[-1]
        event_time, attacker_id, defender_id, base_id = parse_battle_log_filename(filename)
        if (not base_id) or event_time < start_time or event_time >= end_time: continue
        if base_id[0] != 'v': continue # only look at hives

        print >> sys.stderr, event_time, SpinLog.pretty_time(time.gmtime(event_time)), filename
        fd = s3.get_open(bucket, entry['name'], allow_keepalive = False)
        unzipper = subprocess.Popen(['gunzip', '-c', '-'],
                                    stdin = fd.fileno(),
                                    stdout = subprocess.PIPE)
        battle_start = None
        battle_end = None
        for line in unzipper.stdout.xreadlines():
            if '3820_battle_start' in line:
                battle_start = SpinJSON.loads(line)
            elif '3830_battle_end' in line:
                battle_end = SpinJSON.loads(line)
        if (not battle_start) or (not battle_end): continue

        base_template = find_template(hives['spawn'], int(base_id[1:]))
        if not base_template:
            sys.stderr.write('unknown hive %s\n' % base_id)
            continue

        # generate a fake summary
        summary = {
            'time': event_time,
            'attacker_id': battle_start['attacker_user_id'],
            'attacker_level':battle_start['attacker_level'],
            'attacker_outcome':battle_end['battle_outcome'],
            'defender_id':battle_start['opponent_user_id'],
            'defender_level':battle_start['opponent_level'],
            'defender_outcome':'victory' if battle_end['battle_outcome'] == 'defeat' else 'defeat',
            'base_damage': battle_end['base_damage'],
            'base_id':battle_start['base_id'],
            'base_type':'hive',
            'base_template':base_template,
            'loot':battle_end['loot']
            }

        cur = con.cursor()
        cur.execute("SELECT battle_id FROM %s WHERE time = %%s and attacker_id = %%s and defender_id = %%s" % battles_table,
                    (event_time, battle_start['attacker_user_id'], battle_start['opponent_user_id']))
        row = cur.fetchone()
        con.commit()
        if row:
            sys.stderr.write('appears to be a duplicate, skipping!\n')
            continue

        id_generator.set_time(int(time.time()))
        battle_id = id_generator.generate() # arbitrary

        keys = ['battle_id',]
        values = [battle_id,]

        for kname, ktype in battle_fields.iteritems():
            path = kname.split(':')
            probe = summary
            val = None
            for i in xrange(len(path)):
                if path[i] not in probe:
                    break
                elif i == len(path)-1:
                    val = probe[path[i]]
                    break
                else:
                    probe = probe[path[i]]

            if val is not None:
                keys.append(kname)
                values.append(val)

        query = "INSERT INTO " + battles_table + \
                    "("+', '.join(['`'+x+'`' for x in keys])+")"+ \
                    " VALUES ("+', '.join(['%s'] * len(values)) +")"
        print >> sys.stderr, query
        print >> sys.stderr, values

        if not dry_run:
            cur = con.cursor()
            cur.execute(query, values)
            con.commit()



if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(do_slave)
        sys.exit(0)

    game_id = SpinConfig.game()
    commit_interval = 100
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
              'verbose': verbose, 'dry_run': dry_run,
              'commit_interval': commit_interval} for t in range(start_time, end_time+86400, 86400)]

    if parallel <= 1:
        for task in tasks:
            do_slave(task)
    else:
        SpinParallel.go(tasks, [sys.argv[0], '--slave'], on_error = 'break', nprocs=parallel, verbose = False)

