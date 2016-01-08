goog.provide('ItemDisplay');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// library that supports the "item_widget" dialog, which is how we
// display items with stack counts, clickable frames, etc.

goog.require('goog.array');
goog.require('SPUI');
goog.require('SPFX');
goog.require('GameArt');
goog.require('ModChain');

// requires from main.js: player.get_any_abtest_value, player.stattab, get_leveled_quantity, Store.display_user_currency_amount, vec_add,
// Store.gamebucks_ui_name(),
// Store.display_user_currency_amount(), Store.convert_credit_price_to_user_currency()
// player.has_item, player.has_item_equipped,
// pretty_print_number, pretty_print_qty_brief, invoke_inventory_context (XXX which should be moved into here)

/** Check if two items represent the same thing
    @return {boolean} */
ItemDisplay.same_item = function(a, b) {
    var a_level = ('level' in a ? a['level'] : 1);
    var b_level = ('level' in b ? b['level'] : 1);
    var a_stack = ('stack' in a ? a['stack'] : 1);
    var b_stack = ('stack' in b ? b['stack'] : 1);
    return (a['spec'] === b['spec'] &&
            a_level === b_level &&
            a_stack === b_stack);
};

/** return gamedata spec for an item by specname, defaulting to unknown_item if not found
    @param {string} specname */
ItemDisplay.get_inventory_item_spec = function(specname) {
    if(!(specname in gamedata['items'])) {
        specname = 'unknown_item';
    }
    return gamedata['items'][specname];
};

/** For items that apply a new weapon to something (e.g. turret heads), return the spellname of the weapon they apply.
    @param {Object} spec
    @return {string|null} the weapon spellname */
ItemDisplay.get_inventory_item_weapon_spellname = function(spec) {
    if('equip' in spec && ('effects' in spec['equip'])) {
        var effect_list = spec['equip']['effects'];
        for(var i = 0; i < effect_list.length; i++) {
            var effect = effect_list[i];
            if(effect['code'] == 'modstat' && (effect['stat'] == 'weapon' || effect['stat'] == 'continuous_cast') && effect['method'] == 'replace') {
                return effect['strength'];
            }
        }
    }
    return null;
};

/** For items that apply a new weapon to something (e.g. turret heads), return the spell of the weapon.
    Throw exception if spell doesn't exist.
    @param {Object} spec
    @return {Object} the weapon spell */
ItemDisplay.get_inventory_item_weapon_spell = function(spec) {
    var name = ItemDisplay.get_inventory_item_weapon_spellname(spec);
    if(name && name in gamedata['spells']) { return gamedata['spells'][name]; }
    throw Error('item spec does not carry a weapon or weapon spellname is invalid: '+spec['name']+' spellname '+(name ? name : 'null'));
};

/** For a crafting recipe that deterministically yields only one item, return the spec of that item.
    Otherwise, return the spec of unknown_crafting_product.
    @param {Object} recipe
    @param {number=} level
    @return {Object} the product spec */
ItemDisplay.get_crafting_recipe_product_spec = function(recipe, level) {
    level = level || 1;
    var product_list;
    if(Array.isArray(recipe['product']) && recipe['product'].length >= 1 && Array.isArray(recipe['product'][0])) { // per-level list
        product_list = get_leveled_quantity(recipe['product'], level);
    } else {
        product_list = recipe['product'];
    }
    if(product_list.length == 1 && ('spec' in product_list[0]) &&
       (product_list[0]['spec'] in gamedata['items'])) { // note: do not use get_inventory_item_spec() because we want to fail for unknown items
        return gamedata['items'][product_list[0]['spec']];
    }
    return gamedata['items']['unknown_crafting_product'];
};

/** given a 50x50 SPUI.StaticImage widget, set the widget's asset/state/alpha to show the item indicated by 'spec' (a spec from gamedata['items'])
   @param {SPUI.DialogWidget} widget
   @param {Object} spec */
