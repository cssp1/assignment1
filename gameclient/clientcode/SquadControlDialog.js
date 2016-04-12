goog.provide('SquadControlDialog');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('goog.object');
goog.require('SPUI');
goog.require('RaidDialog');

// tightly coupled to main.js, sorry!

// this dialog can be used for "normal" squad control or as a limited-use "squad picker" or "squad deployer"

/** @type {!Object<string,function()>} */
SquadControlDialog.update_receivers = {};
SquadControlDialog.update_receivers_serial = 1;

/** @param {!Array.<number>} coords */
SquadControlDialog.invoke_deploy = function(coords) { return SquadControlDialog.do_invoke('deploy', {'deploy_from': coords}); };

/** @param {!Array.<number>} coords
    @param {Object<string,?>|null} feature at destination */
SquadControlDialog.invoke_call = function(coords, feature) { return SquadControlDialog.do_invoke('call', {'to_coords': coords, 'to_feature': feature || null}); };

SquadControlDialog.invoke_manage = function() { return SquadControlDialog.do_invoke('manage', null); };
SquadControlDialog.invoke_normal = function() { return SquadControlDialog.do_invoke('normal', null); };

/** @param {string} dlg_mode
    @param {Object|null} dlg_mode_data */
SquadControlDialog.do_invoke = function(dlg_mode, dlg_mode_data) {
    // check for no-squad-available error conditions
    if(dlg_mode == 'deploy' || dlg_mode == 'call') {
        var msg = null;
        if(goog.object.getCount(player.squads) < 2) {
            // player has not created any squads yet
            msg = "CANNOT_DEPLOY_SQUADS_NONE";
        }
        if(!msg) {
            var can_do_action = false;
            var needs_additional_deployment = true;
            goog.object.forEach(player.squads, function(squad) {
                if(!(player.squad_is_under_repair(squad['id']) || player.squad_is_in_battle(squad['id']) || !SQUAD_IDS.is_mobile_squad_id(squad['id']) || ((dlg_mode=='deploy')&& player.squad_is_deployed(squad['id'])) || player.squad_is_dead(squad['id']) || player.squad_is_empty(squad['id']))) {

                    can_do_action = true;
                    if(SQUAD_IDS.is_mobile_squad_id(squad['id']) &&
                       (dlg_mode=='call'&&player.squad_is_deployed(squad['id']))) {
                        needs_additional_deployment = false;
                    }
                }
            });
            if(!can_do_action) {
                msg = "CANNOT_DEPLOY_SQUADS_ALL_BUSY";
            } else if(needs_additional_deployment) {
                if(resolve_squad_deployment_problem(false /* is_raid */)) { return null; }
            }
        }
        if(msg) {
            var s = gamedata['errors'][msg];
            invoke_child_message_dialog(s['ui_title'], s['ui_name'], {'dialog':'message_dialog_big',
                                                                      'cancel_button': true,
                                                                      'on_ok': SquadControlDialog.invoke_manage,
                                                                      'ok_button_ui_name': s['ui_button']});
            return null;
        }
    }

    var dialog = new SPUI.Dialog(gamedata['dialogs']['squad_control']);
    dialog.user_data['dialog'] = 'squad_control';
    dialog.user_data['last_columns'] = -1;
    dialog.user_data['dlg_mode'] = dlg_mode;
    if(dlg_mode_data) {
        goog.object.forEach(dlg_mode_data, function(v,k) { dialog.user_data[k] = v; });
    }

    install_child_dialog(dialog);
    dialog.auto_center('root');
    dialog.modal = true;
    dialog.widgets['close_button'].onclick = close_parent_dialog;

    if(dlg_mode == 'normal') {
        init_army_dialog_buttons(dialog.widgets['army_dialog_buttons_army'], 'army', 'squad_control');
    } else {
        dialog.widgets['army_dialog_buttons_army'].show = false;
    }

    var title_mode = (dlg_mode == 'call' && dlg_mode_data['to_feature'] && dlg_mode_data['to_feature']['base_type'] === 'raid' ? 'call_raid' : dlg_mode);
    dialog.widgets['title'].str = dialog.data['widgets']['title']['ui_name_'+title_mode];

    dialog.user_data['receiver_serial'] = SquadControlDialog.update_receivers_serial++;
    SquadControlDialog.update_receivers[dialog.user_data['receiver_serial']] = (function (_dialog) { return function() {
        SquadControlDialog.refresh(_dialog);
        SquadControlDialog.unblock(_dialog);
    }; })(dialog);
    dialog.on_destroy = function(_dialog) { delete SquadControlDialog.update_receivers[_dialog.user_data['receiver_serial']]; };

    SquadControlDialog.refresh(dialog);
    dialog.ondraw = SquadControlDialog.update;

    // ensure region map is somewhat up to date - we need it for pathfinding and quarry detection!
    if(dlg_mode == 'normal' && session.region && session.region.data && session.region.dirty && session.region.map_enabled()) {
        SquadControlDialog.block(dialog);
        session.region.call_when_fresh((function(_dialog) { return function() {
            SquadControlDialog.unblock(_dialog);
        }; })(dialog));
    }

    dialog.widgets['notify_choice'].show = (dlg_mode == 'normal' && spin_frame_platform == 'fb' && player.raids_enabled());

    return dialog;
}

