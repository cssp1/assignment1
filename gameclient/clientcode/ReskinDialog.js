goog.provide('ReskinDialog');

// Copyright (c) 2022 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('SPUI');
goog.require('SPText');

// tightly coupled to main.js, sorry!

/** @param {string|null} category */
ReskinDialog.invoke = function(category) {
    var dialog_data = gamedata['dialogs']['reskin_dialog'];
    var dialog = new SPUI.Dialog(dialog_data);
    dialog.user_data['dialog'] = 'reskin_dialog';
    dialog.user_data['category'] = category;
    var catspec = gamedata['crafting']['categories'][category];
    dialog.widgets['title'].str = catspec['ui_name'];
    dialog.widgets['close_button'].onclick = function() { change_selection(null); };
    dialog.widgets['dev_title'].show = player.is_cheater;
    dialog.user_data['selected_unit'] = 'none';
    dialog.user_data['selected_skin'] = 'none'
    dialog.user_data['unit_page'] = 0;
    dialog.user_data['max_unit_page'] = 0;
    dialog.user_data['skin_page'] = 0;
    dialog.user_data['max_skin_page'] = 0;
    dialog.ondraw = ReskinDialog.update;
    dialog.on_mousewheel_function = ReskinDialog.scroll;
    dialog.widgets['scroll_unit_down'].widgets['scroll_right'].onclick = (function (_dialog) { return function(w) { ReskinDialog.scroll_units(_dialog, 1); }; })(dialog);
    dialog.widgets['scroll_unit_up'].widgets['scroll_left'].onclick = (function (_dialog) { return function(w) { ReskinDialog.scroll_units(_dialog, -1); }; })(dialog);
    dialog.widgets['scroll_skin_down'].onclick = (function (_dialog) { return function(w) { ReskinDialog.scroll_skins(_dialog, 1); }; })(dialog);
    dialog.widgets['scroll_skin_up'].onclick = (function (_dialog) { return function(w) { ReskinDialog.scroll_skins(_dialog, -1); }; })(dialog);
    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;
    return dialog;
};

/** @param {SPUI.Dialog} dialog
    @param {number} delta */
ReskinDialog.scroll = function(dialog, delta) {
    var mouse_x = mouse_state['last_raw_x'];
    var dialog_x = dialog.xy[0];

    var units_x_min = dialog_x + dialog.data['widgets']['unit_frame']['xy'][0] - 15;
    var units_x_max = units_x_min + dialog.data['widgets']['unit_frame']['dimensions'][0] + 30;
    if(mouse_x >= units_x_min && mouse_x <= units_x_max) {
        ReskinDialog.scroll_units(dialog, delta);
    }

    var skins_x_min = dialog_x + dialog.data['widgets']['skin_frame']['xy'][0] - 15;
    var skins_x_max = dialog_x + dialog.data['widgets']['scroll_skin_up']['xy'][0] + dialog.data['widgets']['scroll_skin_up']['dimensions'][0] + 15;
    if(mouse_x >= skins_x_min && mouse_x <= skins_x_max) {
        ReskinDialog.scroll_skins(dialog, delta);
    }
};

/** @param {SPUI.Dialog} dialog
    @param {number} delta */
ReskinDialog.scroll_units = function(dialog, delta) {
    if(delta < 0 && dialog.user_data['unit_page'] > 0) { dialog.user_data['unit_page'] -= 1; }
    if(delta > 0 && dialog.user_data['unit_page'] < dialog.user_data['max_unit_page']) { dialog.user_data['unit_page'] += 1; }
};

/** @param {SPUI.Dialog} dialog
    @param {number} delta */
ReskinDialog.scroll_skins = function(dialog, delta) {
    if(delta < 0 && dialog.user_data['skin_page'] > 0) { dialog.user_data['skin_page'] = dialog.user_data['skin_page'] - 1; }
    if(delta > 0 && dialog.user_data['skin_page'] < dialog.user_data['max_skin_page']) { dialog.user_data['skin_page'] = dialog.user_data['skin_page'] + 1; }
};

/** @param {SPUI.Dialog} dialog
    @param {string|null} name */
ReskinDialog.select_unit = function(dialog, name) {
    dialog.user_data['selected_unit'] = name;
    dialog.user_data['skin_page'] = 0;
    for(var x = 0; x < dialog.data['widgets']['skin_frame']['array'][0]; x++) {
        for(var y = 0; y < dialog.data['widgets']['skin_frame']['array'][1]; y++) {
            var grid_address = x.toString() + ',' + y.toString()
            var skin_slot = 'skin_slot' + grid_address;
            var skin_icon = 'skin_icon' + grid_address;
            var skin_gray_outer = 'skin_gray_outer' + grid_address;
            var skin_frame = 'skin_frame' + grid_address;
            dialog.widgets[skin_gray_outer].show = true;
            dialog.widgets[skin_icon].asset = null;
            dialog.widgets[skin_frame].tooltip.str = null;
            dialog.widgets[skin_frame].onclick = null;
        }
    }
};

