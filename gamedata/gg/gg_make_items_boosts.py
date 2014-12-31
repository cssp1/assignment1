#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this script generates various unit boost items

import SpinConfig
import SpinJSON
import AtomicFileWrite
import sys, re, traceback, os, getopt

# converts a boost duration to how it appears at the end of an item name (eg. 1800 becomes _30min and 129600 becomes _1d12h)
def get_name_duration(duration):
    if duration != 3600:
        suffix = '_'

        days = int(duration / 86400)
        if days > 0:
            suffix += str(days) + 'd'

        hours = int((duration % 86400) / 3600)
        if hours > 0:
            suffix += str(hours) + 'h'

        minutes = int((duration % 3600) / 60)
        if minutes > 0:
            suffix += str(minutes) + 'min'

        return suffix
    else:
        # 1 hour buffs have no duration suffix
        return ''

# converts a boost duration to a human-readable string for use in a boost's ui_description (eg. 1800 becomes 30 minutes and 129600 becomes 1 day, 12 hours)
def get_ui_description_duration(duration):
    s = ''

    days = int(duration / 86400)
    if days > 0:
        s += str(days) + ' day'
        if days > 1:
            s += 's'

    hours = int((duration % 86400) / 3600)
    if hours > 0:
        if s != '':
            s += ', '
        s += str(hours) + ' hour'
        if hours > 1:
            s += 's'

    minutes = int((duration % 3600) / 60)
    if minutes > 0:
        if s != '':
            s += ', '
        s += str(minutes) + ' minute'
        if minutes > 1:
            s += 's'

    return s