SquadControlDialog.block = function(dialog) { dialog.widgets['loading_rect'].show = dialog.widgets['loading_text'].show = dialog.widgets['loading_spinner'].show = true; };
SquadControlDialog.unblock = function(dialog) { dialog.widgets['loading_rect'].show = dialog.widgets['loading_text'].show = dialog.widgets['loading_spinner'].show = false; };

SquadControlDialog.refresh = function(dialog) {
    // get rid of old squad widgets
    var to_remove = [];
    for(var name in dialog.widgets) {
        if(name.indexOf('squad') === 0) {
            to_remove.push(name);
        }
    }

    goog.array.forEach(to_remove, function(name) { dialog.remove(dialog.widgets[name]); delete dialog.widgets[name]; });

    // make list of tiles we're going to create
    var make_squad_tile_args = [];

    // Reserves
    if(dialog.user_data['dlg_mode'] == 'normal' || dialog.user_data['dlg_mode'] == 'manage') {
        make_squad_tile_args.push({squad_id: SQUAD_IDS.RESERVES, template: 'squad_tile'});
    }

    // Base Defenders + other squads, sorted by ID
    var squad_ids = goog.array.map(goog.object.getKeys(player.squads), function(x) { return parseInt(x,10); }).sort();

    goog.array.forEach(squad_ids, function (id) {
        if(id === SQUAD_IDS.BASE_DEFENDERS && (dialog.user_data['dlg_mode'] == 'call' || dialog.user_data['dlg_mode'] == 'deploy')) { return; }
        if(dialog.user_data['dlg_mode'] == 'call' && dialog.user_data['to_feature'] && dialog.user_data['to_feature']['base_type'] == 'raid' && player.squad_is_deployed(id)) { return; }
        make_squad_tile_args.push({squad_id: id, template: 'squad_tile'});
    });

    // Create Squad button
    var builder = find_object_by_type(gamedata['squad_building']);
    if((dialog.user_data['dlg_mode'] == 'normal' || dialog.user_data['dlg_mode'] == 'manage') &&
       (((goog.object.getCount(player.squads)-1) < player.stattab['max_squads'] ||
         !builder ||
         (builder && (builder.level < builder.get_max_ui_level()))))) {
        make_squad_tile_args.push({squad_id: null, template: 'create_squad_tile'});
    }

    // determine number of columns needed to show all tiles
    var need_tiles = make_squad_tile_args.length;
    dialog.user_data['columns'] = (need_tiles <= (dialog.data['widgets']['squad']['array_max'][0]*dialog.data['widgets']['squad']['array_max'][1]) ? Math.min(dialog.data['widgets']['squad']['array_max'][0], need_tiles) : Math.floor((need_tiles+1)/2));

    // creawte the tiles
    var grid_x = 0, grid_y = 0;
    goog.array.forEach(make_squad_tile_args, function(args) {
        SquadControlDialog.make_squad_tile(dialog, args.squad_id, [grid_x, grid_y], dialog.user_data['dlg_mode'], args.template);
        grid_x += 1; if(grid_x >= dialog.user_data['columns']) { grid_x = 0; grid_y += 1; }
    });

    dialog.user_data['scroll_limits'] = [0, Math.max(0, (dialog.user_data['columns']-1) * dialog.data['widgets']['squad']['array_offset'][0] - dialog.widgets['sunken'].wh[0] - dialog.widgets['sunken'].xy[0] + dialog.data['widgets']['squad']['xy'][0] + dialog.data['widgets']['squad']['dimensions'][0] + 1)];
    var scroller = function(incr) { return function(w) {
        var dialog = w.parent;
        dialog.user_data['scroll_goal'] = clamp(dialog.user_data['scroll_goal']+dialog.data['widgets']['squad']['array_offset'][0]*incr,
                                                dialog.user_data['scroll_limits'][0], dialog.user_data['scroll_limits'][1]);
        if(incr > 0) { dialog.user_data['scrolled'] = true; }
    }; };
    dialog.widgets['scroll_left'].onclick = scroller(-2);
    dialog.widgets['scroll_right'].onclick = scroller(2);

    // set initial scroll parameters
    if(dialog.user_data['last_columns'] != dialog.user_data['columns']) {
        dialog.user_data['scroll_pos'] = 0;
        dialog.user_data['scroll_goal'] = 0;
        scroller(0)(dialog.widgets['scroll_left']);
        dialog.user_data['last_columns'] = dialog.user_data['columns'];
    }

    // run the on_mousemove handler to reset hover states
    var offset = [0,0]; if(dialog.parent) { for(var d = dialog.parent; d; d = d.parent) { offset = vec_add(offset, d.xy); } }
    dialog.on_mousemove([mouse_state.last_raw_x, mouse_state.last_raw_y], offset);
};

