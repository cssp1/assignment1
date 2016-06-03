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
    var feature = session.region.find_feature_by_id(feature_id);

    if(!squad || !feature) { return null; }

    var dialog = new SPUI.Dialog(gamedata['dialogs']['raid_dialog']);
    dialog.user_data['dialog'] = 'raid_dialog';
    dialog.user_data['squad_id'] = squad_id;
    dialog.user_data['feature_id'] = feature_id;
    dialog.user_data['icon_unit_specname'] = null; // updated by ondraw
    dialog.user_data['caps'] = null; // cache of squad capabilities, updated by ondraw
    dialog.user_data['scout_data'] = null; // pending

    if(!SquadCapabilities.feature_is_defenseless(feature)) {
        dialog.user_data['scout_data_pending'] = true;
        query_scout_reports(feature['base_id'], goog.partial(RaidDialog.receive_scout_reports, dialog));
    } else {
        dialog.user_data['scout_data_pending'] = false;
    }

    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;
    dialog.widgets['close_button'].onclick = dialog.widgets['cancel_button'].onclick = close_parent_dialog;

    dialog.widgets['attack_button'].onclick = function(w) { RaidDialog.launch(w.parent, 'attack'); };
    dialog.widgets['scout_button'].onclick = function(w) { RaidDialog.launch(w.parent, 'scout'); };
    dialog.widgets['pickup_button'].onclick = function(w) { RaidDialog.launch(w.parent, 'pickup'); };

    dialog.ondraw = RaidDialog.update;
    return dialog;
};

/** @param {!SPUI.Dialog} dialog
    @param {Object<string,?>|null} result */
RaidDialog.receive_scout_reports = function(dialog, result) {
    var feature = session.region.find_feature_by_id(dialog.user_data['feature_id']);

    dialog.user_data['scout_data_pending'] = false;
    // note: ignore scout reports from a previous "generation" of this feature at a different location
    if(result &&
       vec_equals(result['base_map_loc'], feature['base_map_loc']) &&
       (('new_raid_offense' in result) || ('new_raid_defense' in result) || ('new_raid_hp' in result))) {
        dialog.user_data['scout_data'] = result;
    }
};

/** @param {!SPUI.Dialog} dialog
    @param {string} raid_mode ("attack", "defend", "scout", "pickup") */
