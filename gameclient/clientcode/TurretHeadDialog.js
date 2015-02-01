goog.provide('TurretHeadDialog');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('goog.array');
goog.require('SPUI');
goog.require('SPText');
goog.require('ItemDisplay');

// tightly coupled to main.js, sorry!

/** @param {GameObject} emplacement_obj */
TurretHeadDialog.invoke = function(emplacement_obj) {
    var dialog_data = gamedata['dialogs']['turret_head_dialog'];
    var dialog = new SPUI.Dialog(dialog_data);
    dialog.user_data['dialog'] = 'turret_head_dialog';
    dialog.user_data['emplacement'] = emplacement_obj;
    dialog.user_data['builder'] = emplacement_obj;
    dialog.user_data['selected_recipe'] = null;

    dialog.widgets['title'].str = dialog.data['widgets']['title']['ui_name'].replace('%s', gamedata['spells']['CRAFT_FOR_FREE']['ui_name_building_context_emplacement']);
    dialog.widgets['flavor_text'].set_text_with_linebreaking(dialog.data['widgets']['flavor_text']['ui_name'].replace('%s', gamedata['buildings'][get_lab_for('turret_heads')]['ui_name']));
    dialog.widgets['close_button'].onclick = close_parent_dialog;

    // construct recipe list
    dialog.user_data['recipes'] = [];

    for(var name in gamedata['crafting']['recipes']) {
        var spec = gamedata['crafting']['recipes'][name];
        if(spec['crafting_category'] != 'turret_heads') { continue; }
        if('show_if' in spec && !read_predicate(spec['show_if']).is_satisfied(player, null)) { continue; }
        if('activation' in spec && !read_predicate(spec['activation']).is_satisfied(player, null)) { continue; }
        dialog.user_data['recipes'].push(name);
    }

    // scrolling setup
    dialog.user_data['scrolled'] = false;
    dialog.user_data['open_time'] = client_time;
    dialog.widgets['scroll_left'].widgets['scroll_left'].onclick = function(w) { var dialog = w.parent.parent; dialog.user_data['scrolled'] = true; TurretHeadDialog.scroll(dialog, dialog.user_data['page']-1); };
    dialog.widgets['scroll_right'].widgets['scroll_right'].onclick = function(w) { var dialog = w.parent.parent; dialog.user_data['scrolled'] = true; TurretHeadDialog.scroll(dialog, dialog.user_data['page']+1); };

    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;
    dialog.ondraw = TurretHeadDialog.ondraw;
    TurretHeadDialog.scroll(dialog, 0);
    TurretHeadDialog.select_recipe(dialog, null);

    return dialog;
};

/** @param {SPUI.Dialog} dialog
    @param {number} page */
TurretHeadDialog.scroll = function(dialog, page) {
    dialog.user_data['recipes_by_widget'] = null;
    var chapter_recipes = (dialog.user_data['recipes'] ? dialog.user_data['recipes'].length : 0);
    var recipes_per_page = dialog.data['widgets']['recipe_icon']['array'][0]*dialog.data['widgets']['recipe_icon']['array'][1];
    var chapter_pages = dialog.user_data['chapter_pages'] = Math.floor((chapter_recipes+recipes_per_page-1)/recipes_per_page);
    dialog.user_data['page'] = page = (chapter_recipes === 0 ? 0 : clamp(page, 0, chapter_pages-1));

    player.quest_tracked_dirty = true;
};

/** @param {SPUI.Dialog} dialog
    @param {string|null} name */
TurretHeadDialog.select_recipe = function(dialog, name) {
    dialog.user_data['selected_recipe'] = name;
};

