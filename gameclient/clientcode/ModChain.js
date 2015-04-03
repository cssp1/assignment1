goog.provide('ModChain');

// Copyright (c) 2015 SpinPunch. All rights reserved.
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
    if(stat in spec) {
        return get_leveled_quantity(spec[stat], level);
    } else if(stat == 'armor') { // annoying special cases
        return 0;
    } else if(stat == 'permanent_auras') {
        return null;
    } else if(stat == 'on_destroy') {
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
    } else {
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
        newval = lastval*(1-strength);
    } else if(method == '*=(1+strength)') {
        newval = lastval*(1+strength);
    } else if(method == '*=strength') {
        newval = lastval*strength;
    } else if(method == '+=strength') {
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

/** @param {?} base_val
    @param {Object=} props
    @return {ModChain.ModChain} */
ModChain.make_chain = function(base_val, props) {
    var mod = {'kind': 'base', 'val':base_val};
    if(props) { for(var k in props) { mod[k] = props[k]; } }
    return {'val':base_val, 'mods':[mod]};
};

// apply the same stat modifiers in a chain to a new base value
ModChain.recompute_with_new_base_val = function(old_chain, new_base, new_base_level) {
    var new_chain = ModChain.make_chain(new_base, {'level':new_base_level});
    // add each mod from the old chain
    for(var i = 1; i < old_chain['mods'].length; i++) {
        var mod = old_chain['mods'][i];
        var props = {};
        goog.array.forEach(['level','end_time','effect'], function(p) {
            if(p in mod) { props[p] = mod[p]; }
        });
        ModChain.add_mod(new_chain, mod['method'], mod['strength'], mod['kind'], mod['source'], props);
    }
    return new_chain;
};


// OK to reference gamedata directly for GUI-only stuff

ModChain.display_value_on_destroy = function(value, context) {
    if(!value) { return gamedata['strings']['modstats']['none']; }
    if(context == 'widget') { return gamedata['strings']['modstats']['on_destroy_widget']; }
    var total = [];
    for(var i = 0; i < value.length; i++) {
        var val = value[i], v;
        if(val['consequent'] == 'SPAWN_SECURITY_TEAM') {
            var units = [];
            for(var specname in val['units']) {
                units.push(gamedata['strings']['modstats']['security_team_unit'].replace('%qty', val['units'][specname].toString()).replace('%name', gamedata['units'][specname]['ui_name']));
            }
            v = gamedata['strings']['modstats']['security_team'].replace('%units', units.join(', '));
        } else {
            throw Error('unhandled on_destroy consequent '+(val['consequent']||'UNKNOWN').toString());
        }
        total.push(v);
    }
    return total.join(', ');
};

ModChain.display_value = function(value, mode, context) {
    var ui_value;
    if(mode) {
        if(mode == 'one_minus_pct') {
            ui_value = (100*(1-value)).toFixed(0)+'%';
        } else if(mode == 'pct') {
            ui_value = (100*value).toFixed(0)+'%';
        } else if(mode == 'pct.1') {
            ui_value = (100*value).toFixed(1)+'%';
        } else if(mode == 'integer') {
            ui_value = pretty_print_number(value);
        } else if(mode == 'fixed:2') {
            ui_value = value.toFixed(2);
        } else if(mode == 'boolean') {
            ui_value = (value ? '\u2713' : 'X'); // use Unicode checkmark to indicate "yes"
        } else if(mode == 'spellname') {
            if(!value) {
                ui_value = '-';
            } else {
                if(!(value in gamedata['spells'])) { throw Error('bad value for spellname modstat: '+(value ? value.toString() : 'null')); }
                ui_value = gamedata['spells'][value]['ui_name'];
            }
        } else if(mode == 'auras') {
            var ui_list = [];
            goog.array.forEach(value, function(data) {
                if(!(data['aura_name'] in gamedata['auras'])) { throw Error('bad value for aura modstat: '+data['aura_name'].toString()); }
                var spec = gamedata['auras'][data['aura_name']];
                ui_list.push((context == 'widget' && ('ui_name_short' in spec)) ? spec['ui_name_short'] : spec['ui_name']);
            });
            ui_value = ui_list.join(', ');
        } else if(mode == 'on_destroy') {
            return ModChain.display_value_on_destroy(value, context);
        } else if(mode == 'literal') {
            ui_value = value.toString();
        } else {
            throw Error('unknown display mode '+mode);
        }
    } else {
        ui_value = value.toString();
    }
    return ui_value;
};

ModChain.display_tooltip = function(stat, modchain, show_base, ui_data) {
    var display_mode = ui_data['display'] || null;
    var ui_base = ModChain.display_value(modchain['val'], display_mode, 'tooltip');
    if(0 && modchain['mods'].length < 2) {
        return gamedata['strings']['modstats']['base_value'].replace('%value', ui_base).replace('%level', modchain['mods'][0]['level'].toString());
    } else {
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
                var ui_delta = '';
                var invert_sign = (display_mode == 'one_minus_pct' ? -1 : 1);

                if(mod['method'] == '*=(1-strength)') {
                    ui_delta = (invert_sign*mod['strength'] < 0 ? '+' : '-') + (100*(Math.abs(mod['strength']))).toFixed(0)+'%';
                } else if(mod['method'] == '*=(1+strength)') {
                    ui_delta = (invert_sign*mod['strength'] >= 0 ? '+' : '-') + (100*(Math.abs(mod['strength']))).toFixed(0)+'%';
                } else if(mod['method'] == '*=strength') {
                    ui_delta = (invert_sign*mod['strength'] >= 0 ? '' : '-') + (100*(Math.abs(mod['strength']))).toFixed(0)+'%';
                } else if(mod['method'] == 'replace') {
                    ui_delta = ModChain.display_value(mod['strength'], display_mode, 'tooltip');
                } else if(mod['method'] == 'concat') {
                    ui_delta = (modchain['mods'][i-1]['val'] ? '+ ' : '') + ModChain.display_value(mod['strength'], display_mode, 'tooltip');
                } else {
                    var delta = mod['val'] - modchain['mods'][i-1]['val'];
                    ui_delta = (delta >= 0 ? '+' : '-') + ModChain.display_value(Math.abs(delta), display_mode, 'tooltip'); // .toString();
                }

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
                } else if(mod['kind'] == 'aura') {
                    var togo = null;
                    if((mod['end_time']||-1) > 0) {
                        fmt = gamedata['strings']['modstats']['mod_value_ends'];
                        togo = pretty_print_time(mod['end_time']-server_time);
                    }
                    var aspec = gamedata['auras'][mod['source']];
                    var s = fmt.replace('%delta',ui_delta).replace('%thing', aspec['ui_name']);
                    if(togo) { s = s.replace('%togo', togo); }
                    ls.push(s);
                } else {
                    throw Error('unknown mod kind '+mod['kind']);
                }
            }
        });
        var ui_mods = ls.join(gamedata['strings']['modstats']['mod_value_sep']);
        return ui_mods;
    }
};

