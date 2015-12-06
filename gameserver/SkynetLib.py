#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import copy, re, sys

if '../spinpunch-private' not in sys.path:
    sys.path.append('../spinpunch-private')

from SkynetData import spin_targets

# How bidding/LTV estimation works:

# Bids and LTVs for a particular targeting are a product of terms, one term per target.
# Each target's term has 3 parts: 'coeff', 'install_rate', and 'bid_shade'.

# 'coeff' represents our best guess of the relative post-install LTVs in this segment (payback-period LTVs conditional on a true install)
# 'install_rate' tweaks our estimated # of true installs (per click) up or down
# 'bid_shade' modifies ad bids we send to Facebook (without changing the LTV estimate)

# Tweaking:
# 'coeff' should be based on data about player LTV after installing the game. (currently, using "CC L2 within one day" as a proxy)
# 'install_rate' should be scaled using the results of adstats-analyze with --use-analytics to close discrepancies between Actual installs vs. EST installs.
#  *** check install_rate in this order: ALL, then by "m", then by "c", then by "k"
# 'bid_shade' should be used to throttle our ad bids - meaning, to de-weight segments where CPIs are trending higher (reslative to Est LTV) than we want them to be.

# fake stand-in for ad creative parameters
# use this set of parameters instead of get_creatives() if you are
# just doing analysis and do not care about the specific images/titles/bodies.
standin_creatives = {
    'image': { 'name': 'image', 'key': 'x', 'values': 'LITERAL'},
    'title': { 'name': 'title', 'key': 'y', 'values': 'LITERAL'},
    'body':  { 'name': 'body',  'key': 'z', 'values': 'LITERAL'},
    }

standin_spin_params = dict(spin_targets.items()+standin_creatives.items())

def eval_cross_term(coeff_list, tgt, k, v):
    for pred, cons in coeff_list:
        match = True
        for pred_k, pred_v in pred.iteritems():
            if tgt.get(pred_k,None) != pred_v:
                match = False
                break
        if match:
            return cons
    raise Exception('no matching cross term in %s:%s for %s' % (k,v,repr(tgt)))

# Compute the LTV or bid value for a given parameter table and targeting
# "use_bid_shade" should be on for bids, and off for LTV calcs
# if "use_install_rate" is on, then we compute a value conditional on the ad click taking place
# if "use_install_rate" is off, then we compute a value conditional on the true app install taking place
def bid_coeff(table, tgt, base = 1.0, use_bid_shade = False, use_install_rate = True):
    bid = base
    install_rate = 1.0
    ui_info = []

    # XXX legacy support
    if 'game' not in tgt:
        tgt = copy.copy(tgt)
        tgt['game'] = 'tr'

    for k, v in tgt.iteritems():
        param_data = table[k]
        found = False
        if param_data['values'] == 'LITERAL': continue
        for entry in param_data['values']:
            if ('val' in entry and v == entry['val']) or \
               ('val_match' in entry and re.match(make_variable_regexp(entry['val_match'][0]), v[0])):
                found = True
                coeff = entry.get('coeff',1)
                if type(coeff) is list: coeff = eval_cross_term(coeff, tgt, k, v)

                rate = entry.get('install_rate',1)
                if type(rate) is list: rate = eval_cross_term(rate, tgt, k, v)

                install_rate *= rate
                if rate != 1 and use_install_rate: ui_info.append('%.2f %s:%s_install_rate' % (rate, k, v))
                if use_bid_shade:
                    shade = entry.get('bid_shade',1)
                    if type(shade) is list: shade = eval_cross_term(shade, tgt, k, v)
                    coeff *= shade

                if coeff != 1: ui_info.append('%.2f %s:%s' % (coeff, k, v))
                bid *= coeff
                if bid <= 0: return bid, '(<=0)'
                break
        if not found:
            raise Exception('not found: %s:%s' % (k,v))
    if use_install_rate:
        bid *= install_rate
    return bid, install_rate, ' * '.join(ui_info)


# PARAMETER ENCODING
# establishes a unique 1-to-1 mapping between text strings and ad targeting/creative parameters
# used to link clicks/installs back to the ads that caused them, and for naming ads
# {'country': 'us', 'age_range': [18, 24], 'keyword': 'war commander', 'gender': 'm'}  <-> "cus_gm_kec_m2535"
# note! keys are sorted alphabetically to ensure unique 1-to-1 mapping between dicts and these strings

