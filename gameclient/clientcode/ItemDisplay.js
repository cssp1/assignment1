goog.provide('ItemDisplay');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// library that supports the "item_widget" dialog, which is how we
// display items with stack counts, clickable frames, etc.

goog.require('goog.array');
goog.require('SPUI');
goog.require('SPFX');
goog.require('GameArt');

// requires from main.js: player.get_any_abtest_value, player.stattab, get_leveled_quantity, Store.display_user_currency_amount, vec_add,
// Store.gamebucks_ui_name(),
// Store.display_user_currency_amount(), Store.convert_credit_price_to_user_currency()
// player.has_item, player.has_item_equipped,
// pretty_print_number, pretty_print_qty_brief, invoke_inventory_context (XXX which should be moved into here)

/** return gamedata spec for an item by specname, defaulting to unknown_item if not found
    @param {string} specname */
ItemDisplay.get_inventory_item_spec = function(specname) {
    if(!(specname in gamedata['items'])) {
        specname = 'unknown_item';
    }
    return gamedata['items'][specname];
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
    var font_size = widget.data[(is_fungible ? 'text_size' : 'text_size'+(stack >= 10000 ? '_fungible5' : (stack >= 1000 ? '_fungible4' : (stack >= 100 ? '_fungible3' : ''))))];
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
    @param {Array.<number>} color */
ItemDisplay.add_inventory_item_effect = function(widget, str, color) {
    var abspos = [25,25];
    SPFX.add_ui(new SPFX.CombatText(vec_add(abspos, widget.get_absolute_xy()),
                                    0, str,
                                    color, client_time, client_time + 3.0,
                                    {drop_shadow: true, font_size: 15, text_style: "thick", is_ui: true}));
};

/** return displayable name for item of given spec
    @param {Object} spec
    @returns {string} */
ItemDisplay.get_inventory_item_ui_name = function(spec) {
    if(spec['fungible'] && spec['resource'] == 'gamebucks') {
        return Store.gamebucks_ui_name();
    } else {
        return spec['ui_name'];
    }
};

/** return displayable name for item of given spec, using "ui_name_long" if available
    @param {Object} spec
    @returns {string} */
ItemDisplay.get_inventory_item_ui_name_long = function(spec) {
    if(spec['fungible'] && spec['resource'] == 'gamebucks') {
        return Store.gamebucks_ui_name();
    } else {
        return spec['ui_name_long'] || spec['ui_name'];
    }
};

/** return displayable subtitle for item of given spec
    @param {Object} spec
    @returns {string} */
ItemDisplay.get_inventory_item_ui_subtitle = function(spec) {
    var subtitle = null;
    if('ui_subtitle' in spec) {
        subtitle = spec['ui_subtitle'];
    } else {
        subtitle = '';
        if('rarity' in spec) {
            subtitle += gamedata['strings']['rarities'][spec['rarity']+1];
        }
        if('ui_category' in spec) {
            subtitle += ' ' +spec['ui_category'];
        } else if('category' in spec) {
            subtitle += ' ' +gamedata['strings']['item_types'][spec['category']];
        } else if(('use' in spec) && ('spellname' in spec['use'])) { // assumes spells with list use[]s specify category!
            var spellname = ('spellname' in spec['use'] ? spec['use']['spellname'] : null);
            var spell = ('spellname' in spec['use'] ? gamedata['spells'][spec['use']['spellname']] : null);

            subtitle += ' ';

            if(spellname == 'GIVE_UNITS' || spellname == 'GIVE_UNITS_LIMIT_BREAK') {
                subtitle += gamedata['strings']['item_types']['packaged_unit'];
            } else if(spell && (spell['code'] == 'projectile_attack' || spell['code'] == 'instant_repair' || spell['code'] == 'instant_combat_repair')) {
                subtitle += gamedata['strings']['item_types']['battle_consumable'];
            } else if(spellname.indexOf("BUY_RANDOM_") == 0 || spellname.indexOf("FREE_RANDOM_") == 0) {
                subtitle += gamedata['strings']['item_types']['expedition'];
            } else {
                subtitle += gamedata['strings']['item_types']['consumable'];
            }
        } else if('equip' in spec) {
            var equip_type;
            var name = '';
            if(spec['equip']['kind'] == 'building') {
                if(spec['equip']['slot_type'] == 'leader' && ('name' in spec['equip'])) {
                    name = gamedata['buildings'][spec['equip']['name']]['ui_name'];
                    equip_type = 'building_leader';
                } else {
                    equip_type = 'building_equip';
                }
            } else if(spec['equip']['kind'] == 'mobile') {
                if(spec['equip']['slot_type'] == 'leader' && ('name' in spec['equip'])) {
                    name = gamedata['units'][spec['equip']['name']]['ui_name'];
                    equip_type = 'unit_leader';
                } else {
                    equip_type = 'unit_equip';
                }
            } else {
                equip_type = 'equip';
            }
            var slot_type = gamedata['strings']['equip_slots'][spec['equip']['slot_type']]['ui_name'];
            subtitle += ' '+gamedata['strings']['item_types'][equip_type].replace('%SLOT', slot_type).replace('%NAME', name);
        }
    }

    if(gamedata['client']['item_tooltip_stack_max'] && subtitle) {
        var stack_max = ('stack_max' in spec ? spec['stack_max'] : 1);
        if(stack_max > 1) {
            subtitle += ' (Max stack: '+pretty_print_number(stack_max)+')';
        }
    }

    return subtitle;
};

/** return displayable description for item of given spec, using BBCode
    @param {Object} spec
    @param {number=} stack
    @param {number|null=} item_duration
    @param {{hide_item_set:(boolean|undefined)
            }=} opts
    @returns {string} BBCode result */
ItemDisplay.get_inventory_item_ui_description = function(spec, stack, item_duration, opts) {
    var descr = spec['ui_description'];
    if(descr.indexOf("%price") != -1) { // special-case hack for cost-capping auras
        var price = spec['use']['spellarg'][2];
        descr = descr.replace("%price", Store.display_user_currency_amount(Store.convert_credit_price_to_user_currency(price), 'full'));
    }
    while(descr.indexOf("%stack") != -1) {
        descr = descr.replace("%stack", pretty_print_number(stack || 1));
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
            if(_context_parent.user_data['context']) {
                // do not switch if context for this item is already up
                if(_context_parent.user_data['context'].user_data['slot'] === _slot &&
                   _context_parent.user_data['context'].user_data['item'] === _item) {
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
