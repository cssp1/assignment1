goog.provide('ModChain');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('goog.object');

// tools for working with chains of modifiers that operate on player/unit/building stats

// imports: get_leveled_quantity

/** @typedef {Object|null} */
ModChain.ModChain;

ModChain.get_base_value = function(stat, spec, level) {
    if(stat == 'maxvel') {
        return 1; // this is a scaling factor in the combat engine
    } else if(stat == 'permanent_auras') {
        // special case since this could be a list of per-level lists, or a plain all-level list
        if(stat in spec) {
            var val = spec[stat];
            if(Array.isArray(val) && val.length >= 1 && (Array.isArray(val[0]) || val[0] === null)) {
                return get_leveled_quantity(val, level);
            } else {
                return val;
            }
        } else if('equip' in spec && 'effects' in spec['equip']) {
            var ret = null;
            goog.array.forEach(spec['equip']['effects'], function(effect) {
                if(!('code' in effect && effect['code'] === 'modstat')) { return; }
                if(effect['stat'] === stat) {
                    var val = get_leveled_quantity(effect['strength'], level);
                    if(Array.isArray(val) && val.length >= 1 && (Array.isArray(val[0]) || val[0] === null)) {
                        ret = get_leveled_quantity(val, level);
                    } else {
                        ret = val;
                    }
                }
            });
            return ret;
        } else {
            return null;
        }
    } else if(stat.indexOf('impact_auras') === 0) {
        var impact_aura = stat.split(':')[1];
        stat = 'impact_auras';
        var spell = get_auto_spell_raw(spec);
        if(!spell) { return null; }
        var ret = null;
        if(stat in spell) {
            goog.array.forEach(spell['impact_auras'], function(aura) {
                if(aura['spec'] === impact_aura) {
                    ret = {'spec': aura['spec']};
                    if('duration' in aura) {
                        ret['duration'] = get_leveled_quantity(aura['duration'], level);
                    }
                    if('strength' in aura) {
                        ret['strength'] = get_leveled_quantity(aura['strength'], level);
                    }
                    if('duration_vs' in aura) {
                        ret['duration_vs'] = get_leveled_quantity(aura['duration_vs'], level);
                    }
                };
            });
        }
        return ret;
    } else if(stat == 'strike_team') { // special for strike teams
        var effects = spec['equip']['effects'];
        var desc = '';
        for(var i = 0; i < effects.length; i ++) {
            var effect = effects[i];
            if(desc !== '') { continue; }
            if('apply_if' in effect && !read_predicate(effect['apply_if']).is_satisfied(player,null)) { continue; }
            if('stat' in effect && (effect['stat'] == 'on_destroy' || effect['stat'] == 'on_damage' || effect['stat'] == 'on_approach')) {
                var this_effect, secteam;
                this_effect = get_leveled_quantity(effect['strength'], level);
                if(Array.isArray(this_effect)) {
                    secteam = this_effect[0]['units'];
                } else {
                    secteam = this_effect['units'];
                }
                for(var specname in secteam) {
                    var entry = secteam[specname];
                    if(desc !== '') {
                        desc += '\n';
                    }
                    var unit_spec = gamedata['units'][specname];
                    var ui_name = '';
                    var qty;
                    var ui_level = '';
                    if(typeof(entry) === 'number') {
                        qty = entry.toString() + 'x ';
                    } else if('qty' in entry) {
                        qty = entry['qty'].toString() + 'x ';
                        if('force_level' in entry) {
                            ui_level = 'L'+entry['force_level'].toString() + ' ';
                        }
                    }
                    if(qty > 1) {
                        ui_name = unit_spec['ui_name_plural'];
                    } else {
                        ui_name = unit_spec['ui_name'];
                    }
                    desc += qty + ui_level + ui_name;
                }
            }
        }
        return desc;
    } else if(stat in spec) {
        return get_leveled_quantity(spec[stat], level);
    } else if(stat == 'armor') { // annoying special cases
        return 0;
    } else if(stat == 'on_destroy' || stat == 'on_damage' || stat == 'on_approach') {
        return null;
    } else if(stat == 'repair_price_cap') {
        return -1;
    } else if(stat == 'research_level' || stat == 'crafting_level') {
        return level;
    } else if(stat == 'weapon') {
        var spell = get_auto_spell_raw(spec);
        if(!spell) { return null; }
        return spell['name'];
    } else if(stat.indexOf('limit:') == 0) { // for GUI only
        var stat_data = gamedata['strings']['modstats']['stats'][stat];
        var check_spec = gamedata['buildings'][stat_data['check_spec']];
        if(stat_data['check_method'] == 'limit_requires') {
            // XXX hack - assumes pure TECH_LEVEL predicates
            var i = 0;
            for(; i < check_spec['limit_requires'].length; i++) {
                var pred = check_spec['limit_requires'][i];
                if(('min_level' in pred) && pred['min_level'] > level) {
                    break;
                }
            }
            return i;
        } else {
            // assume that we are the townhall
            return get_leveled_quantity(check_spec['limit'], level);
        }
    } else if(stat.indexOf('provides_limited_equipped:') == 0) {
        var thing = stat.replace('provides_limited_equipped:','');
        return get_leveled_quantity(spec['provides_limited_equipped'][thing]||0, level);
    } else if(stat.indexOf('damage_taken_from:') === 0) {
        var thing = stat.replace('damage_taken_from:','');
        if('damage_taken_from' in spec && thing in spec['damage_taken_from']) {
            return get_leveled_quantity(spec['damage_taken_from'][thing], level);
        } else {
            return 1;
        }
    } else if(stat.indexOf('quarry_control_aura:') == 0) {
        var au_specname = stat.replace('quarry_control_aura:','');
        var au_data = goog.array.find(spec['quarry_control_auras'], function(au) { return au['spec'] === au_specname; });
        if(!au_data) {
            throw Error('quarry_control_aura "'+au_specname+'" not found in spec "' + spec['name'] + '"');
        }
        return get_leveled_quantity(au_data['strength'], level);

    } else {
        /*
        if(spec['permanent_modstats']) {
            // grab "strength" for this level as the "base"
            var pm_list = spec['permanent_modstats'];
            if(pm_list.length >= 1 && (Array.isArray(pm_list[0]) || pm_list[0] === null)) {
                pm_list = get_leveled_quantity(pm_list, level);
            }
            for(var i = 0; i < pm_list.length; i++) {
                var pm = pm_list[i];
                if(pm['stat'] === stat) {
                    return get_leveled_quantity(pm['strength'], level);
                }
            }
        }
        */

        return 1;
    }
};