ItemDisplay.set_inventory_item_asset = function(widget, spec) {
    var asset, alpha = 1;
    if('icon' in spec) {
        if(spec['icon'] == 'gamebucks_inventory_icon') {
            asset = player.get_any_abtest_value('gamebucks_inventory_icon', gamedata['store']['gamebucks_inventory_icon']);
        } else {
            asset = spec['icon'];
        }
    } else if('unit_icon' in spec) {
        var unit_spec = gamedata['units'][spec['unit_icon']];
        asset = get_leveled_quantity(unit_spec['art_asset'], 1);
        alpha = (unit_spec['cloaked'] ? gamedata['client']['cloaked_opacity'] : 1);
    } else {
        throw Error('unhandled item icon '+spec['name'].toString());
    }
    var state = ('icon' in GameArt.assets[asset].states ? 'icon' : 'normal');
    widget.asset = asset;
    widget.state = state;
    widget.alpha = alpha;
};

/** return what to display on the inventory icon stack counter, e.g. "15,000" or "15K"
    @param {Object} spec
    @param {number} count */
ItemDisplay.get_inventory_item_stack_str = function(spec, count) {
    if(spec['fungible']) {
        if(spec['resource'] == 'gamebucks') {
            return Store.display_user_currency_amount(count, 'compact');
        } else {
            return pretty_print_qty_brief(count).toUpperCase();
        }
    } else {
        return pretty_print_number(count);
    }
};

/** return what to prefix an item name with, e.g. "(15,000x )Tactical Missile" or "(15K ) Iron"
    @param {Object} spec
    @param {number} count */
ItemDisplay.get_inventory_item_stack_prefix = function(spec, count) {
    if(count == 1) {
        return '';
    } else {
        var s = ItemDisplay.get_inventory_item_stack_str(spec, count);
        if(!spec['fungible']) { s += 'x'; }
        return s + ' ';
    }
};

/** return font to use for displaying an item stack count - use _fungibleX for large numbers if the widget has it available
    @param {SPUI.TextWidget} widget
    @param {boolean} is_fungible
    @param {number} stack
    @returns {SPUI.Font}
 */
ItemDisplay.get_font_for_stack = function(widget, is_fungible, stack) {
    var font_size = widget.data[(is_fungible ? 'text_size' : 'text_size'+(stack >= 1000000 ? '_fungible7' : (stack >= 100000 ? '_fungible6' : (stack >= 10000 ? '_fungible5' : (stack >= 1000 ? '_fungible4' : (stack >= 100 ? '_fungible3' : ''))))))];
    return SPUI.make_font(font_size, font_size+3, 'thick');
};

/** given a SPUI.TextWidget, set it to display a stack count
   @param {SPUI.TextWidget} widget
   @param {Object} spec
   @param {number} stack */
ItemDisplay._set_inventory_item_stack = function(widget, spec, stack) {
    if(stack > 1) {
        widget.show = true;
        //widget.text_offset = [0,0]; // not sure why this was here - might cause problems?
        widget.str = ItemDisplay.get_inventory_item_stack_str(spec, stack);
        widget.font = ItemDisplay.get_font_for_stack(widget, spec['fungible'] || false, stack);
    } else {
        widget.show = false;
    }
};

/** @param {SPUI.TextWidget} widget
    @param {Object} spec
    @param {Object} item an item like {'spec':'abcd', 'stack':1234} */
ItemDisplay.set_inventory_item_stack = function(widget, spec, item) { ItemDisplay._set_inventory_item_stack(widget, spec, item['stack'] || 1); };

/** add a SPFX.CombatText effect to show result of actions on an inventory item widget
    @param {SPUI.DialogWidget} widget
    @param {string} str
    @param {!Array.<number>} color */
ItemDisplay.add_inventory_item_effect = function(widget, str, color) {
    var abspos = [25,25];
    SPFX.add_ui(new SPFX.CombatText(vec_add(abspos, widget.get_absolute_xy()),
                                    0, str,
                                    color, null, 3.0,
                                    {drop_shadow: true, font_size: 15, text_style: "thick", is_ui: true}));
};

/** return displayable name for item of given spec
    @param {Object} spec
    @param {?number=} level
    @returns {string} */
ItemDisplay.get_inventory_item_ui_name = function(spec, level) {
    if(spec['fungible'] && spec['resource'] == 'gamebucks') {
        return Store.gamebucks_ui_name();
    } else {
        var ret = spec['ui_name'];
        if(level) { ret += ' L'+level.toString(); }
        return ret;
    }
};

