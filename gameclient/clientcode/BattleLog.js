goog.provide('BattleLog');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// battle log parser
// converts array of raw metrics to SPText

goog.require('goog.array');
goog.require('SPUI'); // for SPUI.Color
goog.require('SPText');
goog.require('ItemDisplay');

var BattleLog = {};

BattleLog.DIRTABLE = [[0,22.5,"North"],
                      [22.5,67.5,"Northeast"],
                      [67.5,112.5,"East"],
                      [112.5,157.5,"Southeast"],
                      [157.5,202.5,"South"],
                      [202.5,247.5,"Southwest"],
                      [247.5,292.5,"West"],
                      [292.5,337.5,"Northwest"],
                      [337.5,360,"North"]
                     ];

BattleLog.compass_direction = function(ncells, coords) { // OK
    var ctr = vec_scale(0.5, ncells); // OK
    var angle = (Math.atan2(coords[1]-ctr[1],coords[0]-ctr[0])*(180.0/Math.PI) + 90 + 360) % 360;
    var direction = null;
    for(var d = 0; d < BattleLog.DIRTABLE.length; d++) {
        var data = BattleLog.DIRTABLE[d];
        if(angle >= data[0] && angle <= data[1]) {
            direction = data[2];
            break;
        }
    }
    return direction;
};

BattleLog.one_unit = function(kind, level, is_mine, props) {
    var dat = gamedata['units'][kind] || gamedata['buildings'][kind];
    var tx = dat['ui_name'];
    if(level && (level > 0) && (is_mine || gamedata['battle_log_detail'])) {
        tx += ' (L'+level.toString()+')';
    }
    if(props && props['turret_head'] && props['turret_head']['spec'] in gamedata['items']) {
        var head_spec = ItemDisplay.get_inventory_item_spec(props['turret_head']['spec']);
        var head_name = ItemDisplay.strip_inventory_item_ui_name_level_suffix(ItemDisplay.get_inventory_item_ui_name(head_spec));
        var head_level = props['turret_head']['level'] || head_spec['level'];
        if(head_level && (head_level > 0) && (is_mine || head_spec['battle_log_detail'] || gamedata['battle_log_detail'])) {
            head_name += ' (L'+head_level.toString()+')';
        }
        tx += ' / ' + head_name;
    }
    return tx;
};

BattleLog.unit = function(met, is_mine) {
    if('multi_units' in met) {
        var ret = [];
        for(var key in met['multi_units']) {
            var count = met['multi_units'][key];
            var kind_level_props = key.split('|');
            var kind = kind_level_props[0];
            var level = parseInt(kind_level_props[1],10);
            var props = (kind_level_props.length >= 3 ? JSON.parse(kind_level_props[2]) : null);
            var tx = BattleLog.one_unit(kind, level, is_mine, props);
            ret.push(count.toString()+'x '+tx);
        }
        return ret.join(', ');
    } else {
        var props = {};
        if('turret_head' in met) {
            props['turret_head'] = met['turret_head'];
        }
        return BattleLog.one_unit(met['unit_type'], met['level'], is_mine, props);
    }
};

BattleLog.attacker = function(met, is_mine) { // is_mine here means "is friendly" not "is a landmine"
    if(met['attacker_mine']) {
        // mine detonation
        if(met['attacker_mine'] in gamedata['items']) {
            return gamedata['items'][met['attacker_mine']]['ui_name'];
        }
    }

    var kind = met['attacker_type'];
    var dat = gamedata['units'][kind] || gamedata['buildings'][kind];
    var tx = dat['ui_name'];
    var level = met['attacker_level'] || 0;
    if(level && (level > 0) && (is_mine || dat['battle_log_detail'] || gamedata['battle_log_detail'])) {
        tx += ' (L'+level.toString()+')';
    }

    if(met['attacker_turret_head'] && met['attacker_turret_head'] in gamedata['items']) {
        var head_spec = ItemDisplay.get_inventory_item_spec(met['attacker_turret_head']);
        var head_name = ItemDisplay.strip_inventory_item_ui_name_level_suffix(ItemDisplay.get_inventory_item_ui_name(head_spec));
        var head_level = head_spec['level'];
        if(head_level && (head_level > 0) && (is_mine || head_spec['battle_log_detail'] || gamedata['battle_log_detail'])) {
            head_name += ' (L'+head_level.toString()+')';
        }
        tx = tx + ' / ' + head_name;
    }

    return tx;
};

