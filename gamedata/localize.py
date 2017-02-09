#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# GUI text localization system

# This script has two modes:

# In "extract" mode, it scans the raw gamedata.json for ui strings
# that must be localized and writes them to a .pot file.
# This must be run manually whenever you want to update the .pot file.

# In "apply" mode, it reads the raw untranslated gamedata.json plus a
# language-specific .po file and writes out the language-specific
# gamedata.json where all the ui strings are replaced by the
# translated versions. This is run automatically by the make-gamedata Makefile.

# Example commands to update the master .pot files: (to include newly-added strings to translate)
# Execute in gamedata/ directory, and with an up-to-date built gamedata for this game from make-gamedata.sh:
#     export GAME=tr # your game ID
#     export PYTHONPATH=../gameserver
#     ./localize.py --mode extract --quiet ${GAME}/built/gamedata-${GAME}.json ${GAME}/localize/${GAME}.pot

# Example commands to update the per-language .po files: (to match the new .pot files, adding newly-translatable strings and commenting out obsolete translations)
# note: requires gettext - install GNU textutils via distro method or get source from http://ftp.gnu.org/pub/gnu/gettext/
# Execute in gamedata/ directory:
#     export GAME=tr # your game ID
#     for GAMELANG in `env ls ${GAME}/localize/*.po | sed "s1.*localize/${GAME}-11; s1.po11;"`; do msgmerge --update --no-fuzzy-matching --no-wrap ${GAME}/localize/${GAME}-${GAMELANG}.po ${GAME}/localize/${GAME}.pot; done


import SpinConfig
import SpinJSON
import AtomicFileWrite
import polib
import sys, getopt

def accum_entry(entries, msgid, where, verbose):
    if not msgid: return
    occurrence = (where,'')
    if msgid in entries:
        entries[msgid].occurrences.append(occurrence)
    else:
        entries[msgid] = polib.POEntry(msgid = msgid, occurrences = [occurrence])
        if verbose: print >>sys.stderr, "GOT", msgid

# need this because we don't know what kind of crazy OrderedDict class the JSON parser is using
def is_dictlike(obj): return (type(obj) not in (str,unicode,list)) and hasattr(obj, '__getitem__')

def get_strings(path, data, filter = None, is_strings_json = False):
    # strings.json needs special-case handling since it has some strange nested structures

    ret = []
    if type(data) is list:
        for item in data:
            if item:
                ret += get_strings(path+'[]', item, filter = filter, is_strings_json = is_strings_json)
    elif is_dictlike(data):
        if 'predicate' in data: return ret # skip predicates
        for k, v in data.iteritems():
            if is_dictlike(v) or (isinstance(v, list) and len(v) >= 1 and is_dictlike(v[0])):
                ret += get_strings(path+'/'+k, v, filter = filter, is_strings_json = is_strings_json)
            elif (k in ('ui_congrats',) or is_strings_json) and \
                 isinstance(v, list) and len(v) >= 1 and \
                 isinstance(v[0], basestring) and \
                 (k not in ('damage_vs_qualities','periods')):
                for item in v:
                    ret.append((item, path+'/'+k+'[]'))
            elif type(v) in (str, unicode):
                if v and ((not filter) or (k.startswith(filter))) and (k not in ('check_spec','icon','unit_icon','upgrade_icon_tiny')):
                    ret.append((v, path+'/'+k))
#    elif type(data) in (int, float): # shouldn't need this check
#        return ret
    else:
        raise Exception('unhandled thing at %s: %r' % (path, data))

    return ret

# parts of gamedata that need their ui_whatever things translated
TRANSLATE_CATEGORIES = ('dialogs','resources','spells','units','buildings','tech','enhancements','items','auras','errors','store','tutorial','inert','predicate_library','consequent_library','quests','daily_tips','daily_messages','virals','achievement_categories','achievements','fb_notifications','regions','crafting')