/** hack - cut off the " Lxx" level suffix where we don't want it
    @param {string} ui_name
    @returns {string} */
ItemDisplay.strip_inventory_item_ui_name_level_suffix = function(ui_name) {
    var fields = ui_name.split(' ');
    if(fields[fields.length-1][0] == 'L') {
        fields = fields.slice(0, fields.length-1);
        ui_name = fields.join(' ');
    }
    return ui_name;
};

/** return displayable name for item of given spec, using "ui_name_long" if available
    @param {Object} spec
    @param {?number=} level
    @returns {string} */
ItemDisplay.get_inventory_item_ui_name_long = function(spec, level) {
    if(spec['fungible'] && spec['resource'] == 'gamebucks') {
        return Store.gamebucks_ui_name();
    } else {
        var ret = spec['ui_name_long'] || spec['ui_name'];
        if(level) { ret += ' L'+level.toString(); }
        return ret;
    }
};

/** return displayable subtitle for item of given spec
    @param {Object} spec
    @returns {string} */
ItemDisplay.get_inventory_item_ui_subtitle = function(spec) {
    var subtitle_list = []; // space-separated phrases

    if('ui_subtitle' in spec) {
        subtitle_list.push(spec['ui_subtitle']);
    } else {
        if('rarity' in spec) {
            subtitle_list.push(gamedata['strings']['rarities'][spec['rarity']+1]);
        }
        if('ui_category' in spec) {
            subtitle_list.push(spec['ui_category']);
        } else if('category' in spec) {
            subtitle_list.push(gamedata['strings']['item_types'][spec['category']]);
        } else if(('use' in spec) && ('spellname' in spec['use'])) { // assumes spells with list use[]s specify category!
            var spellname = ('spellname' in spec['use'] ? spec['use']['spellname'] : null);
            var spell = ('spellname' in spec['use'] ? gamedata['spells'][spec['use']['spellname']] : null);

            if(spellname == 'GIVE_UNITS' || spellname == 'GIVE_UNITS_LIMIT_BREAK') {
                subtitle_list.push(gamedata['strings']['item_types']['packaged_unit']);
            } else if(spell && (spell['code'] == 'projectile_attack' || spell['code'] == 'instant_repair' || spell['code'] == 'instant_combat_repair')) {
                subtitle_list.push(gamedata['strings']['item_types']['battle_consumable']);
            } else if(spellname.indexOf("BUY_RANDOM_") == 0 || spellname.indexOf("FREE_RANDOM_") == 0) {
                subtitle_list.push(gamedata['strings']['item_types']['expedition']);
            } else {
                subtitle_list.push(gamedata['strings']['item_types']['consumable']);
            }
        } else if('equip' in spec) {
            var equip_type;
            var name = '';
            var crit_list;
            if('compatible' in spec['equip']) {
                crit_list = spec['equip']['compatible'];
            } else {
                crit_list = [spec['equip']]; // legacy raw outer JSON
            }

            // try to find an applicable criterion for the item subtitle

            for(var i = 0; i < crit_list.length; i++) {
                var crit = crit_list[i];

                if(crit['kind'] == 'building') {
                    if(crit['slot_type'] == 'leader' && ('name' in crit)) {
                        var bspec = gamedata['buildings'][crit['name']];
                        if(('show_if' in bspec) && !read_predicate(bspec['show_if']).is_satisfied(player, null)) {
                            continue; // reject invisible buildings
                        }
                        name = bspec['ui_name'];
                        equip_type = 'building_leader';
                    } else {
                        equip_type = 'building_equip';
                    }
                } else if(crit['kind'] == 'mobile') {
                    if(crit['slot_type'] == 'leader' && ('name' in crit)) {
                        var uspec = gamedata['units'][crit['name']];
                        if(('show_if' in uspec) && !read_predicate(uspec['show_if']).is_satisfied(player, null)) {
                            continue; // reject invisible units
                        }
                        name = uspec['ui_name'];
                        equip_type = 'unit_leader';
                    } else {
                        equip_type = 'unit_equip';
                    }
                } else {
                    equip_type = 'equip';
                }
                var slot_type = gamedata['strings']['equip_slots'][crit['slot_type']]['ui_name'];
                subtitle_list.push(gamedata['strings']['item_types'][equip_type].replace('%SLOT', slot_type).replace('%NAME', name));
                break;
            }
        }
    }

    if(gamedata['client']['item_tooltip_max_stack'] && subtitle_list.length > 0) {
        var max_stack = ('max_stack' in spec ? spec['max_stack'] : 1);
        if(max_stack > 1) {
            subtitle_list.push('(Max stack: '+pretty_print_number(max_stack)+')'); // XXXXXX ui_text
        }
    }

    return subtitle_list.join(' ');
};