/** @param {SPUI.Dialog} dialog
    @param {string|null} name */
ReskinDialog.select_skin = function(dialog, name) {
    dialog.user_data['selected_skin'] = name;
};

/** @param {SPUI.Dialog} dialog */
ReskinDialog.update = function(dialog) {
    var category = dialog.user_data['category'];
    var selected_unit = dialog.user_data['selected_unit'];
    var selected_skin = dialog.user_data['selected_skin'];
    var unit_page = dialog.user_data['unit_page'];
    var skin_page = dialog.user_data['skin_page'];
    var catspec = gamedata['crafting']['categories'][category];
    dialog.user_data['units'] = [];
    dialog.user_data['skins'] = [];
    for(var name in gamedata['crafting']['recipes']) {
        var spec = gamedata['crafting']['recipes'][name];
        if(spec['crafting_category'] != category) { continue; }
        if(spec['developer_only'] && (spin_secure_mode || !player.is_developer())) { continue; }
        if('show_if' in spec && !read_predicate(spec['show_if']).is_satisfied(player, null)) { continue; }
        if('activation' in spec && !read_predicate(spec['activation']).is_satisfied(player, null)) { continue; }
        var rec = {'spec': name};
        var unit_name = spec['unit_name'];
        if(selected_unit === 'none') { selected_unit = dialog.user_data['selected_unit'] = unit_name; }
        if(!(goog.array.contains(dialog.user_data['units'], unit_name))) { dialog.user_data['units'].push(unit_name); }
        if(unit_name === selected_unit) {
            if(selected_skin === 'none') { selected_skin = dialog.user_data['selected_skin'] = name; }
            dialog.user_data['skins'].push(rec);
        }
    }
    dialog.user_data['max_unit_page'] = Math.max(0, dialog.user_data['units'].length - dialog.data['widgets']['unit_frame']['array'][1]);
    dialog.user_data['max_skin_page'] = Math.max(0, (dialog.user_data['skins'].length - (dialog.data['widgets']['skin_frame']['array'][0] * dialog.data['widgets']['skin_frame']['array'][1])) / dialog.data['widgets']['skin_frame']['array'][0]);
    ReskinDialog.update_unit_list(dialog);
    ReskinDialog.update_skin_grid(dialog);
    ReskinDialog.update_skin_display(dialog);
    ReskinDialog.update_skin_build_button(dialog);
};

/** @param {SPUI.Dialog} dialog  */
ReskinDialog.update_skin_grid = function(dialog) {
    var skin_page = dialog.user_data['skin_page'];
    dialog.widgets['scroll_skin_up'].show =
    dialog.widgets['scroll_skin_down'].show =
    dialog.widgets['scroll_skin_text'].show = (dialog.user_data['skins'].length > dialog.data['widgets']['skin_frame']['array'][0] * dialog.data['widgets']['skin_frame']['array'][1]);
    dialog.widgets['scroll_skin_up'].state = (dialog.user_data['skin_page'] <= 0 ? 'disabled' : 'normal');
    dialog.widgets['scroll_skin_down'].state = (dialog.user_data['skin_page'] >= dialog.user_data['max_skin_page'] ? 'disabled' : 'normal');
    for(var x = 0; x < dialog.data['widgets']['skin_frame']['array'][0]; x++) {
        for(var y = 0; y < dialog.data['widgets']['skin_frame']['array'][1]; y++) {
            var grid_address = x.toString() + ',' + y.toString()
            var skin_slot = 'skin_slot' + grid_address;
            var skin_icon = 'skin_icon' + grid_address;
            var skin_gray_outer = 'skin_gray_outer' + grid_address;
            var skin_frame = 'skin_frame' + grid_address;
            var skin_index = x + (y * dialog.data['widgets']['skin_frame']['array'][0]) + (skin_page * dialog.data['widgets']['skin_frame']['array'][0]);
            if(skin_index + 1 > dialog.user_data['skins'].length) {
                // reset / hide everything for empty slots
                dialog.widgets[skin_gray_outer].show = true;
                dialog.widgets[skin_icon].asset = null;
                dialog.widgets[skin_frame].onclick = null;
                dialog.widgets[skin_frame].tooltip.str = '';
            } else {
                // show the skin
                var rec = dialog.user_data['skins'][skin_index];
                var rec_name = rec['spec'];
                var skin_spec = gamedata['crafting']['recipes'][rec_name];
                var product_name = skin_spec['product'][0]['spec'];
                var item_spec = gamedata['items'][product_name];
                var selected_unit = dialog.user_data['selected_unit'];
                var unit_spec = gamedata['units'][selected_unit];
                dialog.widgets[skin_gray_outer].show = false;
                dialog.widgets[skin_icon].asset = item_spec['icon'];
                var pred;
                if('requires' in skin_spec) { pred = read_predicate(skin_spec['requires']); }
                if(pred && !pred.is_satisfied(player, null)) {
                    // do something to gray out
                    //dialog.widgets[skin_icon].alpha = 0.3;
                    //dialog.widgets[skin_icon].state = 'disabled';
                }
                dialog.widgets[skin_frame].tooltip.str = dialog.data['widgets']['skin_frame']['ui_tooltip'].replace('%UNITS', unit_spec['ui_name_plural']).replace('%COLOR', skin_spec['color']);
                dialog.widgets[skin_frame].onclick = (function (_dialog, _rec_name) { return function(w) {
                    ReskinDialog.select_skin(_dialog, _rec_name);
                }; })(dialog, rec_name);
            }
        }
    }
}