/** @param {SPUI.Dialog} dialog */
TurretHeadDialog.ondraw = function(dialog) {
    // deal with the recipe selector in the middle
    var flash_scroll = false;
    if(!dialog.user_data['scrolled'] &&
       ((client_time - dialog.user_data['open_time']) < gamedata['store']['store_scroll_flash_time']) &&
       dialog.widgets['scroll_right'].state != 'disabled') {
        flash_scroll = (((client_time/gamedata['store']['store_scroll_flash_period']) % 1) >= 0.5);
    }
    var page = dialog.user_data['page'], chapter_pages = dialog.user_data['chapter_pages'];
    var chapter_recipes = (dialog.user_data['recipes'] ? dialog.user_data['recipes'].length : 0);
    var recipes_per_page = dialog.data['widgets']['recipe_icon']['array'][0]*dialog.data['widgets']['recipe_icon']['array'][1];
    var grid = [0,0];

    // XXX copy/pasted from update_crafting_dialog()
    if(chapter_pages > 0) {
        dialog.user_data['recipes_by_widget'] = {};
        var first_recipe_on_page = page * recipes_per_page;
        var last_recipe_on_page = Math.max(0, Math.min((page+1)*recipes_per_page-1, chapter_recipes-1));
        for(var i = first_recipe_on_page; i <= last_recipe_on_page; i++) {
            var name = dialog.user_data['recipes'][i];
            var spec = gamedata['crafting']['recipes'][name];
            var wname = grid[0].toString() +',' + grid[1].toString();
            dialog.user_data['recipes_by_widget'][wname] = name;
            var tooltip_text = [], tooltip_text_color = SPUI.default_text_color;
            dialog.widgets['recipe_slot'+wname].show =
                dialog.widgets['recipe_icon'+wname].show =
                dialog.widgets['recipe_frame'+wname].show = true;
            var can_craft = true;

            tooltip_text.push(get_crafting_recipe_ui_name(spec));
            dialog.widgets['recipe_icon'+wname].asset = get_crafting_recipe_icon(spec);

            // get list of any unsatisfied requirements
            var pred = null, req = null;
            if(('requires' in spec) && !player.is_cheater) {
                pred = read_predicate(spec['requires']);
                req = pred.ui_describe(player);
                if(req) {
                    tooltip_text.push('');
                    tooltip_text.push(dialog.data['widgets']['recipe_frame']['ui_tooltip_requires'].replace('%s', req));
                    can_craft = false;
                }
            }

            dialog.widgets['recipe_frame'+wname].onclick = (function (_name) { return function(w) {
                if(w.parent.user_data['selected_recipe'] == _name) {
                    if(w.parent.user_data['on_use_recipe']) {
                        // note: assumes on_use_recipe has been set up by an ondraw update
                        w.parent.user_data['on_use_recipe'](w.parent);
                    }
                } else {
                    TurretHeadDialog.select_recipe(w.parent, _name);
                }
            }; })(name);

            dialog.widgets['recipe_gray_outer'+wname].show = !can_craft;
            dialog.widgets['recipe_frame'+wname].state = (name == dialog.user_data['selected_recipe'] ? 'highlight' : 'normal');

            if(can_craft) {
            } else {
                if(pred) {
                    // still allow selecting the recipe so that players can see what its benefits and requirements are
                    tooltip_text_color = SPUI.error_text_color;
                } else {
                    dialog.widgets['recipe_frame'+wname].state = 'disabled';
                }
            }

            if(tooltip_text.length > 0) {
                dialog.widgets['recipe_frame'+wname].tooltip.str = tooltip_text.join('\n');
                dialog.widgets['recipe_frame'+wname].tooltip.text_color = tooltip_text_color;
            } else {
                dialog.widgets['recipe_frame'+wname].tooltip.str = null;
            }
            grid[0] += 1;
            if(grid[0] >= dialog.user_data['recipe_columns']) {
                // clear out unused columns to the right-hand side
                while(grid[0] < dialog.data['widgets']['recipe_icon']['array'][0]) {
                    var widget_name = grid[0].toString() + ',' + grid[1].toString();
                    dialog.widgets['recipe_slot'+widget_name].show =
                        dialog.widgets['recipe_icon'+widget_name].show =
                        dialog.widgets['recipe_gray_outer'+widget_name].show =
                        dialog.widgets['recipe_frame'+widget_name].show = false;
                    grid[0] += 1;
                }

                grid[0] = 0; grid[1] += 1;
            }
        }

        dialog.widgets['scroll_text'].show = !!dialog.data['widgets']['scroll_text']['show']; // allow hiding permanently
        dialog.widgets['scroll_text'].str = dialog.data['widgets']['scroll_text']['ui_name'].replace('%d1',(first_recipe_on_page+1).toString()).replace('%d2',(last_recipe_on_page+1).toString()).replace('%d3',chapter_recipes.toString());
    } else {
        dialog.widgets['scroll_text'].show = false;
    }

    // clear out empty widgets
    while(grid[1] < dialog.data['widgets']['recipe_icon']['array'][1]) {
        while(grid[0] < dialog.data['widgets']['recipe_icon']['array'][0]) {
            var widget_name = grid[0].toString() + ',' + grid[1].toString();
            dialog.widgets['recipe_slot'+widget_name].show =
                dialog.widgets['recipe_icon'+widget_name].show =
                dialog.widgets['recipe_gray_outer'+widget_name].show =
                dialog.widgets['recipe_frame'+widget_name].show = false;
            grid[0] += 1;
        }
        grid[0] = 0; grid[1] += 1;
    }

    dialog.widgets['scroll_left'].widgets['scroll_left'].state = (page != 0 ? 'normal' : 'disabled');
    dialog.widgets['scroll_left'].widgets['scroll_left_bg'].alpha = (page != 0 ? 0.86 : 0.25);
    dialog.widgets['scroll_left'].widgets['scroll_left_bg'].fade_unless_hover = (page != 0 ? 0.5 : 1);
    dialog.widgets['scroll_right'].widgets['scroll_right'].state = ((page < chapter_pages-1) ? 'normal' : 'disabled');
    dialog.widgets['scroll_right'].widgets['scroll_right_bg'].alpha = ((page < chapter_pages-1) ? (flash_scroll ? 1 : 0.86) : 0.25);
    dialog.widgets['scroll_right'].widgets['scroll_right_bg'].fade_unless_hover = ((page < chapter_pages-1) ? (flash_scroll ? 1 : 0.5) : 1);
    dialog.widgets['scroll_left'].show = dialog.widgets['scroll_right'].show = (chapter_pages > 1);

    // deal with the current item
    var emplacement_obj = dialog.user_data['emplacement'];
    var current_name = emplacement_obj.turret_head_item();

    dialog.widgets['no_current'].show = !current_name;
    dialog.widgets['current'].show = !!current_name;

    if(current_name) {
        TurretHeadDialog.set_stats_display(dialog.widgets['current'], dialog.user_data['emplacement'], current_name);
    }

    // click-to-select
    var selected_recipe_name = dialog.user_data['selected_recipe'];
    dialog.widgets['click_to_select_arrow'].show =
        dialog.widgets['click_to_select'].show = !selected_recipe_name;
    dialog.widgets['selected'].show = !!selected_recipe_name;

    if(dialog.widgets['selected'].show) {

        TurretHeadDialog.set_recipe_display(dialog.widgets['selected'], dialog.user_data['emplacement'], selected_recipe_name, dialog);

    } else {
        dialog.widgets['instant_credits'].show =
            dialog.widgets['instant_button'].show =
            dialog.widgets['cost_time_bar'].show =
            dialog.widgets['cost_time_clock'].show =
            dialog.widgets['cost_time'].show =
            dialog.widgets['use_resources_button'].show = false;
    }
};