/** return displayable description for item of given spec, using BBCode
    @param {Object} item
    @param {{hide_item_set:(boolean|undefined),
             hide_level:(boolean|undefined)
            }=} opts
    @returns {string} BBCode result */
ItemDisplay.get_inventory_item_ui_description = function(item, opts) {
    var spec = ItemDisplay.get_inventory_item_spec(item['spec']);
    var stack = ('stack' in item ? item['stack'] : 1);
    var level = ('level' in item ? item['level'] : 1);
    var item_duration = ('item_duration' in item ? item['item_duration'] : null);

    var descr = '';

    if('max_level' in spec && !(opts && opts.hide_level)) {
        var max_level = spec['max_level'];
        if('max_ui_level' in spec) { // allow override for items that can "morph" via crafting to child items with more levels
            max_level = spec['max_ui_level'];
        }
        descr += gamedata['strings']['cursors']['level_x_of_y'].replace('%cur', pretty_print_number(level)).replace('%max',pretty_print_number(max_level))+'\n\n';
    }

    descr += eval_cond_or_literal(spec['ui_description'], player, null);
    if(descr.indexOf("%price") != -1) { // special-case hack for cost-capping auras
        var price = spec['use']['spellarg'][2];
        descr = descr.replace("%price", Store.display_user_currency_amount(Store.convert_credit_price_to_user_currency(price), 'full'));
    }
    while(descr.indexOf("%stack") != -1) {
        descr = descr.replace("%stack", pretty_print_number(stack || 1));
    }
    while(descr.indexOf("%level") != -1) {
        descr = descr.replace("%level", pretty_print_number(stack || 1));
    }

    if(descr.indexOf('%modstats') != -1) {
        var effect_list = null;
        if(spec['equip'] && spec['equip']['effects']) {
            if(spec['equip']['effects'][0]['code'] == 'apply_player_aura') {
                effect_list = gamedata['auras'][spec['equip']['effects'][0]['aura_name']]['effects'];
            } else {
                effect_list = spec['equip']['effects'];
            }
        }
        if(effect_list) {
            var ui_modstat_buff_list = [], ui_modstat_nerf_list = [];
            goog.array.forEach(effect_list, function(eff) {
                var ui_effect = ModChain.display_modstat_effect(eff, level);
                if(ui_effect.is_different) {
                    if(ui_effect.is_better) {
                        ui_modstat_buff_list.push(ui_effect.ui_effect);
                    } else {
                        ui_modstat_nerf_list.push(ui_effect.ui_effect);
                    }
                }
            });
            var ui_modstat_list = ui_modstat_buff_list.concat(ui_modstat_nerf_list);
            descr = descr.replace('%modstats', ui_modstat_list.join('\n'));
        }
    }

    if(spec['item_set'] && !(opts && opts.hide_item_set)) {
        var item_set = gamedata['item_sets'][spec['item_set']];
        var set_cur = (item_set['name'] in player.stattab['item_sets'] ? player.stattab['item_sets'][item_set['name']] : 0);
        var set_max = item_set['members'].length;
        var verb = ('ui_completion_verb' in item_set ? (' '+item_set['ui_completion_verb']):'');
        descr += '\n\n[color=#ffc000]%setname%verb (%cur/%max):[/color]\n'.replace('%setname', item_set['ui_name']).replace('%verb',verb).replace('%cur',set_cur.toString()).replace('%max',set_max.toString());
        var member_list = [];
        goog.array.forEach(item_set['members'], function(member_name) {
            var name = gamedata['items'][member_name]['ui_name'];
            var has_it = (gamedata['count_unequipped_items_in_sets'] ? player.has_item(member_name) : player.has_item_equipped(member_name));
            var line = '[color='+(has_it ? '#00ff00' : '#808080')+']'+name+'[/color]';
            member_list.push(line);
        });
        descr += member_list.join('\n');

        if(item_set['bonus_aura']) {
            var bonus_list = [];
            goog.array.forEach(item_set['bonus_aura'], function(aura_name, i) {
                if(!aura_name) { return; }
                var num_req = i+1;
                var aura = gamedata['auras'][aura_name];
                var txt = ('(%num/%req): '.replace('%num', Math.min(set_cur,num_req).toString()).replace('%req',num_req.toString()))+aura['ui_description'];
                var has_it = set_cur >= num_req;
                var line = '[color='+(has_it ? '#00ff00' : '#808080')+']'+txt+'[/color]';
                bonus_list.push(line);
            });
            if(bonus_list.length > 0) {
                descr += '\n\n'+gamedata['strings']['modstats']['bonuses']+'\n';
                descr += bonus_list.join('\n');
            }
        }
    }

    if(typeof item_duration !== 'undefined' && item_duration !== null) {
        descr += '\n\n';
        if(item_duration > 0) {
            var template = spec['ui_expires'] || gamedata['strings']['inventory_expires'];
            descr += template.replace('%s', do_pretty_print_time(item_duration, 10, true).toLowerCase());
        } else {
            descr += spec['ui_expired'] || gamedata['strings']['inventory_expired'];
        }
    }

    if(spec['refund'] && (('refundable_when' in spec) ? read_predicate(spec['refundable_when']).is_satisfied(player, null) : true)) {
        descr += '\n\n';
        var template = spec['ui_refund'] || gamedata['strings']['inventory_refund'];
        descr += template.replace('%s', ItemDisplay.get_inventory_item_refund_str(spec, 1));
    }

    return descr;
};

