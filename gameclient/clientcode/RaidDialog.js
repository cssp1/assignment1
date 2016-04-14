goog.provide('RaidDialog');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('goog.object');
goog.require('PlayerCache');
goog.require('SPUI');

/** @param {number} squad_id
    @param {string} feature_id
    @return {SPUI.Dialog|null} */
RaidDialog.invoke = function(squad_id, feature_id) {
    var squad = player.squads[squad_id.toString()];
    if(!squad) { return null; }

    var dialog = new SPUI.Dialog(gamedata['dialogs']['raid_dialog']);
    dialog.user_data['dialog'] = 'raid_dialog';
    dialog.user_data['squad_id'] = squad_id;
    dialog.user_data['feature_id'] = feature_id;
    dialog.user_data['icon_unit_specname'] = null; // updated by ondraw

    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;
    dialog.widgets['close_button'].onclick = dialog.widgets['cancel_button'].onclick = close_parent_dialog;
    dialog.widgets['ok_button'].onclick = function(w) {
        var dialog = w.parent;

        var squad_id = dialog.user_data['squad_id'];
        var squad = player.squads[squad_id.toString()];
        var feature = session.region.find_feature_by_id(dialog.user_data['feature_id']);
        if(!squad || !feature) { close_dialog(dialog); return; }

        // find path to target
        var raid_path = player.raid_find_path_to(player.home_base_loc, feature);
        if(!raid_path) {
            var s = gamedata['errors']['INVALID_MAP_LOCATION'];
            invoke_child_message_dialog(s['ui_title'], s['ui_name'].replace('%BATNAME', squad['ui_name'] || ''), {'dialog':'message_dialog_big'});
            return;
        }

        // perform deployment
        squad['pending'] = true;
        var raid_info = {'path': raid_path};
        send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_ENTER_MAP", squad_id, player.home_base_loc, raid_info]);

        // play movement sound
        if(dialog.user_data['icon_unit_specname']) {
            var spec = gamedata['units'][dialog.user_data['icon_unit_specname']];
            if('sound_destination' in spec) {
                GameArt.play_canned_sound(spec['sound_destination']);
            }
        }
        close_dialog(dialog);
    };
    dialog.ondraw = RaidDialog.update;
    return dialog;
};