/** @param {SPUI.Dialog} dialog  */
ReskinDialog.update_skin_display = function(dialog) {
    var selected_skin = dialog.user_data['selected_skin'];
    if(selected_skin === 'none') { // unlikely corner case
        var selected_unit = dialog.user_data['selected_unit'];
        if(selected_unit === 'none') { dialog.widgets['name'].str = dialog.data['widgets']['name']['ui_name_no_unit_selected']; }
        else { dialog.widgets['name'].str = dialog.data['widgets']['name']['ui_name_no_recipe_selected']; }
        dialog.widgets['unit_hero_icon'].show =
        dialog.widgets['description'].show =
        dialog.widgets['requirements_text'].show = false;
        return;
    }
    var skin_spec = gamedata['crafting']['recipes'][selected_skin];
    var item_name = skin_spec['product'][0]['spec'];
    var item_spec = gamedata['items'][item_name];
    var hero_asset = item_spec['equip']['effects'][0]['strength'];
    dialog.widgets['unit_hero_icon'].bg_image = hero_asset;
    dialog.widgets['unit_hero_icon'].state = 'hero';
    dialog.widgets['unit_hero_icon'].show = true;
    dialog.widgets['name'].str = item_spec['ui_name'];
    dialog.widgets['description'].str = item_spec['ui_description'];
    dialog.widgets['requirements_text'].show = false;
    var pred, req_text;
    if('requires' in skin_spec) { pred = read_predicate(skin_spec['requires']); }
    if(pred && !pred.is_satisfied(player, null)) {
        req_text = pred.ui_describe(player);
        if(req_text) {
            dialog.widgets['requirements_text'].show = true;
            dialog.widgets['requirements_text'].str = req_text;
        }
    }
};

/** @param {SPUI.Dialog} dialog */
ReskinDialog.update_unit_list = function(dialog) {
    var unit_page = dialog.user_data['unit_page'];
    var display_page = unit_page + 1;
    var end_display_page = unit_page + dialog.data['widgets']['unit_frame']['array'][1];
    var selected_unit = dialog.user_data['selected_unit'];
    dialog.widgets['scroll_unit_up'].show =
    dialog.widgets['scroll_unit_down'].show =
    dialog.widgets['scroll_unit_text'].show = (dialog.user_data['units'].length > dialog.data['widgets']['unit_frame']['array'][1]);
    dialog.widgets['scroll_unit_up'].widgets['scroll_left'].state = (dialog.user_data['unit_page'] <= 0 ? 'disabled' : 'normal');
    dialog.widgets['scroll_unit_down'].widgets['scroll_right'].state = (dialog.user_data['unit_page'] >= dialog.user_data['max_unit_page'] ? 'disabled' : 'normal');
    dialog.widgets['scroll_unit_text'].str = dialog.data['widgets']['scroll_unit_text']['ui_name'].replace('%d1', display_page.toString()).replace('%d2',end_display_page.toString()).replace('%d3',dialog.user_data['units'].length.toString());
    for(var y = 0; y < dialog.data['widgets']['unit_frame']['array'][1]; y++) {
        var unit_slot = 'unit_slot' + y.toString();
        var unit_icon = 'unit_icon' + y.toString();
        var unit_gray_outer = 'unit_gray_outer' + y.toString();
        var unit_frame = 'unit_frame' + y.toString();
        var unit_list_offset = y + unit_page;
        var unit_name = 'none';
        var unit_spec = null;
        if(unit_list_offset + 1 <= dialog.user_data['units'].length) {
            unit_name = dialog.user_data['units'][unit_list_offset];
            unit_spec = gamedata['units'][unit_name]
        }
        if(unit_name === 'none') {
            dialog.widgets[unit_slot].show =
            dialog.widgets[unit_icon].show =
            dialog.widgets[unit_gray_outer].show =
            dialog.widgets[unit_frame].show = false;
        } else {
            dialog.widgets[unit_frame].tooltip.str = dialog.data['widgets']['unit_frame']['ui_tooltip'].replace('%UNITS', unit_spec['ui_name_plural']);
            dialog.widgets[unit_icon].asset = 'inventory_' + get_current_art_asset(unit_spec);
            dialog.widgets[unit_icon].state = 'normal';
            dialog.widgets[unit_gray_outer].show = false;
            dialog.widgets[unit_frame].onclick = (function (_dialog, _unit_name) { return function(w) {
                ReskinDialog.select_unit(_dialog, _unit_name);
            }; })(dialog, unit_name);
        }
    }
};