/** @param {ModChain.ModChain} modchain
    @param {string} method
    @param {?} strength
    @param {string} kind
    @param {string} source
    @param {Object=} props */
ModChain.add_mod = function(modchain, method, strength, kind, source, props) {
    var lastval = modchain['val'];
    var newval;
    if(method == '*=(1-strength)') {
        if(strength == 0) { return modchain; }
        newval = lastval*(1-strength);
    } else if(method == '*=(1+strength)') {
        if(strength == 0) { return modchain; }
        newval = lastval*(1+strength);
    } else if(method == '*=strength') {
        if(strength == 1) { return modchain; }
        newval = lastval*strength;
    } else if(method == '+=strength') {
        if(strength == 0) { return modchain; }
        newval = lastval+strength;
    } else if(method == 'max') {
        newval = Math.max(lastval, strength);
    } else if(method == 'min') {
        if(lastval < 0) {
            newval = strength;
        } else {
            newval = Math.min(lastval, strength);
        }
    } else if(method == 'replace') {
        newval = strength;
    } else if(method == 'concat') {
        if(lastval) {
            newval = lastval.concat(strength);
        } else {
            newval = strength;
        }
    } else {
        throw Error('unknown method '+method);
    }
    var mod = {'kind':kind, 'source':source, 'method':method, 'strength':strength, 'val':newval};
    if(props) { for(var k in props) { mod[k] = props[k]; } }
    modchain['val'] = newval;
    modchain['mods'].push(mod);
    return modchain;
};

ModChain.get_stat = function(modchain, default_value) {
    if(modchain) { return modchain['val']; }
    return default_value;
};

/** Same as add_mod(), but if a matching kind/source exists, replace it instead of appending
    @param {ModChain.ModChain} modchain
    @param {string} method
    @param {?} strength
    @param {string} kind
    @param {string} source
    @param {Object=} props */
ModChain.add_or_replace_mod = function(modchain, method, strength, kind, source, props) {
    var ret;

    var existing_index = (modchain ? goog.array.findIndex(modchain['mods'], function(mod) {
        return (mod['kind'] === kind) && (mod['source'] === source);
    }) : -1);

    if(existing_index >= 0) {
        // rebuild the chain, skipping the step at "index"
        var new_chain = {'val': modchain['mods'][0]['val'], 'mods': [modchain['mods'][0]]};
        for(var i = 1; i < modchain['mods'].length; i++) {
            var mod = modchain['mods'][i];
            var new_props = {};
            goog.array.forEach(ModChain.persistent_props, function(p) {
                if(p in mod) { new_props[p] = mod[p]; }
            });
            var new_strength = mod['strength'];
            if(i == existing_index) {
                if(mod['method'] !== method) { throw Error('method does not match'); }
                new_strength = strength; // use provided updated strength
                new_props = props; // use provided props
            }
            ModChain.add_mod(new_chain, mod['method'], new_strength, mod['kind'], mod['source'], new_props);
        }
        ret = new_chain;
    } else {
        ret = ModChain.add_mod(modchain, method, strength, kind, source, props);
    }
    ModChain.check_chain(ret);
    return ret;
};

/** @param {?} base_val
    @param {Object=} props
    @return {!ModChain.ModChain} */