/** @param {!SPUI.Dialog} dialog */
RaidDialog.update = function(dialog) {
    var squad_id = dialog.user_data['squad_id'];
    var squad = player.squads[squad_id.toString()];
    var feature = session.region.find_feature_by_id(dialog.user_data['feature_id']);
    if(!squad || !feature) { close_dialog(dialog); return; }

    dialog.widgets['name_left'].str = player.ui_name;
    dialog.widgets['squad_name'].str = squad['ui_name'] || dialog.data['widgets']['squad_name']['ui_name']; // "Unnamed"
    RaidDialog.update_squad_scrollers(dialog, squad_id);

    // scan squad for raid mode, cargo capacity, and unit icon
    var raid_mode = 'pickup'; // XXX could be 'scout'
    /** @type {Object<string,number>|null} */
    var cargo_cap = null;

    for(var obj_id in player.my_army) {
        var obj = player.my_army[obj_id];
        if(obj['squad_id'] === squad_id) {
            // update squad unit icon using any unit from the squad
            var spec = gamedata['units'][obj['spec']]
            dialog.user_data['icon_unit_specname'] = obj['spec'];
            dialog.widgets['squad_unit_icon'].asset = get_leveled_quantity(spec['art_asset'], obj['level']||1);
            for(var res in gamedata['resources']) {
                var amount = get_leveled_quantity(spec['cargo_'+res] || 0, obj['level']||1);
                if(amount > 0) {
                    raid_mode = 'pickup';
                    if(cargo_cap === null) { cargo_cap = {}; }
                    cargo_cap[res] = (cargo_cap[res] || 0) + amount;
                }
            }
        }
    }
    dialog.widgets['site_name'].str = feature['base_ui_name'];
    dialog.widgets['site_icon'].state = (feature['base_type'] == 'quarry' ?
                                         'quarry_'+feature['base_icon'] :
                                         'base');
    var enemy_info = PlayerCache.query_sync_fetch(feature['base_landlord_id']);
    dialog.widgets['name_right'].str = (enemy_info ? PlayerCache._get_ui_name(enemy_info) : null) || dialog.data['widgets']['name_right']['ui_name'];
    dialog.widgets['portrait_left'].set_user(session.user_id, true);
    dialog.widgets['portrait_right'].set_user(feature['base_landlord_id'], true);
    dialog.widgets['level_left'].str = dialog.data['widgets']['level_left']['ui_name'].replace('%level', player.level().toString());
    dialog.widgets['level_right'].str = dialog.data['widgets']['level_right']['ui_name'].replace('%level', (enemy_info ? (enemy_info['player_level'] || 1).toString() : '?'));
    dialog.widgets['coords_left'].str = player.home_base_loc[0].toString()+','+player.home_base_loc[1].toString();
    dialog.widgets['coords_right'].str = feature['base_map_loc'][0].toString()+','+feature['base_map_loc'][1].toString();
    if(feature['base_type'] === 'quarry') {
        var rich_str = quarry_richness_ui_str(feature['base_richness']);
        dialog.widgets['site_size'].str = dialog.data['widgets']['site_size']['ui_name'].replace('%qsize', rich_str);
    } else {
        dialog.widgets['site_size'].str = null;
    }

    // too slow?
    var raid_path = player.raid_find_path_to(player.home_base_loc, feature);
    if(raid_path) {
        var travel_time = player.squad_travel_time(squad_id, raid_path);
        dialog.widgets['travel_time'].str = dialog.data['widgets']['travel_time']['ui_name'].replace('%time', pretty_print_time(travel_time));
    } else {
        dialog.widgets['travel_time'].str = dialog.data['widgets']['travel_time']['ui_name_blocked'];
    }

    if(raid_mode == 'attack' || raid_mode == 'scout') {
        dialog.widgets['advantage'].show =
            dialog.widgets['advantage_label'].show = true;
        var adv = 'very_good'; // "neutral","good","very_good","best","bad","very_bad","worst"
        dialog.widgets['advantage'].set_text_bbcode(dialog.data['widgets']['advantage']['ui_name_'+adv]);
    } else {
        dialog.widgets['advantage'].show =
            dialog.widgets['advantage_label'].show = false;
    }

    var scout_time = -1;
    dialog.widgets['scout_time'].str = (scout_time > 0 ? dialog.data['widgets']['scout_time']['ui_name_scouted'].replace('%time', pretty_print_time_brief(server_time - scout_time)) : dialog.data['widgets']['scout_time']['ui_name']);
    dialog.widgets['scout_time'].show = false; // XXX implement scouting

    // XXX implement raid combat stats
    dialog.widgets['str_sunken_left'].show =
        dialog.widgets['str_sunken_right'].show = false;

    RaidDialog.update_cargo(dialog, squad_id, cargo_cap);
    RaidDialog.update_loot(dialog, feature);

    dialog.widgets['description'].set_text_bbcode(dialog.data['widgets']['description']['ui_name_'+raid_mode]);
};

/** @param {!SPUI.Dialog} dialog
    @param {number} squad_id
    @param {Object<string,number>|null} cargo_cap */
