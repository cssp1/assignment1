goog.provide('ObstacleDialog');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('ItemDisplay');

/** @param {Inert} obj */
ObstacleDialog.invoke = function(obj) {
    var dialog_data = gamedata['dialogs']['obstacle_dialog'];
    var dialog = new SPUI.Dialog(dialog_data);
    dialog.user_data['dialog'] = 'obstacle_dialog';
    dialog.user_data['obj'] = obj;
    dialog.widgets['title'].str = gamedata['spells']['REMOVE_OBSTACLE_FOR_FREE']['ui_name_long'];
    dialog.widgets['name'].str = obj.spec['ui_name_long'] || obj.spec['ui_name'];
    dialog.widgets['description'].set_text_bbcode(obj.get_leveled_quantity(obj.spec['ui_description_long'] || obj.spec['ui_description']));
    dialog.widgets['use_resources_button'].str = gamedata['spells']['REMOVE_OBSTACLE_FOR_FREE']['ui_name'];
    dialog.widgets['close_button'].onclick = close_parent_dialog;

    var can_remove = true, helper = null;

    // PREDICATE requirement
    var pred = null, req = null;
    if(('remove_requires' in obj.spec) && !player.is_cheater) {
        pred = read_predicate(obj.get_leveled_quantity(obj.spec['remove_requires']));
        req = pred.ui_describe(player);
        if(req) {
            dialog.widgets['requirements_text'].set_text_with_linebreaking(req);
            can_remove = false;
            helper = get_requirements_help(pred);
        }
    }

    // RESOURCE requirements
    var grid = [0,0], dims = dialog.data['widgets']['requirements_icon']['array'];
    var res_needed = {};
    goog.object.forEach(gamedata['resources'], function(resdata, resname) {
        var wname = grid[0].toString()+','+grid[1].toString();
        var cost = obj.get_leveled_quantity(obj.spec['remove_cost_'+resname] || 0);
        dialog.widgets['requirements_icon'+wname].show =
            dialog.widgets['requirements_value'+wname].show = (cost > 0);
        if(cost > 0) {
            dialog.widgets['requirements_icon'+wname].asset = resdata['icon_small'];
            dialog.widgets['requirements_value'+wname].str = pretty_print_qty_brief(cost);
            dialog.widgets['requirements_value'+wname].tooltip.str = dialog.data['widgets']['requirements_value']['ui_tooltip'].replace('%res', resdata['ui_name']).replace('%qty', pretty_print_number(cost));
            if(cost > player.resource_state[resname][1]) {
                dialog.widgets['requirements_value'+wname].text_color = SPUI.error_text_color;
                can_remove = false;
                res_needed[resname] = cost - player.resource_state[resname][1];
            } else {
                dialog.widgets['requirements_value'+wname].text_color = SPUI.good_text_color;
            }
        }
        grid[1] += 1;
        if(grid[1] >= dims[1]) {
            grid[1] = 0;
            grid[0] += 1;
        }
    });
    if(!helper && goog.object.getCount(res_needed) > 0) {
        helper = get_requirements_help('resources', res_needed);
    }

    while(grid[0] < dims[0]) {
        while(grid[1] < dims[1]) {
            var wname = grid[0].toString()+','+grid[1].toString();
            dialog.widgets['requirements_icon'+wname].show =
                dialog.widgets['requirements_value'+wname].show = false;
            grid[1] += 1;
        }
        grid[1] = 0;
        grid[0] += 1;
    }

    // ITEM requirements
    var ingr_list = [];
    if('remove_ingredients' in obj.spec) {
        // need to manually check for array-of-arrays, since get_leveled_quantity() won't do it right
        if(Array.isArray(obj.spec['remove_ingredients']) && obj.spec['remove_ingredients'].length >= 1 &&
           Array.isArray(obj.spec['remove_ingredients'][0])) {
            ingr_list = obj.get_leveled_quantity(obj.spec['remove_ingredients']);
        } else {
            ingr_list = obj.spec['remove_ingredients'] || [];
        }
    }

    // have to pre-sum by specname and level in case there are multiple matching entries
    var by_specname_and_level = {};
    goog.array.forEach(ingr_list, function(ingr) {
        var stack = ('stack' in ingr ? ingr['stack'] : 1);
        var key = ingr['spec'];
        if('level' in ingr) {
            key += ':'+ingr['level'].toString();
        }
        by_specname_and_level[key] = (by_specname_and_level[key] || 0) + stack;
    });
    var missing_items = [];
    goog.object.forEach(by_specname_and_level, function(qty, key) {
        var specname_level = key.split(':');
        var specname = specname_level[0], level = (specname_level.length > 1 ? parseInt(specname_level[1],10) : null);
        if(player.inventory_item_quantity(specname, level) < qty) {
            missing_items.push({'spec':specname, 'level':level, 'stack': qty - player.inventory_item_quantity(specname, level)});
        }
    });
    if(missing_items.length > 0) {
        can_remove = false;
        if(!helper) {
            helper = get_requirements_help('crafting_ingredients', missing_items);
        }
    }

    ItemDisplay.display_item_array(dialog, 'requirements_item', ingr_list, {context_parent: dialog,
                                                                            hide_tooltip: true});
    var by_specname = {};
    for(var i = 0; i < dialog.data['widgets']['requirements_item']['array'][0]; i++) {
        if(i < ingr_list.length) {
            var ingr = ingr_list[i];
            var ingr_spec = ItemDisplay.get_inventory_item_spec(ingr['spec']);
            var ingr_stack = ('stack' in ingr ? ingr['stack'] : 1);
            var ingr_level = ('level' in ingr ? ingr['level'] : null);
            var ui_ingr = ItemDisplay.get_inventory_item_stack_prefix(ingr_spec, ingr_stack) + ItemDisplay.get_inventory_item_ui_name_long(ingr_spec, ingr_level);
            dialog.widgets['requirements_item'+i.toString()].widgets['frame'].tooltip.str =
                dialog.data['widgets']['requirements_item']['ui_tooltip'].replace('%ITEM', ui_ingr);

            // group items by spec/level for the tooltip
            var key = ingr['spec'];
            if(ingr_level) { key += ':L'+ingr_level.toString(); }

            var has_it = player.inventory_item_quantity(ingr['spec'], ingr['level']) - (by_specname[key] || 0) >= ingr_stack;
            by_specname[key] = (by_specname[key]||0) + ingr_stack;
            dialog.widgets['requirements_item'+i.toString()].widgets['frame'].state = (has_it ? 'normal_nohighlight' : 'disabled');
            dialog.widgets['requirements_item_status'+i.toString()].show = true;
            dialog.widgets['requirements_item_status'+i.toString()].color = SPUI.make_colorv(dialog.data['widgets']['requirements_item_status'][(has_it ? 'color_present' : 'color_missing')]);
            if(!has_it) {
                can_remove = false;
            }
        } else {
            dialog.widgets['requirements_item_status'+i.toString()].show = false;
        }
    }

    // TIME requirement
    var cost_time = obj.get_leveled_quantity(obj.spec['remove_time']);
    dialog.widgets['cost_time'].str = pretty_print_time_brief(cost_time);

    if(!can_remove) {
        dialog.widgets['use_resources_button'].state = 'disabled_clickable';
        dialog.widgets['use_resources_button'].onclick = helper;
    } else {
        dialog.widgets['use_resources_button'].state = 'normal';
        dialog.widgets['use_resources_button'].onclick = function(w) {
            var dialog = w.parent;
            var obj = w.parent.user_data['obj'];
            close_parent_dialog(w);

            var busy_list = player.remover_get_tasks();
            if(busy_list.length > 0) {
                change_selection(busy_list[0]);
                invoke_speedup_dialog('removing');
                return;
            }

            invoke_ui_locker();
            send_to_server.func(["CAST_SPELL", obj.id, "REMOVE_OBSTACLE_FOR_FREE"]);
        };
    }

    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;
    return dialog;
};