ModChain.make_chain = function(base_val, props) {
    var mod = {'kind': 'base', 'val':base_val};
    if(props) { for(var k in props) { mod[k] = props[k]; } }
    return {'val':base_val, 'mods':[mod]};
};

/** @param {!ModChain.ModChain} chain
    @return {!ModChain.ModChain} */
ModChain.clone = function(chain) {
    var ret = {};
    for(var k in chain) {
        if(k === 'mods') {
            ret[k] = goog.array.clone(chain['mods']);
        } else {
            ret[k] = chain[k];
        }
    }
    return ret;
};

/** Throw an exception if something is broken in the chain data structure
    @param {!ModChain.ModChain} chain */
ModChain.check_chain = function(chain) {
    goog.array.forEach(chain['mods'], function(mod) {
        if((mod['kind'] !== 'base') && (!('strength' in mod) || mod['strength'] === undefined)) {
            throw Error('mod without "strength": '+JSON.stringify(chain));
        }
    });
};

// names of chain step properties to copy when copying to duplicate a chain
ModChain.persistent_props = ['level', 'end_time', 'effect'];

// apply the same stat modifiers in a chain to a new base value
ModChain.recompute_with_new_base_val = function(old_chain, new_base, new_base_level) {
    var new_chain = ModChain.make_chain(new_base, {'level':new_base_level});
    // add each mod from the old chain
    for(var i = 1; i < old_chain['mods'].length; i++) {
        var mod = old_chain['mods'][i];
        var props = {};
        goog.array.forEach(ModChain.persistent_props, function(p) {
            if(p in mod) { props[p] = mod[p]; }
        });
        ModChain.add_mod(new_chain, mod['method'], mod['strength'], mod['kind'], mod['source'], props);
    }
    ModChain.check_chain(new_chain);
    return new_chain;
};

/** Return copy of the chain but without the mod at index "index"
    @param {!ModChain.ModChain} old_chain
    @param {number} index
    @return {!ModChain.ModChain} */
ModChain.recompute_without_mod = function(old_chain, index) {
    var new_chain = ModChain.make_chain(old_chain['mods'][0]['val'], old_chain['mods'][0]['level'] ? {'level': old_chain['mods'][0]['level']} : null);
    // add each mod from the old chain
    for(var i = 1; i < old_chain['mods'].length; i++) {
        if(i === index) { continue; }
        var mod = old_chain['mods'][i];
        var props = {};
        goog.array.forEach(ModChain.persistent_props, function(p) {
            if(p in mod) { props[p] = mod[p]; }
        });
        ModChain.add_mod(new_chain, mod['method'], mod['strength'], mod['kind'], mod['source'], props);
    }
    ModChain.check_chain(new_chain);
    return new_chain;
};

// OK to reference gamedata directly for GUI-only stuff

/** Return textual description of an on_destroy/on_damage/on_approach modstat, which usually means a security team
    @param {string} condition
    @param {Array.<!Object>|null} value
    @param {string} context
    @param {number|null=} ui_mod_level */
ModChain.display_value_secteam = function(condition, value, context, ui_mod_level) {
    if(!value) { return gamedata['strings']['modstats']['none']; }
    if(context == 'widget') {
        var ret = gamedata['strings']['modstats']['on_destroy_widget'];
        if(ui_mod_level) {
            ret = ret.replace('%level', ui_mod_level.toString());
        }
        return ret;
    }
    var total = [];
    for(var i = 0; i < value.length; i++) {
        var val = value[i], v;
        if(val['consequent'] == 'SPAWN_SECURITY_TEAM') {
            var units = [];
            for(var specname in val['units']) {
                var entry = val['units'][specname];
                var qty;
                var ui_level = '';
                if(typeof(entry) === 'number') {
                    qty = entry;
                } else if('qty' in entry) {
                    qty = entry['qty'];
                    if('force_level' in entry) {
                        ui_level = ' L'+entry['force_level'].toString();
                    }
                }
                units.push(gamedata['strings']['modstats']['security_team_unit'].replace('%qty', qty.toString()).replace('%name', gamedata['units'][specname]['ui_name'] + ui_level));
            }
            v = gamedata['strings']['modstats']['security_team'].replace('%units', units.join(', '));
            if(val['persist']) {
                v += ' '+gamedata['strings']['modstats']['security_team_persist'];
            }
        } else {
            throw Error('unhandled '+condition+' consequent '+(val['consequent']||'UNKNOWN').toString());
        }
        total.push(v);
    }
    return total.join(', ');
};

/** Parse "pct.2" decimal precision values from strings.json
    @param {string} mode_string
    @return {{mode: string, precision: number, invert_sign: number}} */
ModChain.parse_display_mode = function(mode_string) {
    var temp = mode_string.split('.');
    var mode = temp[0];
    var precision = (temp.length >= 2 ? parseInt(temp[1],10) : 0);
    return {mode: mode, precision: precision,
            // -1 if lower values actually increase the stat, otherwise 1
            invert_sign: (goog.array.contains(['one_minus_pct'], mode) ? -1 : 1)};
};