SquadControlDialog.update = function(dialog) {
    if(dialog.widgets['loading_text'].show) {
        var prog = (session.region.data ? session.region.refresh_progress() : -1);
        if(prog >= 0) {
            prog = Math.min(prog, 0.99);
            dialog.widgets['loading_text'].str = dialog.data['widgets']['loading_text']['ui_name_progress'].replace('%pct', (100.0*prog).toFixed(0));
        } else {
            dialog.widgets['loading_text'].str = dialog.data['widgets']['loading_text']['ui_name'];
        }
    }

    if(dialog.user_data['scroll_pos'] != dialog.user_data['scroll_goal']) {
        var delta = dialog.user_data['scroll_goal'] - dialog.user_data['scroll_pos'];
        var sign = (delta > 0 ? 1 : -1);
        dialog.user_data['scroll_pos'] += sign * Math.floor(0.15 * Math.abs(delta) + 0.5);
    }
    dialog.widgets['scroll_left'].state = (dialog.user_data['scroll_goal'] <= dialog.user_data['scroll_limits'][0] ? 'disabled' : 'normal');
    dialog.widgets['scroll_right'].state = (dialog.user_data['scroll_goal'] >= dialog.user_data['scroll_limits'][1] ? 'disabled' : 'normal');

    for(var grid_x = 0; grid_x < dialog.user_data['columns']; grid_x += 1) {
        for(var grid_y = 0; grid_y < dialog.data['widgets']['squad']['array'][1]; grid_y += 1) {
            var wname = 'squad'+grid_x.toString()+','+grid_y.toString();
            if(wname in dialog.widgets) {
                dialog.widgets[wname].xy = vec_add(vec_add(vec_mul([grid_x,grid_y], dialog.data['widgets']['squad']['array_offset']), [-dialog.user_data['scroll_pos'],0]), dialog.data['widgets']['squad']['xy']);
            }
        }
    }

    if(dialog.widgets['notify_choice'].show) {
        update_notification_choice_button(dialog.widgets['notify_choice'], 'enable_raid_notifications', 'raid_complete');
    }
};

SquadControlDialog.update_create_squad_tile = function(d) {
    var pred = {'predicate':'LIBRARY', 'name':'squad_play_requirement'};
    var tooltip = null;
    if(goog.object.getCount(player.squads)-1 >= player.stattab['max_squads']) {
        // cannot create more squads, upgrade building first
        var builder = find_object_by_type(gamedata['squad_building']);
        if(!builder) {
            pred = {'predicate': 'AND', 'subpredicates': [
                {'predicate': 'BUILDING_LEVEL', 'building_type': gamedata['squad_building'], 'trigger_level': 1},
                pred]};
        } else {
            var next_level = get_next_level_with_stat_increase(builder.spec, 'provides_squads', builder.level);
            if(next_level < 0) {
                tooltip = gamedata['errors']['CANNOT_CREATE_SQUAD_MAX_LIMIT_REACHED']['ui_name'];
                pred = {'predicate': 'ALWAYS_FALSE', 'ui_name': tooltip};
            } else {
                pred = {'predicate': 'AND', 'subpredicates': [
                    {'predicate': 'BUILDING_LEVEL', 'building_type': gamedata['squad_building'], 'trigger_level': next_level},
                    pred]};
            }
        }
    }
    var rpred = read_predicate(pred);
    var pred_ok = rpred.is_satisfied(player, null);

    d.widgets['create_button'].state = (!pred_ok ? 'disabled_clickable' : 'normal');
    d.widgets['create_button'].tooltip.str = (!pred_ok ? tooltip : null);
    d.widgets['create_button'].onclick = (!pred_ok ? function(w) {
        var helper = get_requirements_help(rpred);
        if(helper) { helper(); }
    } : function(w) {
        var _d = w.parent, _dialog = _d.parent;
        SquadControlDialog.block(_dialog);
        var cur_squads = goog.object.getCount(player.squads)-1;
        var ui_name = gamedata['strings']['icao_alphabet'][(cur_squads+1) % 26].toUpperCase();
        send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_CREATE", ui_name]);
    });
};

