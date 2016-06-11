goog.provide('RaidBattleLog');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    Convert a raid battle summary into an emulation of a line-by-line battle log
    for feeding into BattleLog.js's parser.
*/

goog.require('goog.object');

/** @param {!Object<string,?>} sum
    @return {!Array<!Object<string,?>>} */
RaidBattleLog.from_summary = function(sum) {
    var ret = [];

    ret.push({'time':sum['time'], 'event_name': '3820_battle_start'});

    goog.array.forEach([['attacker_auras', sum['attacker_id']],
                        ['defender_auras', sum['defender_id']]],
                       function(key_owner_id) {
                           var key = key_owner_id[0], owner_id = key_owner_id[1];
                           if(key in sum && sum[key].length > 0) {
                               console.log(sum[key]);
                               ret.push({'user_id': owner_id, 'event_name': '3901_player_auras',
                                         'player_auras': sum[key]});
                           }
                       });

    if('defending_units' in sum) {
        goog.object.forEach(sum['defending_units'], function(qty, specname) {
            for(var i = 0; i < qty; i++) {
                ret.push({'user_id': sum['defender_id'], 'event_name': '3900_unit_exists', 'unit_type': specname});
            }
        });
    }

    if('deployed_units' in sum) {
        goog.object.forEach(sum['deployed_units'], function(qty, specname) {
            for(var i = 0; i < qty; i++) {
                ret.push({'user_id': sum['attacker_id'], 'event_name': '3910_unit_deployed', 'unit_type': specname});
            }
        });
    }

    goog.array.forEach([['units_killed', sum['defender_id']],
                        ['buildings_killed', sum['defender_id']],
                        ['units_lost', sum['attacker_id']],
                        ['buildings_lost', sum['attacker_id']],
                       ], function(key_owner_id) {
        var key = key_owner_id[0], owner_id = key_owner_id[1];
        if('loot' in sum && key in sum['loot']) {
            goog.object.forEach(sum['loot'][key], function(qty, specname) {
                var spec, event_name;
                if(specname in gamedata['buildings']) {
                    spec = gamedata['buildings'][specname];
                    event_name = '3920_building_destroyed';
                } else if(specname in gamedata['units']) {
                    spec = gamedata['units'][specname];
                    event_name = '3930_unit_destroyed';
                } else {
                    return;
                }
                for(var i = 0; i < qty; i++) {
                    ret.push({'event_name': event_name, 'unit_type': specname, 'user_id': owner_id});
                }
            });
        }
                        });

    ret.push({'event_name': '3830_battle_end', 'battle_outcome': sum['attacker_outcome']});

    var scout_data = ['new_raid_hp', 'new_raid_offense', 'new_raid_defense'];
    if(goog.array.some(scout_data, function(key) { return key in sum; })) {
        var event = {'user_id': sum['defender_id'], 'event_name': '3972_raid_scout_result'};
        goog.array.forEach(scout_data, function(key) {
            if(key in sum) {
                event[key] = sum[key];
            }
        });
        ret.push(event);
    }

    return ret;
};
