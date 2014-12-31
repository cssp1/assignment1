#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# simulate power usage as base grows

try:
    import simplejson as json
except:
    import json
import Predicates
import SpinConfig

gamedata = json.load(open(SpinConfig.gamedata_filename()))

class Spec (object):
    def __init__(self):
        pass
    def maxlevel(self):
        assert type(self.build_time) == list
        return len(self.build_time)

def get_spec(specname):
    data = gamedata['buildings'][specname]
    spec = Spec()
    for key, val in data.iteritems():
        setattr(spec, key, val)
    return spec


def get_leveled_quantity(qty, level):
    if type(qty) == list:
        return qty[level-1]
    return qty


class Building (object):
    def __init__(self, spec, level):
        self.spec = spec
        self.level = level
    def __repr__(self):
        return self.spec.ui_name+(' L%d' % self.level)
    def is_under_construction(self): return False
    def get_power(self):
        if hasattr(self.spec, 'consumes_power'):
            return -get_leveled_quantity(self.spec.consumes_power, self.level)
        elif hasattr(self.spec, 'provides_power'):
            return get_leveled_quantity(self.spec.provides_power, self.level)
        return 0

class Player (object):
    def __init__(self):
        self.my_base = []

def build_a_building(player, cc_level):
    for spec_name in gamedata['buildings'].iterkeys():
        if spec_name == gamedata['townhall'] or spec_name == 'barrier': continue
        spec = get_spec(spec_name)
        if hasattr(spec, 'developer_only'): continue
        assert spec.limit
        num_can_build = get_leveled_quantity(spec.limit, cc_level)
        num_built = sum([1 for bldg in player.my_base if bldg.spec.name == spec_name])
        if num_built >= num_can_build:
            continue
        if hasattr(spec, 'requires'):
            req = get_leveled_quantity(spec.requires, 1)
            if not Predicates.read_predicate(req).is_satisfied(player, None):
                continue
        player.my_base.append(Building(spec, 1))
        return True
    return False

def upgrade_a_building(player, cc_level):
    for obj in player.my_base:
        spec = obj.spec
        spec_name = spec.name
        if spec_name == gamedata['townhall'] or spec_name == 'barrier': continue
        if obj.level >= spec.maxlevel(): continue
        if hasattr(spec, 'requires'):
            req = get_leveled_quantity(spec.requires, obj.level+1)
            if not Predicates.read_predicate(req).is_satisfied(player, None):
                continue
        obj.level += 1
        return True
    return False

def make_base(cc_level):
    player = Player()
    player.my_base.append(Building(get_spec(gamedata['townhall']), cc_level))
    while build_a_building(player, cc_level):
        pass
    while upgrade_a_building(player, cc_level):
        pass
    return player.my_base

if __name__ == '__main__':
    for cc_level in xrange(1,6):
        base = make_base(cc_level)
        power_generated = 0
        power_consumed = 0
        for obj in sorted(base, key = lambda obj: obj.spec.name):
            power = obj.get_power()
            if power > 0:
                power_generated += power
            elif power < 0:
                power_consumed += -power
            #print '%-20s %+d' % (repr(obj), power)

        print 'CC LEVEL %d' % cc_level,
        print 'power [%d/%d]' % (power_consumed, power_generated),
        print 'NET power %d' % (power_generated-power_consumed)