/** operates on turret_head_dialog_recipe
    @param {SPUI.Dialog} dialog
    @param {GameObject} emplacement_obj it will go onto
    @param {string} recipe_name of the recipe
    @param {SPUI.Dialog} parent dialog that contains the "Use Resource"/"Instant" buttons and price/time displays */
TurretHeadDialog.set_recipe_display = function(dialog, emplacement_obj, recipe_name, parent) {
    var current_name = emplacement_obj.turret_head_item();
    var current_spec = (current_name ? ItemDisplay.get_inventory_item_spec(current_name) : null);
    var recipe_spec = gamedata['crafting']['recipes'][recipe_name];
    var product_name = recipe_spec['product'][0]['spec'];
    var product_spec = ItemDisplay.get_inventory_item_spec(product_name);
    var product_level = product_spec['level'];

    TurretHeadDialog.set_stats_display(dialog.widgets['stats'], emplacement_obj, product_name);

    // XXX most of this is copy/pasted from update_upgrade_dialog() - maybe unify into some kind of can_cast_spell variant
    var use_resources_offered = true;
    var use_resources_requirements_ok = true, instant_requirements_ok = true, resources_ok = true;
    var tooltip_req_instant = [], tooltip_req_use_resources = [];
    var resources_needed = {}; // dictionary of resource amounts needed
    var ui_resources_needed = [];
    var req = [];
    var use_resources_helper = null, instant_helper = null;

    // RESOURCE requirement
    for(var res in gamedata['resources']) {
        var resdata = gamedata['resources'][res];
        var cost = get_leveled_quantity(recipe_spec['cost'][res]||0, product_level);

        if(!player.is_cheater && cost > 0 && ('allow_instant' in resdata) && !resdata['allow_instant']) {
            instant_requirements_ok = false;
            tooltip_req_instant.push(dialog.parent.data['widgets']['instant_button']['ui_tooltip_rare_res'].replace('%s', resdata['ui_name']));
        }

        if(cost < 0) {
            use_resources_offered = false;
        } else if(player.resource_state[res][1] < cost) {
            resources_ok = false;
            resources_needed[res] = cost - player.resource_state[res][1];
            ui_resources_needed.push(dialog.parent.data['widgets']['use_resources_button']['ui_tooltip_more_res'].replace('%d',pretty_print_number(cost - player.resource_state[res][1])).replace('%s',resdata['ui_name']));
        }

        if('cost_'+res in dialog.widgets) {
            var widget = dialog.widgets['cost_'+res];
            widget.show = (cost > 0);
            if('resource_'+res+'_icon' in dialog.widgets) {
                dialog.widgets['resource_'+res+'_icon'].show = (cost > 0);
            }
            widget.str = pretty_print_qty_brief(cost);
            widget.tooltip.str = widget.data['ui_tooltip'].replace('%RES', resdata['ui_name']).replace('%QTY', pretty_print_number(cost));
            if(cost > 0 && player.resource_state[res][1] < cost) {
                widget.text_color = SPUI.error_text_color;
            } else {
                widget.text_color = SPUI.good_text_color;
            }
        }
    }

    // POWER requirement
    if(1) {
        var old_power = (current_spec ? current_spec['equip']['consumes_power']||0 : 0);
        var during_power = recipe_spec['consumes_power']||0;
        var new_power = product_spec['equip']['consumes_power']||0;
        dialog.widgets['cost_power'].show =
            dialog.widgets['resource_power_icon'].show = (new_power > 0 || old_power > 0);
        if(dialog.widgets['cost_power'].show) {
            dialog.widgets['cost_power'].tooltip.str = dialog.data['widgets']['cost_power']['ui_tooltip'].replace('%CUR', pretty_print_number(old_power)).replace('%AFTER', pretty_print_number(new_power)).replace('%DURING', pretty_print_number(during_power));

            dialog.widgets['cost_power'].str = pretty_print_number(new_power);

            if((session.viewing_base.power_state[1] + new_power - old_power) > session.viewing_base.power_state[0]) {
                dialog.widgets['cost_power'].text_color = SPUI.error_text_color;
                // cannot craft?
            } else {
                dialog.widgets['cost_power'].text_color = SPUI.good_text_color;
            }
        }
    }

    // TIME requirement
    parent.widgets['cost_time_bar'].show =
        parent.widgets['cost_time_clock'].show =
        parent.widgets['cost_time'].show = (current_name != product_name);
    if(parent.widgets['cost_time'].show) {
        parent.widgets['cost_time'].str = pretty_print_time(recipe_spec['craft_time']);
    }

    // PREDICATE requirement
    if('requires' in recipe_spec) {
        var pred = read_predicate(get_leveled_quantity(recipe_spec['requires'], product_level));
        var text = pred.ui_describe(player);
        if(text) {
            req.push(text);
            use_resources_requirements_ok = instant_requirements_ok = false;
            use_resources_helper = instant_helper = get_requirements_help(pred, null);
        }
    }
    dialog.widgets['requirements_text'].set_text_with_linebreaking(req.join(', '));

    // DESCRIPTION
    if(1) {
        var descr_nlines = SPUI.break_lines(product_spec['ui_description'], dialog.widgets['description'].font, dialog.widgets['description'].wh);

        dialog.widgets['description'].tooltip.str = descr_nlines[0];
        var descr_list = descr_nlines[0].split('\n');
        var descr;
        if(descr_list.length > dialog.data['widgets']['description']['max_lines']) {
            descr = descr_list.slice(0, dialog.data['widgets']['description']['max_lines']).join('\n')+'...';
        } else {
            descr = descr_list.join('\n');
        }
        dialog.widgets['description'].str = descr;
    }

    // NOW THE ACTION BUTTONS

    for(var i = 0; i < req.length; i++) {
        tooltip_req_instant.push(req[i]);
        tooltip_req_use_resources.push(req[i]);
    }
    for(var i = 0; i < ui_resources_needed.length; i++) {
        tooltip_req_use_resources.push(ui_resources_needed[i]);
    }
    if(tooltip_req_instant.length > 0) { tooltip_req_instant.splice(0, 0, parent.data['widgets']['use_resources_button']['ui_tooltip_unmet']); }
    if(tooltip_req_use_resources.length > 0) { tooltip_req_use_resources.splice(0, 0, parent.data['widgets']['use_resources_button']['ui_tooltip_unmet']); }

    var craft_spellarg = {'recipe':recipe_name,
                          'delivery':{'obj_id':emplacement_obj.id, 'slot_type':'turret_head', 'slot_index': 0, 'replace': 1}
                         };

    if(current_name != product_name) {
        parent.widgets['use_resources_button'].show = use_resources_offered;
        parent.widgets['use_resources_button'].tooltip.str = null;

        var slow_func = (function (_parent, _obj, _recipe_spec, _product_name, _craft_spellarg) { return function() {

            var new_config = (_obj.config ? goog.object.clone(_obj.config) : {});
            new_config['turret_head'] = _product_name;
            send_to_server.func(["CAST_SPELL", _obj.id, "CONFIG_SET", new_config]);

            start_crafting(_obj, _recipe_spec, _craft_spellarg);
            invoke_ui_locker(_obj.request_sync(), (function (__parent) { return function() { close_dialog(__parent); }; })(_parent));

        }; })(parent, emplacement_obj, recipe_spec, product_name, craft_spellarg);

        if(!emplacement_obj.is_in_sync()) {
            parent.widgets['use_resources_button'].state = 'disabled';
        } else if(use_resources_requirements_ok && resources_ok) {
            parent.widgets['use_resources_button'].state = 'normal';
            parent.widgets['use_resources_button'].onclick = slow_func;
        } else {
            parent.widgets['use_resources_button'].state = 'disabled';
            if(tooltip_req_use_resources.length > 0) {
                parent.widgets['use_resources_button'].tooltip.text_color = SPUI.error_text_color;
                parent.widgets['use_resources_button'].tooltip.str = tooltip_req_use_resources.join('\n');
            }

            var button_is_normal = false;
            if(!use_resources_helper && !resources_ok) {
                // try a resource basket
                // special case that leads to the "buy resources" dialog
                use_resources_helper = get_requirements_help('resources', resources_needed, {continuation:slow_func});

                // don't gray out the button if all resources can be topped-up
                var can_topup = true;
                for(var res in resources_needed) {
                    if(!gamedata['resources'][res]['allow_topup']) {
                        can_topup = false; break;
                    }
                }
                if(can_topup) { button_is_normal = true; }
            }

            if(use_resources_helper) {
                parent.widgets['use_resources_button'].state = (button_is_normal ? 'normal' : 'disabled_clickable');
                parent.widgets['use_resources_button'].onclick = use_resources_helper;
            }
        }

        // "Instant" button

        if(get_leveled_quantity(recipe_spec['craft_gamebucks_cost']||-1, product_level) < 0) {
            // instant upgrade not offered
            parent.widgets['instant_button'].show = parent.widgets['instant_credits'].show = false;
            parent.default_button = parent.widgets['use_resources_button'];

            if(parent.widgets['use_resources_button'].state == 'normal') {
                // make use_resources_button yellow and default
                parent.widgets['use_resources_button'].state = 'active';
            } else if(parent.widgets['use_resources_button'].state == 'disabled_clickable') {
                // parent.widgets['use_resources_button'].state = 'normal'; ?
            }
        } else {
            parent.widgets['instant_button'].show = parent.widgets['instant_credits'].show = true;
            parent.default_button = parent.widgets['instant_button'];
        }

        var price = Store.get_user_currency_price(emplacement_obj.id, gamedata['spells']['CRAFT_FOR_MONEY'], craft_spellarg);

        // just for diagnotics - price should always be -1 if requirements are not met
        if(!instant_requirements_ok && price >= 0 && !player.is_cheater) {
            throw Error('requirements/price mismatch for '+recipe_name);
        }

        widget = parent.widgets['instant_credits'];
        widget.bg_image = player.get_any_abtest_value('price_display_asset', gamedata['store']['price_display_asset']);
        widget.state = Store.get_user_currency();
        widget.str = Store.display_user_currency_price(price); // PRICE
        widget.tooltip.str = Store.display_user_currency_price_tooltip(price);

        if(price < 0) {
            // cannot make a purchase because tech requirements are not fulfilled
            parent.widgets['instant_credits'].onclick = null;
            parent.widgets['instant_button'].state = 'disabled';
            if(tooltip_req_instant.length > 0) {
                parent.widgets['instant_button'].tooltip.str = tooltip_req_instant.join('\n');
                parent.widgets['instant_button'].tooltip.text_color = SPUI.error_text_color;
            }
            if(instant_helper) {
                parent.widgets['instant_button'].state = 'disabled_clickable';
                parent.widgets['instant_credits'].onclick = parent.widgets['instant_button'].onclick = instant_helper;
            }
        } else if(price == 0) {
            throw Error('no code path for free instant craft');
        } else {
            if(!emplacement_obj.is_in_sync()) {
                parent.widgets['instant_button'].state = 'disabled';
                parent.widgets['instant_button'].str = parent.data['widgets']['instant_button']['ui_name_pending'];
                parent.widgets['instant_credits'].parent = parent.widgets['instant_button'].onclick = null;
            } else {
                parent.widgets['instant_button'].state = 'normal';
                parent.widgets['instant_button'].str = parent.data['widgets']['instant_button']['ui_name'];
                parent.widgets['instant_credits'].onclick =
                    parent.widgets['instant_button'].onclick = (function (_obj, _product_name, _craft_spellarg, _parent) { return function(w) {
                        var dialog = w.parent;

                        var new_config = (_obj.config ? goog.object.clone(_obj.config) : {});
                        new_config['turret_head'] = _product_name;
                        send_to_server.func(["CAST_SPELL", _obj.id, "CONFIG_SET", new_config]);

                        if(Store.place_user_currency_order(_obj.id, "CRAFT_FOR_MONEY", _craft_spellarg,
                                                           (function (__parent) { return function() { close_dialog(__parent); } })(_parent))) {
                            invoke_ui_locker(_obj.request_sync());
                        }
                    }; })(emplacement_obj, product_name, craft_spellarg, parent);
            }
        }
    } else { // this product is already equipped
        parent.widgets['use_resources_button'].show =
            parent.widgets['instant_credits'].show =
            parent.widgets['instant_button'].show = false;
    }
};