// compress successive events that are identical except for unit
// type/level into a single equivalent event with grouped units
BattleLog.compress_group = function(group) {
    if(group.length < 1) { return []; }
    if(group.length < 2) { return [group[0]]; }

    var units = {};
    for(var i = 0; i < group.length; i++) {
        var met = group[i];
        var key = met['unit_type']+'|'+met['level'].toString();
        if(met['turret_head']) {
            var props = {'turret_head': met['turret_head']};
            key += '|'+JSON.stringify(props);
        }
        units[key] = (units[key] || 0) + 1;
    }
    var met = {};
    for(var prop in group[0]) {
        if(prop == 'unit_type' || prop == 'level' || prop == 'turret_head') {
            continue;
        }
        met[prop] = group[0][prop];
    }
    met['multi_units'] = units;
    return [met];
};

// apply compression to successive groups of identical events in an entire log
BattleLog.compress = function(metlist) {
    if(metlist.length < 1) { return metlist; }

    var i;
    var ret = [];
    var group = [];

    for(i = 0; i < metlist.length; i++) {
        var met = metlist[i];

        // ignore events pertaining to barriers, and debugging events
        if(met && (met['unit_type'] == 'barrier' ||
                   met['event_name'] == '3940_shot_fired' ||
                   met['event_name'] == '3950_object_hurt')) { continue; }

        // check whether this event can be compressed together with the group
        // note: some of the met and group[0] fields below may be undefined,
        // but the equality check still works!
        if(group.length > 0 &&
           met['event_name'] == group[0]['event_name'] &&
           met['user_id'] == group[0]['user_id'] &&
           met['attacker_obj_id'] == group[0]['attacker_obj_id'] &&
           met['attacker_type'] == group[0]['attacker_type'] &&
           met['unit_type'] && met['level'] &&
           met['event_name'] != '3920_building_destroyed') {
            var can_compress = true;

            if((met['event_name'] == '3910_unit_deployed') &&
               (met['method'] != group[0]['method'])) {
                can_compress = false;
            }

            if(can_compress) {
                // eligible for compression
                group.push(met);
                continue;
            }
        }

        // ineligible, output group
        ret = ret.concat(BattleLog.compress_group(group));
        group = [];
        if(met['unit_type'] && met['level']) {
            group.push(met);
        } else {
            ret.push(met);
        }
    }
    ret = ret.concat(BattleLog.compress_group(group));
    return ret;
};


// return an ARRAY OF PARAGRAPHS
// each PARAGRAPH is an array of LINES
// each LINE is an array of ABlocks

