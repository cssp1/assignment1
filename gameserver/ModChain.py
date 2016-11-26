# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# tools for working with chains of modifiers that operate on player/unit/building stats

def get_leveled_quantity(qty, level): # XXX duplicate
    if type(qty) == list:
        return qty[level-1]
    return qty

def get_base_value(stat, spec, level):
    if stat == 'maxvel': return 1 # this is a scaling factor in the combat engine
    elif stat == 'permanent_auras': # special case since this could be a list of per-level lists, or a plain all-level list
        if hasattr(spec, stat):
            val = getattr(spec, stat)
            if isinstance(val, list) and len(val) >= 1 and (isinstance(val[0], list) or val[0] is None):
                return get_leveled_quantity(val, level)
            else:
                return val
        else:
            return None
    elif hasattr(spec, stat): return get_leveled_quantity(getattr(spec, stat), level)
    elif stat == 'armor': # XXX annoying special case
        return 0
    elif stat in ('on_destroy','on_damage','on_approach'):
        return None
    elif stat == 'repair_price_cap':
        return -1
    elif stat == 'weapon':
        assert len(spec.spells) >= 1
        return spec.spells[0]
    else:
        return 1

def make_chain(base_val, props = None):
    mod = {'kind':'base', 'val':base_val}
    if props:
        for k in props: mod[k] = props[k]
    return {'val':base_val, 'mods':[mod]}

def add_mod(modchain, method, strength, kind, source, props = None):
    lastval = modchain['val']
    if method == '*=(1-strength)':
        if strength == 0: return modchain
        newval = lastval*(1-strength)
    elif method == '*=(1+strength)':
        if strength == 0: return modchain
        newval = lastval*(1+strength)
    elif method == '*=strength':
        if strength == 1: return modchain
        newval = lastval*strength
    elif method == '+=strength':
        if strength == 0: return modchain
        newval = lastval+strength
    elif method == 'max':
        newval = max(lastval, strength)
    elif method == 'min':
        newval = min(lastval, strength) if lastval >= 0 else strength # -1 for "no limit"
    elif method == 'replace':
        newval = strength
    elif method == 'concat':
        if lastval:
            newval = lastval+strength
        else:
            newval = strength
    else:
        raise Exception('unknown method '+method)
    mod = {'kind':kind, 'source':source, 'method':method, 'strength':strength, 'val':newval}
    if props:
        for k in props: mod[k] = props[k]
    modchain['mods'].append(mod)
    modchain['val'] = newval
    return modchain

def get_stat(modchain, default_value):
    if modchain: return modchain['val']
    return default_value