/** @param {SPUI.Dialog} dialog  */
ReskinDialog.update_skin_build_button = function(dialog) {
    var unit_name = dialog.user_data['selected_unit'];
    var selected_skin = dialog.user_data['selected_skin'];
    if(selected_skin === 'none') {
        dialog.widgets['apply_paint_button'].show = false;
        return
    }
    var unit_spec = gamedata['units'][unit_name];
    var unit_category = unit_spec['manufacture_category'];
    dialog.widgets['apply_paint_button'].str = dialog.data['widgets']['apply_paint_button']['ui_name'];
    dialog.widgets['apply_paint_button'].state = 'normal';
    if(unit_category === 'rovers' && (gamedata['game_id'] === 'tr' || gamedata['game_id'] === 'dv' || gamedata['game_id'] === 'fs' || gamedata['game_id'] === 'bfm')) {
        dialog.widgets['apply_paint_button'].str = dialog.data['widgets']['apply_paint_button']['ui_name_infantry'];
    }
    var skin_spec = gamedata['crafting']['recipes'][selected_skin];
    var skin_cat = skin_spec['crafting_category'];
    var builder_type = get_workshop_for(skin_cat);
    var builder = find_object_by_type(builder_type);
    var delivery_slot_type = gamedata['crafting']['categories'][skin_cat]['delivery_slot_type'];
    var can_cast = can_cast_spell_detailed(builder.id, 'CRAFT_FOR_FREE', [{'recipe': selected_skin,
                                                                           'delivery': {'unit_equip_slot':unit_name, 'slot_type':delivery_slot_type, 'slot_index': 0, 'replace': 1}}]);
    var build_cb, pred, req_text;
    if('requires' in skin_spec) { pred = read_predicate(skin_spec['requires']); }
    if(pred && !pred.is_satisfied(player, null)) {
        req_text = pred.ui_describe(player);
        if(req_text) {
            dialog.widgets['apply_paint_button'].tooltip.str = dialog.data['widgets']['apply_paint_button']['ui_tooltip_unmet'] + '\n' + req_text;
            helper = get_requirements_help(pred, null);
            dialog.widgets['apply_paint_button'].state = 'disabled';
            dialog.widgets['apply_paint_button'].str = dialog.data['widgets']['apply_paint_button']['ui_name_unmet'];
            if(unit_category === 'rovers' && (gamedata['game_id'] === 'tr' || gamedata['game_id'] === 'dv' || gamedata['game_id'] === 'fs' || gamedata['game_id'] === 'bfm')) {
                dialog.widgets['apply_paint_button'].str = dialog.data['widgets']['apply_paint_button']['ui_name_infantry_unmet'];
            }
        }
    }
    if(can_cast[0]) {
        // the real build function
        build_cb = (function (_builder, _skin_spec, _unit_name, _delivery_slot_type) { return function() {
                    var extra_params = {'delivery': {'unit_equip_slot':_unit_name, 'slot_type':_delivery_slot_type, 'slot_index': 0, 'replace':1 }, 'level': 1 };
                    start_crafting(_builder, _skin_spec, extra_params);
                    // play sound effect
                    GameArt.play_canned_sound('action_button_134px');
                    return true;
                }; })(builder, skin_spec, unit_name, delivery_slot_type);
    } else if(can_cast[2]) {
        var helper = get_requirements_help(can_cast[2][0], can_cast[2][1], can_cast[2][2]);
        build_cb = (helper ? (function (_helper) { return function() { _helper(); return false; }; })(helper) : null);
    }
    dialog.widgets['apply_paint_button'].onclick = build_cb;
};
