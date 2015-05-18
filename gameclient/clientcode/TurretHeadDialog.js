goog.provide('TurretHeadDialog');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('SPUI');
goog.require('SPText');
goog.require('ItemDisplay');
goog.require('ModChain');

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
    dialog.widgets['dev_title'].show = player.is_cheater;
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

    // count current heads, grouped by limited_equipped
    var count_mounted = {}, count_mounting = {}, count_under_leveled = {};
    // also look for a building that provides the limited_equipped keys
    var provides_limit_building = {}, provides_limit_building_can_upgrade = {};

    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.is_building() && obj.team == 'player') {
            if(obj.is_emplacement()) {
                var head = obj.turret_head_item() || obj.turret_head_inprogress_item();
                if(head) {
                    var head_spec = ItemDisplay.get_inventory_item_spec(head);
                    if('limited_equipped' in head_spec) {
                        var key = head_spec['limited_equipped'];
                        if(head == obj.turret_head_item()) {
                            count_mounted[key] = (count_mounted[key]||0) + 1;
                        } else {
                            count_mounting[key] = (count_mounting[key]||0) + 1;
                        }
                    }
                    if('level' in head_spec && 'associated_tech' in head_spec) {
                        var tech_level = player.tech[head_spec['associated_tech']] || 0;
                        if(tech_level > head_spec['level']) {
                            count_under_leveled[key] = (count_under_leveled[key]||0) + 1;
                        }
                    }
                }
            }
            if('provides_limited_equipped' in obj.spec) {
                for(var key in obj.spec['provides_limited_equipped']) {
                    provides_limit_building[key] = obj;
                    if(obj.level < get_max_ui_level(obj.spec) &&
                       get_leveled_quantity(obj.spec['provides_limited_equipped'][key], obj.level) <
                       get_leveled_quantity(obj.spec['provides_limited_equipped'][key], get_max_ui_level(obj.spec))) {
                        provides_limit_building_can_upgrade[key] = true;
                    }
                }
            }
        }
    }

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

            var product_spec = ItemDisplay.get_inventory_item_spec(spec['product'][0]['spec']);
            tooltip_text.push(ItemDisplay.strip_inventory_item_ui_name_level_suffix(get_crafting_recipe_ui_name(spec)));
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

            // check limited_equipped
            if(product_spec['limited_equipped']) {
                var count = player.count_limited_equipped(product_spec, null);
                var max = player.stattab['limited_equipped'][product_spec['limited_equipped']] || 0;

                dialog.widgets['recipe_limit'+wname].show = true;
                dialog.widgets['recipe_limit'+wname].str = dialog.data['widgets']['recipe_limit']['ui_name'].replace('%cur', count.toString()).replace('%max', max.toString());
                dialog.widgets['recipe_limit'+wname].text_color = SPUI.make_colorv(dialog.data['widgets']['recipe_limit'][(count>=max ? 'text_color_limit' : 'text_color_ok')]);

                if(count_mounted[product_spec['limited_equipped']]) {
                    tooltip_text.push(dialog.data['widgets']['recipe_frame']['ui_tooltip_mounted'].replace('%d', pretty_print_number(count_mounted[product_spec['limited_equipped']]||0)));
                }
                if(count_mounting[product_spec['limited_equipped']]) {
                    tooltip_text.push(dialog.data['widgets']['recipe_frame']['ui_tooltip_mounting'].replace('%d', pretty_print_number(count_mounting[product_spec['limited_equipped']]||0)));
                }
                // note: the counts here might not agree with "count"?
                var ui_limit = dialog.data['widgets']['recipe_frame']['ui_tooltip_limit'].replace('%d', max.toString());
                if(provides_limit_building[product_spec['limited_equipped']] && provides_limit_building_can_upgrade[product_spec['limited_equipped']]) {
                    ui_limit += ' '+dialog.data['widgets']['recipe_frame']['ui_tooltip_limit_upgrade'].replace('%building', provides_limit_building[product_spec['limited_equipped']].spec['ui_name']);
                }
                tooltip_text.push(ui_limit);
                if(count_under_leveled[product_spec['limited_equipped']]) {
                    tooltip_text.push(dialog.data['widgets']['recipe_frame']['ui_tooltip_under_leveled'].replace('%d', pretty_print_number(count_under_leveled[product_spec['limited_equipped']]||0)));
                }
            } else {
                dialog.widgets['recipe_limit'+wname].show = false;
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
            if(grid[0] >= dialog.data['widgets']['recipe_icon']['array'][0]) {
                // clear out unused columns to the right-hand side (unused code)
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
                dialog.widgets['recipe_limit'+widget_name].show =
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
        TurretHeadDialog.set_stats_display(dialog.widgets['current'], dialog.user_data['emplacement'], current_name, null);
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
    var category = gamedata['crafting']['categories'][recipe_spec['crafting_category']];
    var product_name = recipe_spec['product'][0]['spec'];
    var product_spec = ItemDisplay.get_inventory_item_spec(product_name);
    var product_level = product_spec['level'];

    TurretHeadDialog.set_stats_display(dialog.widgets['stats'], emplacement_obj, product_name, (current_name && current_name != product_name) ? current_name : null);

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
        var speed = emplacement_obj.get_stat('crafting_speed', emplacement_obj.get_leveled_quantity(emplacement_obj.spec['crafting_speed'] || 1.0));
        var cost_time = Math.max(1, Math.floor(get_leveled_quantity(recipe_spec['craft_time'], product_level) / speed));
        parent.widgets['cost_time'].str = pretty_print_time(cost_time);
    }

    // PREDICATE requirement
    if(!player.is_cheater && ('requires' in recipe_spec)) {
        var pred = read_predicate(get_leveled_quantity(recipe_spec['requires'], product_level));
        var text = pred.ui_describe(player);
        if(text) {
            req.push(text);
            use_resources_requirements_ok = instant_requirements_ok = false;
            use_resources_helper = instant_helper = get_requirements_help(pred, null);
        }
    }
    dialog.widgets['requirements_text'].set_text_with_linebreaking(req.join(', '));

    // LIMITED EQUIPPED requirement
    if(!player.is_cheater && player.would_violate_limited_equipped(product_spec, new BuildingEquipSlotAddress(emplacement_obj.id, 'turret_head', 0))) {
        use_resources_requirements_ok = instant_requirements_ok = false;
        use_resources_helper = instant_helper = get_requirements_help('limited_equipped', product_spec['name']);
        var msg = parent.data['widgets']['use_resources_button']['ui_tooltip_limited_equipped'];
        tooltip_req_instant.push(msg);
        tooltip_req_use_resources.push(msg);
    }

    // DESCRIPTION
    if(1) {
        var descr_nlines = SPUI.break_lines(product_spec['ui_description'], dialog.widgets['description'].font, dialog.widgets['description'].wh);

        var descr_list = descr_nlines[0].split('\n');
        var descr;
        if(descr_list.length > dialog.data['widgets']['description']['max_lines']) {
            descr = descr_list.slice(0, dialog.data['widgets']['description']['max_lines']).join('\n')+'...';
        } else {
            descr = descr_list.join('\n');
        }
        dialog.widgets['description'].str = descr;
        dialog.widgets['description'].onclick = null;
        ItemDisplay.attach_inventory_item_tooltip(dialog.widgets['description'], {'spec':product_spec['name']}, parent);
        //dialog.widgets['description'].tooltip.str = descr_nlines[0];
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
            if(category['foreman'] && player.foreman_is_busy()) {
                var helper = get_requirements_help('foreman', null);
                if(helper) {
                    parent.widgets['use_resources_button'].onclick = helper;
                } else {
                    parent.widgets['use_resources_button'].onclick = function(w) {
                        var busy_obj = player.foreman_get_tasks()[0]; // this just prompts to speed up one possible building
                        change_selection(busy_obj);
                        invoke_speedup_dialog('busy');
                    };
                }
            } else {
                parent.widgets['use_resources_button'].onclick = slow_func;
            }
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
        parent.widgets['instant_button'].tooltip.str = null;

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
                                                           (function (__parent) { return function(success) { if(success) { close_dialog(__parent); } } })(_parent))) {
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

/** Does this item apply any anti_missile modstats?
    @param {string} item_spec
    @private */
TurretHeadDialog._has_anti_missile = function(item_spec) {
    var has_it = false;
    goog.array.forEach(item_spec['equip']['effects'], function(effect) {
        if(effect['stat'] == 'anti_missile') {
            has_it = true;
        }
    });
    return has_it;
};
/** Create a new modchain with the item's anti-missile stats appended
    @param {ModChain.ModChain} modchain
    @param {string} item_spec
    @private */
TurretHeadDialog._add_anti_missile_mod = function(modchain, item_spec) {
    goog.array.forEach(item_spec['equip']['effects'], function(effect) {
        if(effect['stat'] == 'anti_missile') {
            modchain = ModChain.add_mod(modchain, effect['method'], effect['strength'], 'equipment', item_spec['name']);
        }
    });
    return modchain;
};

// operates on turret_head_dialog_stats
/** @param {SPUI.Dialog} dialog
    @param {GameObject} emplacement_obj it will go onto
    @param {string} name of the turret head item
    @param {string|null} relative_to name of another item to compare this one to */
TurretHeadDialog.set_stats_display = function(dialog, emplacement_obj, name, relative_to) {
    var spec = ItemDisplay.get_inventory_item_spec(name);
    var relative_spec = (relative_to ? ItemDisplay.get_inventory_item_spec(relative_to) : null);

    dialog.widgets['name'].str = ItemDisplay.get_inventory_item_ui_name(spec);
    // main icon
    ItemDisplay.set_inventory_item_asset(dialog.widgets['icon'], spec);

    ItemDisplay.attach_inventory_item_tooltip(dialog.widgets['frame'], {'spec':spec['name']});

    var spell = ItemDisplay.get_inventory_item_weapon_spell(spec);
    var relative_spell = (relative_to ? ItemDisplay.get_inventory_item_weapon_spell(relative_spec) : null);

    // fill in damage_vs icons
    init_damage_vs_icons(dialog, {'kind':'building', 'ui_damage_vs':{}}, // fake building spec to fool init_damage_vs_icons()
                         spell);

    // set up stats display
    var statlist = get_weapon_spell_features2(emplacement_obj.spec, spell);

    // create the UNION of the two stat lists
    if(relative_to) {
        var relative_statlist = get_weapon_spell_features2(emplacement_obj.spec, relative_spell);
        goog.array.forEach(relative_statlist, function(rstat) {
            // when switching from a ranged weapon to a PBAOE weapon, don't show range dropping to zero
            if(rstat == 'weapon_range') { return; }
            if(!goog.array.contains(statlist, rstat)) {
                statlist.push(rstat);
            }
        });
    }

    if(TurretHeadDialog._has_anti_missile(spec) ||
       (relative_spec && TurretHeadDialog._has_anti_missile(relative_spec))) {
           statlist.push('anti_missile');
    }

    for(var i = 0; i < dialog.data['widgets']['descriptionL']['array'][1]; i++) {
        var left = dialog.widgets['descriptionL'+i.toString()], right = dialog.widgets['descriptionR'+i.toString()];
        if(i < statlist.length) {
            left.show = right.show = true;
            var stat = statlist[i];

            var modchain = ModChain.make_chain(ModChain.get_base_value(stat, spec, spec['level'] || 1), {'level':spec['level'] || 1});
            var relative_modchain = (relative_to ? ModChain.make_chain(ModChain.get_base_value(stat, relative_spec, relative_spec['level'] || 1), {'level':relative_spec['level'] || 1}) : null);

            ModChain.display_label_widget(left, stat, spell, true);

            if(stat == 'anti_missile') { // needs special handling because it is a stat of the building, not the weapon spell
                modchain = TurretHeadDialog._add_anti_missile_mod(modchain, spec);
                if(relative_to) {
                    relative_modchain = TurretHeadDialog._add_anti_missile_mod(relative_modchain, relative_spec);
                }
            }

            var detail = ModChain.display_value_detailed(stat, modchain,
                                                         spec, // ??? emplacement_obj.spec
                                                         spec['level'] || 1, // ???
                                                         spell, spec['level'] || 1);

            var relative_detail = (relative_to ? ModChain.display_value_detailed(stat, relative_modchain,
                                                                                 relative_spec, // ??? emplacement_obj.spec
                                                                                 relative_spec['level'] || 1, // ???
                                                                                 relative_spell, relative_spec['level'] || 1) : null);
            var bbstr = detail.str;

            var is_delta = relative_to && (relative_detail.value != detail.value);
            if(is_delta) {
                var delta_sign = (detail.value - relative_detail.value >= 0 ? 1 : -1);
                var is_worse = (detail.value < relative_detail.value);
                var ui_stat = gamedata['strings']['modstats']['stats'][stat];
                if(ui_stat['display'] == 'cooldown' || ui_stat['display'] == 'one_minus_pct' || stat == 'min_range') {
                    is_worse = !is_worse;
                }
                var ui_delta;
                if(ui_stat['display'] == 'one_minus_pct') {
                    ui_delta = pretty_print_number(100.0*Math.abs(detail.value - relative_detail.value)) + '%';
                    delta_sign *= -1;
                } else {
                    ui_delta = pretty_print_number(Math.abs(detail.value - relative_detail.value));
                }
                var ui_sign = delta_sign > 0 ? '+' : '-';
                bbstr += ' [color='+dialog.data['widgets']['descriptionR'][(is_worse ? 'worse_color':'better_color')]+']('+ui_sign+ui_delta+')[/color]';
            }
            right.set_text_bbcode(bbstr);
            right.tooltip.str = detail.tooltip;

        } else {
            left.show = right.show = false;
        }
    }
};