/** Return a textual description of the final post-modification value of a stat
    @param {?} value
    @param {string|null} display_mode
    @param {string} context
    @param {number|null=} ui_mod_level - optional hint to show in the display
                          (this is the "level" of the whole modchain, used for enhancements)
*/
ModChain.display_value = function(value, display_mode, context, ui_mod_level) {
    var ui_value;
    if(display_mode) {
        var parsed = ModChain.parse_display_mode(display_mode);

        if(parsed.mode == 'one_minus_pct') {
            ui_value = (100*(1-value)).toFixed(parsed.precision)+'%';
        } else if(parsed.mode == 'pct') {
            ui_value = (100*value).toFixed(parsed.precision)+'%';
        } else if(parsed.mode == 'pct_minus_one') {
            ui_value = (100*(value-1)).toFixed(parsed.precision)+'%';
        } else if(parsed.mode == 'integer') {
            ui_value = pretty_print_number(value);
        } else if(parsed.mode == 'fixed') {
            ui_value = value.toFixed(parsed.precision);
        } else if(parsed.mode == 'boolean') {
            ui_value = (value ? '\u2713' : 'X'); // use Unicode checkmark to indicate "yes"
        } else if(parsed.mode == 'spellname') {
            if(!value) {
                ui_value = '-';
            } else {
                if(!(value in gamedata['spells'])) { throw Error('bad value for spellname modstat: '+(value ? value.toString() : 'null')); }
                ui_value = gamedata['spells'][value]['ui_name'];
            }
        } else if(parsed.mode == 'auras') {
            if(value === null) {
                ui_value = '';
            } else {
                var ui_list = [];
                goog.array.forEach(value, function(data) {
                    if(!(data['aura_name'] in gamedata['auras'])) { throw Error('bad value for aura modstat: '+data['aura_name'].toString()); }
                    var spec = gamedata['auras'][data['aura_name']];
                    var ui_aura = (context == 'widget' && ('ui_name_short' in spec)) ? spec['ui_name_short'] : spec['ui_name'];

                    // add strength info
                    if(context != 'widget') {
                        var ui_pct = '';
                        // XXX somehow this needs to cascade back to the outer parse code
                        if('ui_strength' in data && typeof(data['ui_strength']) === 'number') {
                            ui_pct = (100 * data['ui_strength']).toFixed(parsed.precision).toString() + '%';
                            ui_aura += ' ' + ui_pct;
                        } else if('aura_strength' in data && typeof(data['aura_strength']) === 'number') {
                            ui_pct = (100 * data['aura_strength']).toFixed(parsed.precision).toString() + '%';
                            ui_aura += ' ' + ui_pct;
                        }
                        if('ui_description' in data) {
                            ui_aura += '\n'+data['ui_description'].replace('%pct', ui_pct);
                        } else {
                            ui_aura += '\n'+spec['ui_description'].replace('%pct', ui_pct);
                        }
                    }

                    ui_list.push(ui_aura);
                });
                ui_value = ui_list.join(', ');
            }
        } else if (parsed.mode == 'auraname') {
            if(value === null) {
                ui_value = '';
            } else {
                var spec = gamedata['auras'][value['spec']];
                var ui_aura = (context == 'widget' && ('ui_name_short' in spec)) ? spec['ui_name_short'] : spec['ui_name'];
                // add strength and duration info
                if(context != 'widget') {
                    var ui_duration = '';
                    var ui_pct = '';
                    if('strength' in value && typeof(value['strength']) === 'number') {
                        ui_pct = (100 * value['strength']).toFixed(parsed.precision).toString() + '%';
                    }
                    if('duration' in value && typeof(value['duration']) === 'number') {
                        ui_duration = (value['duration']).toFixed(parsed.precision).toString() + ' seconds';
                    }
                    ui_aura += '\n' + spec['ui_description'].replace('%pct', ui_pct).replace('%dur', ui_duration);
                    var zero_duration_targets = [];
                    if('duration_vs' in value && typeof(value['duration_vs']) === 'object') {
                        for (var unit_type in value['duration_vs']) {
                            if(value['duration_vs'][unit_type] <= 0) {
                                zero_duration_targets.push(ModChain.get_zero_duration_ui_name(unit_type));
                            }
                        }
                    }
                    if(zero_duration_targets.length > 0) {
                        ui_aura += ModChain.get_zero_duration_label(zero_duration_targets);
                    }


                }
                ui_value = ui_aura;
            }
        } else if(parsed.mode == 'on_destroy' || parsed.mode == 'on_damage' || parsed.mode == 'on_approach') {
            return ModChain.display_value_secteam(parsed.mode, value, context, ui_mod_level);
        } else if(parsed.mode == 'literal') {
            ui_value = value.toString();
        } else {
            throw Error('unknown display mode '+parsed.mode);
        }
    } else {
        // no mode given, just show as a literal
        ui_value = value.toString();
    }
    return ui_value;
};

