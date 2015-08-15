#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# generate boilerplate JSON skeleton for "immortal" and time-limited token AIs

import SpinJSON
import SpinConfig
import AtomicFileWrite
import LootTable
import sys, copy, getopt, os, random

gamedata = None

generic_data = {
    'trophies': {'Normal': 10, 'Heroic':30, 'Epic':50 },

    'loot': {'Normal':[{"table": "ai_generic_normal_low_drop"},
                       {"table": "ai_generic_normal_low_drop"},
                       {"table": "ai_generic_normal_low_drop"},
                       {"table": "ai_generic_normal_low_drop"},
                       {"table": "ai_generic_normal_high_drop"},
                       {"table": "ai_generic_normal_high_drop"},
                       {"table": "ai_generic_normal_high_drop"},
                       {"table": "ai_generic_normal_rare_drop"}],
             'Heroic':[{"table": "ai_generic_heroic_low_drop"},
                       {"table": "ai_generic_heroic_low_drop"},
                       {"table": "ai_generic_heroic_low_drop"},
                       {"table": "ai_generic_heroic_low_drop"},
                       {"table": "ai_generic_heroic_high_drop"},
                       {"table": "ai_generic_heroic_high_drop"},
                       {"table": "ai_generic_heroic_high_drop"},
                       {"table": "ai_generic_heroic_rare_drop"}],
             'Epic':[{"table": "ai_generic_epic_low_drop"},
                     {"table": "ai_generic_epic_low_drop"},
                     {"table": "ai_generic_epic_low_drop"},
                     {"table": "ai_generic_epic_low_drop"},
                     {"table": "ai_generic_epic_high_drop"},
                     {"table": "ai_generic_epic_high_drop"},
                     {"table": "ai_generic_epic_high_drop"},
                     {"table": "ai_generic_epic_high_drop"}],
             }
    }

# buffed iron/water richness used for FIRST PLAY ONLY - replays should drop less loot
# the reduction at high levels counter-animates the ramp-up in ai_bases.json:loot_table :(
TR_BUFFED_BASE_RICHNESS = [0.6,0.6,0.9,0.9,0.6,0.6,0.6,0.6,
                           0.6,0.5,0.45,0.45,0.3,0.3,0.3,0.3,
                           0.4,0.4,0.4,0.4,0.4,0.4,0.4,0.4,
                           0.37,0.32,0.30,0.25,0.23,0.22,0.21,0.20,
                           0.19,0.18,0.17,0.17,0.17,0.17,0.17,0.17,
                           0.17,0.17,0.17,0.17,0.17,0.17,0.17,0.17,
                           0.17,0.17,0.17,0.17,0.17,0.17,0.17,0.17,
                           0.17,0.17,0.17,0.17]
# buffed iron/water drops for AI attack waves, used for FIRST PLAY ONLY
TR_BUFFED_AI_ATTACK_LOOT = [{'multi':[{'spec':'boost_water_1000'}]}, # L1
                            {'multi':[{'spec':'boost_iron_1000'}]},  # L2
                            {'multi':[{'spec':'boost_iron_1000'}]}, # L3
                            {'multi':[{'spec':'boost_iron_1000'}]},  # L4
                            {'multi':[{'spec':'boost_water_5000'}]}, # L5
                            {'multi':[{'spec':'boost_iron_5000'}]},  # L6
                            {'multi':[{'spec':'boost_iron_5000'}]}, # L7
                            {'multi':[{'spec':'boost_iron_25000'}]},  # L8
                            {'multi':[{'spec':'boost_water_5000'}]}, # L9
                            {'multi':[{'spec':'boost_iron_10000'}]},  # L10
                            {'multi':[{'spec':'boost_water_10000'}]}, # L11
                            {'multi':[{'spec':'boost_iron_20000'}]},  # L12
                            {'multi':[{'spec':'boost_water_20000'}]}, # L13
                            {'multi':[{'spec':'boost_iron_30000'}]},  # L14
                            {'multi':[{'spec':'boost_iron_30000'}]}, # L15
                            {'multi':[{'spec':'boost_water_30000'}]},  # L16
                            {'multi':[{'spec':'boost_iron_50000'}]}, # L17
                            {'multi':[{'spec':'boost_iron_50000'}]},  # L18
                            {'multi':[{'spec':'boost_water_50000'}]}, # L19
                            {'multi':[{'spec':'boost_iron_100000'}]}, # L20
                            {'multi':[{'spec':'boost_iron_100000'}]},  # L21
                            {'multi':[{'spec':'boost_water_100000'}]}, # L22
                            {'multi':[{'spec':'boost_iron_250000'}]},  # L23
                            ] + [{'multi':[{'spec':'boost_'+('water' if (level%4)==0 else 'iron')+'_500000'}]} for level in xrange(24,61)]

event_data = {
    # this data has all been moved to .skel files in the individual game title gamedata directories
}

def dump_kv(klist,k,d, depth = 0, fd = sys.stdout):
    print >> fd, '"%s":' % k,
    dump_json(d[k], depth=depth, fd = fd)
    if len(klist) > 0:
        print >> fd, ',',

# annoying custom JSON dump function
def dump_json(val, depth = 0, fd = sys.stdout):
    if type(val) is dict and (('consequent' in val) or ('predicate' in val)):
        # manually dump predicates so they are more human-readable
        print >> fd, '{',
        todump = val.keys()

        if 'consequent' in todump:
            todump.remove('consequent')
            dump_kv(todump, 'consequent', val, depth=depth, fd=fd)
            if ('subconsequents' in todump) and (len(val['subconsequents']) > 1):
                todump.remove('subconsequents')
                print >> fd, '"subconsequents": ['
                for i in xrange(len(val['subconsequents'])):
                    print >> fd, '        '*(depth+1),
                    dump_json(val['subconsequents'][i], depth=depth+1)
                    if i < len(val['subconsequents'])-1:
                        print >> fd, ','
                print >> fd, ']',

            if ('if' in todump):
                todump.remove('if')
                print >> fd, '"if":',
                dump_json(val['if'], depth=depth+1)
                print >> fd, ','
                todump.remove('then')
                print >> fd, '        '*(depth+1),
                print >> fd, '"then":',
                dump_json(val['then'], depth=depth+1)
                if ('else' in todump):
                    print >> fd, ','
                    todump.remove('else')
                    print >> fd, '        '*(depth+1),
                    print >> fd, '"else":',
                    dump_json(val['else'], depth=depth+1)
                else:
                    print >> fd, ''

        if 'predicate' in todump:
            todump.remove('predicate')
            dump_kv(todump, 'predicate', val, depth=depth, fd=fd)
            if ('subpredicates' in todump) and (len(val['subpredicates']) > 1):
                todump.remove('subpredicates')
                print >> fd, '"subpredicates": ['
                for i in xrange(len(val['subpredicates'])):
                    print >> fd, '        '*(depth+1),
                    dump_json(val['subpredicates'][i], depth=depth+1)
                    if i < len(val['subpredicates'])-1:
                        print >> fd, ','
                print >> fd, ']',

            # dump certain fields in fixed order to resemble human-written predicates better
            ORDERED_FIELDS = None

            if val['predicate'] in ('ANY_ABTEST', 'PLAYER_HISTORY'):
                ORDERED_FIELDS = ('key', 'method', 'value', 'default')
            elif val['predicate'] == 'BUILDING_LEVEL':
                ORDERED_FIELDS = ('building_type', 'trigger_level')

            if ORDERED_FIELDS:
                for FIELD in ORDERED_FIELDS:
                    if FIELD in todump:
                        todump.remove(FIELD)
                        dump_kv(todump, FIELD, val, depth=depth, fd=fd)

        while len(todump) > 0:
            dump_kv(todump, todump.pop(), val, depth=depth, fd=fd)
        print >> fd, '}',
    elif 0 and (type(val) is list or type(val) is tuple):
        print >> fd, '['
        for i in xrange(len(val)):
            if depth > 0:
                print >> fd, ' '*depth,

            dump_json(val[i], depth=depth+1)
            if i < len(val)-1:
                print >> fd, ',',
        print >> fd, ']',
    else:
        print >> fd, '',
        SpinJSON.dump(val, fd, pretty = False, newline = False)

def dump_json_toplevel(blob, depth=0, fd = sys.stdout):
    items = sorted(blob.items())
    print >>fd, '{'
    for i in xrange(len(items)):
        key, val = items[i]
        print >>fd, '    '*(depth+1), '"%s":' % key,
        if type(val) is dict:
            dump_json_toplevel(val, fd=fd, depth=depth+1)
        else:
            dump_json(val, fd=fd, depth=depth+1)
        if i != len(items)-1:
            print >>fd, ','
        else:
            print >>fd, '\n', '    '*(depth), '}',

def completion_valentina_message(picture = None, text = None, extra = ''):
    assert picture is not None and type(picture) is str
    assert text is not None and type(text) is str
    return { "consequent": "DISPLAY_MESSAGE", "dialog": "daily_tip",
             "picture_asset": "valentina_cutscene_message_bg",
             "inset_picture": picture,
             "inset_picture_dimensions": [727,133],
             "understood_button_xy": [575,385],
             "understood_button_ui_name": "Proceed",
             "description_xy": [221, 218], "description_dimensions": [500,150],
             "ui_description": text + extra}

def print_auto_gen_warning(fd = sys.stdout):
    print >>fd, "// AUTO-GENERATED FILE - DO NOT EDIT!"
    print >>fd, "// Make changes using make_ai_skeleton.py or the event .skel file."
    print >>fd, "// Skeleton JSON created by:"
    print >>fd, "// PYTHONPATH=../gameserver ./make_ai_skeleton.py " + " ".join(sys.argv[1:])
    print >>fd

def generate_showcase_consequent(game_id, event_dirname, data):
    atom = AtomicFileWrite.AtomicFileWrite('%s/%s_consequent_library_%s.json' % (game_id, game_id, event_dirname), 'w')
    try:
        _generate_showcase_consequent(game_id, event_dirname, data, atom)
        atom.complete()
    except:
        atom.abort()
        raise