def do_extract(gamedata, outfile, verbose = True):
    if verbose: print >>sys.stderr, "read gamedata game_id", gamedata['game_id'], "built", gamedata['gamedata_build_info']['date']
    po = polib.POFile(check_for_duplicates = True, encoding = 'utf-8', wrapwidth = -1)
    po.metadata = { 'Content-Type': 'text/plain; charset=utf-8', 'Content-Transfer-Encoding': '8bit' }
    entries = {} # map from msgid->POEntry
    map(lambda msgid_where: accum_entry(entries, msgid_where[0], msgid_where[1], verbose=verbose), get_strings('strings', gamedata['strings'], filter = None, is_strings_json = True))
    for category in TRANSLATE_CATEGORIES:
        map(lambda msgid_where: accum_entry(entries, msgid_where[0], msgid_where[1], verbose=verbose), get_strings(category, gamedata[category], filter = 'ui_'))
    map(po.append, sorted(entries.values(), key = lambda x: x.msgid))
    po.save(outfile)
    if verbose: print >>sys.stderr, "wrote", outfile

def get_translation(v, entries, verbose):
    if v in entries and entries[v]:
        return entries[v]
    if v.startswith('!TX'):
        raise Exception('missing mandatory translation for string "%s"' % v)
    if verbose: print >>sys.stderr, "untranslated string", '"'+v+'"'
    return v

def put_strings(data, entries, filter = None, is_strings_json = False, verbose = False):
    if type(data) is list:
        for item in data:
            put_strings(item, entries, filter = filter, is_strings_json = is_strings_json, verbose = verbose)
    else:
        assert is_dictlike(data)
        if 'predicate' in data: return # skip predicates
        for k, v in data.iteritems():
            if is_dictlike(v) or (isinstance(v, list) and len(v) >= 1 and is_dictlike(v[0])):
                put_strings(v, entries, filter = filter, is_strings_json = is_strings_json, verbose = verbose)
            elif is_strings_json and isinstance(v, list) and len(v) >= 1 and isinstance(v[0], basestring) and \
                 (k not in ('damage_vs_qualities','periods')):
                for i, item in enumerate(v):
                    v[i] = get_translation(item, entries, verbose)
            elif type(v) in (str, unicode):
                if v and ((not filter) or (k.startswith(filter))):
                    data[k] = get_translation(v, entries, verbose)

def do_apply(locale, gamedata, input_po_file, output_json_file, verbose = True):
    po = polib.pofile(input_po_file, encoding = 'utf-8', wrapwidth = -1)
    entries = dict([(entry.msgid, entry.msgstr) for entry in po])
    # translate in place
    put_strings(gamedata['strings'], entries, filter = None, is_strings_json = True, verbose = verbose)
    for category in TRANSLATE_CATEGORIES:
        put_strings(gamedata[category], entries, filter = 'ui_', verbose = verbose)
    atom = AtomicFileWrite.AtomicFileWrite(output_json_file, 'w')
    SpinJSON.dump(gamedata, atom.fd, ordered=True, pretty=False, newline=True, size_hint = 8*1024*1024) # ,double_precision=5)
    atom.complete()
    if verbose: print >>sys.stderr, "wrote", atom.filename

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['game-id=','mode=','locale=','quiet'])
    game_id = SpinConfig.game()
    verbose = True
    locale = None
    mode = 'apply'
    for key, val in opts:
        if key == '-g' or key == '--game-id': game_id = val
        elif key == '--mode': mode = val
        elif key == '--locale': locale = val
        elif key == '--quiet': verbose = False

    # note! critical that order of dictionary entries be preserved!
    gamedata = SpinJSON.load(open(args[0]), ordered = True) # SpinConfig.gamedata_filename(override_game_id = game_id)))

    if mode == 'extract':
        output_pot_file = args[1]
        do_extract(gamedata, output_pot_file, verbose = verbose)
    elif mode == 'apply':
        if not locale:
            raise Exception('must specify --locale when in apply mode')
        input_po_file = args[1]
        output_json_file = args[2]
        do_apply(locale, gamedata, input_po_file, output_json_file, verbose = verbose)
    else:
        raise Exception('unknown mode '+mode)