// operates on turret_head_dialog_stats
/** @param {SPUI.Dialog} dialog
    @param {GameObject} emplacement_obj it will go onto
    @param {string} name of the turret head item */
TurretHeadDialog.set_stats_display = function(dialog, emplacement_obj, name) {
    var spec = ItemDisplay.get_inventory_item_spec(name);

    dialog.widgets['name'].str = ItemDisplay.get_inventory_item_ui_name(spec);
    // main icon
    ItemDisplay.set_inventory_item_asset(dialog.widgets['icon'], spec);

    var spell = gamedata['spells'][spec['equip']['effects'][0]['strength']];

    // fill in damage_vs icons
    init_damage_vs_icons(dialog, {'kind':'building', 'ui_damage_vs':{}}, // fake building spec to fool init_damage_vs_icons()
                         spell);

    // set up stats display
    var statlist = get_weapon_spell_features2(emplacement_obj.spec, spell);

    goog.array.forEach([['descriptionL0', 'descriptionR0'], ['descriptionL1', 'descriptionR1']], function(wnames, i) {
        var left = dialog.widgets[wnames[0]], right = dialog.widgets[wnames[1]];
        if(i < statlist.length) {
            left.show = right.show = true;
            var stat = statlist[i];
            var modchain = null;
            ModChain.display_label_widget(left, stat, spell);
            ModChain.display_widget(right, stat, modchain,
                                    spec, // ??? emplacement_obj.spec
                                    spec['level'] || 1, // ???
                                    spell, spec['level'] || 1);
        } else {
            left.show = right.show = false;
        }
    });
};