def _generate_showcase_consequent(game_id, event_dirname, data, atom):
    WRAP_IN_ABTEST = False # temporary - wrap in A/B test

    randgen = random.Random(1234) # fix random number seed for loot-table sampling

    has_multiple_difficulties = len(data['difficulties']) > 1
    highest_difficulty = data['difficulties'][-1]

    print_auto_gen_warning(fd = atom.fd)
    for diff in data['difficulties']:
        suffix = data['key_suffix'][diff]
        extra_suffix = data.get('extra_key_suffix',{}).get(diff,None)

        # based on the actual loot tables, try to reverse-engineer what the event is dropping
        has_tokens = False
        final_loot_unit = None
        final_loot_unit_substitute_items = None
        final_loot_item_set = None
        final_loot_item_list = None # can override final_loot_item_set

        sample = get_loot_sample(data['loot'][diff][-1], randgen = randgen)

        #sys.stderr.write("Final loot sample: "+repr(sample)+"\n")
        for item in sample:
            if item['spec'] == 'token':
                has_tokens = True
            elif item['spec'].startswith('leader_'):
                item_set = None

                # brute-force search through item_sets just so that we do not need to import items.json, which causes nasty dependency cycle.
                for set_name, set_data in gamedata['item_sets'].iteritems():
                    if item['spec'] in set_data['members']:
                        item_set = set_name

                if item_set is None:
                    raise Exception('cannot find item_set containing event loot: %s' % (item['spec']))

                if final_loot_item_set is None:
                    final_loot_item_set = item_set
                else:
                    if final_loot_item_set != item_set:
                        raise Exception('inconsistent item_set in event loot: %s vs %s' % (final_loot_item_set, item_set))

            elif item['spec'].endswith('_blueprint'):
                final_loot_unit = item['spec'].split('_blueprint')[0]

                # repeat finding the final loot sample, but assume the player already has the unit, to see what other items might drop
                extra = lambda pred, _unit=final_loot_unit: (pred['predicate'] == 'HAS_ITEM' and pred['item_name'] == _unit+'_blueprint')
                sample = get_loot_sample(data['loot'][diff][-1], randgen = randgen, extra_test = extra)

                # sort items, putting items that have the unit name in their specname first
                sample.sort(key = lambda x: '!!'+x['spec'] if final_loot_unit in x['spec'] else x['spec'])
                #sys.stderr.write("Final loot sample (blueprint already obtained): "+repr(sample)+"\n")
                final_loot_unit_substitute_items = sample[0:3]

        # returns a value contained in a dictionary keyed with the provided difficulty or the value itself
        # if it is not such a dictionary
        def get_for_difficulty(value, diff):
            if isinstance(value, dict):
                if diff in value:
                    return value[diff]
                else:
                    # confirm that the difficulty value in value is actually missing and hasn't just been mistyped
                    for key in value:
                        if key not in data['difficulties']:
                            raise Exception('Invalid difficulty %s specified in %r' % (key, value))

                    return None
            else:
                return value

        # allow manual override of final loot
        if 'final_reward_unit' in data['showcase']: final_loot_unit = get_for_difficulty(data['showcase']['final_reward_unit'], diff)
        if 'final_reward_item_set' in data['showcase']: final_loot_item_set = get_for_difficulty(data['showcase']['final_reward_item_set'], diff)
        if 'final_reward_items' in data['showcase']: final_loot_item_list = get_for_difficulty(data['showcase']['final_reward_items'], diff)

        if not (final_loot_unit or final_loot_item_set or final_loot_item_list):
            raise Exception('Error generating showcase. Cannot figure out what kind of final loot this event drops.')

        # reverse-engineer the intermediate loot drops
        random_loot_phases = [] # list of [{'ends_at':, 'ui_name':X, 'items':[]},...]
        last_random_loot_end = 0

        if 'progression_loot_phases' in data['showcase']:
            progression_loot_phases = data['showcase']['progression_loot_phases']
        else:
            # just treat the entire event as a single difficulty level if it has no loot phases specified
            progression_loot_phases = [{'ui_name': diff, 'ends_at': data['bases_per_difficulty'], 'show_max_items': 20}]

        for entry in progression_loot_phases:
            items = set()
            for level in xrange(last_random_loot_end+1, min(entry['ends_at']+1, data['bases_per_difficulty'])):
                for trial in xrange(100):
                    for TABLE in ('loot', 'loot_once_only'):
                        if TABLE not in data: continue
                        my_loot = data[TABLE][diff][level-1]
                        if not my_loot: continue
                        sample = get_loot_sample(my_loot, randgen = randgen)
                        #sys.stderr.write(("Progression loot sample for %s (L%d): " % (entry['ui_name'], level)) +repr(sample)+"\n")
                        for item in sample:
                            if (final_loot_unit_substitute_items and {'spec':item['spec']} in final_loot_unit_substitute_items) or \
                               (final_loot_item_set and item['spec'] in gamedata['item_sets'][final_loot_item_set]['members']) or \
                               (final_loot_item_list and item in final_loot_item_list): continue # don't overlap with the final items
                            items.add(item['spec'])
            if len(items) < 1:
                raise Exception('Error generating showcase. Cannot figure out progression loot for phase %s' % entry['ui_name'])

            phase = {'ui_name': entry['ui_name'], 'ends_at': entry['ends_at'], 'show_max_items': entry['show_max_items'], 'items': [{'spec':x} for x in items]}
            random_loot_phases.append(phase)
            #sys.stderr.write(("Random loot phase %s: " % (entry['ui_name'])) +repr(phase['items'])+"\n")
            last_random_loot_end = entry['ends_at']

        # set up the text that is displayed on milestone and progression screens
        DEFAULT_PROGRESSION_TEXT_TOKENS = "Continue fighting %AI from your home base or on the Map to win %TOKEN and other rewards.\n\nUse %TOKEN to unlock epic rewards in the %PLUS_STORE_CATEGORY Store."
        DEFAULT_PROGRESSION_TEXT_UNIT = "Continue fighting %AI from your home base to win %FINAL_REWARD and other rewards."
        DEFAULT_PROGRESSION_TEXT_OTHER = "Continue fighting %AI from your home base to win special rewards."

        if has_tokens:
            progression_text = data['showcase'].get('progression_text', DEFAULT_PROGRESSION_TEXT_TOKENS).replace('%AI', data['villain_ui_name'])
        elif final_loot_unit:
            progression_text = data['showcase'].get('progression_text', DEFAULT_PROGRESSION_TEXT_UNIT).replace('%AI', data['villain_ui_name'])
            already_obtained_unit_predicate = {"predicate": "OR", "subpredicates": [{"predicate": "LIBRARY", "name": final_loot_unit+"_unlocked"},
                                                                                    {"predicate": "HAS_ITEM", "item_name": final_loot_unit+"_blueprint"}]}

            progression_text = [[already_obtained_unit_predicate, progression_text.replace('%FINAL_REWARD', 'a bonus item pack')], \
                                [{"predicate": "ALWAYS_TRUE"}, progression_text.replace('%FINAL_REWARD', 'blueprints for the %s' % gamedata['units'][final_loot_unit]['ui_name'])]]
        else:
            # most immortal events reward a unit as the final reward, so just use a generic message as a final fallback option
            progression_text = data['showcase'].get('progression_text', DEFAULT_PROGRESSION_TEXT_OTHER).replace('%AI', data['villain_ui_name'])

        # set up the text that is displayed as a title on intro and progression screens
        if has_multiple_difficulties:
            progression_title = '%s PROGRESSION REWARDS:' % diff.upper()
        else:
            progression_title = 'PROGRESSION REWARDS:'

        # SHOWCASE
        showcase = { "enable": 1, "ui_title": data['event_ui_name'].upper(),
                     "villain_asset": data['villain_attack_portrait'],
                     "ui_villain_name": data['villain_ui_name'],
                     "total_levels": data['bases_per_difficulty'],
                     "progress_key": "ai_"+data['event_name']+suffix+"_progress_now",
                     "progress_key_cooldown": "ai_"+data['event_name']+suffix+"_instance", # this cooldown must be active in order for the progress_key to be valid
                     "achievement_keys": generate_achievement_keys(data, has_tokens)
                     }
        if 'skip' in data and any(data['skip'][diff]): # only emit if some entries are nonzero
            showcase['level_skip'] = copy.deepcopy(data['skip'][diff])

        if has_tokens:
            showcase['token_item'] = 'token'
            showcase['corner_token_mode'] = 'token_progress'
            showcase['conquest_key'] = 'ai_'+data['event_name']+extra_suffix+'_conquests'
            showcase['ui_final_reward_label'] = 'NEW:'
            showcase['plus_store_category'] = 'event_prizes'
            showcase['ui_subtitle'] = 'SPECIAL EVENT'
        else:
            if has_multiple_difficulties:
                showcase['ui_final_reward_label'] = '%s DIFFICULTY REWARDS:' % highest_difficulty.upper()
                showcase['ui_subtitle'] = '%s DIFFICULTY' % diff.upper()
            else:
                showcase['ui_final_reward_label'] = 'FINAL REWARDS:'
                showcase['ui_subtitle'] = 'SINGLE PLAYER'

        if final_loot_unit:
            showcase['final_reward_unit'] = final_loot_unit
            showcase["ui_final_reward_title_bbcode"] = "[color=#ffff08]%s[/color]" % gamedata['units'][final_loot_unit]['ui_name']
            showcase["ui_final_reward_subtitle_bbcode"] = gamedata['units'][final_loot_unit]['ui_tip']

            if final_loot_unit_substitute_items: # show these items only if you already have obtained the unit
                already_obtained_unit_predicate = {"predicate": "OR", "subpredicates": [{"predicate": "LIBRARY", "name": final_loot_unit+"_unlocked"},
                                                                                        {"predicate": "HAS_ITEM", "item_name": final_loot_unit+"_blueprint"}]}
                showcase["final_reward_items"] = [[already_obtained_unit_predicate, final_loot_unit_substitute_items],
                                                  [{"predicate": "ALWAYS_TRUE"}, []]]
                showcase["ui_final_reward_title_bbcode"] = [[already_obtained_unit_predicate, showcase["ui_final_reward_title_bbcode"] + " [color=#ffffff]BONUS PACK[/color]"],
                                                            [{"predicate": "ALWAYS_TRUE"}, showcase["ui_final_reward_title_bbcode"]]]
                showcase["ui_final_reward_subtitle_bbcode"] = [[already_obtained_unit_predicate, "Epic special items"],
                                                               [{"predicate": "ALWAYS_TRUE"}, showcase["ui_final_reward_subtitle_bbcode"]]]

        if final_loot_item_list:
            # since final_loot_item_list may be a single list or a list of lists due to having different loot on later runs,
            # we need a special case to handle this as make_per_run_cond_chain will just assume the single list is a set of
            # items that drop across multiple runs
            if len(final_loot_item_list) > 0 and isinstance(final_loot_item_list[0], list):
                showcase['final_reward_items'] = make_per_run_cond_chain(data, lambda i, start_time, end_time: final_loot_item_list[i])
            else:
                showcase['final_reward_items'] = final_loot_item_list

            final_reward_items_title = data['showcase'].get('final_reward_items_title', None)
            if isinstance(final_reward_items_title, list):
                showcase['ui_final_reward_title_bbcode'] = make_per_run_cond_chain(data, lambda i, start_time, end_time: get_for_difficulty(final_reward_items_title[i], diff))
            else:
                showcase['ui_final_reward_title_bbcode'] = get_for_difficulty(final_reward_items_title, diff)

            final_reward_items_subtitle = data['showcase'].get('final_reward_items_subtitle', None)
            if isinstance(final_reward_items_subtitle, list):
                showcase['ui_final_reward_subtitle_bbcode'] = make_per_run_cond_chain(data, lambda i, start_time, end_time: get_for_difficulty(final_reward_items_subtitle[i], diff))
            else:
                showcase['ui_final_reward_subtitle_bbcode'] = get_for_difficulty(final_reward_items_subtitle, diff)
        elif final_loot_item_set:
            showcase['final_reward_items'] = [{'spec':name} for name in gamedata['item_sets'][final_loot_item_set]['members']]
            showcase['ui_final_reward_title_bbcode'] = "[color=#ffff08]%s[/color]" % gamedata['item_sets'][final_loot_item_set]['ui_name']
            showcase['ui_final_reward_subtitle_bbcode'] = gamedata['item_sets'][final_loot_item_set].get('ui_description', None)

        # allow manual overrides of the final reward text
        for FIELD in ('ui_final_reward_title_bbcode', 'ui_final_reward_subtitle_bbcode', 'ui_plus_bbcode'):
            if FIELD in data['showcase']:
                showcase[FIELD] = data['showcase'][FIELD]

        if len(random_loot_phases) > 0:
            # predicate that is true if you are past level "lev"
            def past_level(lev): return {"predicate": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+suffix+"_progress_now", "method": ">=", "value": lev}
            showcase["ui_random_rewards_text"] = []
            showcase["feature_random_items"] = []
            showcase["feature_random_item_count"] = []

            for phase_num in xrange(len(random_loot_phases)-1, -1, -1):
                # start at the highest phase and go down
                pred = past_level(random_loot_phases[phase_num-1]['ends_at']) if phase_num > 0 else {'predicate': 'ALWAYS_TRUE'}
                ui_text = "RANDOM REWARDS TO WIN"
                if len(random_loot_phases) > 1:
                    ui_text += " (%s DIFFICULTY)" % (random_loot_phases[phase_num]['ui_name'].upper())
                ui_text += ":"
                showcase["ui_random_rewards_text"].append([pred, ui_text])
                showcase["feature_random_items"].append([pred, random_loot_phases[phase_num]['items']])
                showcase["feature_random_item_count"].append([pred, random_loot_phases[phase_num]['show_max_items']])

        showcase_cons = { "consequent": "DISPLAY_MESSAGE", "dialog": "showcase",
                          "event_countdown_hack": { "enable": 1,
                                                    "reset_origin_time": data['reset_origin_time'],
                                                    "reset_interval": data['reset_interval'] },
                          "showcase_hack": showcase }
        atom.fd.write('"ai_%s%s_showcase": ' % (data['event_name'], data['key_suffix'][diff]))
        if WRAP_IN_ABTEST:
            showcase_cons = { "consequent": "IF", "if": {"predicate": "ANY_ABTEST", "key": "enable_showcase", "value": 1},
                              "then": showcase_cons }
        dump_json_toplevel(showcase_cons, fd = atom.fd)
        atom.fd.write(',\n\n')

        # MILESTONE_SHOWCASE
        # make the "milestone" version of the showcase (shown after completing a difficulty tier) - delete random items, add VICTORY text, big progress bar, and optional progression instructions
        atom.fd.write('"ai_%s%s_milestone_showcase": ' % (data['event_name'], data['key_suffix'][diff]))
        milestone_showcase = copy.deepcopy(showcase)
        for FIELD in ('corner_token_mode','feature_random_items','feature_random_item_count','final_reward_unit','final_reward_items',
                      'ui_final_reward_label','ui_final_reward_subtitle_bbcode','ui_final_reward_title_bbcode','ui_random_rewards_text'):
            if FIELD in milestone_showcase: del milestone_showcase[FIELD]
        if data['showcase'].get('progression_reward_items',False):
            milestone_showcase['ui_progression_text'] = progression_text
        if has_tokens:
            milestone_showcase['show_plus_text'] = 0 # disable SALE/PLUS text
        milestone_showcase['victory'] = 1
        milestone_showcase['ui_victory_subtitle'] = []
        milestone_showcase['show_progress_bar'] = 'large'
        if len(random_loot_phases) > 0:
            for phase_num in xrange(len(random_loot_phases)-1, -1, -1):
                # start at the highest phase and go down
                if phase_num > 0:
                    pred = {"predicate": "PLAYER_HISTORY", "key": milestone_showcase['progress_key'], "method": ">=", "value": random_loot_phases[phase_num]['ends_at']}
                else:
                    pred = {'predicate': 'ALWAYS_TRUE'}
                ui_text = "%s DIFFICULTY CONQUERED" % random_loot_phases[phase_num]['ui_name'].upper()
                milestone_showcase["ui_victory_subtitle"].append([pred, ui_text])

        milestone_showcase_cons = { "consequent": "DISPLAY_MESSAGE", "dialog": "showcase",
                                    "event_countdown_hack": { "enable": 1,
                                                              "reset_origin_time": data['reset_origin_time'],
                                                              "reset_interval": data['reset_interval'] },
                                    "showcase_hack": milestone_showcase }
        if WRAP_IN_ABTEST:
            milestone_showcase_cons = { "consequent": "IF", "if": {"predicate": "ANY_ABTEST", "key": "enable_showcase", "value": 1},
                                        "then": milestone_showcase_cons }
        dump_json_toplevel(milestone_showcase_cons, fd = atom.fd)
        atom.fd.write(',\n\n')

        # VICTORY_SHOWCASE
        # make "victory" version - delete random items, add VICTORY text
        atom.fd.write('"ai_%s%s_victory_showcase": ' % (data['event_name'], data['key_suffix'][diff]))
        victory_showcase = copy.deepcopy(showcase)
        for FIELD in ('ui_random_rewards_text','feature_random_items','feature_random_item_count','corner_token_mode'):
            if FIELD in victory_showcase: del victory_showcase[FIELD]
        victory_showcase['victory'] = 1
        if has_tokens:
            victory_showcase['corner_token_mode'] = 'token_gettothemap'
            victory_showcase['ui_victory_subtitle'] = 'Now get to the map!'
        else:
            victory_showcase['ui_victory_subtitle'] = 'Check your Warehouse for rewards!'

        victory_showcase_cons = { "consequent": "DISPLAY_MESSAGE", "dialog": "showcase",
                                  "event_countdown_hack": { "enable": 1, "ui_title": "YOUR OPPONENT IS:", "ui_value": "NETURALIZED" },
                                  "showcase_hack": victory_showcase }
        if WRAP_IN_ABTEST:
            victory_showcase_cons = { "consequent": "IF", "if": {"predicate": "ANY_ABTEST", "key": "enable_showcase", "value": 1},
                                      "then": victory_showcase_cons }
        dump_json_toplevel(victory_showcase_cons, fd = atom.fd)
        atom.fd.write(',\n\n')

        # LOGIN_SHOWCASE
        # make "login" version - delete random items, add NEW THIS WEEK text
        # note: this adds the extra_key_suffix to the consequent name since the tip name should be changed for each event release
        tip_name = 'ai_%s%s%s_login_showcase' % (data['event_name'], data['key_suffix'][diff], data['extra_key_suffix'][diff])
        atom.fd.write('"%s": ' % tip_name)
        login_showcase = copy.deepcopy(showcase)
        for FIELD in ('ui_random_rewards_text','feature_random_items','feature_random_item_count','corner_token_mode'):
            if FIELD in login_showcase: del login_showcase[FIELD]
        if has_tokens:
            login_showcase['corner_token_mode'] = 'token_login'
        else:
            login_showcase['corner_ai_asset'] = data['villain_attack_portrait'].replace('attack_portrait', 'console')
        def make_login_header_text(i, start_time, end_time):
            if start_time > 0:
                return '[color=#ffff00]NEW:[/color] [absolute_time=%s]' % start_time
            else:
                return None
        login_showcase['ui_login_header_bbcode'] = make_per_run_cond_chain(data, make_login_header_text)
        login_showcase['ui_login_title_bbcode'] = '[color=#dd00dd][b]Return of %s[/b][/color]' % data['event_ui_name'].upper()

        # construct the text on the login dialog
        if has_tokens:
            login_showcase['ui_login_body_bbcode'] = '[color=#ffff00]Earn [color=#ffffff]%%TOKEN[/color] by fighting [color=#ffffff]%s[/color] to buy ' % data['event_ui_name'].upper()
        else:
            login_showcase['ui_login_body_bbcode'] = '[color=#ffff00]Win '

        if final_loot_item_list:
            # just use SPECIAL LOOT here since it's hard to determine which item we should be showing from a list of items
            login_showcase['ui_login_body_bbcode'] += '[color=#ffffff]SPECIAL LOOT[/color]'
        elif final_loot_item_set:
            login_showcase['ui_login_body_bbcode'] += '[color=#ffffff]%s[/color]' % gamedata['item_sets'][final_loot_item_set]['ui_name'].upper()
        elif final_loot_unit:
            login_showcase['ui_login_body_bbcode'] += 'the [color=#ffffff]%s[/color] unit' % gamedata['units'][final_loot_unit]['ui_name'].upper()
        else:
            # one of the above cases must be true because we checked that earlier
            pass

        if has_tokens:
            login_showcase['ui_login_body_bbcode'] += '.'
        else:
            login_showcase['ui_login_body_bbcode'] += ' by fighting [color=#ffffff]%s[/color] from the [color=#ffffff]ATTACK[/color] menu.' % data['event_ui_name'].upper()

        login_showcase['ui_login_body_bbcode'] += '\n\nClick [color=#ffffff]FIGHT NOW[/color] to start immediately.'

        login_showcase['ui_ok_button'] = 'Fight Now'
        login_showcase['ok_button_consequent'] = { "consequent": "AND", "subconsequents":
                                                   [{"consequent": "DAILY_TIP_UNDERSTOOD", "name_from_context": "daily_tip"}] + [make_fight_now_consequent(data, has_tokens)] }
        login_showcase_cons = { "consequent": "DISPLAY_MESSAGE", "dialog": "showcase",
                                "event_countdown_hack": { "enable": 1,
                                                          "reset_origin_time": data['reset_origin_time'],
                                                          "reset_interval": data['reset_interval'] },
                                "showcase_hack": login_showcase }
        if WRAP_IN_ABTEST:
            login_showcase_cons = { "consequent": "IF", "if": {"predicate": "ANY_ABTEST", "key": "enable_showcase", "value": 1},
                                    "then": login_showcase_cons }
        dump_json_toplevel(login_showcase_cons, fd = atom.fd)

        # build progression loot variants
        if data['showcase'].get('progression_reward_items',False):

            atom.fd.write(',\n\n')
            progression_reward_items = get_progression_reward_items(data['loot'][diff],
                                                                    data['showcase'].get('include_resource_boosts_in_progression', False),
                                                                    data['showcase'].get('include_random_loot_in_progression', False))

            # PROGRESSION_INTRO_SHOWCASE
            # shows progression reward items PLUS final reward items and corner_token instruction (shown at the first level)
            atom.fd.write('"ai_%s%s_progression_intro_showcase": ' % (data['event_name'], data['key_suffix'][diff]))
            intro_showcase = copy.deepcopy(showcase)
            for FIELD in ('show_progress_bar', 'feature_random_item_count', 'feature_random_items'):
                if FIELD in intro_showcase: del intro_showcase[FIELD]

            if has_tokens:
                intro_showcase['corner_token_mode'] = 'token_login'
            else:
                intro_showcase['corner_ai_asset'] = data['villain_attack_portrait'].replace('attack_portrait', 'console')

            intro_showcase['progression_reward_items'] = progression_reward_items
            intro_showcase['ui_random_rewards_text'] = progression_title

            intro_showcase_cons = { "consequent": "DISPLAY_MESSAGE", "dialog": "showcase",
                                    "event_countdown_hack": { "enable": 1,
                                                              "reset_origin_time": data['reset_origin_time'],
                                                              "reset_interval": data['reset_interval'] },
                                    "showcase_hack": intro_showcase }
            if WRAP_IN_ABTEST:
                intro_showcase_cons = { "consequent": "IF", "if": {"predicate": "ANY_ABTEST", "key": "enable_showcase", "value": 1},
                                          "then": intro_showcase_cons }
            dump_json_toplevel(intro_showcase_cons, fd = atom.fd)
            atom.fd.write(',\n\n')

            # PROGRESSION_SHOWCASE
            # shows progression reward items WITHOUT final reward items PLUS big progress bar and progression instructions
            atom.fd.write('"ai_%s%s_progression_showcase": ' % (data['event_name'], data['key_suffix'][diff]))
            progression_showcase = copy.deepcopy(showcase)
            for FIELD in ('corner_token_mode','feature_random_items','feature_random_item_count','final_reward_unit','final_reward_items',
                          'ui_final_reward_label','ui_final_reward_subtitle_bbcode','ui_final_reward_title_bbcode'):
                if FIELD in progression_showcase: del progression_showcase[FIELD]
            if has_tokens:
                progression_showcase['show_plus_text'] = 0 # disable SALE/PLUS text
            progression_showcase['progression_reward_items'] = progression_reward_items
            progression_showcase['ui_progression_text'] = progression_text
            progression_showcase['ui_random_rewards_text'] = progression_title
            progression_showcase['show_progress_bar'] = 'large'

            progression_showcase_cons = { "consequent": "DISPLAY_MESSAGE", "dialog": "showcase",
                                          "event_countdown_hack": { "enable": 1,
                                                                    "reset_origin_time": data['reset_origin_time'],
                                                                    "reset_interval": data['reset_interval'] },
                                          "notification_params": { "priority": -15 }, # reduce priority so that this appears after loot dialogs
                                          "showcase_hack": progression_showcase }
            if WRAP_IN_ABTEST:
                progression_showcase_cons = { "consequent": "IF", "if": {"predicate": "ANY_ABTEST", "key": "enable_showcase", "value": 1},
                                          "then": progression_showcase_cons }
            dump_json_toplevel(progression_showcase_cons, fd = atom.fd)

        if diff != data['difficulties'][-1]:
            atom.fd.write(',')
        atom.fd.write('\n')