/** return SPUI.Color corresponding to item rarity
    @param {Object} spec
    @returns {SPUI.Color} */
ItemDisplay.get_inventory_item_color = function(spec) {
    if('name_color' in spec) { return SPUI.make_colorv(spec['name_color']); }
    var rarity = spec['rarity'] || 0;
    var col = gamedata['client']['loot_rarity_colors'][rarity+1];
    return new SPUI.Color(col[0], col[1], col[2], 1);
};

/** return displayable refund description for a refundable item
    @param {Object} spec
    @param {number} count
    @returns {string} */
ItemDisplay.get_inventory_item_refund_str = function(spec, count) {
    var refund = spec['refund'];
    if(refund.length != 1 || !('spec' in refund[0])) {
        throw Error('unhandled refund str '+JSON.stringify(spec['refund']));
    }
    var stack = count * (refund[0]['stack'] || 1);
    var refund_spec = ItemDisplay.get_inventory_item_spec(refund[0]['spec']);
    return ItemDisplay.get_inventory_item_stack_prefix(refund_spec, stack) + ItemDisplay.get_inventory_item_ui_name(refund_spec);
};

/** Fill an entire widget array with a list of items
   @param {SPUI.Dialog} dialog parent dialog
   @param {string} prefix name of item display widget
   @param {Array.<Object>} item_list list of items to display, like [{'spec':'abcd','stack':123}, ... ]
   @param {{max_count_limit:(number|undefined),
            permute:(boolean|undefined),
            glow:(boolean|undefined),
            hide_stack:(boolean|undefined),
            hide_tooltip:(boolean|undefined),
            context_parent:(SPUI.Dialog|undefined)
            }=} opts
 */