def ensure_keys_are_unique(targets):
    seen = {}
    for val in targets.itervalues():
        if val['key'] in seen:
            raise Exception('non-unique key: %s' % val['key'])
        else:
            seen[val['key']]=1
ensure_keys_are_unique(spin_targets)

def make_variable_regexp(template):
    return template.replace('$DATE', '(?P<DATE>[0-9]{8})').replace('$COUNTRY', '(?P<COUNTRY>[a-z,]+)')+'$'

MATCH_VARIABLES = ('DATE', 'COUNTRY')
def collapse_match_variables(template, matches):
    # perform variable replacements from the matching abbrev into the value
    for varname in MATCH_VARIABLES:
        if '$'+varname in template:
            replist = [match.group(varname) for match in matches]
            all_same = True
            for i in xrange(1, len(replist)):
                if replist[i] != replist[0]:
                    all_same = False
                    break
            if all_same:
                replist = [replist[0]]
            template = template.replace('$'+varname, ','.join(replist))
    return template

def expand_match_variables(template, match):
    # inverse of collapse_match_variables()
    ret = [template]
    for varname in MATCH_VARIABLES:
        if '$'+varname in template:
            if ',' in match.group(varname):
                assert len(ret) == 1
                ret = [ret[0].replace('$'+varname, x) for x in match.group(varname).split(',')]
            else:
                for i in xrange(len(ret)):
                    ret[i] = ret[i].replace('$'+varname, match.group(varname))
    return ret

def encode_one_param(table, name, value):
    data = table[name]
    if data['values'] == 'LITERAL': return data['key']+value
    for vdat in data['values']:
        if 'val' in vdat and vdat['val'] == value:
            abbrev = vdat.get('abbrev', value)
            if abbrev is None: return None
            return data['key']+abbrev
        elif 'val_match' in vdat and type(value) is list:
            matches = []
            for val in value:
                match = re.match(make_variable_regexp(vdat['val_match'][0]), val)
                if match:
                    matches.append(match)
            if len(matches) == len(value):
                return data['key']+collapse_match_variables(vdat['abbrev_match'], matches)
    raise Exception('cannot encode: "%s":"%s"' % (name,value))

def decode_one_param(table, param):
    if len(param) < 2:
        raise Exception('bad param: "%s"' % param)
    key, val = param[0], param[1:]
    for data in table.itervalues():
        if key == data['key']:
            if data['values'] == 'LITERAL': return data['name'], val
            for vdat in data['values']:
                if 'abbrev_match' in vdat:
                    # regular-expression match with substitution into 'val'
                    match = re.match(make_variable_regexp(vdat['abbrev_match']), val)
                    if match:
                        assert type(vdat['val_match']) is list
                        assert len(vdat['val_match']) == 1
                        return data['name'], expand_match_variables(vdat['val_match'][0], match)
                elif 'abbrev' in vdat and vdat['abbrev'] == val:
                    # abbreviated stand-in for full 'val'
                    return data['name'], vdat['val']
                elif vdat['val'] == val:
                    # just plain literal 'val'
                    return data['name'], vdat['val']
    raise Exception('param not found: param "%s" key "%s"' % (param,key))

def encode_params(table, params):
    return '_'.join(sorted(filter(lambda x: x is not None, [encode_one_param(table,n,v) for n,v in params.iteritems()]), key = lambda x: x[0]))

def decode_params(table, s, error_on_invalid = True):
    try:
        ret = dict()
        for param in s.split('_'):
            name, value = decode_one_param(table,param)
            ret[name] = value
        return ret
    except Exception as e:
        if error_on_invalid:
            raise Exception('error decoding "%s":\n%s' % (s,str(e)))
        else:
            pass
    return None

# like decode_params, but allows ! for negation
def decode_filter(table, s):
    ret = dict()
    for param in s.split('_'):
        if param[1:] == 'MISSING':
            coded_name = param[0]
            for data in table.itervalues():
                if data['key'] == coded_name:
                    ret[data['name']] = 'MISSING'
                    break
        else:
            if param[0] == '!':
                coded_value = param[1:]
            else:
                coded_value = param
            name, value = decode_one_param(table, coded_value)
            if param[0] == '!':
                ret[name] = {'!':value}
            else:
                ret[name] = value
    return ret
def match_params(candidate, filter):
    for k,v in filter.iteritems():
        candidate_val = candidate.get(k,'MISSING')
        if type(v) is dict and '!' in v:
            if candidate_val == v['!']: return False
        elif type(v) in (str,unicode) and ('.' in v):
            return re.compile(v).match(candidate_val)
        else:
            if candidate_val != v: return False
    return True

