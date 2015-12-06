#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# automatically generate Alloy SKU tables for Kongregate

import SpinJSON
import SpinConfig
import AtomicFileWrite
import sys, re, os, getopt

import locale # for pretty number printing only
locale.setlocale(locale.LC_ALL, '')

# regular expression that matches C++-style comments
comment_remover = re.compile('//.*?$') # |/\*.*?/*/
verbose = True

if __name__ == '__main__':


    game_id = SpinConfig.game()

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'uv', ['game-id=',])
    for key, val in opts:
        if key == '--game-id':
            game_id = val
        elif key == '-u':
            verbose = False

    out_fd = AtomicFileWrite.AtomicFileWrite(args[0], 'w', ident=str(os.getpid()))
    print >> out_fd.fd, "// AUTO-GENERATED BY make_ai_bases_client.py"

    out = {}

    COMMENTS = [None, None, 'Most Popular', None, None, None]

    SLATES = { "P100M": { "level": 100, "kind": "M",
                          "currency": "kgcredits",
                          "skus": [{'alloy': 20000, 'kgcredits':2000},
                                   {'alloy': 10000, 'kgcredits': 1000},
                                   {'alloy': 5000, 'kgcredits': 500},
                                   {'alloy': 2500, 'kgcredits': 250},
                                   {'alloy': 1000, 'kgcredits': 100},
                                   {'alloy': 500, 'kgcredits': 50}
                                   ] },
               "P100D1": { "level": 100, "kind": "D1",
                          "currency": "kgcredits",
                          "skus": [{'alloy': 24000, 'kgcredits':1999, 'nominal_alloy': 20000, 'ui_comment': 'Best Value', 'ui_pile_size': 5, 'loot_table': 'item_bundle_20000'},
                                   {'alloy': 11500, 'kgcredits': 999, 'nominal_alloy': 10000, 'ui_comment': None, 'ui_pile_size': 4, 'loot_table': 'item_bundle_10000'},
                                   {'alloy': 5500, 'kgcredits': 499, 'nominal_alloy': 5000, 'ui_comment': 'Most Popular', 'ui_pile_size': 3, 'loot_table': 'item_bundle_5000'},
                                   {'alloy': 1050, 'kgcredits': 99, 'nominal_alloy': 1000, 'ui_comment': None, 'ui_pile_size': 2, 'loot_table': 'item_bundle_1000'},
                                   {'alloy': 500, 'kgcredits': 49, 'ui_comment': None, 'ui_pile_size': 0, 'loot_table': 'item_bundle_500'}
                                   ] },
               "P100D2": { "level": 100, "kind": "D2",
                          "currency": "kgcredits",
                          "skus": [{'alloy': 24000, 'kgcredits':1999, 'nominal_alloy': 20000, 'ui_comment': 'Best Value', 'ui_pile_size': 5, 'loot_table': 'item_bundle_20000'},
                                   {'alloy': 11500, 'kgcredits': 999, 'nominal_alloy': 10000, 'ui_comment': None, 'ui_pile_size': 4, 'loot_table': 'item_bundle_10000'},
                                   {'alloy': 5500, 'kgcredits': 499, 'nominal_alloy': 5000, 'ui_comment': 'Most Popular', 'ui_pile_size': 3, 'loot_table': 'item_bundle_5000'},
                                   {'alloy': 2650, 'kgcredits': 249, 'nominal_alloy': 2500, 'ui_comment': None, 'ui_pile_size': 2, 'loot_table': 'item_bundle_2500'},
                                   {'alloy': 1050, 'kgcredits': 99, 'nominal_alloy': 1000, 'ui_comment': None, 'ui_pile_size': 1, 'loot_table': 'item_bundle_1000'},
                                   {'alloy': 500, 'kgcredits': 49, 'ui_comment': None, 'ui_pile_size': 0, 'loot_table': 'item_bundle_500'}
                                   ] },
               "P100FLASH50": { "level": 50, "kind": "FLASH50", # 50% Off sale for flash offers
                          "currency": "kgcredits",
                          "skus": [{'alloy': 24000, 'kgcredits':999, 'ui_pile_size': 5, 'ui_bonus': '50% Off', 'nominal_alloy': 20000, 'ui_banner': 'SALE', 'ui_comment': 'Best Value'},
                                   {'alloy': 11500, 'kgcredits':499, 'ui_pile_size': 4, 'ui_bonus': '50% Off', 'nominal_alloy': 10000, 'ui_banner': 'SALE', 'ui_comment': None},
                                   {'alloy': 5500, 'kgcredits': 249, 'ui_pile_size': 3, 'ui_bonus': '50% Off', 'nominal_alloy': 5000, 'ui_banner': 'SALE', 'ui_comment': 'Most Popular'},
                                   {'alloy': 2650, 'kgcredits': 120, 'ui_pile_size': 2, 'ui_bonus': '50% Off', 'nominal_alloy': 2500, 'ui_banner': 'SALE', 'ui_comment': None},
                                   {'alloy': 1050, 'kgcredits': 49,'ui_pile_size': 1, 'ui_bonus': '50% Off', 'nominal_alloy': 1000, 'ui_banner': 'SALE', 'ui_comment': None},
                                   {'alloy': 500, 'kgcredits': 24, 'ui_pile_size': 0, 'ui_bonus': '50% Off', 'ui_banner': 'SALE', 'ui_comment': None},
                                   ] },
               "P100FLASH25": { "level": 25, "kind": "FLASH25", # 75% Off sale for flash offers
                          "currency": "kgcredits",
                          "skus": [{'alloy': 24000, 'kgcredits':499, 'ui_pile_size': 5, 'ui_bonus': '75% Off', 'nominal_alloy': 20000, 'ui_banner': 'SALE', 'ui_comment': 'Best Value'},
                                   {'alloy': 11500, 'kgcredits':249, 'ui_pile_size': 4, 'ui_bonus': '75% Off', 'nominal_alloy': 10000, 'ui_banner': 'SALE', 'ui_comment': None},
                                   {'alloy': 5500, 'kgcredits': 124, 'ui_pile_size': 3, 'ui_bonus': '75% Off', 'nominal_alloy': 5000, 'ui_banner': 'SALE', 'ui_comment': 'Most Popular'},
                                   {'alloy': 2650, 'kgcredits': 60, 'ui_pile_size': 2, 'ui_bonus': '75% Off', 'nominal_alloy': 2500, 'ui_banner': 'SALE', 'ui_comment': None},
                                   {'alloy': 1050, 'kgcredits': 24,'ui_pile_size': 1, 'ui_bonus': '75% Off', 'nominal_alloy': 1000, 'ui_banner': 'SALE', 'ui_comment': None},
                                   {'alloy': 500, 'kgcredits': 12, 'ui_pile_size': 0, 'ui_bonus': '75% Off', 'ui_banner': 'SALE', 'ui_comment': None},
                                   ] },

               }

    for slate_name, val in SLATES.iteritems():
        check_level = None
        last_level = None
        last_sku = None

        sorted_skus = sorted(val['skus'], key = lambda x: -x['alloy']) # from high to low price

        biggest_sku = sorted_skus[0]
        second_biggest_sku = sorted_skus[1]

        for sku_index in xrange(len(val['skus'])):
            data = val['skus'][sku_index]
            comment = val.get('comments',COMMENTS)[sku_index]

            sku_name = 'BUY_GAMEBUCKS_%d' % data['alloy'] + '_KG_'+slate_name

            # perform some sanity checks on pricing
            if last_sku is not None:
                # make sure SKUs are listed in descending order
                assert data['alloy'] < last_sku['alloy']

            # check for big (>50%) deviations in alloy exchange rate across SKUs
            this_level = float(data['alloy'])/data[val['currency']]
            if check_level is not None:
                delta = abs((this_level - check_level)/check_level)
                if delta > 0.20:
                    raise Exception('big deviation on SKU %s %d vs %d: check_level %f this_level %f' % (sku_name, last_sku['alloy'], data['alloy'], check_level, this_level))
            check_level = this_level

            # make sure discount factor does not decline for larger purchases
            if last_level is not None:
                if this_level > last_level:
                    raise Exception('alloy exchange rate declines on SKU: '+sku_name)
            last_level = this_level
            last_sku = data

            assert sku_name not in out
            pretty_alloy_amount = locale.format('%d', data['alloy'], True)
            sku = {
                'quantity': data['alloy'],
                'ui_name': '%GAMEBUCKS_QUANTITY %GAME_NAME %GAMEBUCKS_NAME',
                'ui_description': "%GAMEBUCKS_QUANTITY %GAME_NAME %GAMEBUCKS_NAME, which can be spent in game on speed-ups, resources, and special items",
                'activation': 'instant', 'icon': 'store_icon_grow_perimeter',
                'paid': 1,
                'currency': val['currency'],
                'price_formula': 'constant',
                'price': data[val['currency']],
                }
            if 'ui_pile_size' in data: sku['ui_pile_size'] = data['ui_pile_size']
            if 'nominal_alloy' in data: sku['nominal_quantity'] = data['nominal_alloy']
            if 'loot_table' in data: sku['loot_table'] = data['loot_table']
            if comment: sku['ui_comment'] = comment

            ui_bonus_list = []
            if ui_bonus_list:
                sku['ui_bonus'] = '\n'.join(ui_bonus_list)

            pred = {'predicate': 'AND', 'subpredicates':[
                       {'predicate': 'FRAME_PLATFORM', 'platform': 'kg'},
                       {'predicate': 'GAMEDATA_VAR', 'name': 'store.buy_gamebucks_sku_kind', 'value': val.get('kind','UNUSED')},
                       ] }

            # prevent player from seeing biggest sku until has purchased at least as much as second-biggest
            if data is biggest_sku: # and len(val['skus']) >= 6:
                pred['subpredicates'].append({'predicate':'PLAYER_HISTORY', 'key':'money_spent', 'method':'>=',
                                              'value': 0.07*second_biggest_sku['kgcredits'] - 0.01})

            sku['requires'] = pred
            out[sku_name] = sku

    out_keys = sorted(out.keys(), key = lambda x: -int(x.split('_')[2]))
    for name in out_keys:
        data = out[name]
        print >>out_fd.fd, '"%s":' % name, SpinJSON.dumps(data, pretty = False),
        if name != out_keys[-1]:
            print >>out_fd.fd, ','
        else:
            print >>out_fd.fd

    out_fd.complete()