SquadControlDialog.make_squad_tile = function(dialog, squad_id, ij, dlg_mode, template) {
    var d = new SPUI.Dialog(gamedata['dialogs'][template], dialog.data['widgets']['squad']);
    d.xy = vec_add(dialog.data['widgets']['squad']['xy'], vec_mul(ij, dialog.data['widgets']['squad']['array_offset']));
    var name = 'squad'+ij[0].toString()+','+ij[1].toString();
    if(name in dialog.widgets) {
        throw Error('double-create of '+name+': '+dialog.widgets[name].get_address());
    }
    dialog.widgets[name] = d;
    dialog.add_before(dialog.widgets['loading_rect'], d);

    if(template === 'create_squad_tile') {
        d.ondraw = SquadControlDialog.update_create_squad_tile;
    } else if(template === 'squad_tile') {
        d.user_data['squad_id'] = squad_id;
        d.user_data['icon_unit_specname'] = null;
        d.widgets['manage_button'].onclick = function(w) {
            SquadManageDialog.invoke_squad_manage(w.parent.user_data['squad_id']);
        };
        d.widgets['delete_button'].onclick = function(w) {
            var _d = w.parent, _dialog = _d.parent;

            var delete_func = (function (__d, __dialog) { return function() {
                SquadControlDialog.block(__dialog);
                send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_DELETE", __d.user_data['squad_id']]);
            }; })(_d, _dialog);

            squad_delete_confirm(_d.user_data['squad_id'], delete_func);
        };

        // special modes
        if(dlg_mode == 'deploy') {
            d.widgets['deploy_button'].onclick = function(w) {
                if(resolve_squad_deployment_problem(false /* is_raid */)) { return; }

                // navigate back to the regional map
                // parent is squad_tile, parent.parent is squad_control, parent.parent.parent is map dialog
                var _squad_tile = w.parent;
                if(_squad_tile) {
                    var squad_id = _squad_tile.user_data['squad_id'];

                    // note: most error cases are handled by the 'can_do_action' logic in update_squad_tile

                    var _squad_control = _squad_tile.parent;
                    if(_squad_control) {
                        var _map_dialog = _squad_control.parent;
                        if(_map_dialog && _map_dialog.user_data['dialog'] == 'region_map_dialog') {
                            // yay we got it
                            // close squad control to get back to the map

                            // pop up deployment cursor
                            var from_loc = _squad_control.user_data['deploy_from'];
                            var icon_assetname = _squad_tile.widgets['unit_icon0,0'].widgets['icon'].asset;
                            _map_dialog.widgets['map'].invoke_deploy_cursor(from_loc, squad_id, icon_assetname);
                        }
                    }
                    close_parent_dialog(_squad_tile);
                }
            }
        } else if(dlg_mode == 'call') {
            d.widgets['call_button'].onclick = function(w) {
                // navigate back to the regional map
                // parent is squad_tile, parent.parent is squad_control, parent.parent.parent is map dialog
                var _squad_tile = w.parent;
                if(_squad_tile) {
                    var squad_id = _squad_tile.user_data['squad_id'];
                    var squad_data = player.squads[squad_id.toString()];
                    var _squad_control = _squad_tile.parent;
                    if(_squad_control) {
                        var to_loc = _squad_control.user_data['to_coords'];
                        var to_feature = _squad_control.user_data['to_feature'];
                        var is_raid = (to_feature && to_feature['base_type'] === 'raid');
                        var raid_distance = -1, raid_type = null;
                        if(is_raid) {
                            raid_distance = hex_distance(to_loc, player.home_base_loc);
                            raid_type = (to_feature['base_type'] === 'home' ? 'pvp' : 'pve');
                        }

                        // note: most error cases are handled by the 'can_do_action' logic in update_squad_tile
                        if(player.squad_is_deployed(squad_id)) {
                            // queue movement
                            player.squad_set_client_data(squad_id, 'squad_orders', {'move': to_loc});
                        } else {
                            if(resolve_squad_deployment_problem(is_raid, raid_distance, raid_type)) { return; }

                            // find a place to deploy the squad
                            var deploy_at = null;
                            if(!is_raid) {
                                var neighbors = session.region.get_neighbors(player.home_base_loc);
                                goog.array.forEach(neighbors, function(xy) {
                                    if(!session.region.occupancy.is_blocked(xy, player.make_squad_cell_checker())) {
                                        deploy_at = xy;
                                    }
                                });
                            } else {
                                deploy_at = player.home_base_loc;
                            }

                            if(!deploy_at) {
                                var s = gamedata['errors']['INVALID_MAP_LOCATION'];
                                invoke_child_message_dialog(s['ui_title'], s['ui_name'].replace('%BATNAME', squad_data['ui_name']), {'dialog':'message_dialog_big'});
                                return;
                            }

                            var raid_info = null;
                            if(is_raid) {
                                // find path to target
                                var raid_path = player.raid_find_path_to(player.home_base_loc, to_feature);
                                if(!raid_path) {
                                    var s = gamedata['errors']['INVALID_MAP_LOCATION'];
                                    invoke_child_message_dialog(s['ui_title'], s['ui_name'].replace('%BATNAME', squad_data['ui_name']), {'dialog':'message_dialog_big'});
                                    return;
                                }
                                raid_info = {'path': raid_path};
                            }

                            // perform deployment
                            player.squads[squad_id.toString()]['pending'] = true;

                            send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_ENTER_MAP", squad_id, deploy_at, raid_info]);

                            if(!is_raid && !vec_equals(deploy_at, to_loc)) {
                                // queue movement
                                player.squad_set_client_data(squad_id, 'squad_orders', {'move': to_loc});
                            }

                            // play movement sound
                            if(_squad_tile.user_data['icon_unit_specname']) {
                                var spec = gamedata['units'][_squad_tile.user_data['icon_unit_specname']];
                                if('sound_destination' in spec) {
                                    GameArt.play_canned_sound(spec['sound_destination']);
                                }
                            }
                        }
                    }
                    close_parent_dialog(_squad_tile);
                }
            }
        }
        d.ondraw = SquadControlDialog.update_squad_tile;
    }
};


