goog.provide('BattleLog');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// battle log parser
// converts array of raw metrics to SPText

goog.require('goog.array');
goog.require('goog.object');
goog.require('SPUI'); // for SPUI.Color
goog.require('SPText');
goog.require('ItemDisplay');

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
        // sort unit specnames with most "impressive" ones first
        var key_list = goog.object.getKeys(met['multi_units']);
        key_list.sort(function(a,b) {
            var a_specname = a.split('|')[0];
            var b_specname = b.split('|')[0];
            return compare_specnames(a_specname,b_specname);
        });
        goog.array.forEach(key_list, function(key) {
            var count = met['multi_units'][key];
            var kind_level_props = key.split('|');
            var kind = kind_level_props[0];
            var level = (kind_level_props.length >= 2 ? parseInt(kind_level_props[1],10) : -1);
            var props = (kind_level_props.length >= 3 ? JSON.parse(kind_level_props[2]) : null);
            var tx = BattleLog.one_unit(kind, level, is_mine, props);
            ret.push(count.toString()+'x '+tx);
        });
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
    var looted = {}; // accumulators for looted/lost amounts

    for(var i = 0; i < group.length; i++) {
        var met = group[i];
        var key = met['unit_type']+'|'+('level' in met ? met['level'].toString() : '?');
        if(met['turret_head']) {
            var props = {'turret_head': met['turret_head']};
            key += '|'+JSON.stringify(props);
        }
        units[key] = (units[key] || 0) + 1;
        for(var prop in met) {
            if(prop.indexOf('looted_') === 0 || prop.indexOf('lost_') === 0) {
                looted[prop] = (prop in looted ? looted[prop] : 0) + met[prop];
            }
        }
    }
    var met = {};
    for(var prop in group[0]) {
        if(prop == 'unit_type' || prop == 'level' || prop == 'turret_head' ||
           prop.indexOf('looted_') === 0 || prop.indexOf('lost_') === 0) {
            continue;
        }
        met[prop] = group[0][prop];
    }
    met['multi_units'] = units;
    for(var k in looted) {
        met[k] = looted[k];
    }
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
        // ignore units already dead at start of battle
        if(met && (met['unit_type'] == 'barrier' ||
                   met['event_name'] == '3940_shot_fired' ||
                   met['event_name'] == '3950_object_hurt' ||
                   (met['event_name'] == '3900_unit_exists' && (met['hp']===0) || met['hp_ratio']===0))) { continue; }



        // check whether this event can be compressed together with the group
        // note: some of the met and group[0] fields below may be undefined,
        // but the equality check still works!
        if(group.length > 0 &&
           met['event_name'] == group[0]['event_name'] &&
           met['user_id'] == group[0]['user_id'] &&
           met['attacker_obj_id'] == group[0]['attacker_obj_id'] &&
           met['attacker_type'] == group[0]['attacker_type'] &&
           met['unit_type'] &&
           !(met['event_name'] == '3920_building_destroyed' && ('level' in met) && ('attacker_type' in met))) {

            // building_destroyed events are only compressed if there is almost no data on them (for raids)

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
        if(met['unit_type']) {
            group.push(met);
        } else {
            ret.push(met);
        }
    }
    ret = ret.concat(BattleLog.compress_group(group));
    return ret;
};


/** Clean up a player ui_name for use in the battle log entries
    @param {string} n
    @param {boolean} is_ai
    @param {boolean} is_viewer
    @return {string} */
BattleLog.format_name_for_display = function(n, is_ai, is_viewer) {
    if(is_viewer) { return 'You'; }
    var name_start = 0, name_end = 0;
    // special handling for "Mr. Skilling" -> "Skilling" and "The Hammers" -> "The Hammers" (instead of "Hammers")
    if(n.indexOf('Mr. ') == 0) {
        name_start = 1; name_end = 1;
    } else if(n.indexOf('The ') == 0) {
        name_start = 0; name_end = 1;
    } else if(!is_ai) {
        // for player opponents, strip off the rank/title prefix
        n = PlayerCache.strip_title_prefix(n);
    }
    var broken_name = n.split(' ');
    return broken_name.slice(name_start, name_end+1).join(' ');
};
/** Make possessive version of a name
    @param {string} name
    @param {boolean} is_viewer
    @return {string} */
