goog.provide('MountedWeaponDialog');

// Copyright (c) 2019 Battlehouse Inc. All rights reserved.
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

/** @param {GameObject} mounting_obj */
MountedWeaponDialog.invoke = function(mounting_obj) {
    var dialog_data = gamedata['dialogs']['mounted_weapon_dialog'];
    var dialog = new SPUI.Dialog(dialog_data);
    var crafting_category = 'turret_heads'; // used for limited_equiped calculations later on
    var research_category = 'mounted_weapons'; // current research dialog has limited buttons, so all mounted weapons share turret_heads category research.
    var building_context = 'ui_name_building_context_emplacement'; // key for UI string in gamedata['spells']['CRAFT_FOR_FREE'] describing this mounting method
    var slot_type = 'turret_head'; // used for delivery later on
    if (mounting_obj.is_trapped_barrier()) {
        building_context = 'ui_name_building_context_barrier_trap';
        crafting_category = 'barrier_traps';
        slot_type = 'barrier_trap';
    } else if (mounting_obj.is_armed_building()) {
        building_context = 'ui_name_building_context_building_weapon';
        crafting_category = 'building_weapons';
        slot_type = 'building_weapon';
    } else if (mounting_obj.is_armed_townhall()) {
        building_context = 'ui_name_building_context_townhall_weapon';
        crafting_category = 'townhall_weapons';
        slot_type = 'townhall_weapon';
    } else if (mounting_obj.is_security_node()) {
        building_context = 'ui_name_building_context_security_node';
        crafting_category = 'security_nodes_' + mounting_obj.spec.name; // security node hack - have to use a per-building category change to get nodes to work in multiple building types
        slot_type = 'security_node';
    }
    dialog.user_data['dialog'] = 'mounted_weapon_dialog';
    dialog.user_data['emplacement'] = mounting_obj;
    dialog.user_data['builder'] = mounting_obj;
    dialog.user_data['crafting_category'] = crafting_category;
    dialog.user_data['slot_type'] = slot_type;
    dialog.user_data['selected_recipe'] = null;

    dialog.widgets['title'].str = dialog.data['widgets']['title']['ui_name'].replace('%s', gamedata['spells']['CRAFT_FOR_FREE'][building_context]);
    dialog.widgets['dev_title'].show = player.is_cheater;
    dialog.widgets['flavor_text'].set_text_with_linebreaking(dialog.data['widgets']['flavor_text']['ui_name'].replace('%s', gamedata['buildings'][get_lab_for(research_category)]['ui_name']));
    dialog.widgets['close_button'].onclick = close_parent_dialog;

    // construct recipe list
    dialog.user_data['recipes'] = [];

    for(var name in gamedata['crafting']['recipes']) {
        var spec = gamedata['crafting']['recipes'][name];
        if(spec['crafting_category'] != crafting_category) { continue; }
        if('show_if' in spec && !read_predicate(spec['show_if']).is_satisfied(player, null)) { continue; }
        if('activation' in spec && !read_predicate(spec['activation']).is_satisfied(player, null)) { continue; }
        dialog.user_data['recipes'].push(name);
    }

    // scrolling setup
    dialog.user_data['scrolled'] = false;
    dialog.user_data['open_time'] = client_time;
    dialog.widgets['scroll_left'].widgets['scroll_left'].onclick = function(w) { var dialog = w.parent.parent; dialog.user_data['scrolled'] = true; MountedWeaponDialog.scroll(dialog, dialog.user_data['page']-1); };
    dialog.widgets['scroll_right'].widgets['scroll_right'].onclick = function(w) { var dialog = w.parent.parent; dialog.user_data['scrolled'] = true; MountedWeaponDialog.scroll(dialog, dialog.user_data['page']+1); };

    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;
    dialog.ondraw = MountedWeaponDialog.ondraw;
    MountedWeaponDialog.scroll(dialog, 0);
    MountedWeaponDialog.select_recipe(dialog, null);

    return dialog;
};

/** @param {SPUI.Dialog} dialog
    @param {number} page */