SquadControlDialog.update_squad_tile = function(dialog) {
    var dlg_mode;
    if(dialog.parent) {
        dlg_mode = dialog.parent.user_data['dlg_mode'];
    } else {
        return; // orphaned
    }

    // treat manage the same as normal here
    if(dlg_mode == 'manage') { dlg_mode = 'normal'; }

    var squad_data = (dialog.user_data['squad_id'] === SQUAD_IDS.RESERVES ?
                      {'ui_name': gamedata['strings']['squads']['reserves'], 'id': SQUAD_IDS.RESERVES } :
                      player.squads[dialog.user_data['squad_id'].toString()]);
    dialog.widgets['name'].str = squad_data['ui_name'];

    var units_by_type = {};
    var max_space = (dialog.user_data['squad_id'] === SQUAD_IDS.RESERVES ?
                     player.stattab['total_space'] :
                     (dialog.user_data['squad_id'] === SQUAD_IDS.BASE_DEFENDERS ?
                      player.stattab['main_squad_space'] :
                      player.stattab['squad_space']));
    var cur_space = 0, max_hp = 0, cur_hp = 0, cur_units = 0;
    var squad_is_damaged = false, squad_is_destroyed = (dialog.user_data['squad_id'] === SQUAD_IDS.RESERVES ? false : true);
    var cost_to_repair = {};

    goog.object.forEach(player.my_army, function(obj, obj_id) {
        if((obj['squad_id']||0) !== dialog.user_data['squad_id']) { return; }
        units_by_type[obj['spec']] = (units_by_type[obj['spec']]||0) + 1;
        var spec = gamedata['units'][obj['spec']];
        var level = obj['level'] || 1;
        cur_space += get_leveled_quantity(spec['consumes_space']||0, level);
        cur_units += 1;
        var curmax = army_unit_hp(obj);
        cur_hp += curmax[0];
        max_hp += curmax[1];
        if(curmax[0] > 0) { squad_is_destroyed = false; }
        if(curmax[0] < curmax[1]) {
            if((army_unit_repair_state(obj) == 0) && player.can_repair_unit_of_spec(spec, curmax[0])) {
                squad_is_damaged = true;
                var mycost = mobile_cost_to_repair(spec, level, curmax[0], curmax[1], player);
                for(var resname in gamedata['resources']) {
                    cost_to_repair[resname] = (cost_to_repair[resname]||0) + mycost[resname];
                }
                cost_to_repair['time'] = (cost_to_repair['time']||0) + mycost['time'];
            }
        }
    });

    var squad_is_deployed = player.squad_is_deployed(squad_data['id']);
    var squad_is_under_repair = player.squad_is_under_repair(squad_data['id']);
    var squad_in_battle = player.squad_is_in_battle(squad_data['id']);
    var squad_can_speedup = player.squad_speedups_enabled() && squad_is_deployed && !squad_in_battle && player.squad_is_moving(squad_data['id']);

    dialog.widgets['space_bar'].show = dialog.widgets['space_label'].show =
        dialog.widgets['hp_bar'].show = dialog.widgets['hp_label'].show =
        (dialog.user_data['squad_id'] !== SQUAD_IDS.RESERVES);
    dialog.widgets['space_bar'].progress = cur_space / Math.max(max_space,1);
    dialog.widgets['hp_bar'].progress = (max_hp > 0 ? (cur_hp/max_hp) : 0);

    var my_status, my_status_s = '', my_status_time = '';
    if(squad_data['id'] === SQUAD_IDS.RESERVES) {
        my_status = 'in_reserve';
    } else if(squad_data['id'] === SQUAD_IDS.BASE_DEFENDERS) {
        my_status = 'defending_home_base';
    } else if(squad_in_battle) {
        my_status = 'in_battle';
        my_status_s = squad_data['map_loc'][0].toString()+','+squad_data['map_loc'][1].toString();
    } else if(cur_units <= 0) {
        my_status = 'empty';
    } else if(cur_hp <= 0) {
        my_status = 'destroyed';
    } else if(squad_is_deployed) {
        if(player.squad_is_moving(squad_data['id'])) {
            var orders = player.squad_get_client_data(squad_data['id'], 'squad_orders');
            if(orders && (('recall' in orders) || ('recall_after_halt' in orders))) {
                my_status = 'returning_to_home_base';
            } else {
                my_status = 'traveling';
                my_status_s = squad_data['map_loc'][0].toString()+','+squad_data['map_loc'][1].toString();
            }
            my_status_time = pretty_print_time_brief(Math.max(squad_data['map_path'][squad_data['map_path'].length-1]['eta'] - server_time, 1));
        } else {
            var feat = (session.region.map_enabled() ? session.region.find_feature_at_coords(squad_data['map_loc']) : null);
            if(feat && feat['base_type'] == 'quarry') {
                my_status = 'quarry';
                my_status_s = feat['base_ui_name'];
            } else {
                my_status = 'deployed';
                my_status_s = squad_data['map_loc'][0].toString()+','+squad_data['map_loc'][1].toString();
            }
        }
    } else if(squad_is_under_repair) {
        my_status = 'under_repair';
    } else if(squad_is_damaged) {
        my_status = 'damaged';
    } else {
        my_status = 'ready';
    }
    dialog.widgets['status'].str = gamedata['strings']['squads']['status'][my_status].replace('%s', my_status_s).replace('%time', my_status_time);
    dialog.widgets['bg'].color = SPUI.make_colorv(dialog.data['widgets']['bg']['color_'+my_status]);
    dialog.widgets['status'].text_color = dialog.widgets['bg'].outline_color = SPUI.make_colorv(dialog.data['widgets']['bg']['outline_color_'+my_status]);
    dialog.widgets['name'].text_color = SPUI.make_colorv(dialog.data['widgets']['name'][('text_color_'+my_status in dialog.data['widgets']['name'] ? 'text_color_'+my_status : 'text_color')]);

    var types_to_show = goog.object.getKeys(units_by_type);
    types_to_show.sort(compare_specnames);

    dialog.user_data['icon_unit_specname'] = (types_to_show.length >= 1 ? types_to_show[0] : null);

    var i = 0, grid_x = 0, grid_y = 0;
    while(i < types_to_show.length && grid_y < dialog.data['widgets']['unit_icon']['array'][1]) {
        var wname = grid_x.toString()+','+grid_y.toString();
        unit_icon_set(dialog.widgets['unit_icon'+wname], types_to_show[i], units_by_type[types_to_show[i]], null, null,
                      (squad_is_under_repair || squad_is_deployed || (squad_data['id'] === SQUAD_IDS.RESERVES) ? 'disabled' : null));
        i += 1;
        grid_x += 1;
        if(grid_x >= dialog.data['widgets']['unit_icon']['array'][0]) { grid_x = 0; grid_y += 1; }
    }
    while(grid_y < dialog.data['widgets']['unit_icon']['array'][1]) {
        while(grid_x < dialog.data['widgets']['unit_icon']['array'][0]) {
            var wname = grid_x.toString()+','+grid_y.toString();
            unit_icon_set(dialog.widgets['unit_icon'+wname], null, -1, null, null);
            grid_x += 1;
        }
        grid_x = 0; grid_y += 1;
    }

    var hover = (dialog.mouse_enter_time > 0) && (dialog.parent.mouse_enter_time > 0);
    var can_do_action = false; // apples when dlg_mode is deploy or call
    var repair_in_sync = synchronizer.is_in_sync(unit_repair_sync_marker);

    if(dialog.user_data['squad_id'] === SQUAD_IDS.RESERVES) {
        dialog.widgets['coverup'].show = false;
    } else if(dlg_mode == 'normal') {
        dialog.widgets['coverup'].show = hover || squad_is_under_repair || squad_in_battle || (!squad_is_deployed && squad_is_damaged);
    } else if(dlg_mode == 'deploy' || dlg_mode == 'call') {
        can_do_action = !(squad_is_under_repair || squad_in_battle || !SQUAD_IDS.is_mobile_squad_id(dialog.user_data['squad_id']) || ((dlg_mode=='deploy') && squad_is_deployed) || squad_is_destroyed || (cur_units <= 0)); // || (my_status == 'quarry'));
        dialog.widgets['coverup'].show = hover || !can_do_action;
    }

    dialog.widgets['delete_button'].show = (dlg_mode=='normal') && hover && SQUAD_IDS.is_mobile_squad_id(dialog.user_data['squad_id']) && !squad_is_deployed && !squad_in_battle;
    dialog.widgets['manage_button'].show = (dlg_mode=='normal') && hover && dialog.user_data['squad_id'] != SQUAD_IDS.RESERVES && !squad_in_battle;

    dialog.widgets['deploy_button'].show = (dlg_mode=='deploy') && hover && can_do_action;
    dialog.widgets['call_button'].show = (dlg_mode=='call') && hover && can_do_action;
    dialog.widgets['deploy_button'].state = dialog.widgets['call_button'].state = (can_do_action && !squad_data['pending'] ? 'normal' : 'disabled');

    dialog.widgets['repair_remain_bg'].show =
        dialog.widgets['repair_remain_icon'].show =
        dialog.widgets['repair_remain_value'].show = (dlg_mode=='normal') && squad_is_under_repair && !squad_in_battle;
    dialog.widgets['finish_button'].show =
        dialog.widgets['price_display'].show = (dlg_mode=='normal') && (squad_is_under_repair || squad_can_speedup) && !squad_in_battle;
    dialog.widgets['price_spinner'].show = (dialog.widgets['price_display'].show && (!repair_in_sync || squad_data['pending']));
    dialog.widgets['cancel_button'].show = (dlg_mode=='normal') && squad_is_under_repair && !squad_in_battle && hover;

    if(squad_is_under_repair && !squad_in_battle) {
        var repair_togo = player.unit_repair_queue[player.unit_repair_queue.length-1]['finish_time']-server_time;
        dialog.widgets['repair_remain_value'].str = pretty_print_time(repair_togo);
        if(repair_togo <= 1) {
            // start pinging for repair completion
            request_unit_repair_update();
        }

        dialog.widgets['cancel_button'].onclick = function (w) {
            var _dialog = w.parent;
            SquadControlDialog.block(_dialog.parent);
            send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_REPAIR_CANCEL", _dialog.user_data['squad_id']]);
            unit_repair_sync_marker = synchronizer.request_sync();
        };
        dialog.widgets['cancel_button'].state = (repair_in_sync ? 'normal' : 'disabled');

        var price = Store.get_user_currency_price(GameObject.VIRTUAL_ID, gamedata['spells']['UNIT_REPAIR_SPEEDUP_FOR_MONEY'], null);
        dialog.widgets['price_display'].bg_image = player.get_any_abtest_value('price_display_short_asset', gamedata['store']['price_display_short_asset']);
        dialog.widgets['price_display'].state = Store.get_user_currency();
        dialog.widgets['price_display'].str = (!repair_in_sync ? '' : Store.display_user_currency_price(price, 'compact')); // PRICE
        dialog.widgets['finish_button'].str = dialog.data['widgets']['finish_button']['ui_name'+(!repair_in_sync ? '_pending': '')];
        dialog.widgets['price_display'].tooltip.str = (!repair_in_sync ? null : Store.display_user_currency_price_tooltip(price));
        if(price >= 0) {
            dialog.widgets['finish_button'].onclick = function() {
                if(Store.place_user_currency_order(GameObject.VIRTUAL_ID, "UNIT_REPAIR_SPEEDUP_FOR_MONEY", null, null)) {
                    unit_repair_sync_marker = synchronizer.request_sync();
                    invoke_ui_locker(unit_repair_sync_marker);
                }
            };
            dialog.widgets['finish_button'].state = (repair_in_sync ? 'normal' : 'disabled');
            dialog.widgets['price_display'].onclick = (!repair_in_sync ? null: dialog.widgets['finish_button'].onclick);
        } else {
            if(!player.unit_speedups_enabled()) {
                dialog.widgets['finish_button'].show = dialog.widgets['price_display'].show = false;
            } else {
                dialog.widgets['finish_button'].state = 'disabled';
                dialog.widgets['price_display'].onclick = null;
            }
        }
    } else if(squad_can_speedup) {
        var price = Store.get_user_currency_price(GameObject.VIRTUAL_ID, gamedata['spells']['SQUAD_MOVEMENT_SPEEDUP_FOR_MONEY'], dialog.user_data['squad_id']);
        dialog.widgets['price_display'].bg_image = player.get_any_abtest_value('price_display_short_asset', gamedata['store']['price_display_short_asset']);
        dialog.widgets['price_display'].state = Store.get_user_currency();
        dialog.widgets['price_display'].str = (squad_data['pending'] ? '' : Store.display_user_currency_price(price, 'compact')); // PRICE
        dialog.widgets['finish_button'].str = dialog.data['widgets']['finish_button']['ui_name'+(squad_data['pending'] ? '_pending': '')];
        dialog.widgets['price_display'].tooltip.str = (squad_data['pending'] ? null : Store.display_user_currency_price_tooltip(price));
        if(price >= 0) {
            dialog.widgets['finish_button'].onclick = function(w) {
                var dialog = w.parent;
                if(Store.place_user_currency_order(GameObject.VIRTUAL_ID, "SQUAD_MOVEMENT_SPEEDUP_FOR_MONEY", dialog.user_data['squad_id'], null)) {
                    player.squads[dialog.user_data['squad_id'].toString()]['pending'] = true;
                }
            };
            dialog.widgets['finish_button'].state = (!squad_data['pending'] ? 'normal' : 'disabled');
            dialog.widgets['price_display'].onclick = (squad_data['pending'] ? null: dialog.widgets['finish_button'].onclick);
        } else {
            dialog.widgets['finish_button'].state = 'disabled';
            dialog.widgets['price_display'].onclick = null;
        }
    }

    //console.log('squad ' +player.squads[dialog.user_data['squad_id'].toString()]['ui_name']+' mode '+dlg_mode+' damaged '+squad_is_damaged+' under_rep '+squad_is_under_repair+' is deployed '+squad_is_deployed+' in battle '+squad_in_battle);

    dialog.widgets['start_repair_button'].show = (dlg_mode=='normal') && (squad_is_damaged && !squad_is_under_repair && !squad_is_deployed && !squad_in_battle && (dialog.user_data['squad_id'] !== SQUAD_IDS.RESERVES));
    dialog.widgets['requirements_bg'].show =
        dialog.widgets['requirements_time_icon'].show =
        dialog.widgets['requirements_time_value'].show = (dialog.widgets['start_repair_button'].show && hover);
    for(var res in gamedata['resources']) {
        if('requirements_'+res+'_icon' in dialog.widgets) {
            dialog.widgets['requirements_'+res+'_icon'].show =
                dialog.widgets['requirements_'+res+'_value'].show = dialog.widgets['requirements_time_icon'].show;
        }
    }

    if(dialog.widgets['start_repair_button'].show) {
        if(hover) {
            for(var resname in gamedata['resources']) {
                if('requirements_'+resname+'_value' in dialog.widgets) {
                    dialog.widgets['requirements_'+resname+'_value'].str = pretty_print_number(cost_to_repair[resname]||0);
                }
            }
            dialog.widgets['requirements_time_value'].str = pretty_print_time(cost_to_repair['time']||0);
        }
        dialog.widgets['start_repair_button'].state = (repair_in_sync ? 'normal' : 'disabled');
        dialog.widgets['start_repair_button'].str = dialog.data['widgets']['start_repair_button'][(repair_in_sync ? 'ui_name' : 'ui_name_pending')];
        dialog.widgets['start_repair_button'].onclick = function(w) {
            var _dialog = w.parent;
            SquadControlDialog.block(_dialog.parent);
            send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_REPAIR_QUEUE", _dialog.user_data['squad_id']]);
            unit_repair_sync_marker = synchronizer.request_sync();
        };
    }
};
