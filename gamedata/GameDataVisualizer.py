#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# pretty-print gamedata for easier human analysis

from math import sqrt
import re
import SpinConfig
from GameDataUtil import get_max_level # get_leveled_quantity

gamedata = None # will be loaded later

def natural_sort_key(s, _nsre=re.compile('([0-9]+)')):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(_nsre, s)]

def pretty_print_time_brief(sec):
    d = int(sec/86400)
    sec -= 86400*d
    h = int(sec/3600)
    sec -= 3600*h
    m = int(sec/60)
    sec -= 60*m
    ret = ''
    if d > 0:
        ret += '%dd' % d
    if h > 0:
        ret += '%dh' % h
    if d <= 0 and h < 4:
        ret += '%dm' % m
    #ret += '%ds' % sec
    return ret

def pretty_print_qty(qty):
    if qty >= 1000000:
        return '%.1fM' % (qty/1000000.0)
    elif qty >= 10000:
        return '%dK' % (qty//1000)
    elif qty >= 1000:
        return '%.1fK' % (qty/1000.0)
    return str(qty)

def pretty_print_stat(key, val):
    if isinstance(val, basestring):
        return val.encode('utf-8')
    if isinstance(val, list):
        return ', '.join(pretty_print_stat(key, v) for v in val)
    if key.endswith('_time'):
        return pretty_print_time_brief(val)
    elif key.endswith('_days'):
        if val < 1:
            return '%.2fd' % val
        else:
            return '%.1fd' % val
    else:
        return pretty_print_qty(val)
    #return val_str = '{:,}'.format(val)

class Table(object):
    """ Generic table that shows key/value stats where the values are per-level arrays.
    Also supports showing per-tier stats, optionally.

    Note: data must all consist of per-level arrays. Duplicate scalars into arrays first.
    """

    def __init__(self, title, data, tiers = None, tier_data = None):
        self.title = title
        self.data = data # {key: [val1, val2, val3, ...], ...}
        if data:
            self.max_level = len(self.data[next(self.data.iterkeys())])
        else:
            self.max_level = len(tiers)
        self.tiers = tiers # [1,1,2,3,4,5, ... ] corresponding to val1, val2, ...
        self.tier_data = tier_data

    def as_html(self, fd):
        fd.write('<h2>%s</h2>' % self.title)
        fd.write('<table>\n')

        fd.write('<thead>')
        if self.tiers is not None:
            fd.write('<tr class="tiers">')
            fd.write('<th class="tiers_label">Tier</th>')
            last_tier = self.tiers[0]
            ncols = 1
            # loop through levels (there can be multiple levels per tier)
            for j in range(self.max_level):
                tier = self.tiers[j]
                if tier != last_tier:
                    fd.write('<th colspan="%d">%d</th>' % (ncols-1, last_tier))
                    ncols = 1
                if j == self.max_level-1:
                    fd.write('<th colspan="%d">%d</th>' % (ncols, tier))
                last_tier = tier
                ncols += 1
            fd.write('</tr>\n')

        if self.data:
            fd.write('<tr class="levels">')
            fd.write('<th>Level</th>')
            for j in range(self.max_level):
                fd.write('<th colspan="%d">%d</th>' % (1, j+1))
            fd.write('</tr>\n')

        fd.write('</thead>\n')
        fd.write('<tbody>\n')

        if self.tier_data: # some data are per-tier, not per-level
            assert self.tiers is not None
            for i, key in enumerate(sorted(self.tier_data.keys())):
                fd.write('<tr class="stat">')
                fd.write('<td>%s</td>' % key)

                last_tier = self.tiers[0]
                ncols = 1
                # loop through levels (there can be multiple levels per tier)
                for j in range(self.max_level):
                    tier = self.tiers[j]

                    colspan = None

                    if tier != last_tier:
                        colspan = ncols-1
                        val = self.tier_data[key][last_tier-1]
                        fd.write('<td colspan="%d">%s</td>' % (colspan, pretty_print_stat(key, val)))
                        ncols = 1

                    if j == self.max_level-1:
                        colspan = ncols
                        val = self.tier_data[key][tier-1]
                        fd.write('<td colspan="%d">%s</td>' % (colspan, pretty_print_stat(key, val)))

                    last_tier = tier
                    ncols += 1
                fd.write('</tr>\n')

        for i, key in enumerate(sorted(self.data.keys())):
            fd.write('<tr class="stat">')
            fd.write('<td>%s</td>' % key)
            for val in self.data[key]:
                fd.write('<td>%s</td>' % pretty_print_stat(key, val))
            fd.write('</tr>\n')

        fd.write('</tbody>\n')
        fd.write('</table>\n')

class BuildingTable(Table):
    FIELDS = {'max_hp','build_time','upgrade_credit_cost','upgrade_gamebucks_cost',
              'consumes_power','provides_power',
              'production_capacity'}

    def __init__(self, name, spec):
        max_level = get_max_level(spec)
        data = {}
        for k, v in spec.iteritems():
            if not (k in self.FIELDS or
                    k.startswith('build_cost_') or
                    k.startswith('produces_') or
                    k.startswith('storage_')): continue
            if isinstance(v, list):
                val = v
            else:
                val = [v,] * max_level
            data[k] = val

        tier_data = {}

        if gamedata['townhall']:
            if name == gamedata['townhall']:
                tiers = list(range(1, max_level+1))
            elif 'requires' in spec:
                last_tier = 1
                tiers = []
                for pred in spec['requires']:
                    if pred['predicate'] == 'BUILDING_LEVEL' and \
                       pred['building_type'] == gamedata['townhall']:
                        tier = pred['trigger_level']
                    else:
                        tier = last_tier
                    tiers.append(tier)
                    last_tier = tier
                if 'limit' in spec and isinstance(spec['limit'], list):
                    tier_data['limit'] = spec['limit']
        else:
            tiers = None

        Table.__init__(self, name, data, tiers = tiers, tier_data = tier_data)

class TechTable(Table):
    FIELDS = {'research_time','upgrade_credit_cost','upgrade_gamebucks_cost'}
    SPELL_FIELDS = {'damage','cooldown','range'}
    UNIT_FIELDS = {'build_time','max_hp'}

    def __init__(self, name, spec):
        max_level = get_max_level(spec)
        data = {}
        for k, v in spec.iteritems():
            if not (k in self.FIELDS or
                    k.startswith('cost_')): continue
            if isinstance(v, list):
                val = v
            else:
                val = [v,] * max_level
            data[k] = val

        if 'associated_unit' in spec:
            ui_name = spec['associated_unit'] + ' / ' + name
            unit_spec = gamedata['units'][spec['associated_unit']]
            assert unit_spec['level_determined_by_tech'] == name
            assert get_max_level(unit_spec) == max_level
            for k, v in unit_spec.iteritems():
                if not (k in self.UNIT_FIELDS or
                        k.startswith('build_cost_')): continue
                if isinstance(v, list):
                    val = v
                else:
                    val = [v,] * max_level
                data['unit:'+k] = val

            auto_spell = gamedata['spells'][unit_spec['spells'][0]]
            assert auto_spell['activation'] == 'auto'
            for k, v in auto_spell.iteritems():
                if not (k in self.SPELL_FIELDS): continue
                if isinstance(v, list):
                    val = v
                else:
                    val = [v,] * max_level
                data['weapon:'+k] = val

        else:
            ui_name = name

        tier_data = {}

        if gamedata['townhall']:
            if 'requires' in spec:
                last_tier = 0
                tiers = []
                for pred in spec['requires']:
                    tier = get_tier_requirement(pred)
                    tier = max(last_tier, tier)
                    tiers.append(tier)
                    last_tier = tier
        else:
            tiers = None

        Table.__init__(self, ui_name, data, tiers = tiers, tier_data = tier_data)

def get_tier_summary(building_names, tech_names):
    n_tiers = get_max_level(gamedata['buildings'][gamedata['townhall']])


    # get implied relative value of resources
    cheapest_value = max(gamedata['store']['resource_price_formula_by_townhall_level'][resname][-1] \
                         for resname in gamedata['resources'])
    relative_res = dict((resname, cheapest_value / gamedata['store']['resource_price_formula_by_townhall_level'][resname][-1]) \
                        for resname in gamedata['resources'])
    res_internal_weight = gamedata['store']['resource_internal_weight']

    def unsplit_res(amounts):
        return sum((relative_res[resname]*amounts[resname]*res_internal_weight[resname] for resname in amounts), 0)

    summary = {'power_consumed':[0]*n_tiers,
               'power_produced':[0]*n_tiers,
               'building_upgrade_res':[0]*n_tiers,
               'building_upgrade_days':[0]*n_tiers,
               'building_upgrade_num':[0]*n_tiers,
               'tech_upgrade_res': [0]*n_tiers,
               'tech_upgrade_days': [0]*n_tiers,
               'tech_upgrade_num': [0]*n_tiers,
               'units_unlocked': [0]*n_tiers,
               'harvest_rate_daily':[0]*n_tiers,
               'storage': [0]*n_tiers,
               'squad_of_10_rep_time': [0]*n_tiers,
               'buildings_repair_time':[0]*n_tiers,
               'base_area': [0]*n_tiers, # square grid cells occupied by buildings
               'new_buildings': [[] for i in range(n_tiers)],
               }
    for res in gamedata['resources']:
        summary['storage_'+res] = [0] * n_tiers

    for tier in range(1, n_tiers+1):
        for category in ('infantry', 'armor', 'aircraft'):
            # find units of appropriate tier (this is approximate)
            for t in range(tier, 0, -1):
                unit_name = '%s_tier_%d' % (category,t)
                if unit_name in gamedata['units']:
                    summary['squad_of_10_rep_time'][tier-1] += \
                                                            int(3.33 * gamedata['units'][unit_name]['build_time'][0])
                    break

    for name in building_names:
        data = gamedata['buildings'][name]
        max_level = get_max_level(data)

        level = 0
        last_limit = 0

        # per building instance quantities

        # note: these need to continue across tiers
        power_consumed_this_tier = 0
        power_produced_this_tier = 0
        harvest_rate_daily_this_tier = dict((res, 0) for res in gamedata['resources'])
        storage_this_tier = dict((res, 0) for res in gamedata['resources'])
        buildings_repair_time_this_tier = 0

        for tier in range(1, n_tiers+1):

            # these get re-initialized to zero each tier
            upgrade_res_this_tier = 0
            upgrade_days_this_tier = 0
            base_area_this_tier = 0

            # upgrade until we can upgrade no more at this tier
            if name == gamedata['townhall']:
                max_level_this_tier = tier

            elif 'requires' in data:
                max_level_this_tier = max_level
                for i, pred in enumerate(data['requires']):
                    if get_tier_requirement(pred) > tier:
                        max_level_this_tier = (i+1) - 1
                        break

            while level < max_level_this_tier:
                # simulate upgrade
                level += 1

                # note: doesn't count the L1-N upgrades when limit increases
                summary['building_upgrade_num'][tier-1] += 1

                upgrade_res_this_tier += unsplit_res(dict((res,
                                                           data['build_cost_'+res][level-1] if 'build_cost_'+res in data else 0) for res in gamedata['resources']))

                # convert seconds to days
                upgrade_days_this_tier += data['build_time'][level-1] / 86400.0
                if 'consumes_power' in data:
                    power_consumed_this_tier = max(power_consumed_this_tier, data['consumes_power'][level-1])
                if 'provides_power' in data:
                    power_produced_this_tier = max(power_produced_this_tier, data['provides_power'][level-1])
                for res in gamedata['resources']:
                    if 'produces_'+res in data:
                        # convert per-hour to per-day
                        harvest_rate_daily_this_tier[res] = max(harvest_rate_daily_this_tier[res], 24*data['produces_'+res][level-1])
                    if 'storage_'+res in data:
                        storage_this_tier[res] = max(storage_this_tier[res], data['storage_'+res][level-1])
                if 'repair_time' in data and isinstance(data['repair_time'], list):
                    buildings_repair_time_this_tier = max(buildings_repair_time_this_tier, data['repair_time'][level-1])

            if max_level_this_tier < 1:
                limit = 0
            else:
                limit = data.get('limit', 1)
                if isinstance(limit, list):
                    limit = limit[tier-1]

            # did we build a new one?
            if limit > last_limit:
                for k in range(limit - last_limit):
                    summary['new_buildings'][tier-1].append('%s (%dx%d)' % (name,
                                                                            data['gridsize'][0],
                                                                            data['gridsize'][1]))

            summary['base_area'][tier-1] += limit * data['gridsize'][0]*data['gridsize'][1]

            summary['building_upgrade_res'][tier-1] += limit * upgrade_res_this_tier
            summary['building_upgrade_days'][tier-1] += limit * upgrade_days_this_tier
            summary['power_consumed'][tier-1] += limit * power_consumed_this_tier
            summary['power_produced'][tier-1] += limit * power_produced_this_tier
            summary['harvest_rate_daily'][tier-1] += limit * unsplit_res(harvest_rate_daily_this_tier)
            summary['storage'][tier-1] += limit * unsplit_res(storage_this_tier)
            for res in gamedata['resources']:
                summary['storage_'+res][tier-1] += limit * storage_this_tier[res]
            # note: all repair happens in parallel
            summary['buildings_repair_time'][tier-1] = max(summary['buildings_repair_time'][tier-1], buildings_repair_time_this_tier)

            last_limit = limit

    # convert base_area to base_diameter
    summary['base_diameter'] = map(lambda area: int(sqrt(area)), summary['base_area'])
    # ignore new buildings at first tier
    summary['new_buildings'][0] = [['N/A']]

    for name in tech_names:
        data = gamedata['tech'][name]
        max_level = get_max_level(data)
        level = 0

        for tier in range(1, n_tiers+1):
            # these get re-initialized to zero each tier
            upgrade_res_this_tier = 0
            upgrade_days_this_tier = 0

            # upgrade until we can upgrade no more at this tier
            if 'requires' in data:
                max_level_this_tier = max_level
                for i, pred in enumerate(data['requires']):
                    if get_tier_requirement(pred, verbose = False) > tier:
                        max_level_this_tier = (i+1) - 1
                        break

            while level < max_level_this_tier:
                # simulate upgrade
                level += 1

                if level == 1:
                    summary['units_unlocked'][tier-1] += 1

                summary['tech_upgrade_num'][tier-1] += 1

                upgrade_res_this_tier += unsplit_res(dict((res,
                                                           data['cost_'+res][level-1] if 'cost_'+res in data else 0) for res in gamedata['resources']))


                # convert seconds to days
                upgrade_days_this_tier += data['research_time'][level-1] / 86400.0

            summary['tech_upgrade_res'][tier-1] += upgrade_res_this_tier
            summary['tech_upgrade_days'][tier-1] += upgrade_days_this_tier

    return summary

# return the minimum tier you must be at to satisfy a given predicate
def get_tier_requirement(pred, verbose = False):
    ret = 1
    if pred['predicate'] == 'BUILDING_LEVEL':
        if pred['building_type'] == gamedata['townhall']:
            return pred['trigger_level']
        else:
            spec = gamedata['buildings'][pred['building_type']]
            assert 'requires' in spec
            for other_level in range(1, pred['trigger_level']+1):
                ret = max(ret, get_tier_requirement(spec['requires'][other_level-1], verbose = verbose))
            if verbose:
                print pred['building_type'], 'level', pred['trigger_level'], 'at', ret

    elif pred['predicate'] == 'TECH_LEVEL':
        spec = gamedata['tech'][pred['tech']]
        for other_level in range(1, pred['min_level']+1):
            ret = max(ret, get_tier_requirement(spec['requires'][other_level-1], verbose = verbose))
        if verbose:
            print pred['tech'], 'level', pred['min_level'], 'at', ret, spec['requires'][other_level-1]
    elif pred['predicate'] == 'AND':
        for sub in pred['subpredicates']:
            ret = max(ret, get_tier_requirement(sub, verbose = verbose))
    elif pred['predicate'] == 'ALWAYS_TRUE':
        pass
    else:
        raise Exception('unhandled predicate %r' % pred)
    return ret

class PageOfTables(object):
    def __init__(self, table_list):
        self.table_list = table_list
    def as_html(self, fd):
        fd.write('''
<html>
<head>
<style>
body {
    background: #ffffff;
    font-family: sans-serif;
}
table {
    border-collapse: collapse;
    width: 100%;
    table-layout: fixed;
}
table, th, td { border: 1px solid #808080; }
.tiers th {
    background-color: #4CAF50;
    color: white;
}
.tiers th.tiers_label {
    width: 120px;
}
.levels th {
    background-color: #AFAF50;
    color: white;
}
.stat td {
    font-family: sans-serif;
    font-size: 75%;
    text-align: right;
}
th, td {
    padding: 3px;
    text-align: left;
}
tr:nth-child(even) { background-color: #f2f2f2 }
</style>
</head>
<body>
''')
        for table in self.table_list:
            table.as_html(fd)
        fd.write('''
</body>
</html>
''')

if __name__ == '__main__':
    import sys, os, getopt
    import AtomicFileWrite
    import SpinJSON

    out_filename = '-'
    tier_building = None

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'o:', ['tier-building='])
    for key, val in opts:
        if key == '-o': out_filename = val
        elif key == '--tier-building': tier_building = val

    if len(args) < 1:
        print 'usage: GameDataVisualizer.py -o [output] buildings.json [--tier-building=toc]'
        sys.exit(1)

    gamedata = {'buildings': SpinJSON.load(open(args[0])),
                'tech': SpinJSON.load(open(args[1])),
                'units': SpinJSON.load(open(args[2])),
                'spells': SpinConfig.load(args[3], stripped = True), # weapons only
                'resources': SpinConfig.load(args[4]),
                'store': SpinJSON.load(open(args[5])),
                'townhall': tier_building
                }

    if out_filename == '-':
        out_fd = sys.stdout
        out_atom = None
    else:
        out_atom = AtomicFileWrite.AtomicFileWrite(out_filename, 'w', ident=str(os.getpid()))
        out_fd = out_atom.fd

    # get list of buildings to process
    building_names = sorted(gamedata['buildings'].keys())

    # remove non-relevant buildings
    building_names = filter(lambda name: (not gamedata['buildings'][name].get('developer_only') or \
                              name in ('weapon_factory', 'weapon_lab', 'turret_emplacement')),
                            building_names)

    if gamedata['townhall']:
        # put tier building first
        building_names.remove(gamedata['townhall'])
        building_names = [gamedata['townhall'],]+building_names


    # get list of techs to process
    tech_names = sorted(gamedata['tech'].keys(), key=natural_sort_key)

    table_list = [BuildingTable(name, gamedata['buildings'][name]) for name in building_names] + \
                 [TechTable(name, gamedata['tech'][name]) for name in tech_names]

    if gamedata['townhall']:
        # add summary data
        summary_data = get_tier_summary(building_names, tech_names)
        n_tiers = get_max_level(gamedata['buildings'][gamedata['townhall']])
        table_list = [Table('SUMMARY', {}, range(1, n_tiers+1), summary_data),] + table_list

    PageOfTables(table_list).as_html(out_fd)

    if out_atom:
        out_atom.complete()
