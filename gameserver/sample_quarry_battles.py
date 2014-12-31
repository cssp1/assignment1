#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import sys, os, time, getopt, re
import SpinJSON # fast JSON library
import SpinConfig

quarries = SpinConfig.load(SpinConfig.gamedata_component_filename('quarries_compiled.json'))

time_now = int(time.time())

def metrics_log_iterator(filename):
    for line in open(filename).xreadlines():
        if '3830_battle_end' not in line:
            continue
        event = SpinJSON.loads(line)
        base_id = event.get('base_id','')
        if (not base_id.startswith('q')):
            continue
        quarry_id = int(base_id[1:])
        yield quarry_id

def battle_log_dir_iterator(dirname):
    log_re = re.compile('^[0-9]+-[0-9]+-vs-[0-9]+-at-(.+).json.*$')
    for filename in os.listdir(dirname):
        match = log_re.match(filename)
        if match:
            base_id = match.groups()[0]
            if (not base_id.startswith('q')):
                continue
            quarry_id = int(base_id[1:])
            yield quarry_id

# main program
if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])

    by_template = {}

    for filename in args:
        if filename.endswith('.json'):
            iter = metrics_log_iterator(filename)
        else:
            iter = battle_log_dir_iterator(filename)

        for quarry_id in iter:
            template = None
            for spawn in quarries['spawn']:
                if quarry_id >= spawn['id_start'] and quarry_id < spawn['id_start'] + spawn['num']:
                    template = spawn['template']
                    break
            if not template:
                raise Exception('unknown quarry_id %d' % quarry_id)
            by_template[template] = by_template.get(template,0) + 1

    total = sum(by_template.itervalues(), 0)

    for name in sorted(by_template.keys()):
        print name, '%.2f' % (by_template[name]/(1.0*total))
