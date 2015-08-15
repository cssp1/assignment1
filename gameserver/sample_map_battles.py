#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# collect counts of battles against each quarry/hive template
# ./sample_map_battles.py logs/*-battles
# ./sample_map_battles.py s3:spinpunch-trprod-battle-logs:tr-battles-

import sys, os, time, getopt, re, csv
import SpinJSON # fast JSON library
import SpinS3
import SpinConfig

s3_keyfile = SpinConfig.aws_key_file()

quarries = SpinJSON.load(SpinConfig.gamedata_component_filename('quarries_compiled.json'))
hives = SpinJSON.load(SpinConfig.gamedata_component_filename('hives_compiled.json'))

# ensure that the spawn list is ordered by id_start - necessary for find_template() below
for spawn_list in quarries['spawn'], hives['spawn']:
    spawn_list.sort(key = lambda x: x['id_start'])

time_now = int(time.time())


def metrics_log_iterator(filename):
    for line in open(filename).xreadlines():
        if '3830_battle_end' not in line:
            continue
        event = SpinJSON.loads(line)
        base_id = event.get('base_id','')
        if not base_id:
            continue
        yield event['time'], base_id

log_re = re.compile('^([0-9]+)-[0-9]+-vs-[0-9]+-at-(.+).json.*$')
def parse_battle_log_filename(filename):
    match = log_re.match(filename)
    if match:
        event_time = int(match.groups()[0])
        base_id = match.groups()[1]
        return event_time, base_id
    return None

def battle_log_dir_iterator(dirname):
    for filename in os.listdir(dirname):
        ret = parse_battle_log_filename(filename)
        if ret:
            yield ret

def s3_battle_log_iterator(bucket, dirname):
    con = SpinS3.S3(s3_keyfile)
    for entry in con.list_bucket(bucket, prefix=dirname):
        ret = parse_battle_log_filename(entry['name'].split('/')[-1])
        if ret:
            yield ret

def find_template(spawn_list, id):
    for i in xrange(len(spawn_list)):
        spawn = spawn_list[i]
        # we've changed spawn numbers from time to time, so we can't just check
        # id >= spawn['id_start'] and id < spawn['id_start'] + spawn['num']
        # instead, assume that the spawn entries are in sorted order
        if id >= spawn['id_start'] and (i >= len(spawn_list)-1 or id < spawn_list[i+1]['id_start']):
            return spawn['template']
    return None

# main program
if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])

    CSV_FIELDS = ['Date', 'Kind', 'Template', 'Battle_Count']

    # initialize CSV writer object
    writer = csv.DictWriter(sys.stdout, CSV_FIELDS, dialect='excel')

    # write the header row
    writer.writerow(dict((fn,fn) for fn in CSV_FIELDS))

    csv_obj = {}

    by_date_by_template = {}

    for filename in args:
        if filename.startswith('s3:'):
            fields = filename.split(':')
            iter = s3_battle_log_iterator(fields[1], fields[2])

        elif filename.endswith('.json'):
            iter = metrics_log_iterator(filename)
        else:
            iter = battle_log_dir_iterator(filename)

        for event_time, base_id in iter:
            template = None
            kind = None
            if base_id[0] == 'q':
                kind = 'quarry'
                template = find_template(quarries['spawn'], int(base_id[1:]))
                if not template:
                    sys.stderr.write('unknown quarry %s\n' % base_id)
                    continue
            elif base_id[0] == 'v':
                kind = 'hive'
                template = find_template(hives['spawn'], int(base_id[1:]))
                if not template:
                    sys.stderr.write('unknown hive %s\n' % base_id)
                    continue

            if not template:
                continue

            # convert UNIX timestamp to yyyymmdd format
            ts = time.gmtime(event_time)
            date_str = '%04d%02d%02d' % (ts.tm_year, ts.tm_mon, ts.tm_mday)

            if date_str not in by_date_by_template:
                by_date_by_template[date_str] = {}
            key = (kind, template)
            by_date_by_template[date_str][key] = by_date_by_template[date_str].get(key,0) + 1

    for date_str in sorted(by_date_by_template.keys(), key = int):
        for template_kind, template_name in sorted(by_date_by_template[date_str].keys()):
            csv_obj['Date'] = date_str
            csv_obj['Kind'] = template_kind
            csv_obj['Template'] = template_name
            csv_obj['Battle_Count'] = by_date_by_template[date_str][(template_kind, template_name)]
            writer.writerow(csv_obj)