# test code
if 0:
    spin_test_creatives = {
        'image': {'name': 'image', 'key': 'x', 'values': [{'val':'0000', 'coeff':1.0},
                                                          {'val':'0001', 'coeff':1.0}]},
        'title': {'name': 'title', 'key': 'y', 'values': [{'val':'0000', 'coeff':1.0},
                                                          {'val':'0001', 'coeff':1.0}]},
        'body': {'name': 'body', 'key': 'z', 'values': [{'val':'0000', 'coeff':1.0},
                                                        {'val':'0001', 'coeff':1.0}]},
        }
    tgt = {'country':'us','gender':'m', 'age_range':[18,24], 'keyword':['thunder run']}
    crt = {'image':'0001', 'title':'0001', 'body':'0001'}
    combo = dict(tgt.items() + crt.items())
    combo_params = dict(spin_targets.items()+spin_test_creatives.items())
    print tgt, encode_params(spin_targets,tgt), decode_params(spin_targets,encode_params(spin_targets,tgt))
    print crt, encode_params(spin_test_creatives,crt), decode_params(spin_test_creatives,encode_params(spin_test_creatives,crt))
    print combo, encode_params(combo_params,combo), decode_params(combo_params,encode_params(combo_params,combo))
    import sys
    sys.exit(0)

def decode_adgroup_name(params, name):
    if name.startswith('Sky'):
        name_fields = name.split(' ')
        stgt = name_fields[-1]
        try:
            tgt = decode_params(params, stgt)
            assert encode_params(params, tgt) == stgt # ensure mapping is unique
            return stgt, tgt
        except:
            pass
    return None, None

# convert string target like "amf2_krts" to dict target {'a': 'mf2', 'k':'rts'}
# this does NOT preserve enough info to launch ads - it's for easier querying in MongoDB
def stgt_to_dtgt(stgt):
    return dict((x[0], x[1:]) for x in stgt.split('_'))


# used to filter out mistakes
def adgroup_name_is_bad(name):
    if ('BAD' in name) or ('OLD' in name): return True
    return False

# translate from Facebook JSON to a Mongo-safe encoding
def _mongo_enc(item):
    # Mongo does not accept dictionary keys that contain ".", so replace them
    if type(item) is dict:
        for k in item.keys():
            if ('.' in k):
                k2 = k.replace('.','&#46;')
            else:
                k2 = k

            v = _mongo_enc(item[k])
            if k2 != k: del item[k]
            item[k2] = v

    elif type(item) is list:
        ret = []
        for entry in item:
            ret.append(_mongo_enc(entry))
        return ret
    return item

def mongo_enc(item):
    ret = _mongo_enc(item)
    return ret

# OBSOLETe - use adgroup_dtgt_filter_query() instead
def adgroup_name_filter_query(tgt_filter):
    adgroup_query = []
    for k, v in tgt_filter.iteritems():
        if v == 'MISSING': continue # could optimize this later
        negate = False
        if type(v) is dict and ('!' in v):
            negate = True
            p = encode_one_param(standin_spin_params, k, v['!'])
        else:
            p = encode_one_param(standin_spin_params, k, v)
        expr = '^.*[_ ]%s[_ $]' %p
        reg = re.compile(expr)
        if negate: reg = {'$not':reg}
        adgroup_query.append(('name', reg))
    return adgroup_query

def adgroup_dtgt_filter_query(dtgt, dtgt_key = 'dtgt'):
    query = {}
    for k, v in dtgt.iteritems():
        qkey = dtgt_key+'.'+mongo_enc(k)
        if v == 'MISSING':
            query[qkey] = {'$exists':False}
            continue
        else:
            if type(v) is dict and ('!' in v): # negate
                query[qkey] = {'$neq':mongo_enc(v['!'])}
            elif type(v) in (str,unicode) and ('.' in v): # treat as a regular expression, as with cgianalytics.Query.match_acquisition_ad_skynet()
                query[qkey] = {'$regex':v}
            else:
                query[qkey] = mongo_enc(v)
    return query

# return a set of column name, type tuples for encoding "dtgt" targeting into an SQL table
def get_tgt_fields_for_sql():
    ret = []
    for item in standin_spin_params.itervalues():
        datatype = 'VARCHAR(64)'

        # ensure there is always a valid "game" field
        if item['name'] == 'game':
            datatype += ' NOT NULL'

        ret.append(('tgt_%s' % item['name'], datatype))
    ret.sort()
    return ret