# returns a list of player history keys for an event that will be used for the achievement counter in the showcase dialog
def generate_achievement_keys(data, has_tokens):
    achievement_keys = []

    for diff in data['difficulties']:
        suffix = data['key_suffix'][diff]
        extra_suffix = data.get('extra_key_suffix',{}).get(diff,None)

        # note that these may be duplicated if multiple difficulties share the same suffix or extra suffix
        achievement_keys += ["ai_"+data['event_name']+suffix+"_progress"] + (["ai_"+data['event_name']+extra_suffix+"_progress"] if extra_suffix else [])
        if has_tokens:
            achievement_keys += ["ai_"+data['event_name']+suffix+"_conquests"] + (["ai_"+data['event_name']+extra_suffix+"_conquests"] if extra_suffix else [])

        if diff in data.get('speedrun_time', {}):
            achievement_keys += ["ai_"+data['event_name']+suffix+"_speedrun"]

    # eliminate any duplicates that may have come up due to multiple difficulties sharing the same extra suffix
    return list(set(achievement_keys))

# return a consequent for the "Fight Now" button on the event login announcement
def make_fight_now_consequent(data, has_tokens):
    ret = { "consequent": "COND", "cond": []}
    for diff in data['difficulties']:
        suffix = data['key_suffix'][diff]
        for i in xrange(0, data['bases_per_difficulty']):
            base_id = data['starting_base_id'] + i
            if 'skip' in data and data['skip'][diff][i]:
                continue
            kind = (data['kind'][i] if ('kind' in data) else 'ai_base')
            ret['cond'].append([{"predicate": "AI_BASE_ACTIVE", "user_id": base_id},
                                {"consequent": "START_AI_ATTACK", "attack_id": base_id} if kind == 'ai_attack' else \
                                {"consequent": "VISIT_BASE", "user_id": base_id}])

    if has_tokens:
        ret['cond'].append([{"predicate": "AND", "subpredicates":[{"predicate": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+suffix+"_progress_now",
                                                                   "method": ">=", "value": data['bases_per_difficulty']},
                                                                  {"predicate": "LIBRARY", "name": data['event_name']+'_map_bases_unlocked'}]},
                    # go to map (or show instructions to relocate base)
                    {"consequent": "IF", "if": {"predicate": "LIBRARY", "name": "in_nosql_region"},
                     "then": {"consequent": "AND", "subconsequents": [
                         {"consequent": "INVOKE_MAP_DIALOG", "chapter": "quarries" }, # show Regional Map
                         {"consequent": "IF", # show arrow to Hive Finder if player has not used it before
                          "if": {"predicate": "PLAYER_HISTORY", "key": "feature_used:hive_finder_used", "method": "<", "value":1},
                          "then": {"consequent": "TUTORIAL_ARROW", "child":1, "arrow_type": "button", "direction": "down", "dialog_name": "region_map_dialog", "widget_name": "hive_finder"}}
                         ]},
                     "else": {"consequent": "AND", "subconsequents": [
                         {"consequent": "INVOKE_MAP_DIALOG", "chapter": "rivals" },
                         {"consequent": "MESSAGE_BOX", "child":1, "y_position": 0.10, "widgets": { "description": {
                             "ui_name": "Relocate your base to battle %s on the Map and win more rewards." % data['villain_ui_name']
                         } } },
                         {"consequent": "TUTORIAL_ARROW", "child":1, "arrow_type": "button", "direction": "up", "dialog_name": "map_ladder_pvp_dialog", "widget_name": "relocate_button"}]}}
                    ])

    # final fallback: single player list
    ret['cond'].append([{"predicate":"ALWAYS_TRUE"}, {"consequent": "INVOKE_MAP_DIALOG", "chapter": "computers" }])
    return ret