/** Return a plain-text lavel of no-effect targets for impact_auras that don't affect every target type
    @param {Array} zero_duration_targets
    @return {string} */
ModChain.get_zero_duration_label = function(zero_duration_targets) {
    if(zero_duration_targets.length === 1) { return '\nNo effect against ' + zero_duration_targets[0] + '.'; }
    if(zero_duration_targets.length === 2) { return '\nNo effect against ' + zero_duration_targets[0] + ' and ' + zero_duration_targets[1] + '.'; }
    var zero_duration_label = '\nNo effect against ';
    for(var i = 0; i < zero_duration_targets.length - 1; i++) {
        zero_duration_label += zero_duration_targets[i] + ', ';
    }
    zero_duration_label += 'and ' + zero_duration_targets[zero_duration_targets.length - 1] + '.';
    return zero_duration_label;
}

/** Return the ui_name of plain-text lavel of no-effect targets for impact_auras that don't affect every target type
    @param {string} kind
    @return {string} */
ModChain.get_zero_duration_ui_name = function(kind) {
    if(kind in gamedata['strings']['defense_types']) { return gamedata['strings']['defense_types'][kind]['ui_name_plural']; }
    var ui_name = '';
    if(kind.indexOf(',') !== -1) {
        var terms = kind.split(',');
        ui_name = ModChain.get_zero_duration_ui_name(terms[0]);
        for(var j = 1; j < terms.length; j++) {
            var term = terms[j];
            ui_name += ' that are ';
            if(term[0] === '!') {
                ui_name += 'not ';
                term = term.slice(1);
            }
            ui_name += ModChain.get_zero_duration_ui_name(term);
        }
    }
    return ui_name;
}

/** Return a plain-text description of a percentage delta in a stat with appropriate precision
    @param {number} strength
    @param {number} min_precision
    @return {string} */
ModChain.display_delta_percent = function(strength, min_precision) {
    var val = Math.abs(strength);
    // awkward: use additional precision, if necessary, to show deltas like 2.4%
    var ret = (100*val).toFixed(min_precision);
    for(var prec = min_precision+1; prec < 3; prec += 1) {
        var v2 = (100*val).toFixed(prec);
        if(v2[v2.length-1] == '0') {
            break;
        }
        ret = v2;
    }
    if(ret.indexOf('NaN') !== -1) { throw Error('stat displayed as NaN! strength '+JSON.stringify(strength)+' min_precision '+JSON.stringify(min_precision)); }
    return ret+'%';
};

/** Return a plain-text description of the CHANGE in a stat due to a mod, and a flag for whether it's better or worse after the delta
    @param {?} strength
    @param {string|null} display_mode - display_mode from strings.json
    @param {string} method - the modification method
    @param {?=} cur_value - current value on mod chain, for fallback case where we don't know the chain method
    @param {?=} prev_value - previous value on mod chain, just for showing concat as "+"
    @return {{ui_delta: string, is_better: boolean, is_different: boolean}}
*/
ModChain.display_delta = function(strength, display_mode, method, cur_value, prev_value) {
    var parsed = (display_mode ? ModChain.parse_display_mode(display_mode) : null);
    var ui_delta = '';
    var is_better = true;
    var is_different = true;

    if(method == '*=(1-strength)') {
        is_better = parsed.invert_sign*strength < 0;
        is_different = (strength != 0);
        ui_delta = (is_better ? '+' : '-') + ModChain.display_delta_percent(strength, parsed.precision);
    } else if(method == '*=(1+strength)') {
        is_better = parsed.invert_sign*strength >= 0;
        is_different = (strength != 0);
        ui_delta = (is_better ? '+' : '-') + ModChain.display_delta_percent(strength, parsed.precision);
    } else if(method == '*=strength') {
        is_better = parsed.invert_sign*strength >= 0;
        is_different = (strength != 1);
        ui_delta = (is_better ? '' : '-') + ModChain.display_delta_percent(strength, parsed.precision);
    } else if(method == 'replace') {
        ui_delta = ModChain.display_value(strength, display_mode, 'tooltip');
    } else if(method == 'concat') {
        ui_delta = (prev_value ? '+ ' : '') + ModChain.display_value(strength, display_mode, 'tooltip');
    } else {
        if(cur_value === undefined || prev_value === undefined) { throw Error('unknown method '+method+' and no cur/prev values'); }
        var delta = cur_value - prev_value;
        is_better = delta >= 0;
        is_different = (cur_value != prev_value);
        ui_delta = (is_better ? '+' : '-') + ModChain.display_value(Math.abs(delta), display_mode, 'tooltip'); // .toString();
    }
    return {ui_delta:ui_delta, is_better:is_better, is_different: is_different};
};

/** Given an (equip or aura) effect like {"code":"modstat", "stat":"foo", ...}, return a BBCode textual description of what the effect does.
    @param {!Object} effect
    @param {number} level
    @return {{ui_effect: string, is_better: boolean, is_different: boolean}} */
