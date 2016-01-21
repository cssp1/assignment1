#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# switchable interface to various JSON libraries

# preference is ujson (really fast, but no ordering support) > simplejson > Python-shipped json
import os

has_simplejson = False
try:
    import simplejson
    has_simplejson = True
except:
    pass

# get an ordered dict class
import collections
if hasattr(collections, 'OrderedDict'): # only available in Python 2.7+
    ordered_dict_klass = collections.OrderedDict
else:
    import OrderedDict
    ordered_dict_klass = OrderedDict.OrderedDict

has_ujson = False
if (not os.getenv('NO_UJSON')):
    try:
        import ujson
        has_ujson = True
    except:
        pass

# fallback system JSON library, loaded lazily
json = None
def system_json():
    global json
    if json is None:
        json = __import__('json')
    return json

def load(fd, ordered = False):
    if has_ujson and (not ordered): return ujson.load(fd)
    if has_simplejson:
        loader = simplejson.load
    else:
        loader = system_json().load

    if ordered:
        return loader(fd, object_pairs_hook = ordered_dict_klass)
    else:
        return loader(fd)

def loads(s, ordered = False):
    if has_ujson and (not ordered): return ujson.loads(s)
    if has_simplejson:
        loader = simplejson.loads
    else:
        loader = system_json().loads

    if ordered:
        return loader(s, object_pairs_hook = ordered_dict_klass)
    else:
        return loader(s)

def dump(obj, fd, pretty = False, newline = False, size_hint = 0, double_precision = 5, ordered = False):
    if has_ujson and (not ordered):
        ujson.dump(obj, fd, DJM_append_newline = newline, DJM_size_hint = size_hint, DJM_pretty = pretty, double_precision = double_precision, ensure_ascii = True)
    else:
        separators = (', ', ': ') if pretty else (',',':')
        if has_simplejson:
            simplejson.dump(obj, fd, separators=separators)
        else:
            system_json().dump(obj, fd, separators=separators)
        if newline:
            fd.write('\n')

def dumps(obj, pretty = False, newline = False, size_hint = 0, double_precision = 5, ordered = False):
    if has_ujson and (not ordered):
        return ujson.dumps(obj, DJM_append_newline = newline, DJM_size_hint = size_hint, DJM_pretty = pretty, double_precision = double_precision, ensure_ascii = True)
    else:
        separators = (', ', ': ') if pretty else (',',':')
        if has_simplejson:
            ret = simplejson.dumps(obj, separators=separators)
        else:
            ret = system_json().dumps(obj, separators=separators)
        if newline:
            ret += '\n'
        return ret