# returns a sample of what loot will drop a given level of an event
def get_loot_sample(loot_table, randgen, extra_test = None):
    def loot_pred_resolver(pred, extra_test):
        if extra_test and extra_test(pred): return True
        if pred['predicate'] == 'ALWAYS_TRUE': return True
        if pred['predicate'] == 'NOT':
            return not loot_pred_resolver(pred['subpredicates'][0], extra_test)
        if pred['predicate'] == 'OR':
            for sub in pred['subpredicates']:
                if loot_pred_resolver(sub, extra_test):
                    return True
        return False

    return LootTable.get_loot(gamedata['loot_tables'], [loot_table], rand_func = randgen.random, cond_resolver = lambda pred, _extra = extra_test: loot_pred_resolver(pred, _extra))

# report token events that use different loot/richness for reruns and immortals that have the same richness for reruns
def check_one_time_loot(event_name, data):
    randgen = random.Random(1234)

    if 'loot' in data:
        def is_token_event(data):
            for difficulty in data['difficulties']:
                if diff in data['loot']:
                    for item in get_loot_sample(data['loot'][diff][-1], randgen):
                        if item['spec'] == 'token':
                            return True
            return False

        if is_token_event(data):
            if 'loot_once_only' in data:
                print >> sys.stderr, 'warning: token event %s drops reduced loot on repeated playthroughs. Remove loot_only_once and fold into regular loot.' % event_name
            if data.get('base_richness_on_replay', 1) != 1:
                print >> sys.stderr, 'warning: token event %s drops reduced resources on repeated playthroughs. Remove base_richness_on_replay.' % event_name
        else:
            if data.get('base_richness_on_replay', 1) != 1:
                print >> sys.stderr, 'warning: immortal event %s drops reduced resources on repeated playthroughs. Remove base_richness_on_replay.' % event_name