# converts a boost duration to a human-readable string for use in a boost's ui_name (eg. 1800 becomes 30m and 129600 becomes 1.5d)
def get_ui_name_duration(duration):
    s = ''

    days = int(duration / 86400)
    hours = int((duration % 86400) / 3600)
    minutes = int((duration % 3600) / 60)

    if days > 0:
        if hours > 0 or minutes > 0:
            return '%.1fd' % (duration / 86400)
        else:
            return '%dd' % days
    elif hours > 0:
        if minutes > 0:
            return '%.1fh' % (float(duration % 86400) / 3600)
        else:
            return '%dh' % hours
    elif minutes > 0:
        return '%dm' % minutes
    else:
        return ''

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])
    ident = str(os.getpid())

    # read unit data
    gamedata = {'units': SpinConfig.load(args[0])}
    out_fd = AtomicFileWrite.AtomicFileWrite(args[1], 'w', ident=ident)

    # provide special behaviour for unit-type boosts
    unit_types = {'rover': {'name': 'rover', 'ui_name': 'Infantry', 'ui_name_plural': 'infantry'},
                  'transport': {'name': 'transport', 'ui_name': 'Armor', 'ui_name_plural': 'armored units'},
                  'starcraft': {'name': 'starcraft', 'ui_name': 'Aircraft', 'ui_name_plural': 'aircraft'}}

    # templates for different boost types and their properties
    boost_types = {'damage': {'name': '{unit[name]}_damage_boost_{pct}pct{name_duration}', 'ui_name': '{pct}% {unit[ui_name]} Damage Boost ({ui_name_duration})',
                              'ui_description': 'Activate to increase damage done by your {unit[ui_name_plural]} by {pct}%. Lasts {ui_description_duration}.',
                              'icon': 'inventory_damage_{unit[name]}_{icon_color}', 'aura': '{unit[name]}_damage_boosted'},
                   'damage_resist': {'name': '{unit[name]}_damage_resist_boost_{pct}pct{name_duration}', 'ui_name': '{pct}% {unit[ui_name]} Toughness Boost ({ui_name_duration})',
                                    'ui_description': 'Activate to reduce damage taken by your {unit[ui_name_plural]} by {pct}%. Lasts {ui_description_duration}.',
                                    'icon': 'inventory_armor_{unit[name]}_{icon_color}', 'aura': '{unit[name]}_damage_resist_boosted'},
                   'range': {'name': '{unit[name]}_range_boost_{pct}pct{name_duration}', 'ui_name': '{pct}% {unit[ui_name]} Range Boost ({ui_name_duration})',
                             'ui_description': 'Activate to increase weapon range of your {unit[ui_name_plural]} by {pct}%. Lasts {ui_description_duration}.',
                             'icon': 'inventory_range_{unit[name]}_{icon_color}', 'aura': '{unit[name]}_range_boosted'},
                   'speed': {'name': '{unit[name]}_speed_boost_{pct}pct{name_duration}', 'ui_name': '{pct}% {unit[ui_name]} Speed Boost ({ui_name_duration})',
                             'ui_description': 'Activate to increase movement speed of your {unit[ui_name_plural]} by {pct}%. Lasts {ui_description_duration}.',
                             'icon': 'inventory_speed_{unit[name]}_{icon_color}', 'aura': '{unit[name]}_speed_boosted'},
                   'splash_range': {'name': '{unit[name]}_splash_range_boost_{pct}pct{name_duration}', 'ui_name': '{pct}% {unit[ui_name]} Splash Range Boost ({ui_name_duration})',
                                    'ui_description': 'Activate to increase the splash range of your {unit[ui_name_plural]} by {pct}%. Lasts {ui_description_duration}.',
                                    'icon': 'inventory_range_{unit[name]}_{icon_color}', 'aura': '{unit[name]}_splash_range_boosted'}}
    # maps boost strength to their icon/rarities (eg. a 10% boost has rarity 1 and a black icon)
    rarities = {10: 1, 20: 1, 30: 2, 40: 2, 50: 3}
    icon_colors = {10: 'black', 20: 'gray', 30: 'green', 40: 'blue', 50: 'purple'}

    stack_size = 5

    # define the actual boosts
    unit_boosts = {}
    unit_boosts_unused = {}

    # generate the json for the boosts
    out = {'items':[]}
    for unit_name, types in unit_boosts.iteritems():
        if unit_name in unit_types:
            unit = unit_types[unit_name]
        else:
            unit = gamedata['units'][unit_name]

        for type, boosts in types.iteritems():
            boost_type = boost_types[type]

            for boost in boosts:
                pct = int(boost['strength'] * 100)

                if 'icon_color' in boost:
                    icon_color = boost['icon_color']
                else:
                    icon_color = icon_colors[pct]

                if 'rarity' in boost:
                    rarity = boost['rarity']
                else:
                    rarity = rarities[pct]

                format_args = {'unit': unit,
                               'boost': boost,
                               'pct': pct,
                               'name_duration': get_name_duration(boost['duration']),
                               'ui_name_duration': get_ui_name_duration(boost['duration']),
                               'ui_description_duration': get_ui_description_duration(boost['duration']),
                               'icon_color': icon_color}

                out['items'].append({'name': boost_type['name'].format(**format_args),
                                     'ui_name': boost_type['ui_name'].format(**format_args),
                                     'ui_description': boost_type['ui_description'].format(**format_args),
                                     'icon': boost_type['icon'].format(**format_args),
                                     'rarity': rarity,
                                     'stack_max': stack_size,
                                     'use': {'spellname': 'APPLY_AURA', 'spellarg': ['player', boost_type['aura'].format(**format_args), boost['strength'], boost['duration']]}})

    print >> out_fd.fd, '// AUTO-GENERATED BY make_items_boosts.py'
    count = 0

    if not out['items']:
        # need to provide a stand-in item to avoid syntax errors, since this is preceded by ','
        print >>out_fd.fd, '"{0}":'.format('dummy_boost_item'), SpinJSON.dumps({
            "name": "dummy_boost_item",
            "ui_name": "Dummy Boost Item",
            "ui_description": "Dummy Boost Item",
            "icon": "inventory_unknown"
            }, pretty = True)

    for item in out['items']:
        print >>out_fd.fd, '"{0}":'.format(item['name']), SpinJSON.dumps(item, pretty = True)

        if count != len(out['items'])-1:
            print >>out_fd.fd, ','
        count += 1
    out_fd.complete()