ModChain.display_modstat_effect = function(effect, level) {
    if(effect['code'] != 'modstat') { throw Error('invalid effect code '+effect['code']); }
    if(!(effect['stat'] in gamedata['strings']['modstats']['stats'])) { throw Error('unknown stat '+effect['stat']); }
    var ui_data = gamedata['strings']['modstats']['stats'][effect['stat']];

    var strength = get_leveled_quantity(effect['strength'], level);
    var affected_data, affected_key; // look up strings
    if(effect['affects']) {
        affected_data = gamedata['strings']['modstats']['affects'];
        affected_key = effect['affects'];
    } else if(effect['affects_kind']) {
        affected_data = gamedata['strings']['modstats']['affects_kind'];
        affected_key = effect['affects_kind'];
    } else if(effect['affects_building']) {
        affected_data = gamedata['strings']['modstats']['affects_building'];
        if(typeof effect['affects_building'] == 'object') { // array
            affected_key = effect['affects_building'].join(',');
        } else {
            affected_key = effect['affects_building'];
        }
    } else {
        throw Error('error parsing effect affects '+JSON.stringify(effect));
    }
    if(!(affected_key in affected_data)) {
        throw Error('affected_key '+affected_key+' not found in gamedata.strings.modstats');
    }

    var ui_affected = affected_data[affected_key];
    var ui_stat = ui_data['ui_name'];
    var delta = ModChain.display_delta(strength, ui_data['display']||null, effect['method']);

    var ret = gamedata['strings']['modstats'][delta.is_better ? 'effect' : 'effect_worse'].replace('%affected', ui_affected).replace('%stat', ui_stat).replace('%delta', delta.ui_delta);
    return {ui_effect: ret, is_better: delta.is_better, is_different: delta.is_different};
};


/** Return the full multi-line plain-text tooltip describing an entire modchain
    @param {string} stat
    @param {?} modchain
    @param {boolean} show_base
    @param {!Object} ui_data
    @return {string} */
ModChain.display_tooltip = function(stat, modchain, show_base, ui_data) {
    var display_mode = ui_data['display'] || null;
    ModChain.check_chain(modchain);

    var ui_base = ModChain.display_value(modchain['val'], display_mode, 'tooltip');

        var ls = [];
        goog.array.forEach(modchain['mods'], function(mod, i) {

            if(mod['kind'] == 'base') {
                if(i != 0) { throw Error('base mod is not first in chain'); }
                if(show_base) {
                    var fmt = gamedata['strings']['modstats']['base_value'].replace('%stat', ui_data['ui_name']);
                    ls.push(fmt.replace('%value', ModChain.display_value(mod['val'], display_mode, 'tooltip')).replace('%level', mod['level'].toString()));
                }
            } else {
                var fmt = gamedata['strings']['modstats']['mod_value'];
                if(i <= 0) { throw Error('non-base mod is first in chain'); }
                if(i == 1) {
                    if(show_base) { ls.push(''); } // make spacing look nice
                    ls.push(gamedata['strings']['modstats']['bonuses']);
                }
                if(!mod || mod['strength'] === undefined) { throw Error('bad mod: '+JSON.stringify(mod)+' IN '+JSON.stringify(modchain)); }

                var ui_delta = ModChain.display_delta(mod['strength'], display_mode, mod['method'], mod['val'], modchain['mods'][i-1]['val']).ui_delta;

                if(mod['kind'] == 'equipment') {
                    var espec = gamedata['items'][mod['source']];

                    // look for set bonus
                    var item_set = null, item_set_min = -1;
                    if('effect' in mod) {
                        var effect = espec['equip']['effects'][mod['effect']];
                        if(('apply_if' in effect) && effect['apply_if']['predicate'] == 'HAS_ITEM_SET') {
                            item_set = gamedata['item_sets'][effect['apply_if']['item_set']];
                            if('min' in effect['apply_if']) { item_set_min = effect['apply_if']['min']; }
                        }
                    }
                    if(item_set) {
                        fmt = gamedata['strings']['modstats']['mod_value_item_set'];
                    }
                    var s = fmt.replace('%delta',ui_delta).replace('%thing', espec['ui_name']);
                    if(item_set) {
                        s = s.replace('%itemset', item_set['ui_name']);
                        s = s.replace('%setcur', (item_set_min > 0 ? item_set_min : player.stattab['item_sets'][item_set['name']]).toString());
                        s = s.replace('%setmax', item_set['members'].length.toString());
                    }
                    ls.push(s);
                } else if(mod['kind'] == 'building') {
                    var bspec = gamedata['buildings'][mod['source']];
                    ls.push(fmt.replace('%delta',ui_delta).replace('%thing', bspec['ui_name'] + ' L'+mod['level'].toString()));
                } else if(mod['kind'] == 'tech') {
                    var tspec = gamedata['tech'][mod['source']];
                    ls.push(fmt.replace('%delta',ui_delta).replace('%thing', tspec['ui_name'] + ' L'+mod['level'].toString()));
                } else if(mod['kind'] == 'enhancement') {
                    var espec = gamedata['enhancements'][mod['source']];
                    ls.push(fmt.replace('%delta',ui_delta).replace('%thing', espec['ui_name'] + ' L'+mod['level'].toString()));
                } else if(mod['kind'] == 'aura') {
                    var togo = null;
                    if((mod['end_time']||-1) > 0) {
                        fmt = gamedata['strings']['modstats']['mod_value_ends'];
                        togo = pretty_print_time(mod['end_time']-server_time);
                    }
                    var aspec = gamedata['auras'][mod['source']];
                    var s = fmt.replace('%delta',ui_delta).replace('%thing', aspec['ui_name'].replace('%level', (mod['level']||1).toString()));
                    if(togo) { s = s.replace('%togo', togo); }
                    ls.push(s);
                } else {
                    throw Error('unknown mod kind '+mod['kind']);
                }
            }
        });
        var ui_mods = ls.join(gamedata['strings']['modstats']['mod_value_sep']);
        return ui_mods;
};