BattleLog.make_possessive = function(name, is_viewer) {
    if(is_viewer) { return 'Your'; }
    return name+(name[name.length-1] == 's' ? "'" : "'s");
};

// return an ARRAY OF PARAGRAPHS
// each PARAGRAPH is an array of LINES
// each LINE is an array of ABlocks

// note: for a third-party battle involving an alliancemate, "my_id"
// refers to the alliancemate involved in the battle, who should be
// considered the "good guy" (or -1 to favor neither participant).

// viewer_id is the id of the player looking at the log (who should be
// referred to as "You").

BattleLog.parse = function(my_id, viewer_id, summary, metlist) {
    var ncells = ('base_ncells' in summary && summary['base_ncells'] ? summary['base_ncells'] : gamedata['map']['default_ncells']); // OK
    metlist = BattleLog.compress(metlist);

    // get names and possessives for attacker and defender

    var names = {}, poss = {};
    var myrole, opprole;
    if(my_id == summary['defender_id']) {
        myrole = 'defender';
        opprole = 'attacker';
    } else {
        myrole = 'attacker';
        opprole = 'defender';
    }

    names[myrole] = names[summary[myrole+'_id']] = BattleLog.format_name_for_display(summary[myrole+'_name'], is_ai_user_id_range(summary[myrole+'_id']), viewer_id === summary[myrole+'_id']);
    poss[myrole] = poss[summary[myrole+'_id']] = BattleLog.make_possessive(names[myrole], viewer_id === summary[myrole+'_id']);

    names[opprole] = names[summary[opprole+'_id']] = BattleLog.format_name_for_display(summary[opprole+'_name'], is_ai_user_id_range(summary[opprole+'_id']), viewer_id === summary[opprole+'_id']);
    poss[opprole] = poss[summary[opprole+'_id']] = BattleLog.make_possessive(names[opprole], viewer_id === summary[opprole+'_id']);

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
    var start = -1; // battle start time

    var ui_battle_kind = (summary['battle_type'] === 'raid' ?
                          (summary['raid_mode'] === 'scout' ?
                           'Scout attempt' : 'Raid')
                          : 'Battle');

    // show unit casualties
    if('loot' in summary) {
        var casualties_shown = false;
        // note: the sense of units_killed/units_lost is inverted for AI attacks
        var defender_losses_key, attacker_losses_key;
        if(summary['battle_type'] === 'defense') {
            attacker_losses_key = 'units_killed';
            defender_losses_key = 'units_lost';
        } else {
            defender_losses_key = 'units_killed';
            attacker_losses_key = 'units_lost';
        }

        goog.array.forEach([{loot_key: defender_losses_key, role: 'defender'}, {loot_key: attacker_losses_key, role: 'attacker'}], function(entry) {
            if(entry.loot_key in summary['loot']) {

                // create units-only version of the killed/lost dictionaries (that include buildings)
                var units_only = goog.object.filter(summary['loot'][entry.loot_key], function(count, key) {
                    return (key in gamedata['units']);
                });
                if(goog.object.getCount(units_only) < 1) { return; }

                // casualties are bad for you and good for other
                var pr = (myrole === entry.role) ? props.bad : props.good;
                var line = [];
                line.push(new SPText.ABlock(poss[entry.role]+' unit casualties: ', pr.normal));
                line.push(new SPText.ABlock(BattleLog.unit({'multi_units':units_only}, myrole === entry.role), pr.hi));
                line.push(new SPText.ABlock('.', pr.normal));
                ret.push([line]);
                casualties_shown = true;
            }
        });
        if(casualties_shown) { // add divider bar
            var divider_text = ''; // '---------------------------------------------------------------------------'
            ret.push([[new SPText.ABlock(divider_text, props.neutral.normal)]]);
        }
    }

    // some lines to re-order after the end of the normal timestamped sequence
    var footer = [];

    for(var i = 0; i < metlist.length; i++) {
        var met = metlist[i];
        var line = [];
        var pr = props.neutral;

        if(met['event_name'] == '3820_battle_start' || met['event_name'] == '3850_ai_attack_start') {
            start = met['time'];
            // note: GUI displays the timestamp as a "Battle ID" to reduce player confusion, but it's just the UNIX
            // timestamp of the battle start, NOT an actual unique ID.
            line.push(new SPText.ABlock(ui_battle_kind+' starts at '+(new Date(1000*summary['time'])).toUTCString()+' (Battle ID '+summary['time'].toString()+')', props.neutral.normal));
            /* might be redundant/counterproductive to show this
            if(summary['attacker_could_revenge_until'] > 0) {
                ret.push([line]);
                line = [new SPText.ABlock(names['attacker'] + ' ' + (summary['attacker_could_revenge_until'] >= server_time ? (summary['attacker_id'] === viewer_id ? 'have' : 'has') : 'had') +' revenge rights against ' + poss['defender'] + ' home base until ' + pretty_print_date_and_time_utc(summary['attacker_could_revenge_until']) + ' GMT', pr.normal)];
            }
            */
        } else if('time' in met) {
            line.push(new SPText.ABlock((met['time']-start).toString()+'s: ', pr.normal));
        }

        if(met['event_name'] == '3820_battle_start' || met['event_name'] == '3850_ai_attack_start') {
            // nothing
        } else if(met['event_name'] == '3900_unit_exists') {
            if(met['hp'] === 0 || met['hp_ratio'] === 0) { continue; } // dead unit
            if(summary['raid_mode'] === 'scout') {
                line.push(new SPText.ABlock(poss['defender']+' defending scouts: ', pr.normal));
            } else {
                line.push(new SPText.ABlock(poss['defender']+' defenses: ', pr.normal));
            }
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
            if(met['user_id'] == viewer_id) {
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
                    loot.push(new SPText.ABlock(pretty_print_number(amount) + ' '+ resdata['ui_name'], {color:color}));
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
            var tx = ui_battle_kind + ' ended: ';
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
                if(viewer_id == summary['attacker_id']) {
                    tx += 'You are victorious!';
                } else {
                    tx += 'Victory for '+names['attacker']+'!';
                }
            } else {
                if(viewer_id == summary['attacker_id']) {
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
        } else if(met['event_name'] == '3972_raid_scout_result') {
            if('new_raid_hp' in met) {
                var hp = met['new_raid_hp'];
                var ui_str_list = [];
                var CATS = gamedata['strings']['damage_vs_categories'];
                for(var c = 0; c < CATS.length; c++) {
                    var key = CATS[c][0], catname = CATS[c][1];
                    var ui_catname = gamedata['strings']['manufacture_categories'][catname];
                    if(hp[key] > 0 && ui_catname) {
                        ui_str_list.push(ui_catname['plural']+' '+pretty_print_number(hp[key])+' HP');
                    }
                }
                var ui_str = (ui_str_list.length > 0 ? ui_str_list.join('\n') : 'None');
                line.push(new SPText.ABlock(poss[met['user_id']]+' raid strength remaining: '+ui_str, pr.normal));
            }
        } else if(met['event_name'] == '3890_revenge_enabled') {
            pr = (met['user_id'] == my_id) ? props.good : props.bad;

            // add after end
            footer.push([[new SPText.ABlock('Because of this attack, ' + names[met['user_id']]+' can take revenge on ' + poss[met['against']] + ' home base regardless of level difference until ' + pretty_print_date_and_time_utc(met['end_time']) + ' GMT', pr.normal)]]);
            continue;
        } else {
            line.push(new SPText.ABlock(met['event_name'], pr.normal));
        }

        ret.push([line]);

    }

    ret = ret.concat(footer);

    //console.log(ret);
    return ret;
};