RaidDialog.launch = function(dialog, raid_mode) {
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
    var raid_info = {'path': raid_path,
                     'mode': raid_mode};
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

/** @param {!SPUI.Dialog} dialog */
RaidDialog.update = function(dialog) {
    var squad_id = dialog.user_data['squad_id'];
    var squad = player.squads[squad_id.toString()];
    var feature = session.region.find_feature_by_id(dialog.user_data['feature_id']);
    var caps = dialog.user_data['caps'] = player.get_mobile_squad_capabilities();
    var cap = caps[squad_id.toString()];

    if(!squad || !feature || !cap || !cap.can_raid_feature(feature) || player.squad_is_deployed(squad_id)) {
        close_dialog(dialog); return;
    }

    dialog.widgets['name_left'].str = player.ui_name;
    dialog.widgets['squad_name'].str = squad['ui_name'] || dialog.data['widgets']['squad_name']['ui_name']; // "Unnamed"
    dialog.widgets['squad_unit_icon'].asset = cap.icon_asset;

    RaidDialog.update_squad_scrollers(dialog, squad_id);

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

    var raid_mode = null;
    if(cap.can_pickup_feature(feature)) {
        raid_mode = 'pickup';
    } else if(cap.can_scout_feature(feature) &&
              (dialog.widgets['scout_button'].mouse_enter_time > 0 || !cap.can_attack_feature(feature))) {
        raid_mode = 'scout';
    } else if(cap.can_attack_feature(feature)) {
        raid_mode = 'attack';
    } else {
        raid_mode = 'unable';
    }

    // too slow?
    var raid_path = player.raid_find_path_to(player.home_base_loc, feature);
    if(raid_path) {
        var travel_time = player.squad_travel_time(squad_id, raid_path, raid_mode);
        dialog.widgets['travel_time'].str = dialog.data['widgets']['travel_time']['ui_name'].replace('%time', pretty_print_time(travel_time));
    } else {
        dialog.widgets['travel_time'].str = dialog.data['widgets']['travel_time']['ui_name_blocked'];
    }

    var scout_data = null;

    if(!SquadCapabilities.feature_is_defenseless(feature)) {
        dialog.widgets['scout_time'].show = true;
        dialog.widgets['scout_spinner'].show = !!dialog.user_data['scout_data_pending'];

        if(dialog.user_data['scout_data_pending']) {
            dialog.widgets['scout_time'].str = dialog.data['widgets']['scout_time']['ui_name_pending'];
            RaidDialog.update_strength(dialog, 'right', null, false, null);

        } else {
            scout_data = dialog.user_data['scout_data'] || null;

            if(scout_data) {
                var scout_time = scout_data['time'];
                dialog.widgets['scout_time'].str = dialog.data['widgets']['scout_time']['ui_name_scouted'].replace('%time', pretty_print_time_brief(server_time - scout_time));
            } else {
                dialog.widgets['scout_time'].str = dialog.data['widgets']['scout_time']['ui_name_unscouted'];
            }
            RaidDialog.update_strength(dialog, 'right',
                                       // their strength
                                       (raid_mode !== 'pickup' && raid_mode !== 'scout' && scout_data && scout_data['new_raid_hp'] ? scout_data['new_raid_hp'] : null),
                                       (raid_mode === 'scout'),
                                       // my strength to normalize against
                                       (raid_mode === 'pickup' ? null : (raid_mode === 'scout' ? cap.scout_raid_hp : cap.total_raid_hp)));

        }

        dialog.widgets['str_unknown_right'].show = (scout_data === null);

        dialog.widgets['advantage'].show =
            dialog.widgets['advantage_label'].show = true;
        var adv = (raid_mode !== 'scout' && scout_data && scout_data['new_raid_defense'] ? RaidDialog.calc_advantage(cap.total_raid_offense, scout_data['new_raid_defense']) : 'unknown');
        dialog.widgets['advantage'].set_text_bbcode(dialog.data['widgets']['advantage']['ui_name_'+adv]);

    } else { // defenseless feature, no scouting necessary
        dialog.widgets['advantage'].show =
            dialog.widgets['advantage_label'].show =
            dialog.widgets['scout_spinner'].show =
            dialog.widgets['scout_time'].show = false;
        RaidDialog.update_strength(dialog, 'right', null, false, null);
        dialog.widgets['str_unknown_right'].show = false;
    }

    RaidDialog.update_strength(dialog, 'left',
                               // my strength
                               (raid_mode === 'pickup' ? null : (raid_mode === 'scout' ? cap.scout_raid_hp : cap.total_raid_hp)),
                               (raid_mode === 'scout'),
                               // enemy strength to normalize against
                               (raid_mode !== 'pickup' && raid_mode !== 'scout' && scout_data && scout_data['new_raid_hp'] ? scout_data['new_raid_hp'] : null));

    RaidDialog.update_cargo(dialog, squad_id, (raid_mode === 'scout' ? null : cap.max_cargo));
    RaidDialog.update_loot(dialog, (raid_mode === 'scout' ? null : feature));

    dialog.widgets['description'].set_text_bbcode(dialog.data['widgets']['description']['ui_name_'+raid_mode]);

    dialog.widgets['scout_button'].show = cap.can_scout_feature(feature);
    dialog.widgets['pickup_button'].show = cap.can_pickup_feature(feature);
    dialog.widgets['attack_button'].show = !dialog.widgets['pickup_button'].show && cap.can_attack_feature(feature);
    if(raid_mode != 'unable') {
        dialog.default_button = dialog.widgets[raid_mode+'_button'];
    } else {
        dialog.default_button = null;
    }
};

/** @param {Object<string,number>} attacker_strength
    @param {Object<string,number>} defender_strength
    @return {string} "neutral","good","very_good","best","bad","very_bad","worst" */
RaidDialog.calc_advantage = function(attacker_strength, defender_strength) {
    var CATS = gamedata['strings']['damage_vs_categories'];

    // very, very rough way to calculate advantage: look only at the
    // single category with the absolute highest strength

    var absolute_max = 0;
    var absolute_max_i = -1;
    for(var i = 0; i < CATS.length; i++) {
        var key = CATS[i][0], catname = CATS[i][1];
        var a = attacker_strength[key] || 0;
        var b = defender_strength[key] || 0;
        if(a > absolute_max || b > absolute_max) {
            absolute_max = Math.max(a,b);
            absolute_max_i = i;
        }
    }

    //console.log('attacker '+JSON.stringify(attacker_strength)+'\ndefender '+JSON.stringify(defender_strength));

    if(absolute_max_i >= 0) {
        var catname = CATS[absolute_max_i][0];
        //console.log('critical stat '+catname);
        var a = attacker_strength[catname] || 0;
        var b = defender_strength[catname] || 0;
        if(a < 0.75 * b) {
            return 'bad';
        } else if(b < 0.75 * a) {
            return 'good';
        } else {
            return 'neutral';
        }
    }

    return 'neutral';
};

/** @param {!SPUI.Dialog} dialog
    @param {string} side
    @param {Object<string,number>|null} strength
    @param {boolean} scout_mode
    @param {Object<string,number>|null} opponent_strength - for normalizing against
*/
RaidDialog.update_strength = function(dialog, side, strength, scout_mode, opponent_strength) {
    var scout_only = false;

    dialog.widgets['str_label_'+side].show =
        dialog.widgets['str_sunken_'+side].show =
        dialog.widgets['str_line_'+side].show = (strength !== null);
    for(var x = 0; x < dialog.data['widgets']['str_prog_'+side]['array'][0]; x++) {
        dialog.widgets['str_prog_'+side+x.toString()].show =
            dialog.widgets['damage_vs_'+side+x.toString()].show = false;
    }

    if(dialog.widgets['str_label_'+side].show) {
        dialog.widgets['str_label_'+side].str = dialog.data['widgets']['str_label_'+side][scout_mode ? 'ui_name_scout' : 'ui_name'];
    }

    if(strength === null) { return; }

    // normalize strengths
    var norm = 0.001;
    for(var k in strength) {
        var q = strength[k] || 0;
        if(q > norm) {
            norm = q;
        }
    }
    if(opponent_strength) {
        for(var k in opponent_strength) {
            var q = opponent_strength[k] || 0;
            if(q > norm) {
                norm = q;
            }
        }
    }

    // all normal categories
    var CATS = gamedata['strings']['damage_vs_categories']; // .concat([["scout","scout"]]);
    var x = 0;
    for(var i = 0; i < CATS.length; i++) {
        // note: key is a defense_type, and is the actual stat used for calculations
        // catname is a corresponding manufacture_category or object_kind, FOR UI ONLY
        var key = CATS[i][0], catname = CATS[i][1];

        if(key === 'building' && side === 'left') {
            // skip buildings for the attacker
            continue;
        }

        var widget = dialog.widgets['damage_vs_'+side+x.toString()];

        var q = strength[key] || 0;
        if(scout_only && key !== 'scout') { // deactivate non-scouting units
            q = 0;
            widget.show = false;
            dialog.widgets['str_prog_'+side+x.toString()].show = false;
        } else {
            widget.show = true;
            dialog.widgets['str_prog_'+side+x.toString()].show = (q > 0);
            dialog.widgets['str_prog_'+side+x.toString()].progress = q/norm;
        }

        widget.asset = 'damage_vs_'+key;
        widget.state = gamedata['strings']['damage_vs_qualities'][(q <= 0 ? 0 : 3)]; // XXX hard-code color for now

        var ui_name;
        if(catname in gamedata['strings']['manufacture_categories']) {
            ui_name = gamedata['strings']['manufacture_categories'][catname]['plural'];
        } else if(catname in gamedata['strings']['object_kinds']) {
            ui_name = gamedata['strings']['object_kinds'][catname]['plural'];
        } else if(catname === 'scout') {
            ui_name = gamedata['strings']['scout'];
        } else {
            throw Error('unknown manuf category or object kind '+catname);
        }
        widget.tooltip.str = widget.data['ui_tooltip'].replace('%CATNAME', ui_name).replace('%d', pretty_print_number(q));
        x += 1;
        if(x >= dialog.data['widgets']['str_prog_'+side]['array'][0]) { break; }
    }
};

/** @param {!SPUI.Dialog} dialog
    @param {number} squad_id
    @param {Object<string,number>|null} cargo_cap */
RaidDialog.update_cargo = function(dialog, squad_id, cargo_cap) {
    var row = 0;
    dialog.widgets['cargo_label'].show = cargo_cap && (goog.object.getCount(cargo_cap) > 0);
    if(dialog.widgets['cargo_label'].show) {
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
    @param {Object<string,?>|null} feature */
RaidDialog.update_loot = function(dialog, feature) {
    var row = 0;
    dialog.widgets['loot_label'].show = (feature && 'base_resource_loot' in feature);
    if(feature && 'base_resource_loot' in feature) {
        // normalize to highest amount of any remaining resource
        var max_amount = 1;
        for(var res in feature['base_resource_loot']) {
            max_amount = Math.max(max_amount, feature['base_resource_loot'][res]);
        }
        for(var res in gamedata['resources']) {
            var resdata = gamedata['resources'][res];
            var amount = feature['base_resource_loot'][res] || 0;
            dialog.widgets['loot_bar'+row.toString()].show =
                dialog.widgets['loot_prog'+row.toString()].show =
                dialog.widgets['loot_icon'+row.toString()].show =
                dialog.widgets['loot_amount'+row.toString()].show = true;
            dialog.widgets['loot_icon'+row.toString()].asset = resdata['icon_small'];
            dialog.widgets['loot_prog'+row.toString()].progress = amount/max_amount;
            dialog.widgets['loot_prog'+row.toString()].full_color = SPUI.make_colorv(resdata['bar_full_color']);
            dialog.widgets['loot_amount'+row.toString()].str = pretty_print_number(amount);
            row += 1;
            if(row >= dialog.data['widgets']['loot_bar']['array'][1]) { break; }
        }
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
    var caps = dialog.user_data['caps']; // assumes this is already updated
    var feature = session.region.find_feature_by_id(dialog.user_data['feature_id']);

    // sort all raid squads in numerical order
    var squad_list = goog.array.map(goog.object.getKeys(player.squads), function(sid) { return parseInt(sid,10); });
    squad_list = goog.array.filter(squad_list, function(id) { return SQUAD_IDS.is_mobile_squad_id(id) &&
                                                              !player.squad_is_deployed(id) &&
                                                              caps[id.toString()] &&
                                                              caps[id.toString()].can_raid_feature(feature); });
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