# given the array of loot tables for an event difficulty (one per level),
# return a list of the special progression reward items, suitable for including in showcase['progression_reward_items']
def get_progression_reward_items(loot, include_resource_boosts, include_random_loot):
    # Returns a loot table transformed so that it contains notable loot drops at each level of progression. This involves
    # expanding loot table references into a list of items and removing loot considered boring (eg resources or random drops).
    def filter_progression_loot(loot):
        if not loot or 'nothing' in loot:
            return None
        elif 'spec' in loot:
            # this level drops an item so filter out any tokens or resource boosts
            if loot['spec'] == 'token':
                return None
            elif any(loot['spec'].startswith('boost_%s_' % resource) for resource in gamedata['resources']):
                if not include_resource_boosts:
                    return None
                else:
                    return loot
            else:
                return loot
        elif isinstance(loot, list):
            # this level drops one of many things so filter all of them
            new_loot = []

            for entry in loot:
                new_entry = filter_progression_loot(entry)

                if new_entry:
                    new_loot.append(new_entry)

            if len(new_loot) == 1:
                return new_loot[0]
            else:
                return new_loot
        elif 'multi' in loot:
            # this level drops multiple things so filter all of them
            new_loot = []

            for entry in loot['multi']:
                new_entry = filter_progression_loot(entry)

                if new_entry:
                    new_loot.append(new_entry)

            if new_loot:
                if len(new_loot) > 1:
                    return {'multi': new_loot}
                else:
                    return new_loot[0]
            else:
                return None
        elif 'table' in loot:
            # this level contains drops from a loot table that we need to expand
            table_name = loot['table']

            if not table_name.startswith('event_loot_'):
                return filter_progression_loot(gamedata['loot_tables'][table_name]['loot'])
            else:
                # only include guarenteed random loot drops (event_loot_*_item) if specified in the skeleton
                if include_random_loot and table_name.endswith('_item'):
                    return {'spec': 'random_loot'}
                else:
                    return None
        elif 'cond' in loot:
            # still return a conditional so that players see the correct loot for themselves
            return {'cond': [(pred, filter_progression_loot(value)) for pred, value in loot['cond']]}
        else:
            raise Exception('error: invalid loot %s' % loot)

    ret = []

    for i in xrange(len(loot)):
        level = i + 1

        filtered_loot = filter_progression_loot(loot[i])
        if filtered_loot:
            ret.append({'level': level, 'loot': filtered_loot})

    return ret

# make a cond chain with a value customized to each rergun segment of a multi-segment event.
# make_value is a function that is given the (index, start_time, end_time) for the segment and returns the customized value
def make_per_run_cond_chain(data, make_value):
    if 'show_times' in data:
        show_times = data['show_times']
    else:
        show_times = [[data.get('reveal_time', -1), data.get('hide_time', -1)]]

    if len(show_times) == 1:
        return make_value(0, show_times[0][0], show_times[0][1])
    else:
        return [[{"predicate": "ABSOLUTE_TIME", "range": [t[0], t[1]]}, make_value(i, t[0], t[1])] for i, t in enumerate(show_times)]