ItemDisplay.display_item_array = function(dialog, prefix, item_list, opts) {
    var options = opts || {};

    var array_dims = dialog.data['widgets'][prefix]['array'];
    var max_count_limit = options.max_count_limit || -1; // maximum number of items to display, -1 for no limit

    if(options.permute && item_list.length > 0) { // randomly shuffle the items
        // perform random permutation of the list. See http://en.wikipedia.org/wiki/Fisher%E2%80%93Yates_shuffle.
        // XXX only permute within rarity classes?
        var new_list = [null];
        goog.array.forEach(item_list, function(item, i) {
            var j = Math.floor(Math.random()*(i+1));
            new_list[i] = new_list[j];
            new_list[j] = item;
        });
        item_list = new_list;
    }

    // constrain list length
    var max_count = array_dims[0]*array_dims[1];
    if(max_count_limit >= 0) {
        max_count = Math.min(max_count, max_count_limit);
    }
    if(max_count < item_list.length) {
        item_list = item_list.slice(0, max_count);
    }
    var i = 0;
    for(var y = 0; y < array_dims[1]; y++) {
        for(var x = 0; x < array_dims[0]; x++) {
            var wname = SPUI.get_array_widget_name('', array_dims, [x,y]);
            var d = dialog.widgets[prefix+wname];
            d.show = (i < item_list.length);
            if(d.show) {
                ItemDisplay.display_item(d, item_list[i], options);
            }
            i++;
        }
    }
};

/** Attaches an item's tooltip to the provided widget so that it will appear on mouse over
   @param {SPUI.DialogWidget} widget
   @param {Object} item
   @param {SPUI.Dialog|null=} context_parent
 */
ItemDisplay.attach_inventory_item_tooltip = function(widget, item, context_parent) {
    // we have to assume widget.parent is a dialog
    context_parent = context_parent || /** @type {SPUI.Dialog} */ (widget.parent);
    if(!context_parent.user_data) {
        throw Error('context_parent must be a SPUI.Dialog');
    }

    // show tooltip on enter
    widget.onenter = (function (_slot, _item, _context_parent) {
        return function(w) {
            // XXX horrible awkward hack to suppress tooltips when covered by other dialogs
            if(w.parent && w.parent.parent && w.parent.parent.user_data && w.parent.parent.user_data['hide_tooltips']) { return; }

            if(_context_parent.user_data['context']) {
                // do not switch if context for this item is already up
                if(_context_parent.user_data['context'].user_data['slot'] === _slot &&
                   ItemDisplay.same_item(_context_parent.user_data['context'].user_data['item'],  _item)) {
                    return;
                }
            }
            invoke_inventory_context(_context_parent, w, _slot, _item, false);
        };
    })(widget.get_address(), item, context_parent);

    // hide tooltip on leave
    widget.onleave_cb = (function (_slot, _item, _context_parent) {
        return function(w) {
            if(_context_parent.user_data['context'] &&
               _context_parent.user_data['context'].user_data['slot'] === _slot) {
                invoke_inventory_context(_context_parent, w, -1, null, false);
            }
        };
    })(widget.get_address(), item, context_parent);

    // trigger tooltip immediately if mouse is there already
    if(widget.mouse_enter_time > 0) {
        widget.onenter(widget);
    }
};

/** Undoes the above
   @param {SPUI.DialogWidget} widget
 */
ItemDisplay.remove_inventory_item_tooltip = function(widget) {
    widget.onenter = widget.onleave_cb = null;
};

/** Show a single item in using an item_display dialog
    @param {SPUI.Dialog} item_display
    @param {Object} item an item of the form {'spec': 'aaa', ...}
    @param {{glow:(boolean|undefined),
             hide_stack:(boolean|undefined),
             hide_tooltip:(boolean|undefined),
             context_parent:(SPUI.Dialog|undefined)
             }=} opts
 */
ItemDisplay.display_item = function(item_display, item, opts) {
    var options = opts || {};

    // we have to assume item_display.parent is a dialog
    var context_parent = options.context_parent || /** @type {SPUI.Dialog} */ (item_display.parent);

    if(!context_parent.user_data) {
        throw Error('context_parent must be a SPUI.Dialog');
    }

    var spec = ItemDisplay.get_inventory_item_spec(item['spec']);

    item_display.widgets['item_glow'].show = !!options.glow;
    ItemDisplay.set_inventory_item_asset(item_display.widgets['item'], spec);
    if(!options.hide_stack) {
        ItemDisplay.set_inventory_item_stack(item_display.widgets['stack'], spec, item);
    }
    if(!options.hide_tooltip) {
        ItemDisplay.attach_inventory_item_tooltip(item_display.widgets['frame'], item, context_parent);
    }
};
