#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# stand-alone library for parsing gamedata, without instantiating server-side objects

def get_leveled_quantity(qty, level):
    if type(qty) is list:
        return qty[level-1]
    return qty

# note: these are the officially-defined parameters that determine the max level of a spec
# it is mandatory that these be level-dependent arrays in the spec, even if the value does not change with level
MAX_LEVEL_FIELD = {'units': 'max_hp', 'buildings': 'build_time', 'tech': 'research_time'}

def get_max_level(spec):
    if ('kind' in spec):
        if spec['kind'] == 'mobile':
            kind = 'units'
        elif spec['kind'] == 'building':
            kind = 'buildings'
    elif 'research_time' in spec:
        kind = 'tech'
    elif 'product' in spec: # crafting recipe
        return 1
    else:
        raise Exception('cannot determine kind')
    return len(spec[MAX_LEVEL_FIELD[kind]])

def get_kind(spec):
    if ('kind' in spec):
        return 'unit' if spec['kind'] == 'mobile' else spec['kind']
    elif 'research_time' in spec:
        return 'tech'
    elif 'product' in spec:
        return 'crafting_recipe'
    else:
        raise Exception('cannot determine kind')