if __name__ == '__main__':
    print_auto_gen_warning()

    separate_files = True # changed to default 2013 Aug 21
    base_filename_convention = 'new'
    base_file_dir = None
    game_id = SpinConfig.game()

    opts, args = getopt.gnu_getopt(sys.argv, 'g:', ['separate-files','base-filename-convention='])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '--separate-files': separate_files = True
        elif key == '--base-filename-convention': base_filename_convention = val

    # manually load some parts of gamedata. Do not require ALL of it, in order to avoid a chicken-and-egg dependency cycle.
    gamedata_main_options = SpinConfig.load(SpinConfig.gamedata_component_filename('main_options.json', override_game_id = game_id), stripped = True, override_game_id = game_id)
    gamedata = {'townhall': gamedata_main_options['townhall']}
    gamedata['resources'] = SpinConfig.load(SpinConfig.gamedata_component_filename('resources.json', override_game_id = game_id), override_game_id = game_id)
    gamedata['units'] = SpinConfig.load(SpinConfig.gamedata_component_filename('units.json', override_game_id = game_id), override_game_id = game_id)
    gamedata['item_sets'] = SpinConfig.load(SpinConfig.gamedata_component_filename('item_sets.json', override_game_id = game_id), override_game_id = game_id)
    gamedata['loot_tables'] = SpinConfig.load(SpinConfig.gamedata_component_filename('loot_tables.json', override_game_id = game_id), override_game_id = game_id)
    gamedata['matchmaking'] = SpinConfig.load(SpinConfig.gamedata_component_filename('matchmaking.json', override_game_id = game_id), override_game_id = game_id)
    gamedata['achievements'] = SpinConfig.load(SpinConfig.gamedata_component_filename('achievements.json', override_game_id = game_id), override_game_id = game_id)

    if args[1] in event_data: # event data hard-coded in this file
        data = event_data[args[1]]
    else: # look for .skel file
        skeleton_filename = args[1] # '%s/%s_ai_bases_%s.skel' % (game_id, game_id, event_name)
        try:
            data_buf = open(skeleton_filename).read()
        except:
            raise Exception('skeleton file not found: %s' % skeleton_filename)
        data = eval(data_buf)

    event_dirname = data.get('event_dirname', data['event_name'])

    auto_cutscenes = None

    # create loot showcase
    if 'showcase' in data:
        generate_showcase_consequent(game_id, event_dirname, data)

        # automatically add showcase cutscenes, if necessary
        if data['showcase'].get('automatic_showcase_cutscenes', False):
            auto_cutscenes = dict((diff, [[] for _ in xrange(data['bases_per_difficulty'])]) for diff in data['difficulties'])

            for diff in data['difficulties']:
                if 'skip' in data:
                    skip = data['skip'][diff]
                else:
                    skip = [0,] * data['bases_per_difficulty']

                level_map = [] # map from "original" progression index to skipped progression index (many-to-one)
                unskipped_count = 0
                first_unskipped = -1
                last_unskipped = -1
                for i in xrange(data['bases_per_difficulty']):
                    level_map.append(unskipped_count)
                    if not skip[i]:
                        last_unskipped = unskipped_count
                        if first_unskipped < 0:
                            first_unskipped = unskipped_count
                        unskipped_count += 1

                # add progression_intro showcase on first level and victory showcase on final level
                if data['showcase'].get('progression_reward_items',False):
                    auto_cutscenes[diff][first_unskipped].append({'speaker': 'progression_intro_showcase'})
                auto_cutscenes[diff][last_unskipped].append({'speaker': 'victory_showcase'})

                # add milestone showcases at the end of each progression phase (and before progress screens)
                # note that this uses the "fake" progression loot phases listed in the "showcase", NOT the true skeleton "difficulty" phases
                for phase in data['showcase'].get('progression_loot_phases', []):
                    if phase['ends_at'] < last_unskipped + 1:
                        auto_cutscenes[diff][level_map[phase['ends_at'] - 1]].append({'speaker': 'milestone_showcase'})

                # add progression showcases before and after major loot drops
                if data['showcase'].get('progression_reward_items',False):
                    progression_reward_items = get_progression_reward_items(data['loot'][diff],
                                                                            data['showcase'].get('include_resource_boosts_in_progression', False),
                                                                            data['showcase'].get('include_random_loot_in_progression', False))
                    for reward in progression_reward_items:
                        level = reward['level'] - 1

                        if unskipped_count > 8 and level > 1: # level before the loot drop, but only if difficulty has >8 levels
                            auto_cutscenes[diff][level_map[level - 1]].append({'speaker': 'progression_showcase'})
                        if level > 0 and level < last_unskipped: # level after the loot drop, if it's not the very last progression level of the event
                            auto_cutscenes[diff][level_map[level]].append({'speaker': 'progression_showcase'})

                # add intermediate showcase screens
                for i in xrange(data['bases_per_difficulty'] - 4):
                    # if there's a series of 5 levels without showcases in a row, add one to the 3rd level
                    if not auto_cutscenes[diff][level_map[i]] and len([x for x in xrange(5) if auto_cutscenes[diff][level_map[i + x]]]) == 0:
                        auto_cutscenes[diff][level_map[i + 2]].append({'speaker': 'showcase'})

    # create skeleton JSON header
    if separate_files:
        # make directory for base files
        test_file = '%s/%s_ai_bases.json' % (game_id, game_id)
        if not os.path.exists(test_file):
            print '%s does not exist - make sure you are running this command in the gamedata/ directory' % test_file
            sys.exit(1)

        base_file_dir = '%s/%s_ai_bases_%s' % (game_id, game_id, event_dirname)
        if not os.path.exists(base_file_dir):
            sys.stderr.write('creating directory %s\n' % base_file_dir)
            os.mkdir(base_file_dir)

    base_id = data['starting_base_id']
    for diff in data['difficulties']:
        print "// %s difficulty" % diff.upper()
        for i in xrange(data['bases_per_difficulty']):
            print "// %d Base %d" % (base_id, i+1)
            base_id += 1
        print "// %d Placeholder for reset" % base_id
        base_id += 1
        print

    # predicate for time-based showing/hiding of the AI
    if 'show_times' in data:
        time_pred = { "predicate": "OR", "subpredicates": [ {"predicate": "ABSOLUTE_TIME", "range": [t[0],t[1]]} for t in data['show_times'] ] }
    elif ('reveal_time' in data) or ('hide_time' in data):
        time_pred = { "predicate": "ABSOLUTE_TIME", "range": [data.get('reveal_time',-1),data.get('hide_time',-1)] }
    else:
        time_pred = None


    base_id = data['starting_base_id']

    # total index among unskipped bases across all difficulties
    overall_unskipped_count = 0

    # total number of unskipped bases across all difficulties
    overall_num_unskipped_bases = 0
    for diff in data['difficulties']:
        if 'skip' in data:
            skip = data['skip'][diff]
            overall_num_unskipped_bases += data['bases_per_difficulty'] - sum(skip) # total number of unskipped bases this difficulty
        else:
            overall_num_unskipped_bases += data['bases_per_difficulty']


    for diff in data['difficulties']:
        instance_cdname = "ai_"+data['event_name']+data['key_suffix'][diff]+"_instance"

        if diff in data['speedrun_time']:
            speedrun_aura = data['event_name'] + data['key_suffix'][diff] + '_speedrun_contender'
        else:
            speedrun_aura = None

        def make_ui_priority_for_time(i, start_time, end_time):
            priority = data['map_ui_priority'][diff]
            default_priority = {'mf':300}.get(game_id,100)
            if priority != default_priority:
                raise Exception('event %s should have map_ui_priority = %d' % (data['event_name'], default_priority))

            if start_time > 0: # append the starting week number as a fractional part to the ui_priority so the "freshest" event wins ties.
                priority += 0.001 * SpinConfig.get_pvp_week(gamedata['matchmaking']['week_origin'], start_time)

            if len(data['difficulties']) > 1:
                # ensure difficulties appear in correct order
                priority += 0.0001*(1 - 0.1*data['difficulties'].index(diff))

            return priority
        ui_priority = make_per_run_cond_chain(data, make_ui_priority_for_time)

        unskipped_count = 0 # index of this base within the difficulty level, not counting skipped previous bases
        if 'skip' in data:
            skip = data['skip'][diff]
            num_unskipped_bases = data['bases_per_difficulty'] - sum(skip) # total number of unskipped bases this difficulty
        else:
            num_unskipped_bases = data['bases_per_difficulty']

        for i in xrange(data['bases_per_difficulty']):
            skip = ('skip' in data) and data['skip'][diff][i]
            is_first_base = unskipped_count == 0

            ui_map_name = data['event_ui_name'] + (" (%s)" % diff if len(data['difficulties']) > 1 else '')

            print '''
////////////////////////////////////////////////////////////
//
// %s - [%s] - Stage %d
//
////////////////////////////////////////////////////////////
''' % \
            (data['event_ui_name'], diff.upper(), i+1)

            print '"%d": {' % base_id

            json = []

            kind = (data['kind'][i] if ('kind' in data) else 'ai_base')
            assert kind in ('ai_base', 'ai_attack')

            json += [("kind", kind)]

            json += [
                ("ui_name", data['villain_ui_name']),
                ("ui_map_name", ui_map_name),
                ("ui_info", "%s%s%s\nBase %d of %d\nReward: %s%s" % \
                (data['event_ui_name'], (' (%s difficulty)' % diff if len(data['difficulties'])>1 else ''),
                 "\nAI Enemy: %s" % data['villain_ui_name'] if data['villain_ui_name'] != data['event_ui_name'] else '', unskipped_count+1, num_unskipped_bases,
                 data['final_reward_info'][diff], ('\n'+data['extra_ui_info']) if 'extra_ui_info' in data else '')),
                ("ui_progress", { # within difficulty
                                  "cur": unskipped_count, "max": num_unskipped_bases,
                                  # across all difficulties
                                  "overall_cur": overall_unskipped_count, "overall_max": overall_num_unskipped_bases }),
                ("ui_difficulty", diff),
                ("ui_priority", ui_priority),
                ("portrait", data['villain_portrait'][diff]),
                ("resources", { "player_level": data['starting_ai_level'][diff]+ i * data['ai_level_gain_per_base'],
                               "water": 0, "iron": 0 }),
                ]

            if 'villain_map_portrait' in data:
                json += [("map_portrait", data['villain_map_portrait'][diff])]

            if 'base_resource_loot' in data and data['base_resource_loot'][diff][i] is not None:
                json += [("base_resource_loot", data['base_resource_loot'][diff][i])]
                if 'base_richness' in data and data['base_richness'][diff][i] is not None:
                    raise Exception('you cannot use base_richness at the same time as base_resource_loot')
            else:
                assert data['base_richness'][diff][i] is not None
                rich = data['base_richness'][diff][i]
                if type(rich) not in (int, float):
                    raise Exception('base_richness value must be a number: %r' % rich)
                json += [("base_richness", data['base_richness'][diff][i])]

            json.append(('auto_level',1))

            for FIELD in ('ui_info_url', 'analytics_tag'):
                if FIELD in data: json.append((FIELD, data[FIELD]))

            if is_first_base:
                json += [("ui_resets", data['ui_resets'])]
            json += [("ui_instance_cooldown", instance_cdname)]

            abtest_pred = { "predicate": "ANY_ABTEST", "key": data['abtest'], "value": 1 } if ('abtest' in data) else None

            show_pred = {"predicate": "AND", "subpredicates": [ ] }
            if time_pred: show_pred['subpredicates'] += [ time_pred ]
            if abtest_pred: show_pred['subpredicates'] += [ abtest_pred ]

            if skip: show_pred['subpredicates'] += [{"predicate": "ALWAYS_FALSE"}]

            if is_first_base:
                # first base in series

                show_pred['subpredicates'] += [{ "predicate": "NOT", "subpredicates": [{"predicate": "COOLDOWN_ACTIVE", "name": instance_cdname}]}]

                if diff == 'Normal':
                    show_pred['subpredicates'] += [
                        { "predicate": "BUILDING_LEVEL", "building_type": gamedata['townhall'], "trigger_level": data['cc_level_to_see'][diff] },
                        ]
                elif diff == 'Heroic':
                    show_pred['subpredicates'] += [
                        { "predicate": "BUILDING_LEVEL", "building_type": gamedata['townhall'], "trigger_level": data['cc_level_to_see'][diff] }
                        ]
                elif diff == 'Epic':
                    show_pred['subpredicates'] += [
                        { "predicate": "BUILDING_LEVEL", "building_type": gamedata['townhall'], "trigger_level": data['cc_level_to_see'][diff] },
#                        { "predicate": "PLAYER_HISTORY", "ui_name": "Complete %s on Heroic difficulty" % data['event_ui_name'],
#                          "key": "ai_"+data['event_name']+"_heroic_progress", "method": ">=", "value": data['bases_per_difficulty'] },
                        ]
                else:
                    raise Exception('unhandled case')
            else:
                # not first base
                show_pred['subpredicates'] += [{ "predicate": "COOLDOWN_ACTIVE", "name": instance_cdname }]

                this_pred = {"predicate": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_progress_now", "method": "==", "value": i}

                # check if any previous bases leading up to this one were skipped
                skipped_progress = []
                if 'skip' in data:
                    for j in xrange(i-1,-1,-1):
                        if data['skip'][diff][j]:
                            skipped_progress.append(j)
                        else:
                            break

                if skipped_progress:
                    show_pred['subpredicates'] += [{"predicate": "OR", "subpredicates": [this_pred] + \
                                                    [{"predicate": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_progress_now", "method": "==", "value": j } for j in skipped_progress]
                                                    }]
                else:
                    show_pred['subpredicates'] += [this_pred]

            # activation predicate is more restrictive than show_if
            act_pred = copy.deepcopy(show_pred)

            if is_first_base:
                if diff == 'Normal':
                    act_pred['subpredicates'] += [
                        { "predicate": "BUILDING_LEVEL", "building_type": gamedata['townhall'], "trigger_level": data['cc_level_to_play'][diff] },
                        ]
                elif diff == 'Heroic':
                    act_pred['subpredicates'] += [
                        { "predicate": "BUILDING_LEVEL", "building_type": gamedata['townhall'], "trigger_level": data['cc_level_to_play'][diff] },
                        { "predicate": "PLAYER_HISTORY", "ui_name": "Complete %s on Normal difficulty" % data['event_ui_name'],
                          "key": "ai_"+data['event_name']+"_progress", "method": ">=", "value": data['bases_per_difficulty'] },
                        ]
                elif diff == 'Epic':
                    speedrun_key = "ai_%s_heroic_speedrun" % data['event_name']
                    speedrun_achievement_name = 'Heroic Blitz at %s' % data['event_ui_name']

                    # get the name of the speedrun achievement for display in the event's tooltip
                    for achievement in gamedata['achievements'].values():
                        # ignore nested achievement requirements since all existing speed run achievements have the speedrun key as the only requirement
                        goal = achievement.get('goal', {})
                        if goal.get('predicate', '') == 'PLAYER_HISTORY' and goal.get('key', '') == speedrun_key:
                            speedrun_achievement_name = achievement['ui_name']
                            break

                    act_pred['subpredicates'] += [
                        { "predicate": "BUILDING_LEVEL", "building_type": gamedata['townhall'], "trigger_level": data['cc_level_to_play'][diff] },
                        { "predicate": "PLAYER_HISTORY", "ui_name": "Earn the \""+speedrun_achievement_name+"\" achievement\nby completing Heroic difficulty in less than "+data['speedrun_ui_time']['Heroic'], "key": speedrun_key, "method": ">=", "value": 1 },
                        ]

            if kind == 'ai_attack':
                act_pred['subpredicates'] += [  { "predicate": "OBJECT_UNDAMAGED", "spec": gamedata['townhall'] } ]

            # optional extra lock predicate on bases
            # this can be either a list of AND'ed predicates, which applies to L1 only for each difficulty
            # or a list of list of AND'ed predicates, one per level
            extra_activation_pred = None
            if 'extra_activation_predicates' in data:
                assert diff in data['extra_activation_predicates']
                if type(data['extra_activation_predicates'][diff][0]) is dict:
                    # predicate applies to the first level only
                    if is_first_base:
                        extra_activation_pred = data['extra_activation_predicates'][diff]
                else:
                    # one predicate per base
                    extra_activation_pred = data['extra_activation_predicates'][diff][i]

            # make sure we got either None, or a list of predicates to be AND'ed
            assert (extra_activation_pred is None) or ((type(extra_activation_pred) is list) and (type(extra_activation_pred[0]) is dict))

            if extra_activation_pred:
                act_pred['subpredicates'] += extra_activation_pred

            if show_pred == act_pred:
                # skip show_if if it is identical to activation
                show_pred = None
            else:
                # remove duplications between show_if and activation
                if len(show_pred['subpredicates']) > 0:
                    dupes = []
                    for pred in act_pred['subpredicates']:
                        if pred in show_pred['subpredicates']:
                            dupes.append(pred)
                    if len(dupes) > 0:
                        act_pred['subpredicates'].insert(0, {"predicate": "AI_BASE_SHOWN", "user_id": base_id})
                        for dupe in dupes:
                            act_pred['subpredicates'].remove(dupe)

            if show_pred and len(show_pred['subpredicates']) > 0:
                json += [("show_if", show_pred)]

            assert len(act_pred['subpredicates']) > 0
            json += [("activation", act_pred)]

            # get cutscenes
            cutscenes = None
            if 'cutscenes' in data:
                if type(data['cutscenes']) is dict and (diff in data['cutscenes']):
                    cutscenes = data['cutscenes'][diff] # per-difficulty cutscenes
                else:
                    cutscenes = data['cutscenes'] # same cutscenes for each difficulty


            # get on_visit cutscene consequents
            on_visit_cutscene = None
            if cutscenes:
                on_visit_cutscene = cutscenes[i].get('on_visit', None)

            speaker_msg = []
            if on_visit_cutscene:
                speaker_num = 1
                for scene in on_visit_cutscene:
                    if scene['speaker'] == 'valentina':
                        picture = scene.get('inset_picture',None)
                        if not picture:
                            # if no special inset picture specified, use the generic Valentina dialog
                            msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "message_dialog_big", "ui_title": "Incoming Transmission",
                                  "tag": "%s_%d_visit_%d" % (data['event_name'], base_id, speaker_num), "frequency": "session",
                                  "notification_params": {"show_if_away":1,"priority":10},
                                  "ui_description": scene['text'] }
                        else:
                            msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "daily_tip",
                                  "tag": "%s_%d_visit_%d" % (data['event_name'], base_id, speaker_num), "frequency": "session",
                                  "notification_params": { "show_if_away": 1, "priority": 10 },
                                  "picture_asset": "valentina_cutscene_message_bg",
                                  "inset_picture": picture, "inset_picture_dimensions": [727,133],
                                  "understood_button_xy": [575,385], "understood_button_ui_name": "Proceed",
                                  "description_xy": [221,218], "description_dimensions": [500,150],
                                  "ui_description": scene['text'] }
                    elif scene['speaker'] == 'villain':
                        picture = scene.get('inset_picture',None)
                        if not picture:
                          msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "ai_base_conquer_message",
                              "tag": "%s_%d_visit_%d" % (data['event_name'], base_id, speaker_num), "frequency": "session",
                              "notification_params": {"show_if_away":1,"priority":10},
                              "picture": data['villain_attack_portrait'],
                              "ai_name": data['villain_ui_name'],
                              "ui_description":scene['text'] }
                        # To have an inset picture with the villain speaking, define the 'villain_message_picture_asset' in the scene (727,388).
                        else:
                          msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "daily_tip",
                                  "tag": "%s_%d_visit_%d" % (data['event_name'], base_id, speaker_num), "frequency": "session",
                                  "notification_params": {"show_if_away":1,"priority":10},
                                  "picture_asset": scene['villain_message_picture_asset'],
                                  "inset_picture": picture, "inset_picture_dimensions": [727,133],
                                  "understood_button_xy": [575,385], "understood_button_ui_name": "Proceed",
                                  "description_xy": [221,218], "description_dimensions": [500,150],
                                  "ui_description": scene['text'] }
                    #To call a promotional tip - Set the speaker to "event_countdown_hack" and call the 'message_picture_asset' from the cutscene.
                    elif scene['speaker'] == 'event_countdown_hack':
                        msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "daily_tip",
                                  "tag": "%s_%d_visit_%d" % (data['event_name'], base_id, speaker_num), "frequency": "session",
                                  "notification_params": {"show_if_away":1,"priority":10},
                                  "picture_asset": scene['message_picture_asset'],
                                  "understood_button_xy": [575,385], "understood_button_ui_name": "Understood",
                                  "event_countdown_hack": { "enable": 1, "reset_origin_time": data['reset_origin_time'], "reset_interval": data['reset_interval'], "xy": [440, 95], "dimensions": [341, 25], "text_size": 20}}
                    #To use a speaker other than the villain or valentina, then enter their attack portrait as the 'speaker' and their ui_name as 'speaker_ui_name'
                    else:
                        msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "ai_base_conquer_message",
                              "tag": "%s_%d_visit_%d" % (data['event_name'], base_id, speaker_num), "frequency": "session",
                              "notification_params": {"show_if_away":1,"priority":10},
                              "picture": scene['speaker'],
                              "ai_name": scene['speaker_ui_name'],
                              "ui_description": scene['text'] }
                        #raise Exception('unhandled case: %s' % scene['speaker'])

                    if 'show_if' in scene:
                        msg = { "consequent": "IF", "if": scene['show_if'], "then": msg }

                    speaker_msg.append(msg)

                    speaker_num += 1

            # set up on_visit consequents
            visit_pred = None
            if speaker_msg:
                if kind == 'ai_attack':
                    if len(speaker_msg) > 1:
                        raise Exception('on_visit for AI attacks must consist of only one DISPLAY_MESSAGE')
                    visit_pred = speaker_msg[0]
                else:
                    visit_pred = {"consequent": "AND", "subconsequents": speaker_msg}

            attack_pred = None
            trophy_pred = None

            # add "attempted" progress key
            attempt_pred = { "consequent": "AND", "subconsequents": [
                { "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_attempted", "method": "max", "value": i+1 },
                ] }
            if ('extra_key_suffix' in data):
                attempt_pred['subconsequents'] += [{ "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['extra_key_suffix'][diff]+"_attempted", "method": "max", "value": i+1 }]

            if kind == 'ai_base':
                if not visit_pred: visit_pred = attempt_pred
                else: visit_pred['subconsequents'] += [ attempt_pred ]
            else:
                if not attack_pred: attack_pred = attempt_pred
                else: attack_pred['subconsequents'] += [ attempt_pred ]

            if 'trophy_event' in data:
                trophy_pred = { "consequent": "APPLY_AURA",
                                "aura_name": "trophy_reward_pve_"+('home' if kind == 'ai_attack' else 'away'),
                                "stack": generic_data['trophies'][diff],
                                "stack_decay": "event", "stack_decay_min": generic_data['trophies'][diff],
                                "stack_decay_event_kind": "current_trophy_pve_challenge",
                                "stack_decay_event_name": data['trophy_event'] }

                if kind == 'ai_base':
                    # add bonus aura for this being the first attack on a fresh instance
                    trophy_pred = { "consequent": "AND", "subconsequents": [
                        trophy_pred,
                        { "consequent": "IF", "if": { "predicate": "AI_INSTANCE_GENERATION", "method": "<", "value": 1 },
                          "then": { "consequent": "APPLY_AURA",
                                    "aura_name": "trophy_reward_pve_"+('home' if kind == 'ai_attack' else 'away') + "_bonus",
                                    "stack": generic_data['trophies'][diff],
                                    "stack_decay": "event", "stack_decay_min": generic_data['trophies'][diff],
                                    "stack_decay_event_kind": "current_trophy_pve_challenge",
                                    "stack_decay_event_name": data['trophy_event'] }
                          }
                        ] }

                # for AI bases, the trophy setup code goes in on_visit, but for AI attacks, it goes in on_attack

                if kind == 'ai_base':
                    if not visit_pred: visit_pred = trophy_pred
                    else: visit_pred['subconsequents'] += [ trophy_pred ]
                else:
                    if not attack_pred: attack_pred = trophy_pred
                    else: attack_pred['subconsequents'] += [ trophy_pred ]

            if data.get('base_richness_on_replay',1) != 1:
                richness_pred = { "consequent": "IF",
                                  "if": {"predicate": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_progress", "method": "<", "value": i+1},
                                  "then": { "consequent": "APPLY_AURA",
                                            # note: apply a strength of 0 - this is for GUI display only, the base_richness is unchanged!
                                            "aura_name": kind+"_first_time_loot_bonus", "aura_strength": 0 },
                                  "else": { "consequent": "APPLY_AURA",
                                            # only affects AI bases, but show in GUI display for AI attacks
                                            "aura_name": kind+"_replay_loot_malus", "aura_strength": -(1-data['base_richness_on_replay']) } }
                if kind == 'ai_base':
                    if not visit_pred: visit_pred = richness_pred
                    else: visit_pred['subconsequents'] += [ richness_pred ]
                elif kind == 'ai_attack':
                    if not attack_pred: attack_pred = richness_pred
                    else: attack_pred['subconsequents'] += [ richness_pred ]

            if visit_pred:
                json += [("on_visit", visit_pred)]

            if kind == 'ai_attack' and attack_pred:
                json += [('on_attack', attack_pred)]

            completion = { "consequent": "AND", "subconsequents": [] }

            if 'loot_once_only' in data:
                loot = data['loot_once_only'][diff][i]
                if len(data['loot_once_only'][diff]) != data['bases_per_difficulty']:
                    raise Exception("ERROR! number of entries in loot_once_only table (%d) does not match bases_per_difficulty (%d)!" % (len(data['loot_once_only'][diff]), data['bases_per_difficulty']))

                if loot:
                    # must run this consequent BEFORE setting ai_x_progress
                    completion['subconsequents'] += [{"consequent": "IF",
                                                      "if": {"predicate": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_progress", "method": "<", "value": i+1},
                                                      "then": {"consequent": "GIVE_LOOT", "reason": kind, "loot": [loot] } }]

            # set progress history keys
            completion['subconsequents'] += [
                { "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_progress", "method": "max", "value": i+1 },
                { "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_progress_now", "method": "set", "value": i+1 }
                ]
            if ('extra_key_suffix' in data):
                completion['subconsequents'] += [{ "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['extra_key_suffix'][diff]+"_progress", "method": "max", "value": i+1 }]

            if is_first_base:
                completion['subconsequents'] += [
                    { "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_times_started", "method": "increment", "value": 1 },
                    { "consequent": "COOLDOWN_TRIGGER", "name": instance_cdname, "method": "periodic", "origin": data['reset_origin_time'], "period": data['reset_interval'] },
                    ]
                if ('extra_key_suffix' in data):
                    completion['subconsequents'] += [{ "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['extra_key_suffix'][diff]+"_times_started", "method": "increment", "value": 1 }]
                if speedrun_aura:
                    completion['subconsequents'] += [
                        { "consequent": "APPLY_AURA", "aura_name": speedrun_aura, "aura_duration": data['speedrun_time'][diff] },
                        ]

            elif i == (data['bases_per_difficulty']-1):
                completion['subconsequents'] += [
                    { "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_times_completed", "method": "increment", "value": 1 },
                    ]
                if ('extra_key_suffix' in data):
                    completion['subconsequents'] += [{ "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['extra_key_suffix'][diff]+"_times_completed", "method": "increment", "value": 1 }]

                if speedrun_aura:
                    if_i_win = [{ "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_speedrun", "method": "max", "value": 1 },
                                { "consequent": "REMOVE_AURA", "aura_name": speedrun_aura }]
                    if ('extra_key_suffix' in data):
                        if_i_win.append({ "consequent": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['extra_key_suffix'][diff]+"_speedrun", "method": "max", "value": 1 })
                    completion['subconsequents'] += [
                        { "consequent": "IF", "if": { "predicate": "AURA_ACTIVE", "aura_name": speedrun_aura },
                          # player DID complete the event in time
                          "then": {"consequent": "AND", "subconsequents": if_i_win}
                          }
                        ]

            loot_table = data.get('loot', generic_data['loot'])
            if len(loot_table[diff]) != data['bases_per_difficulty']:
                raise Exception("ERROR! number of entries in loot table (%d) does not match bases_per_difficulty (%d)!" % (len(loot_table), data['bases_per_difficulty']))

            loot = loot_table[diff][i]
            if loot:
                completion['subconsequents'] += [ { "consequent": "GIVE_LOOT", "reason": kind, "loot": [loot] } ]

            # get completion cutscene consequents
            completion_cutscene = []
            if cutscenes:
                completion_cutscene += cutscenes[i].get('completion', [])

            # append auto_cutscenes after any manually-defined cutscenes
            if auto_cutscenes:
                completion_cutscene += auto_cutscenes[diff][i]

            completion_msg = []
            if completion_cutscene:
                for scene in completion_cutscene:
                    picture = scene.get('inset_picture', None)
                    if scene['speaker'] == 'valentina':
                        # FINAL BASE
                        if i == (data['bases_per_difficulty']-1):
                            if diff == 'Normal' and ('Heroic' in data['difficulties']):
                                msg = {"consequent": "IF", "if": { "predicate":"PLAYER_HISTORY", "key": gamedata['townhall']+"_level", "method": ">=", "value": data['cc_level_to_play']['Heroic'] },
                                     "then": completion_valentina_message(picture = picture, text = scene['text'], extra = " - CAN PROCEED TO HEROIC"),
                                     "else": completion_valentina_message(picture = picture, text = scene['text'], extra = " - CANNOT PROCEED TO HEROIC YET")
                                     }
                            elif diff == 'Heroic' and ('Epic' in data['difficulties']):
                                msg = { "consequent": "IF", "if": { "predicate": "AND", "subpredicates": [
                                    { "predicate": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_speedrun", "method": ">=", "value": 1 },
                                    { "predicate": "PLAYER_HISTORY", "key": gamedata['townhall']+"_level", "method": ">=", "value": data['cc_level_to_play']['Epic'] } ] },
                                    "then": completion_valentina_message(picture = picture, text = scene['text'], extra = " - CAN PROCEED TO EPIC"),
                                    "else": completion_valentina_message(picture = picture, text = scene['text'], extra = " - CANNOT PROCEED TO EPIC YET")
                                   }
                            else:
                                # no special treatment
                                msg = completion_valentina_message(picture = picture, text = scene['text'])

                        else: # not a final base

                            if not picture:
                                # if no special inset picture specified, use the generic Valentina dialog
                                msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "message_dialog_big", "ui_title": "Incoming Transmission",
                                      "ui_description": scene['text'] }
                            else:
                                msg = completion_valentina_message(picture = picture, text = scene['text'])

                    elif scene['speaker'] == 'villain':
                        picture = scene.get('inset_picture',None)
                        if not picture:
                          msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "ai_base_conquer_message",
                              "picture": data['villain_attack_portrait'], "sound": "level_up_sound",
                              "ai_name": data['villain_ui_name'],
                              "ui_description": scene['text'] }
                        # To have an inset picture with the villain speaking, define the 'villain_message_picture_asset' in the scene (727,388).
                        else:
                          msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "daily_tip",
                                  "picture_asset": scene['villain_message_picture_asset'],
                                  "inset_picture": picture, "inset_picture_dimensions": [727,133],
                                  "understood_button_xy": [575,385], "understood_button_ui_name": "Proceed",
                                  "description_xy": [221,218], "description_dimensions": [500,150],
                                  "ui_description": scene['text'] }
                    #To call a promotional tip - Set the speaker to "event_countdown_hack" and call the 'message_picture_asset' from the cutscene.
                    elif scene['speaker'] == 'event_countdown_hack':
                        msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "daily_tip",
                                  "picture_asset": scene['message_picture_asset'],
                                  "understood_button_xy": [575,385], "understood_button_ui_name": "Understood",
                                  "event_countdown_hack": { "enable": 1, "reset_origin_time": data['reset_origin_time'], "reset_interval": data['reset_interval'], "xy": [440, 95], "dimensions": [341, 25], "text_size": 20}}

                    elif scene['speaker'].endswith('showcase'):
                        if i == (data['bases_per_difficulty']-1): # final base
                            showcase_kind = "victory_showcase"
                        else:
                            showcase_kind = scene['speaker']
                        msg = { "consequent": "LIBRARY", "name": "ai_"+data['event_name']+data['key_suffix'][diff]+"_"+showcase_kind }

                    #To use a speaker other than the villain or valentina, then enter their attack portrait as the 'speaker' and their ui_name as 'speaker_ui_name'
                    else:
                        msg = { "consequent": "DISPLAY_MESSAGE", "dialog": "ai_base_conquer_message",
                              "picture": scene['speaker'], "sound": "level_up_sound",
                              "ai_name": scene['speaker_ui_name'],
                              "ui_description": scene['text'] }
                        #raise Exception('unhandled case: %s' % speaker)

                    if 'show_if' in scene:
                        msg = { "consequent": "IF", "if": scene['show_if'], "then": msg }

                    completion_msg.append(msg)

            completion['subconsequents'] += completion_msg

            json += [("completion", completion)]

            if kind == 'ai_base':
                base = [("tech",{})]
                if 'base_climate' in data:
                    base += [("base_climate", data['base_climate'][i])]
                base += [("buildings", [{"xy":[90,90],"spec":gamedata['townhall']}]),
                         ("units",[])]

            elif kind == 'ai_attack':
                example_unit = {'mf': 'mining_droid',
                                'tr': 'rifleman',
                                'mf2': 'shock_trooper',
                                'bfm': 'marine',
                                }[game_id]
                base = [("units", [{"direction": "n", example_unit: 1}])]

            if separate_files:
                # write the base_json to a separate file, then include it into the skeleton
                if base_filename_convention == 'new':
                    base_file = '$GAME_ID_ai_%s_%d_%s.json' % (event_dirname, base_id, kind[3:])
                elif base_filename_convention == 'old':
                    base_file = '$GAME_ID_ai_bases_%s_%d.json' % (event_dirname, base_id)
                else:
                    raise Exception('unknown base_filename_convention')

                base_file_path = base_file_dir + '/' + base_file.replace('$GAME_ID', game_id)
                if os.path.exists(base_file_path):
                    pass
                else:
                    # create the base JSON file
                    sys.stderr.write('creating %s\n' % base_file_path)
                    fd = open(base_file_path, 'w')
                    for i in xrange(len(base)):
                        key, val = base[i]
                        print >> fd, '"%s":' % key,
                        dump_json(val, fd=fd)
                        if i != len(base)-1:
                            print >> fd, ','
                        else:
                            print >> fd, ''
                    pass

                relative_path = '$GAME_ID_ai_bases_%s/%s' % (event_dirname, base_file)
                base_json = [("base_source_file", '$GAME_ID/'+relative_path),
                             '#include_stripped "%s"' % relative_path]
            else:
                base_json = base

            json += base_json

            for i in xrange(len(json)):
                if type(json[i]) in (str, unicode):
                    # literal strings are only used for #includes
                    assert json[i].startswith('#include')
                    print json[i], # XXXXXX this adds a trailing space
                else:
                    assert type(json[i]) in (tuple, list)
                    key, val = json[i]
                    print '    "%s":' % key,
                    dump_json(val)
                if i != len(json)-1:
                    print ','
                else:
                    print ''

            print '},'

            base_id += 1
            if not skip:
                unskipped_count += 1
                overall_unskipped_count += 1

        # placeholder base
        print
        print "// PLACEHOLDER BASE FOR %s WHILE WAITING FOR RESET" % diff.upper()
        print '"%d": {' % base_id

        show_pred = {"predicate": "AND", "subpredicates": [ ] }
        if time_pred:
            show_pred['subpredicates'] += [ time_pred ]
        show_pred['subpredicates'] += [ { "predicate": "PLAYER_HISTORY", "key": "ai_"+data['event_name']+data['key_suffix'][diff]+"_progress_now", "method": "==", "value": data['bases_per_difficulty'] },
                                        { "predicate": "COOLDOWN_ACTIVE", "name": instance_cdname } ]

        json = [
            ("ui_name", data['villain_ui_name']),
            ("ui_map_name", ui_map_name),
            ("ui_priority", ui_priority),
            ("portrait", data['villain_portrait'][diff]),
            ("resources", { "player_level": data['starting_ai_level'][diff], "water": 0, "iron": 0 }),
            ("auto_level", 1),
            ("ui_info", "VICTORY COMPLETE\n" + data['ui_resets'])]

        if 'villain_map_portrait' in data:
            json += [("map_portrait", data['villain_map_portrait'][diff])]

        for FIELD in ('ui_info_url', 'analytics_tag'):
            if FIELD in data: json.append((FIELD, data[FIELD]))

        assert unskipped_count == num_unskipped_bases
        assert (not (('skip' in data) and data['skip'][diff][-1])) # if last base is skipped, then we need to change our show_if predicate

        # Dummy base "activation" predicate message can show for two cases:
        # 1. Player has already completed the event this week, and needs to wait for next week.
        # 2. While still logged in, a week boundary passes. The engine currently doesn't update the
        # available AI list in this case, so the player will still see last week's dummy base. XXX needs fix.
        json += [("ui_progress", { # within this difficulty
                                   "cur": unskipped_count, "max": num_unskipped_bases,
                                   # across all difficulties
                                   "overall_cur": overall_unskipped_count, "overall_max": overall_num_unskipped_bases }),
                 ("ui_difficulty", diff),
                 ("ui_spy_button","Defeated"),
                 ("ui_instance_cooldown",instance_cdname),
                 ("show_if", show_pred),
                 ("activation", {"predicate": "ALWAYS_FALSE", "ui_name": "You've already completed %s this week" % ui_map_name }),
                 ("tech",{}),
                 ("buildings", [{"xy":[90,90],"spec":gamedata['townhall']}]),
                 ("units",[])]



        for key, val in json:
            print '    "%s":' % key,
            dump_json(val)
            if key != 'units':
                print ','
            else:
                print ''
        if diff == data['difficulties'][-1]:
            print '}'
        else:
            print '},'
        base_id += 1

        # print warnings about the skeleton
        check_one_time_loot(data['event_name'], data)