/** Set a SPUI TextWidget to display the right text label and tooltip for a stat
    @param {!SPUI.TextWidget} widget
    @param {string} stat
    @param {Object?} auto_spell
    @param {boolean} enable_tooltip */
ModChain.display_label_widget = function(widget, stat, auto_spell, enable_tooltip) {
    // flip over to a different variant for one-shot weapons
    if(stat == 'weapon_damage' && auto_spell && auto_spell['kills_self']) {
        stat = 'weapon_damage_kills_self';
    } else if(stat == 'weapon_range') {
        if(!auto_spell) {
            // this is a range modifier for a mounted weapon that will mod the weapon spell later
            stat = 'weapon_range_modifier';
        } else if(auto_spell['code'] === 'pbaoe') {
            // flip over to a different variant for point-blank AoE weapons
            stat = 'weapon_range_pbaoe'; // this is the trigger range, not the harmful radius
        }
    } else if (stat.indexOf('impact_auras') === 0) {
        // switch to impact_auras if it's an impact aura
        stat = 'impact_auras';
        enable_tooltip = false;
    }

    var ui_data = gamedata['strings']['modstats']['stats'][stat];
    if(!ui_data) { throw Error('gamedata.strings.modstats missing stat '+stat); }

    widget.str = ui_data['ui_name'];
    if(widget.tooltip) {
        widget.tooltip.str = (enable_tooltip ? ui_data['ui_tooltip'] : null);
    }
};