MountedWeaponDialog.scroll = function(dialog, page) {
    dialog.user_data['recipes_by_widget'] = null;
    var chapter_recipes = (dialog.user_data['recipes'] ? dialog.user_data['recipes'].length : 0);
    var recipes_per_page = dialog.data['widgets']['recipe_icon']['array'][0]*dialog.data['widgets']['recipe_icon']['array'][1];
    var chapter_pages = dialog.user_data['chapter_pages'] = Math.floor((chapter_recipes+recipes_per_page-1)/recipes_per_page);
    dialog.user_data['page'] = page = (chapter_recipes === 0 ? 0 : clamp(page, 0, chapter_pages-1));

    player.quest_tracked_dirty = true;
};

/** @param {SPUI.Dialog} dialog
    @param {string|null} name */
MountedWeaponDialog.select_recipe = function(dialog, name) {
    dialog.user_data['selected_recipe'] = name;
};

/** @param {SPUI.Dialog} dialog */
MountedWeaponDialog.ondraw = function(dialog) {
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

    // count current traps, grouped by limited_equipped
    var count_attached = {}, count_attaching = {}, count_under_leveled = {};
    // also look for a building that provides the limited_equipped keys
    var provides_limit_building = {}, provides_limit_building_can_upgrade = {};

    session.for_each_real_object(function(obj) {
        if(obj.is_building() && obj.team == 'player') {
            var mounted = null;
            if (dialog.user_data['crafting_category'] === 'barrier_traps' && obj.is_trapped_barrier()) {
                mounted = obj.barrier_trap_item() || obj.barrier_trap_inprogress_item();
            } else if (dialog.user_data['crafting_category'] === 'turret_heads' && obj.is_emplacement()) {
                mounted = obj.turret_head_item() || obj.turret_head_inprogress_item();
            } else if (dialog.user_data['crafting_category'] === 'building_weapons' && obj.is_armed_building()) {
                mounted = obj.building_weapon_item() || obj.building_weapon_inprogress_item();
            } else if (dialog.user_data['crafting_category'] === 'townhall_weapons' && obj.is_armed_townhall()) {
                mounted = obj.townhall_weapon_item() || obj.townhall_weapon_inprogress_item();
            } else if (dialog.user_data['crafting_category'] === 'security_nodes' && obj.is_security_node()) {
                mounted = obj.security_node_item() || obj.security_node_inprogress_item();
            }
            if(mounted) {
                var mounted_spec = ItemDisplay.get_inventory_item_spec(mounted['spec']);
                if('limited_equipped' in mounted_spec) {
                    var key = mounted_spec['limited_equipped'];
                    if(dialog.user_data['crafting_category'] === 'barrier_traps' && mounted === obj.barrier_trap_item()) {
                        count_attached[key] = (count_attached[key] || 0) + 1;
                    } else if (dialog.user_data['crafting_category'] === 'turret_heads' && mounted === obj.turret_head_item()) {
                        count_attached[key] = (count_attached[key] || 0) + 1;
                    } else if (dialog.user_data['crafting_category'] === 'building_weapons' && mounted === obj.building_weapon_item()) {
                        count_attached[key] = (count_attached[key] || 0) + 1;
                    } else if (dialog.user_data['crafting_category'] === 'townhall_weapons' && mounted === obj.townhall_weapon_item()) {
                        count_attached[key] = (count_attached[key] || 0) + 1;
                    } else if (dialog.user_data['crafting_category'] === 'security_nodes' && mounted === obj.security_node_item()) {
                        count_attached[key] = (count_attached[key] || 0) + 1;
                    } else {
                        count_attaching[key] = (count_attaching[key] || 0) + 1;
                    }
                }
                if('level' in mounted_spec && 'associated_tech' in mounted_spec) {
                    var tech_level = player.tech[mounted_spec['associated_tech']] || 0;
                    if(tech_level > mounted_spec['level']) {
                        count_under_leveled[key] = (count_under_leveled[key]||0) + 1;
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
    });

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

            // check for max craftable level
            var recipe_level = 1;
            if('associated_tech' in spec) {
                recipe_level = player.tech[spec['associated_tech']] || 1;
            }

            var product_item = get_crafting_recipe_product_list(spec, recipe_level)[0];
            var product_spec = ItemDisplay.get_inventory_item_spec(product_item['spec']);
            tooltip_text.push(ItemDisplay.strip_inventory_item_ui_name_level_suffix(get_crafting_recipe_ui_name(spec)));
            dialog.widgets['recipe_icon'+wname].asset = get_leveled_quantity(get_crafting_recipe_icon(spec, recipe_level), recipe_level);

            // get list of any unsatisfied requirements
            var pred = null, req = null;
            if(('requires' in spec) && !player.is_cheater) {
                pred = read_predicate(get_leveled_quantity(spec['requires'], recipe_level));
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

                if(count_attached[product_spec['limited_equipped']]) {
                    tooltip_text.push(dialog.data['widgets']['recipe_frame']['ui_tooltip_mounted'].replace('%d', pretty_print_number(count_attached[product_spec['limited_equipped']]||0)));
                }
                if(count_attaching[product_spec['limited_equipped']]) {
                    tooltip_text.push(dialog.data['widgets']['recipe_frame']['ui_tooltip_mounting'].replace('%d', pretty_print_number(count_attaching[product_spec['limited_equipped']]||0)));
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
                    MountedWeaponDialog.select_recipe(w.parent, _name);
                }
                player.quest_tracked_dirty = true;
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
    var mounting_obj = dialog.user_data['emplacement'];
    var current_item = null;
    if (mounting_obj.is_emplacement()) {
        current_item = mounting_obj.turret_head_item();
    } else if (mounting_obj.is_trapped_barrier()) {
        current_item = mounting_obj.barrier_trap_item();
    } else if (mounting_obj.is_armed_building()) {
        current_item = mounting_obj.building_weapon_item();
    } else if (mounting_obj.is_armed_townhall()) {
        current_item = mounting_obj.townhall_weapon_item();
    } else if (mounting_obj.is_security_node()) {
        current_item = mounting_obj.security_node_item();
    }

    dialog.widgets['no_current'].show = !current_item;
    dialog.widgets['current'].show = !!current_item;

    if(current_item) {
        MountedWeaponDialog.set_stats_display(dialog.widgets['current'], dialog.user_data['emplacement'], current_item, null, false);
    }

    // click-to-select
    var selected_recipe_name = dialog.user_data['selected_recipe'];
    dialog.widgets['click_to_select_arrow'].show =
        dialog.widgets['click_to_select'].show = !selected_recipe_name;
    dialog.widgets['selected'].show = !!selected_recipe_name;

    if(dialog.widgets['selected'].show) {
        dialog.widgets['selected'].user_data['current_item'] = current_item;
        dialog.widgets['selected'].user_data['slot_type'] = dialog.user_data['slot_type']; // adds slot type to subdialog for delivery slot later
        MountedWeaponDialog.set_recipe_display(dialog.widgets['selected'], dialog.user_data['emplacement'], selected_recipe_name, dialog);

    } else {
        dialog.widgets['instant_credits'].show =
            dialog.widgets['instant_button'].show =
            dialog.widgets['cost_time_bar'].show =
            dialog.widgets['cost_time_clock'].show =
            dialog.widgets['cost_time'].show =
            dialog.widgets['use_resources_button'].show = false;
    }
};

/** operates on mounted_weapon_dialog_recipe
    @param {SPUI.Dialog} dialog
    @param {GameObject} mounting_obj it will go onto
    @param {string} recipe_name of the recipe
    @param {SPUI.Dialog} parent dialog that contains the "Use Resource"/"Instant" buttons and price/time displays */
MountedWeaponDialog.set_recipe_display = function(dialog, mounting_obj, recipe_name, parent) {
    var slot_type = dialog.user_data['slot_type']; // default to turret_head, changes based on type of crafting
    var current_item = dialog.user_data['current_item']; // set in MountedWeaponDialog.ondraw(), where it defaults to null and changes based on mounting type
    var current_spec = (current_item ? ItemDisplay.get_inventory_item_spec(current_item['spec']) : null);
    var current_level = (current_item ? current_item['level'] : 1);
    var recipe_spec = gamedata['crafting']['recipes'][recipe_name];
    var category = gamedata['crafting']['categories'][recipe_spec['crafting_category']];

    var recipe_level;
    if('associated_tech' in recipe_spec) {
        recipe_level = player.tech[recipe_spec['associated_tech']] || 1;
    } else {
        // note: product could still have level > 1 if it's specified in the product item spec
        recipe_level = 1;
    }

    var product_item = get_crafting_recipe_product_list(recipe_spec, recipe_level)[0];
    var product_level = ItemDisplay.get_inventory_item_level(product_item);
    var product_spec = ItemDisplay.get_inventory_item_spec(product_item['spec']);

    var compat_list;
    if('compatible' in product_spec['equip']) {
        compat_list = product_spec['equip']['compatible'];
    } else {
        compat_list = [product_spec['equip']];
    }

    // see if we need to down-level the recipe
    var downleveled = false;

    // note: to keep code simple, assume product level and recipe level match for this case
    if(!session.home_base && 'associated_tech' in recipe_spec && recipe_level > 1 && product_level == recipe_level) {
        goog.array.forEach(compat_list, function(compat) {
            if('min_level' in compat) {
                var min_level = get_leveled_quantity(compat['min_level'], product_level);
                if(mounting_obj.level < min_level) {
                    // imagine the destination building is upgraded as much as possible, before hitting its own predicate
                    var max_mount_level = mounting_obj.level;
                    for(; max_mount_level < get_max_level(mounting_obj.spec) &&
                        read_predicate(get_leveled_quantity(mounting_obj.spec['requires'], max_mount_level + 1)).is_satisfied(player, null); max_mount_level += 1) {}

                    // downlevel
                    var new_product_level = product_level;
                    while(new_product_level > 1 && max_mount_level < get_leveled_quantity(compat['min_level'], new_product_level)) {
                        new_product_level -= 1;
                    }
                    if(new_product_level < product_level) {
                        //console.log("DOWNLEVELING FROM "+product_level.toString()+' TO '+new_product_level.toString()+' max_mount_level '+max_mount_level.toString());
                        downleveled = true;
                        recipe_level = new_product_level;
                        product_item = get_crafting_recipe_product_list(recipe_spec, recipe_level)[0];
                        product_level = ItemDisplay.get_inventory_item_level(product_item);
                        if(product_level != new_product_level) {
                            throw Error('new_product_level mismatch');
                        }
                        product_spec = ItemDisplay.get_inventory_item_spec(product_item['spec']);
                    }
                }
            }
        });
    }
    parent.widgets['label_downleveled'].show = downleveled;

    MountedWeaponDialog.set_stats_display(dialog.widgets['stats'], mounting_obj, product_item,
                                       // show current_item for comparison, if different from product_item
                                       (current_item && !ItemDisplay.same_item(current_item, product_item) ? current_item : null), downleveled);

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
        var cost = get_leveled_quantity(get_leveled_quantity(recipe_spec['cost'], recipe_level)[res]||0, recipe_level);

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
        var old_power = (current_spec ? get_leveled_quantity(current_spec['equip']['consumes_power'], current_level) : 0);
        var during_power = get_leveled_quantity(recipe_spec['consumes_power'] || 0, recipe_level);
        var new_power = get_leveled_quantity(product_spec['equip']['consumes_power'] || 0, product_level);
        dialog.widgets['cost_power'].show =
            dialog.widgets['resource_power_icon'].show = (new_power > 0 || old_power > 0);
        if(dialog.widgets['cost_power'].show) {
            dialog.widgets['cost_power'].tooltip.str = dialog.data['widgets']['cost_power']['ui_tooltip'].replace('%CUR', pretty_print_number(old_power)).replace('%AFTER', pretty_print_number(new_power)).replace('%DURING', pretty_print_number(during_power));

            var ui_delta;
            if(new_power > old_power) {
                ui_delta = '+' + pretty_print_number(new_power - old_power);
            } else if(new_power < old_power) {
                ui_delta = '-' + pretty_print_number(old_power - new_power);
            } else {
                ui_delta = '+0';
            }
            dialog.widgets['cost_power'].str = dialog.data['widgets']['cost_power']['ui_name'].replace('%AFTER', pretty_print_number(new_power)).replace('%DELTA', ui_delta);

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
        parent.widgets['cost_time'].show = !current_item || !ItemDisplay.same_item(current_item, product_item);
    if(parent.widgets['cost_time'].show) {
        var speed = mounting_obj.get_stat('crafting_speed', mounting_obj.get_leveled_quantity(mounting_obj.spec['crafting_speed'] || 1.0));
        var cost_time = Math.max(1, Math.floor(get_leveled_quantity(recipe_spec['craft_time'], recipe_level) / speed));
        parent.widgets['cost_time'].str = pretty_print_time(cost_time);
    }

    // PREDICATE requirement
    if(!player.is_cheater && ('requires' in recipe_spec)) {
        var pred = read_predicate(get_leveled_quantity(recipe_spec['requires'], recipe_level));
        var text = pred.ui_describe(player);
        if(text) {
            req.push(text);
            use_resources_requirements_ok = instant_requirements_ok = false;
            use_resources_helper = instant_helper = get_requirements_help(pred, null);
        }
    }
    dialog.widgets['requirements_text'].set_text_with_linebreaking(req.join(', '));

    // BUILDING COMPATIBILITY requirement
    if(!player.is_cheater) {
        goog.array.forEach(compat_list, function(compat) {
            if('min_level' in compat) {
                var min_level = get_leveled_quantity(compat['min_level'], product_level);
                if(mounting_obj.level < min_level) {
                    var pred = read_predicate({'predicate': 'BUILDING_LEVEL',
                                               'building_type': mounting_obj.spec['name'],
                                               'trigger_level': min_level,
                                               'obj_id': mounting_obj.id});
                    req.push(pred.ui_describe(player));
                    use_resources_requirements_ok = instant_requirements_ok = false;
                    use_resources_helper = instant_helper = get_requirements_help(pred, null);
                }
            }
        });
    }

    // LIMITED EQUIPPED requirement
    if(!player.is_cheater && player.would_violate_limited_equipped(product_spec, new BuildingEquipSlotAddress(mounting_obj.id, slot_type, 0))) {
        use_resources_requirements_ok = instant_requirements_ok = false;
        use_resources_helper = instant_helper = get_requirements_help('limited_equipped', product_spec['name']);
        var msg = parent.data['widgets']['use_resources_button']['ui_tooltip_limited_equipped'];
        tooltip_req_instant.push(msg);
        tooltip_req_use_resources.push(msg);
    }

    // DESCRIPTION
    if(1) {
        var descr_nlines = SPUI.break_lines(get_leveled_quantity(product_spec['ui_description'], product_level),
                                            dialog.widgets['description'].font, dialog.widgets['description'].wh);

        var descr_list = descr_nlines[0].split('\n');
        var descr;
        if(descr_list.length > dialog.data['widgets']['description']['max_lines']) {
            descr = descr_list.slice(0, dialog.data['widgets']['description']['max_lines']).join('\n')+'...';
        } else {
            descr = descr_list.join('\n');
        }
        dialog.widgets['description'].str = descr;
        dialog.widgets['description'].onclick = null;
        ItemDisplay.attach_inventory_item_tooltip(dialog.widgets['description'], product_item, parent);
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

    var craft_spellarg = {'recipe':recipe_name, 'level': recipe_level,
                          'delivery':{'obj_id':mounting_obj.id, 'slot_type':slot_type, 'slot_index': 0, 'replace': 1}
                         };

    if(!current_item || !ItemDisplay.same_item(current_item, product_item)) {
        parent.widgets['use_resources_button'].show = use_resources_offered;
        parent.widgets['use_resources_button'].tooltip.str = null;

        var slow_func = (function (_parent, _obj, _recipe_spec, _product_item, _craft_spellarg) { return function() {

            var new_config = (_obj.config ? goog.object.clone(_obj.config) : {});
            new_config[slot_type] = _product_item['spec'];
            send_to_server.func(["CAST_SPELL", _obj.id, "CONFIG_SET", new_config]);

            start_crafting(_obj, _recipe_spec, _craft_spellarg);
            invoke_ui_locker(_obj.request_sync(), (function (__parent) { return function() { close_dialog(__parent); }; })(_parent));

        }; })(parent, mounting_obj, recipe_spec, product_item, craft_spellarg);

        if(!mounting_obj.is_in_sync()) {
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

        if(get_leveled_quantity(recipe_spec['craft_gamebucks_cost']||-1, recipe_level) < 0) {
            // instant upgrade not offered
            parent.widgets['instant_button'].show = parent.widgets['instant_credits'].show = false;
            parent.default_button = parent.widgets['use_resources_button'];

            if(parent.widgets['use_resources_button'].state == 'normal') {
                // make use_resources_button yellow and default
                parent.widgets['use_resources_button'].state = 'active';
            }
            // else if(parent.widgets['use_resources_button'].state == 'disabled_clickable') {
                // parent.widgets['use_resources_button'].state = 'normal'; ?
            // }
        } else {
            parent.widgets['instant_button'].show = parent.widgets['instant_credits'].show = true;
            parent.default_button = parent.widgets['instant_button'];
        }

        var price = Store.get_user_currency_price(mounting_obj.id, gamedata['spells']['CRAFT_FOR_MONEY'], craft_spellarg);

        // just for diagnostics - price should always be -1 if requirements are not met
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
            if(!mounting_obj.is_in_sync()) {
                parent.widgets['instant_button'].state = 'disabled';
                parent.widgets['instant_button'].str = parent.data['widgets']['instant_button']['ui_name_pending'];
                parent.widgets['instant_credits'].parent = parent.widgets['instant_button'].onclick = null;
            } else {
                parent.widgets['instant_button'].state = 'normal';
                parent.widgets['instant_button'].str = parent.data['widgets']['instant_button']['ui_name'];
                parent.widgets['instant_credits'].onclick =
                    parent.widgets['instant_button'].onclick = (function (_obj, _product_item, _craft_spellarg, _parent) { return function(w) {
                        var dialog = w.parent;

                        var new_config = (_obj.config ? goog.object.clone(_obj.config) : {});
                        new_config[slot_type] = _product_item['spec'];
                        send_to_server.func(["CAST_SPELL", _obj.id, "CONFIG_SET", new_config]);

                        if(Store.place_user_currency_order(_obj.id, "CRAFT_FOR_MONEY", _craft_spellarg,
                                                           (function (__parent) { return function(success) { if(success) { close_dialog(__parent); } } })(_parent))) {
                            invoke_ui_locker(_obj.request_sync());
                        }
                    }; })(mounting_obj, product_item, craft_spellarg, parent);
            }
        }
    } else { // this product is already equipped
        parent.widgets['use_resources_button'].show =
            parent.widgets['instant_credits'].show =
            parent.widgets['instant_button'].show = false;
    }
};

/** Does this item apply any anti_missile modstats?
    @param {!Object} item_spec
    @private */
MountedWeaponDialog._has_anti_missile = function(item_spec) {
    var has_it = false;
    goog.array.forEach(item_spec['equip']['effects'], function(effect) {
        if(effect['stat'] == 'anti_missile') {
            has_it = true;
        }
    });
    return has_it;
};
/** Create a new modchain with the item's anti-missile stats appended
    @param {!ModChain.ModChain} modchain
    @param {!Object} item_spec
    @return {!ModChain.ModChain}
    @private */
MountedWeaponDialog._add_anti_missile_mod = function(modchain, item_spec, item_level) {
    goog.array.forEach(item_spec['equip']['effects'], function(effect) {
        if(effect['stat'] == 'anti_missile') {
            modchain = ModChain.clone(modchain);
            modchain = ModChain.add_mod(modchain, effect['method'], get_leveled_quantity(effect['strength'], item_level), 'equipment', item_spec['name']);
        }
    });
    return modchain;
};

/** Strip off an anti-missile modchain mod that comes from another turret head
    @param {!ModChain.ModChain} modchain
    @return {!ModChain.ModChain}
    @private */
MountedWeaponDialog._remove_turret_head_anti_missile_mod = function(modchain) {
    goog.array.forEach(modchain['mods'], function(mod, i) {
        if(mod['kind'] == 'equipment' && mod['source'] in gamedata['items'] && gamedata['items'][mod['source']]['equip']['slot_type'] == 'turret_head') {
            modchain = ModChain.recompute_without_mod(modchain, i);
        }
    });
    return modchain;
};

/** Does this item apply any permanent_auras modstats?
    @param {!Object} item_spec
    @private */
MountedWeaponDialog._has_permanent_auras = function(item_spec) {
    var has_it = false;
    goog.array.forEach(item_spec['equip']['effects'], function(effect) {
        if(effect['stat'] == 'permanent_auras') {
            has_it = true;
        }
    });
    return has_it;
};
/** Create a new modchain with the item's permanent_auras stats appended
    @param {!ModChain.ModChain} modchain
    @param {!Object} item_spec
    @return {!ModChain.ModChain}
    @private */
MountedWeaponDialog._add_permanent_auras_mod = function(modchain, item_spec, item_level) {
    goog.array.forEach(item_spec['equip']['effects'], function(effect) {
        if(effect['stat'] == 'permanent_auras') {
            modchain = ModChain.clone(modchain);
            modchain = ModChain.add_mod(modchain, effect['method'], get_leveled_quantity(effect['strength'], item_level), 'equipment', item_spec['name']);
        }
    });
    return modchain;
};

/** Strip off a permanent auras modchain mod that comes from another security node
    @param {!ModChain.ModChain} modchain
    @return {!ModChain.ModChain}
    @private */
MountedWeaponDialog._remove_security_node_permanent_auras_mod = function(modchain) {
    goog.array.forEach(modchain['mods'], function(mod, i) {
        if(mod['kind'] == 'equipment' && mod['source'] in gamedata['items'] && gamedata['items'][mod['source']]['equip']['slot_type'] == 'security_node') {
            modchain = ModChain.recompute_without_mod(modchain, i);
        }
    });
    return modchain;
};

// operates on mounted_weapon_dialog_stats
/** @param {SPUI.Dialog} dialog
    @param {GameObject} mounting_obj it will go onto
    @param {!Object} item - the mounted item
    @param {Object|null} relative_to - another mounted item to compare this one to
    @param {boolean} is_downleveled - to show an asterisk for down-leveled mount destinations */
MountedWeaponDialog.set_stats_display = function(dialog, mounting_obj, item, relative_to, is_downleveled) {
    var spec = ItemDisplay.get_inventory_item_spec(item['spec']);
    var level = ItemDisplay.get_inventory_item_level(item);
    var icon_spec = {'icon': get_leveled_quantity(spec['icon'], level)};
    var relative_spec = (relative_to ? ItemDisplay.get_inventory_item_spec(relative_to['spec']) : null);
    var relative_level = (relative_to ? ItemDisplay.get_inventory_item_level(relative_to) : -1);

    dialog.widgets['name'].str = ItemDisplay.get_inventory_item_ui_name(spec);
    if('level' in item) { // leveled item
        dialog.widgets['name'].str += ' L'+item['level'].toString();
        if(is_downleveled) {
            dialog.widgets['name'].str += '*';
        }
    }

    // main icon
    ItemDisplay.set_inventory_item_asset(dialog.widgets['icon'], icon_spec);

    ItemDisplay.attach_inventory_item_tooltip(dialog.widgets['frame'], item);

    var spell = (ItemDisplay.get_inventory_item_weapon_spellname(spec) ? ItemDisplay.get_inventory_item_weapon_spell(spec) : null);
    var relative_spell = ((relative_to && ItemDisplay.get_inventory_item_weapon_spellname(relative_spec)) ? ItemDisplay.get_inventory_item_weapon_spell(relative_spec) : null);

    // fill in damage_vs icons
    init_damage_vs_icons(dialog, {'kind':'building', 'ui_damage_vs':{}}, // fake building spec to fool init_damage_vs_icons()
                         spell);

    // set up stats display
    var statlist = (spell ? get_weapon_spell_features2(mounting_obj.spec, spell) : []);

    // create the UNION of the two stat lists
    if(relative_to) {
        var relative_statlist = (relative_spell ? get_weapon_spell_features2(mounting_obj.spec, relative_spell) : []);
        goog.array.forEach(relative_statlist, function(rstat) {
            // when switching from a ranged weapon to a PBAOE weapon, don't show range dropping to zero
            if(rstat == 'weapon_range') { return; }
            if(!goog.array.contains(statlist, rstat)) {
                statlist.push(rstat);
            }
        });
    }

    if(MountedWeaponDialog._has_anti_missile(spec) ||
       (relative_spec && MountedWeaponDialog._has_anti_missile(relative_spec))) {
           statlist.push('anti_missile');
    }

    if(MountedWeaponDialog._has_permanent_auras(spec) ||
       (relative_spec && MountedWeaponDialog._has_permanent_auras(relative_spec))) {
           statlist.push('permanent_auras');
    }

    for(var i = 0; i < dialog.data['widgets']['descriptionL']['array'][1]; i++) {
        var left = dialog.widgets['descriptionL'+i.toString()], right = dialog.widgets['descriptionR'+i.toString()];
        if(i < statlist.length) {
            left.show = right.show = true;
            var stat = statlist[i];

            // grab the stat from the mount object, if it has it. This might not work if there's overlap
            // between modstats that apply to mounts (?)
            var modchain = mounting_obj.modstats[stat] || ModChain.make_chain(ModChain.get_base_value(stat, spec, level), {'level':level});
            var relative_modchain = (relative_to ? mounting_obj.modstats[stat] || ModChain.make_chain(ModChain.get_base_value(stat, relative_spec, relative_level), {'level':relative_level}) : null);

            ModChain.display_label_widget(left, stat, spell, true);

            if(stat == 'anti_missile') { // needs special handling because it is a stat of the building, not the weapon spell
                // strip off anti-missile mods from any other turret head (but leave alone mods from leader items etc)
                modchain = MountedWeaponDialog._remove_turret_head_anti_missile_mod(modchain);
                modchain = MountedWeaponDialog._add_anti_missile_mod(modchain, spec, level);
                if(relative_modchain && relative_spec) {
                    relative_modchain = MountedWeaponDialog._remove_turret_head_anti_missile_mod(relative_modchain);
                    relative_modchain = MountedWeaponDialog._add_anti_missile_mod(relative_modchain, relative_spec, relative_level);
                }
            } else if(stat == 'permanent_auras') { // needs special handling because it is a stat of the building, not the weapon spell
                // strip off anti-missile mods from any other turret head (but leave alone mods from leader items etc)
                modchain = MountedWeaponDialog._remove_security_node_permanent_auras_mod(modchain);
                modchain = MountedWeaponDialog._add_permanent_auras_mod(modchain, spec, level);
                if(relative_modchain && relative_spec) {
                    relative_modchain = MountedWeaponDialog._remove_security_node_permanent_auras_mod(relative_modchain);
                    relative_modchain = MountedWeaponDialog._add_permanent_auras_mod(relative_modchain, relative_spec, relative_level);
                }
            }

            var detail = ModChain.display_value_detailed(stat, modchain,
                                                         spec, level,
                                                         // NOT mounting_obj.spec, mounting_obj.level,
                                                         spell, level);

            var relative_detail = (relative_to ? ModChain.display_value_detailed(stat, relative_modchain,
                                                                                 relative_spec,
                                                                                 relative_level,
                                                                                 relative_spell, relative_level) : null);
            var bbstr = detail.str;

            var is_delta = relative_to && (relative_detail.value != detail.value);
            if(is_delta) {
                var delta_sign = (detail.value - relative_detail.value >= 0 ? 1 : -1);
                var is_worse = (detail.value < relative_detail.value);
                var ui_stat = gamedata['strings']['modstats']['stats'][stat];
                if(stat.indexOf('impact_auras') === 0) {
                    ui_stat = gamedata['strings']['modstats']['stats']['impact_auras'];
                }
                if((ui_stat['better']||1) < 0) {
                    is_worse = !is_worse; // flip sign of better vs. worse
                }
                var ui_delta;
                if(ui_stat['display'] && ui_stat['display'].indexOf('one_minus_pct') === 0) {
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