RaidDialog.update_cargo = function(dialog, squad_id, cargo_cap) {
    var row = 0;
    dialog.widgets['cargo_label'].show = !!cargo_cap;
    if(cargo_cap) {
        // normalize to highest amount of any resource
        var max_amount = 1;
        for(var res in cargo_cap) {
            max_amount = Math.max(max_amount, cargo_cap[res]);
        }
        for(var res in gamedata['resources']) {
            var resdata = gamedata['resources'][res];
            var amount = cargo_cap[res] || 0;
            dialog.widgets['cargo_bar'+row.toString()].show =
                dialog.widgets['cargo_prog'+row.toString()].show =
                dialog.widgets['cargo_icon'+row.toString()].show =
                dialog.widgets['cargo_amount'+row.toString()].show = true;
            dialog.widgets['cargo_icon'+row.toString()].asset = resdata['icon_small'];
            dialog.widgets['cargo_prog'+row.toString()].progress = amount/max_amount;
            dialog.widgets['cargo_prog'+row.toString()].full_color = SPUI.make_colorv(resdata['bar_full_color']);
            dialog.widgets['cargo_amount'+row.toString()].str = pretty_print_number(amount);
            row += 1;
            if(row >= dialog.data['widgets']['cargo_bar']['array'][1]) { break; }
        }
    } else {
    }

    while(row < dialog.data['widgets']['cargo_bar']['array'][1]) {
        dialog.widgets['cargo_bar'+row.toString()].show =
            dialog.widgets['cargo_prog'+row.toString()].show =
            dialog.widgets['cargo_icon'+row.toString()].show =
            dialog.widgets['cargo_amount'+row.toString()].show = false;
        row += 1;
    }
};

/** @param {!SPUI.Dialog} dialog
    @param {!Object<string,?>} feature */
RaidDialog.update_loot = function(dialog, feature) {
    var row = 0;
    dialog.widgets['loot_label'].show = ('base_resource_loot' in feature);
    if('base_resource_loot' in feature) {
        // normalize to highest amount of any remaining resource
        var max_amount = 1;
        for(var res in feature['base_resource_loot']) {
            max_amount = Math.max(max_amount, feature['base_resource_loot'][res]);
        }
        for(var res in gamedata['resources']) {
            var resdata = gamedata['resources'][res];
            var amount = feature['base_resource_loot'][res] || 0;
            dialog.widgets['loot_icon'+row.toString()].asset = resdata['icon_small'];
            dialog.widgets['loot_prog'+row.toString()].progress = amount/max_amount;
            dialog.widgets['loot_prog'+row.toString()].full_color = SPUI.make_colorv(resdata['bar_full_color']);
            dialog.widgets['loot_amount'+row.toString()].str = pretty_print_number(amount);
            row += 1;
            if(row >= dialog.data['widgets']['loot_bar']['array'][1]) { break; }
        }
    } else {
    }

    while(row < dialog.data['widgets']['loot_bar']['array'][1]) {
        dialog.widgets['loot_bar'+row.toString()].show =
            dialog.widgets['loot_prog'+row.toString()].show =
            dialog.widgets['loot_icon'+row.toString()].show =
            dialog.widgets['loot_amount'+row.toString()].show = false;
        row += 1;
    }

    dialog.widgets['item_loot_label'].show = false; // for now
};

/** @param {!SPUI.Dialog} dialog
    @param {number} squad_id */
RaidDialog.update_squad_scrollers = function(dialog, squad_id) {
    // sort all raid squads in numerical order
    var squad_list = goog.array.map(goog.object.getKeys(player.squads), function(sid) { return parseInt(sid,10); });
    squad_list = goog.array.filter(squad_list, function(id) { return player.squad_is_raid(id) && !player.squad_is_deployed(id); });
    squad_list.sort();
    var cur_index = squad_list.indexOf(squad_id);
    dialog.widgets['squad_scroll_left'].state = (cur_index > 0 ? 'normal' : 'disabled');
    if(cur_index > 0) {
        dialog.widgets['squad_scroll_left'].onclick = (function (new_sid) { return function(w) {
            var dialog = w.parent; dialog.user_data['squad_id'] = new_sid;
        }; })(squad_list[cur_index - 1]);
    }
    dialog.widgets['squad_scroll_right'].state = (cur_index >= 0 && cur_index < squad_list.length-1 ? 'normal' : 'disabled');
    if(cur_index >= 0 && cur_index < squad_list.length-1) {
        dialog.widgets['squad_scroll_right'].onclick = (function (new_sid) { return function(w) {
            var dialog = w.parent; dialog.user_data['squad_id'] = new_sid;
        }; })(squad_list[cur_index + 1]);
    }
};