/** get SPUI widget settings for a nice GUI display of a modified stat, including bigass explanatory tooltip
    @param {string} stat
    @param {Object|null} modchain
    @param {Object} spec
    @param {number} level
    @param {Object} auto_spell
    @param {number} auto_spell_level
    @return {{str:string,
              value:?,
              tooltip:string,
              color:SPUI.Color}}
*/
ModChain.display_value_detailed = function(stat, modchain, spec, level, auto_spell, auto_spell_level) {
    if(!modchain) {
        modchain = ModChain.make_chain(ModChain.get_base_value(stat, spec, level), {'level':level});
    }
    var ui_data = gamedata['strings']['modstats']['stats'][stat];
    var extra = null;
    var show_base = false;

    // don't bother showing "base" values for stats that are not part of the spec
    if(stat in spec) {
        show_base = true;
    } else if(stat.indexOf('damage_taken_from:') === 0 &&
              'damage_taken_from' in spec &&
              stat.split(':')[1] in spec['damage_taken_from']) {
        show_base = true;
    }

    // special case for weapon stats - these go into combat stats, so their "base" value is actually something like 1.0
    // recompute them with base values taken from the actual auto_spell stats
    if(stat == 'weapon_damage') {
        show_base = true;
        var spell = auto_spell;
        if(!spell) { throw Error('Attempting display_value_detailed for spec ' + spec['name'] + ' but it has no valid auto_spell'); }
        var base_dps = get_leveled_quantity(spell['damage'], auto_spell_level);

        if(spell['kills_self']) {
            // flip over to a different variant for one-shot weapons
            ui_data = gamedata['strings']['modstats']['stats']['weapon_damage_kills_self'];
        }

        // add DoT damage
        if('impact_auras' in spell) {
            goog.array.forEach(spell['impact_auras'], function(aura_data) {
                var aura = gamedata['auras'][aura_data['spec']];
                var is_dot = false;
                if('effects' in aura) {
                    goog.array.forEach(aura['effects'], function(effect) {
                        if(effect['code'] == 'on_fire') {
                            is_dot = true;
                        }
                    });
                }
                if(is_dot) {
                    base_dps += Math.floor(get_leveled_quantity(/*spell['impact_aura_duration'] ||*/ 1, auto_spell_level) *
                                           get_leveled_quantity(aura_data['strength'] || 1, auto_spell_level));
                }
            });
        }

        var base_cooldown = get_leveled_quantity(spell['cooldown']||1, auto_spell_level); // might need fixing if we ever have cooldown mods
        if(base_cooldown === undefined) {
            throw Error('spell cooldown undefined at level '+auto_spell_level.toString()+': '+spell['name']);
        }
        var base_per_shot = base_dps * base_cooldown;
        modchain = ModChain.recompute_with_new_base_val(modchain, base_dps, level);
        extra = ui_data['ui_extra'].replace('%DPS', ModChain.display_value(modchain['val'], ui_data['display'], 'tooltip')).replace('%SHOT', ModChain.display_value(modchain['val']*base_cooldown, ui_data['display'], 'tooltip')).replace('%COOLDOWN', base_cooldown.toFixed(2));
    } else if(goog.array.contains(['weapon_range','effective_weapon_range','splash_range','min_range','accuracy'], stat)) {
        // special case for weapon stats other than damage
        show_base = !!auto_spell;

        if(stat == 'weapon_range') {
            if(!auto_spell) {
                ui_data = gamedata['strings']['modstats']['stats']['weapon_range_modifier'];

            } else if(auto_spell['code'] === 'pbaoe') {
                // flip over to a different variant for point-blank AoE weapons
                ui_data = gamedata['strings']['modstats']['stats']['weapon_range_pbaoe']; // this is the trigger range, not the harmful radius
            }
        }

        // these stats correspond to spell parameters with slightly different names
        var source_stat = {'weapon_range':'range', 'effective_weapon_range':'effective_range'}[stat] || stat;
        // allow manual override of values displayed in GUI, to help with distance unit mismatches
        if(source_stat == 'splash_range' && ('ui_splash_range' in auto_spell)) { source_stat = 'ui_splash_range'; }
        modchain = ModChain.recompute_with_new_base_val(modchain,
                                                        (auto_spell ? get_leveled_quantity(auto_spell[source_stat]||0,auto_spell_level)
                                                         : ModChain.get_base_value(stat, spec, level)),
                                                        level);
    } else if(stat == 'weapon') {
        show_base = true;
    } else if (stat.indexOf('impact_auras') === 0) {
        // weapon impact auras pass the aura name as part of the stat, which needs to be stripped out for the correct ui_data
        ui_data = gamedata['strings']['modstats']['stats']['impact_auras'];
        ui_data['ui_tooltip'] = ModChain.display_value(modchain['val'], ui_data['display'], 'tooltip');
    }

    ModChain.check_chain(modchain);

    var color = SPUI.default_text_color;

    // has final stat changed from base value? if so, alter color
    if(modchain['mods'].length>1 && modchain['val'] != modchain['mods'][0]['val']) {
        var is_worse = false;
        if(typeof(modchain['val']) === 'number') {
            if(modchain['val'] < modchain['mods'][0]['val']) {
                is_worse = true;
            }
            if((ui_data['better']||1) < 0) {
                is_worse = !is_worse;
            }
        }
        color = (is_worse ? SPUI.make_colorv([1,1,0,1]) : SPUI.good_text_color);
    }

    if((stat === 'on_destroy' || stat === 'on_approach' || stat === 'on_damage') && modchain['mods'].length > 1) {
        for(var i = 0; i < modchain['mods'].length; i ++) {
            var mod = modchain['mods'][i];
            if(mod.method && mod.method === 'replace') { show_base = false; }
        }
    }

    return {str: ModChain.display_value(modchain['val'], ui_data['display']||null, 'widget', ModChain.get_ui_mod_level(modchain)),
            value: modchain['val'],
            tooltip: gamedata['strings']['modstats']['tooltip_'+(!show_base && (modchain['mods'].length<2) ? 'base':'mods')].replace('%NAME', ui_data['ui_name']).replace('%DESCRIPTION', ui_data['ui_tooltip']).replace('%MODS', ModChain.display_tooltip(stat, modchain, show_base, ui_data)) + (extra ? '\n\n'+extra : ''),
            color: color};
};

/** @param {Object|null} modchain
    @return {number|null} */
ModChain.get_ui_mod_level = function(modchain) {
    if(!modchain) { return null; }
    var ret = 0;
    goog.array.forEach(modchain['mods'], function(mod) {
        if('level' in mod &&
           (mod['kind'] === 'tech' ||
            mod['kind'] === 'enhancement')) {
            ret = Math.max(ret, mod['level']);
        }
    });
    return (ret > 0 ? ret : null);
};

/** same as above, and then apply to a SPUI widget
    @param {SPUI.DialogWidget} widget
    @param {string} stat
    @param {Object|null} modchain
    @param {Object} spec
    @param {number} level
    @param {Object} auto_spell
    @param {number} auto_spell_level
    @param {boolean} enable_tooltip
*/
ModChain.display_widget = function(widget, stat, modchain, spec, level, auto_spell, auto_spell_level, enable_tooltip) {
    var detail = ModChain.display_value_detailed(stat, modchain, spec, level, auto_spell, auto_spell_level);
    widget.str = detail.str;
    widget.tooltip.str = (enable_tooltip ? detail.tooltip : null);
    widget.text_color = detail.color;
};