ModChain.display_label_widget = function(widget, stat, auto_spell) {
    // flip over to a different variant for one-shot weapons
    if(stat == 'weapon_damage' && auto_spell['kills_self']) {
        stat = 'weapon_damage_kills_self';
    }
    var ui_data = gamedata['strings']['modstats']['stats'][stat];
    if(!ui_data) { throw Error('gamedata.strings.modstats missing stat '+stat); }

    widget.str = ui_data['ui_name'];
    if(widget.tooltip) {
        widget.tooltip.str = ui_data['ui_tooltip'];
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
    var show_base = (stat in spec); // don't bother showing "base" values for stats that are not part of the spec

    // special case for weapon stats - these go into combat stats, so their "base" value is actually something like 1.0
    // recompute them with base values taken from the actual auto_spell stats
    if(stat == 'weapon_damage') {
        show_base = true;
        var spell = auto_spell;
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
        var base_per_shot = base_dps * base_cooldown;
        modchain = ModChain.recompute_with_new_base_val(modchain, base_dps, level);
        extra = ui_data['ui_extra'].replace('%DPS', ModChain.display_value(modchain['val'], ui_data['display'], 'tooltip')).replace('%SHOT', ModChain.display_value(modchain['val']*base_cooldown, ui_data['display'], 'tooltip')).replace('%COOLDOWN', base_cooldown.toFixed(2));
    } else if(goog.array.contains(['weapon_range','effective_weapon_range','splash_range','min_range','accuracy'], stat)) {
        // special case for weapon stats other than damage
        show_base = true;
        // these stats correspond to spell parameters with slightly different names
        var source_stat = {'weapon_range':'range', 'effective_weapon_range':'effective_range'}[stat] || stat;
        // allow manual override of values displayed in GUI, to help with distance unit mismatches
        if(source_stat == 'splash_range' && ('ui_splash_range' in auto_spell)) { source_stat = 'ui_splash_range'; }
        modchain = ModChain.recompute_with_new_base_val(modchain, get_leveled_quantity(auto_spell[source_stat]||0,auto_spell_level), level);
    } else if(stat == 'weapon') {
        show_base = true;
    }

    return {str: ModChain.display_value(modchain['val'], ui_data['display']||null, 'widget'),
            value: modchain['val'],
            tooltip: gamedata['strings']['modstats']['tooltip_'+(!show_base && (modchain['mods'].length<2) ? 'base':'mods')].replace('%NAME', ui_data['ui_name']).replace('%DESCRIPTION', ui_data['ui_tooltip']).replace('%MODS', ModChain.display_tooltip(stat, modchain, show_base, ui_data)) + (extra ? '\n\n'+extra : ''),
            color: ((modchain['mods'].length>1 && modchain['val'] != modchain['mods'][0]['val']) ? SPUI.good_text_color : SPUI.default_text_color)};
};

/** same as above, and then apply to a SPUI widget
    @param {SPUI.DialogWidget} widget
    @param {string} stat
    @param {Object|null} modchain
    @param {Object} spec
    @param {number} level
    @param {Object} auto_spell
    @param {number} auto_spell_level
*/
ModChain.display_widget = function(widget, stat, modchain, spec, level, auto_spell, auto_spell_level) {
    var detail = ModChain.display_value_detailed(stat, modchain, spec, level, auto_spell, auto_spell_level);
    widget.str = detail.str;
    widget.tooltip.str = detail.tooltip;
    widget.text_color = detail.color;
};