BattleLog.parse = function(my_id, summary, metlist) {
    var ncells = ('base_ncells' in summary && summary['base_ncells'] ? summary['base_ncells'] : gamedata['map']['default_ncells']); // OK
    metlist = BattleLog.compress(metlist);

    // get names for attacker and defender
    var names = {}, poss = {};
    var myrole, opprole;
    if(my_id == summary['defender_id']) {
        myrole = 'defender';
        opprole = 'attacker';
    } else {
        myrole = 'attacker';
        opprole = 'defender';
    }

    names[myrole] = names[my_id] = 'You';
    poss[myrole] = poss[my_id] = 'Your';

    // special handling for "Mr. Skilling" -> "Skilling" and "The Hammers" -> "The Hammers" (instead of "Hammers")
    if(1) {
        var name_start = 0, name_end = 0;
        if(summary[opprole+'_name'].indexOf('Mr. ') == 0) {
            name_start = 1; name_end = 1;
        } else if(summary[opprole+'_name'].indexOf('The ') == 0) {
            name_start = 0; name_end = 1;
        }
        var broken_name = summary[opprole+'_name'].split(' ');
        names[opprole] = names[summary[opprole+'_id']] = broken_name.slice(name_start, name_end+1).join(' ');
    } else {
        names[opprole] = names[summary[opprole+'_id']] = summary[opprole+'_name'].split(' ')[0];
    }

    poss[opprole] = poss[summary[opprole+'_id']] = names[opprole]+(names[opprole][names[opprole].length-1] == 's' ? "'" : "'s");

    var color_good = 'rgba(0,180,0,1)';
    var color_good_hi = 'rgba(100,255,100,1)';
    var color_bad = 'rgba(240,0,0,1)';
    var color_bad_hi = 'rgba(255,100,100,1)';
    var color_neutral = 'rgba(220,220,220,1)';
    var color_neutral_hi = 'rgba(255,255,255,1)';
    var white = 'rgba(255,255,255,1)';

    var props = { neutral: { normal: {color:color_neutral},
                             hi: {color:color_neutral_hi} },
                  good: { normal: {color:color_good},
                          hi: {color:color_good_hi} },
                  bad: { normal: {color:color_bad},
                         hi: {color:color_bad_hi} } };

    var ret = [];
    var start = -1;
    for(var i = 0; i < metlist.length; i++) {
        var met = metlist[i];
        var line = [];
        var pr = props.neutral;

        if(met['event_name'] == '3820_battle_start' || met['event_name'] == '3850_ai_attack_start') {
            start = met['time'];
            line.push(new SPText.ABlock('Battle starts at '+(new Date(1000*summary['time'])).toUTCString()+' (Timestamp '+summary['time'].toString()+')', props.neutral.normal));
        } else {
            line.push(new SPText.ABlock((met['time']-start).toString()+'s: ', pr.normal));
        }

        if(met['event_name'] == '3820_battle_start' || met['event_name'] == '3850_ai_attack_start') {
            // nothing
        } else if(met['event_name'] == '3900_unit_exists') {
            line.push(new SPText.ABlock(poss['defender']+' defenses: ', pr.normal));
            line.push(new SPText.ABlock(BattleLog.unit(met, myrole === 'defender'), pr.hi));
        } else if(met['event_name'] == '3901_player_auras') {
            var aura_list = [];
            goog.array.forEach(met['player_auras'], function(data) {
                if(!(data['spec'] in gamedata['auras'])) { return; }
                var spec = gamedata['auras'][data['spec']];
                if(('show' in spec) && !spec['show']) { return; }
                if(('show_in_battle_log' in spec) && !spec['show_in_battle_log']) { return; }
                var name = spec['ui_name'];
                if(name.indexOf('%level') >= 0) {
                    var level = ('level' in data ? data['level'] : 1);
                    name = name.replace('%level', pretty_print_number(level));
                }
                aura_list.push(name);
            });
            if(aura_list.length > 0) {
                //pr = (met['user_id'] == my_id) ? props.good : props.bad;
                line.push(new SPText.ABlock(poss[met['user_id']]+' active effects: ', pr.normal));
                line.push(new SPText.ABlock(aura_list.join(', '), pr.hi));
            } else {
                continue;
            }
        } else if(met['event_name'] == '3970_security_team_spawned' || met['event_name'] == '3971_security_team_spawned_from_unit') {
            pr = (met['user_id'] == my_id) ? props.good : props.bad;
            line.push(new SPText.ABlock(poss[met['user_id']]+' ', pr.normal));
            line.push(new SPText.ABlock(BattleLog.one_unit(met['source_obj_specname'],met['source_obj_level'],myrole==='defender',null), pr.hi));
            var msg = {'3970_security_team_spawned':'spawns guards',
                       '3971_security_team_spawned_from_unit':'unloads guards'}[met['event_name']];
            line.push(new SPText.ABlock(' '+msg+': ', pr.normal));
            line.push(new SPText.ABlock(BattleLog.unit(met, myrole === 'defender'), pr.hi));
        } else if(met['event_name'] == '3960_combat_spell_cast') {
            if(met['spellname'] in gamedata['spells']) {
                pr = (met['user_id'] == my_id) ? props.good : props.bad;
                var spell = gamedata['spells'][met['spellname']];
                line.push(new SPText.ABlock(names[met['user_id']]+' '+spell['ui_activation']+' '+spell['ui_name_article']+' ', pr.normal));
                line.push(new SPText.ABlock(spell['ui_name'], pr.hi));

                if(spell['code'] === 'projectile_attack') {
                    if('spellarg' in met && met['spellarg'].length >= 1) {
                        var direction = BattleLog.compass_direction(ncells, met['spellarg'][0]); // OK
                        if(direction) {
                            line.push(new SPText.ABlock(' in the ', pr.normal));
                            line.push(new SPText.ABlock(direction, pr.hi));
                        }
                    }
                }
            }
        } else if(met['event_name'] == '3910_unit_deployed') {
            var deploy;
            if(met['user_id'] == my_id) {
                deploy = 'deploy';
            } else {
                deploy = 'deploys';
            }
            if(met['method'] == 'donated') {
                deploy += ' '+gamedata['strings']['alliance']+' reinforcements';
            }

            line.push(new SPText.ABlock(names['attacker']+' '+deploy+': ', pr.normal));
            line.push(new SPText.ABlock(BattleLog.unit(met, myrole === 'attacker'), pr.hi));

            // deployment location
            if(('x' in met) && ('y' in met)) {
                var direction = BattleLog.compass_direction(ncells, [met['x'],met['y']]); // OK
                if(direction) {
                    line.push(new SPText.ABlock(' in the ', pr.normal));
                    line.push(new SPText.ABlock(direction, pr.hi));
                }
            }

        } else if(met['event_name'] == '3920_building_destroyed'||
                  met['event_name'] == '3930_unit_destroyed') {
            var show_items_destroyed = true;

            if(met['obj_id'] && met['obj_id'] == met['attacker_obj_id'] && met['attacker_mine']) {
                // invert the usual sense of "pr" - your own mine exploding is good, enemy's mine exploding is bad
                pr = (met['user_id'] == my_id) ? props.good : props.bad;
            } else {
                pr = (met['user_id'] == my_id) ? props.bad : props.good;
            }

            if('attacker_type' in met) {
                line.push(new SPText.ABlock(poss[met['attacker_user_id']]+' ', pr.normal));

                if(met['obj_id'] && met['obj_id'] == met['attacker_obj_id']) {
                    if(met['attacker_mine']) {
                        var mine_spec = gamedata['items'][met['attacker_mine']];
                        var mine_name = (mine_spec ? mine_spec['ui_name'] : BattleLog.attacker(met, met['attacker_user_id'] === my_id));
                        line.push(new SPText.ABlock(mine_name, pr.hi));
                    } else {
                        line.push(new SPText.ABlock(BattleLog.attacker(met, met['attacker_user_id'] === my_id), pr.hi));
                    }
                    line.push(new SPText.ABlock((met['attacker_mine'] ? ' detonates' : ' explodes'), pr.normal));
                    show_items_destroyed = false;
                } else {
                    line.push(new SPText.ABlock(BattleLog.attacker(met, met['attacker_user_id'] === my_id), pr.hi));
                    line.push(new SPText.ABlock(' destroys ', pr.normal));
                    line.push(new SPText.ABlock(poss[met['user_id']]+' ', pr.normal));
                    line.push(new SPText.ABlock(BattleLog.unit(met, met['user_id'] === my_id), pr.hi));
                }
            } else {
                line.push(new SPText.ABlock(poss[met['user_id']]+' ', pr.normal));
                line.push(new SPText.ABlock(BattleLog.unit(met, met['user_id'] === my_id), pr.hi));
                line.push(new SPText.ABlock(' was destroyed', pr.normal));
            }

            var loot = [], is_lost = false;

            goog.object.forEach(gamedata['resources'], function(resdata, res) {
                var amount;
                if(myrole === 'defender' && ('lost_'+res) in met) {
                    is_lost = true;
                    amount = met['lost_'+res];
                } else {
                    if(gamedata['show_uncapped_loot']) {
                        amount = met['looted_uncapped_'+res] || 0;
                    } else {
                        amount = met['looted_'+res] || 0;
                    }
                }

                if(amount > 0) {
                    if(loot.length > 0) {
                        loot.push(new SPText.ABlock(', ', pr.normal));
                    }
                    var color;
                    if('text_color' in resdata) {
                        color = SPUI.make_colorv(resdata['text_color']).str();
                    } else if(res in gamedata['client']['loot_text_color']) {
                        color = SPUI.make_colorv(gamedata['client']['loot_text_color'][res]).str();
                    } else {
                        color = white;
                    }
                    loot.push(new SPText.ABlock(amount.toString() + ' '+ resdata['ui_name'], {color:color}));
                }
            });

            if(loot.length > 0) {
                line.push(new SPText.ABlock((is_lost ? (' - '+names[met['user_id']]+' lost ') : ', looting '), pr.normal));
                line = line.concat(loot);
            }

            if(show_items_destroyed && ('items_destroyed' in met)) {
                var dic = {};
                goog.array.forEach(met['items_destroyed'], function(specname) {
                    dic[specname] = (dic[specname]||0)+1;
                });
                var ls = [];
                goog.object.forEach(dic, function(qty, specname) {
                    var spec = ItemDisplay.get_inventory_item_spec(specname);
                    ls.push(ItemDisplay.get_inventory_item_stack_prefix(spec, qty) + ItemDisplay.get_inventory_item_ui_name(spec));
                });
                if(ls.length > 0) {
                    line.push(new SPText.ABlock('. Equipment destroyed: ', pr.normal));
                    line.push(new SPText.ABlock(ls.join(', '), pr.hi));
                }
            }

        } else if(met['event_name'] == '3829_battle_auto_resolved') {
            line.push(new SPText.ABlock(names[met['user_id']]+' auto-resolved the battle, with the following outcome:', pr.hi));
        } else if(met['event_name'] == '3830_battle_end' || met['event_name'] == '3860_ai_attack_end') {
            var tx = 'Battle ended: ';
            var outcome = met['battle_outcome'];
            if(met['event_name'] == '3860_ai_attack_end') {
                // invert sense of battle_outcome for AI attack
                if(outcome == 'victory') {
                    outcome = 'defeat';
                } else {
                    outcome = 'victory';
                }
            }
            if(outcome == 'victory') {
                if(my_id == summary['attacker_id']) {
                    tx += 'You are victorious!';
                } else {
                    tx += 'Victory for '+names['attacker']+'!';
                }
            } else {
                if(my_id == summary['attacker_id']) {
                    tx += names['attacker']+' withdraw';
                } else {
                    tx += names['attacker']+' withdraws';
                }
            }
            if(('loot' in met) && ('battle_stars' in met['loot'])) {
                var star_count = goog.object.getCount(met['loot']['battle_stars']);
                if(star_count > 0) {
                    tx += ' '+gamedata['strings']['battle_end']['ladder'][(star_count == 1 ? 'stars_singular' : 'stars_plural')].replace('%s', star_count.toString()) + '!';
                }
            }
            line.push(new SPText.ABlock(tx, pr.normal));
        } else {
            line.push(new SPText.ABlock(met['event_name'], pr.normal));
        }

        ret.push([line]);

    }
    //console.log(ret);
    return ret;
};
