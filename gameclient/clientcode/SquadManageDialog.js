goog.provide('SquadManageDialog');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('goog.object');
goog.require('SPUI');

// tightly coupled to main.js, sorry!

SquadManageDialog.invoke_squad_manage = function(squad_id) {
    var squad = player.squads[squad_id.toString()];
    if(!squad) { return; }

    var dialog = new SPUI.Dialog(gamedata['dialogs']['squad_manage']);
    dialog.user_data['dialog'] = 'squad_manage';
    dialog.user_data['squad_id'] = squad_id;
    dialog.user_data['squad'] = squad;
    dialog.user_data['name_changed'] = false;
    dialog.user_data['reserve_scroll_pos'] = 0;
    dialog.user_data['reserve_scroll_goal'] = 0;
    dialog.user_data['reserve_scroll_limits'] = [0,0];
    dialog.user_data['squad_scroll_pos'] = 0;
    dialog.user_data['squad_scroll_goal'] = 0;
    dialog.user_data['squad_scroll_limits'] = [0,0];

    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;
    dialog.widgets['close_button'].onclick = dialog.widgets['save_button'].onclick = close_parent_dialog;
    dialog.widgets['name_input'].str = squad['ui_name'];
    if(squad_id === SQUAD_IDS.BASE_DEFENDERS) {
        dialog.widgets['name_input_bg'].show = dialog.widgets['name_input'].show = false;
        dialog.widgets['title'].str = squad['ui_name'];
    } else {
        dialog.widgets['name_input'].ontype = function(w) { w.parent.user_data['name_changed'] = true; };
        dialog.widgets['name_input'].ontextready = function(w, str) {
            var _dialog = w.parent;
            if(!str) { w.str = _dialog.user_data['squad']['ui_name']; return; }
            send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_RENAME", _dialog.user_data['squad_id'], SPHTTP.wrap_string(str)]);
            _dialog.user_data['name_changed'] = false;
        };
    }
    dialog.on_destroy = function(dialog) {
        // send out pending name change
        if(dialog.user_data['name_changed'] && dialog.widgets['name_input'].str && (dialog.user_data['squad_id'].toString() in player.squads)) {
            send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_RENAME", dialog.user_data['squad_id'], SPHTTP.wrap_string(dialog.widgets['name_input'].str)]);
        }
    };


    dialog.widgets['disband_button'].onclick = function(w) {
        var _dialog = w.parent; var _squad_data = _dialog.user_data['squad'];
        var delete_func = (function (__dialog, __squad_data) { return function() {
            var maybe_squad_control = __dialog.parent;
            close_parent_dialog(__dialog.widgets['disband_button']);
            if(maybe_squad_control && maybe_squad_control.user_data && maybe_squad_control.user_data['dialog'] == 'squad_control') {
                squad_control_block(maybe_squad_control);
            }
            send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_DELETE", __squad_data['id']]);
        }; })(_dialog, _squad_data);

        squad_delete_confirm(_squad_data['id'], delete_func);
    };

    dialog.widgets['find_on_map_button'].onclick = function(w) {
        var squad_data = w.parent.user_data['squad'];
        if('map_loc' in squad_data) {
            var pos = player.squad_interpolate_pos_and_heading(squad_data['id'])[0];

            // we're usually underneath squad_control which is underneath either the desktop, or an existing map dialog
            var map_dialog;
            if(w.parent.parent && w.parent.parent.parent && w.parent.parent.parent.user_data && w.parent.parent.parent.user_data['dialog'] == 'region_map_dialog') {
                map_dialog = w.parent.parent.parent;
                close_parent_dialog(w.parent.parent);
                map_dialog.widgets['map'].pan_to_cell(pos, {slowly:true});
            } else {
                change_selection_ui(null);
                map_dialog = invoke_region_map(pos);
            }
            if(map_dialog) {
                map_dialog.widgets['map'].follow_travel = false;
                map_dialog.widgets['map'].zoom_all_the_way_in();
            }
        }
    };

    dialog.widgets['halt_button'].onclick = function(w) {
        var squad_data = w.parent.user_data['squad'];
        player.squad_halt(squad_data['id']);
    };

    dialog.widgets['recall_button'].onclick = function(w) {
        var squad_data = w.parent.user_data['squad'];
        player.squad_recall(squad_data['id']);
    };

    var scroller = function(kind, incr) { return function(w) {
        var dialog = w.parent;
        dialog.user_data[kind+'_scroll_goal'] = clamp(dialog.user_data[kind+'_scroll_goal']+dialog.data['widgets'][kind+'_unit']['array_offset'][0]*incr,
                                                      dialog.user_data[kind+'_scroll_limits'][0], dialog.user_data[kind+'_scroll_limits'][1]);
    }; };
    dialog.widgets['reserve_scroll_left'].onclick = scroller('reserve', -2);
    dialog.widgets['reserve_scroll_right'].onclick = scroller('reserve', 2);
    dialog.widgets['squad_scroll_left'].onclick = scroller('squad', -4);
    dialog.widgets['squad_scroll_right'].onclick = scroller('squad', 4);
    dialog.ondraw = SquadManageDialog.update_squad_manage;
};

SquadManageDialog.update_squad_manage = function(dialog) {
    var squad = player.squads[dialog.user_data['squad_id'].toString()];
    if(!squad) { dialog.widgets['close_button'].onclick(dialog.widgets['close_button']); return; }

    // always allow assign/unassign to base defenders, even without squad_play_requirement
    var pred = (SQUAD_IDS.is_mobile_squad_id(dialog.user_data['squad_id']) ? {'predicate':'LIBRARY', 'name':'squad_play_requirement'} : {'predicate': 'ALWAYS_TRUE'});
    var rpred = read_predicate(pred);
    var pred_ok = rpred.is_satisfied(player, null);
    var pred_help = (!pred_ok ? get_requirements_help(rpred) : null);

    // separate predicate check to deploy one addtional squad
    var deploy_pred_ok, deploy_pred_help;
    if(SQUAD_IDS.is_mobile_squad_id(dialog.user_data['squad_id'])) {
        var deploy_pred = {'predicate':'AND', 'subpredicates': [pred, get_squad_deployment_predicate()]};
        var deploy_rpred = read_predicate(deploy_pred);
        deploy_pred_ok = deploy_rpred.is_satisfied(player, null);
        deploy_pred_help = (!deploy_pred_ok ? get_requirements_help(deploy_rpred) : null);
    } else {
        deploy_pred_ok = pred_ok;
        deploy_pred_help = pred_help;
    }

    // clear out unit icons
    for(var name in dialog.widgets) {
        if(name.indexOf('reserve_unit') === 0 || name.indexOf('squad_unit') === 0) {
            unit_icon_set(dialog.widgets[name], null, -1, null, null);
        } else if(name.indexOf('squad_hp_bar') === 0) {
            dialog.widgets[name].show = false;
        }
    }

    // scan for units
    var reserve_units_by_type = {}, squad_units = [];
    var max_squad_space = (dialog.user_data['squad_id'] === SQUAD_IDS.BASE_DEFENDERS ? player.stattab['main_squad_space'] : player.stattab['squad_space']);
    var cur_squad_space = 0;
    var max_hp = 0, cur_hp = 0;
    var travel_speed = -1;
    var squad_is_deployed = player.squad_is_deployed(squad['id']);
    var squad_is_moving = player.squad_is_moving(squad['id']);
    var squad_is_under_repair = player.squad_is_under_repair(squad['id']);
    var squad_in_battle = player.squad_is_in_battle(squad['id']);

    goog.object.forEach(player.my_army, function(obj, obj_id) {
        var obj_squad_id = obj['squad_id'] || 0;
        if(obj_squad_id === SQUAD_IDS.RESERVES) {
            reserve_units_by_type[obj['spec']] = (reserve_units_by_type[obj['spec']]||0) + 1;
        } else if(obj_squad_id === dialog.user_data['squad_id']) {
            squad_units.push(obj);
            cur_squad_space += get_leveled_quantity(gamedata['units'][obj['spec']]['consumes_space']||0, obj['level']||1);
            var curmax = army_unit_hp(obj);
            cur_hp += curmax[0]; max_hp += curmax[1];
            var speed = get_leveled_quantity(gamedata['units'][obj['spec']]['maxvel']||0, obj['level']||1);
            if(travel_speed < 0) {
                travel_speed = speed;
            } else {
                travel_speed = Math.min(travel_speed, speed);
            }
        }
    });

    // add current production to space usage
    if(!gamedata['produce_to_reserves'] && dialog.user_data['squad_id'] === SQUAD_IDS.BASE_DEFENDERS) {
        cur_squad_space += player.get_manufacture_queue_space_usage();
    }

    var squad_is_dead = (max_hp > 0 && cur_hp <= 0);

    dialog.widgets['capacity_bar'].progress = cur_squad_space/Math.max(max_squad_space,1);
    dialog.widgets['capacity_label'].str = dialog.data['widgets']['capacity_label']['ui_name'].replace('%cur', pretty_print_number(cur_squad_space)).replace('%max', pretty_print_number(max_squad_space));

    // note: travel speed shown in GUI is not multiplied by the unit_travel_speed_factor or sttab
    dialog.widgets['travel_speed'].show = (dialog.user_data['squad_id'] != SQUAD_IDS.BASE_DEFENDERS);
    if(dialog.widgets['travel_speed'].show) {
        dialog.widgets['travel_speed'].str = dialog.data['widgets']['travel_speed']['ui_name'].replace('%s', (travel_speed > 0 ? travel_speed.toFixed(1) : '-'));
    }

    dialog.widgets['includes_manufacturing'].show = (dialog.user_data['squad_id'] === SQUAD_IDS.BASE_DEFENDERS) && (!player.squads_enabled() || !gamedata['produce_to_reserves']);

    var reserve_types_to_show = goog.object.getKeys(reserve_units_by_type);
    reserve_types_to_show.sort(army_unit_compare_specnames);
    squad_units.sort(army_unit_compare);

    // show manufacture-queued units in base defenders, after all other units
    if((!player.squads_enabled() || !gamedata['produce_to_reserves']) && (dialog.user_data['squad_id'] === SQUAD_IDS.BASE_DEFENDERS)) {
        goog.object.forEach(session.cur_objects.objects, function(obj) {
            if(obj.team === 'player' && obj.is_building() && obj.is_manufacturer()) {
                goog.array.forEach(obj.manuf_queue, function(item) {
                    squad_units.push({'obj_id':'IN_PRODUCTION', 'pending':1, 'in_manuf_queue':1,
                                      'spec': item['spec_name'], 'level': item['level']||1});
                });
            }
        });
    }

    var reserve_columns = dialog.user_data['reserve_columns'] = (reserve_types_to_show.length < dialog.data['widgets']['reserve_unit']['array_max'][0]*dialog.data['widgets']['reserve_unit']['array_max'][1] ? dialog.data['widgets']['reserve_unit']['array_max'][0] : Math.ceil((reserve_types_to_show.length+1)/dialog.data['widgets']['reserve_unit']['array_max'][1]));
    var squad_columns = dialog.user_data['squad_columns'] = (squad_units.length < dialog.data['widgets']['squad_unit']['array_max'][0]*dialog.data['widgets']['squad_unit']['array_max'][1] ? dialog.data['widgets']['squad_unit']['array_max'][0] : Math.ceil((squad_units.length+1)/dialog.data['widgets']['squad_unit']['array_max'][1]));

    dialog.user_data['reserve_scroll_limits'] = [0, Math.max(0, reserve_columns-dialog.data['widgets']['reserve_unit']['array_max'][0]) * dialog.data['widgets']['reserve_unit']['array_offset'][0]];
    dialog.user_data['squad_scroll_limits'] = [0, Math.max(0, squad_columns-dialog.data['widgets']['squad_unit']['array_max'][0]) * dialog.data['widgets']['squad_unit']['array_offset'][0]];

    goog.array.forEach(['reserve', 'squad'], function(kind) {
        dialog.user_data[kind+'_scroll_goal'] = clamp(dialog.user_data[kind+'_scroll_goal'], dialog.user_data[kind+'_scroll_limits'][0],  dialog.user_data[kind+'_scroll_limits'][1]);
        if(dialog.user_data[kind+'_scroll_pos'] != dialog.user_data[kind+'_scroll_goal']) {
            var delta = dialog.user_data[kind+'_scroll_goal'] - dialog.user_data[kind+'_scroll_pos'];
            var sign = (delta > 0 ? 1 : -1);
            dialog.user_data[kind+'_scroll_pos'] += sign * Math.floor(0.15 * Math.abs(delta) + 0.5);
        }
        dialog.widgets[kind+'_scroll_left'].state = (dialog.user_data[kind+'_scroll_goal'] <= dialog.user_data[kind+'_scroll_limits'][0] ? 'disabled' : 'normal');
        dialog.widgets[kind+'_scroll_right'].state = (dialog.user_data[kind+'_scroll_goal'] >= dialog.user_data[kind+'_scroll_limits'][1] ? 'disabled' : 'normal');
    });

    // show/hide right-hand widgets as appropriate
    dialog.widgets['reserve_topbar_label'].show =
        dialog.widgets['reserve_scroll_left'].show =
        dialog.widgets['reserve_scroll_right'].show = !squad_is_deployed;
    dialog.widgets['deployed_topbar_label'].show =

        dialog.widgets['deployed_midbar'].show =
        dialog.widgets['deployed_decoration'].show =
        dialog.widgets['deployed_unit_icon'].show =
        dialog.widgets['deployed_midbar_label'].show =
        dialog.widgets['deployed_midbar_coords'].show = squad_is_deployed;

    if(squad_is_deployed) {
        var orders = player.squad_get_client_data(squad['id'], 'squad_orders');

        // the definition of "recalling" is a little looser than squad_is_moving, since there may be a halt involved in the middle
        var squad_is_recalling = orders && ('recall' in orders || 'recall_after_halt' in orders);

        dialog.widgets['deployed_midbar_label'].str = dialog.data['widgets']['deployed_midbar_label']['ui_name' + ((squad_is_moving || squad_is_recalling) ? '_moving' : '')];
        dialog.widgets['deployed_midbar_coords'].str = ((vec_equals(squad['map_loc'], player.home_base_loc) || squad_is_recalling) ? gamedata['strings']['regional_map']['home_base'] : dialog.data['widgets']['deployed_midbar_coords']['ui_name'].replace('%x', squad['map_loc'][0].toString()).replace('%y', squad['map_loc'][1].toString()));
        dialog.widgets['deployed_unit_icon'].asset = (squad_units.length >= 1 ? get_leveled_quantity(gamedata['units'][squad_units[0]['spec']]['art_asset'], squad_units[0]['level']||1) : null);
        dialog.widgets['deployed_unit_icon'].rotating = squad_is_moving;
    }

    dialog.widgets['reserve_none_label'].show = !squad_is_deployed && (reserve_types_to_show.length < 1);
    if(dialog.widgets['reserve_none_label'].show) {
        dialog.widgets['reserve_none_label'].str = dialog.data['widgets']['reserve_none_label']['ui_name'+(squad_units.length >= 1 ? '' : '_squad_empty')];
    }

    dialog.widgets['squad_none_label'].show = !squad_is_deployed && (squad_units.length < 1);
    if(dialog.widgets['squad_none_label'].show) {
        dialog.widgets['squad_none_label'].str = dialog.data['widgets']['squad_none_label']['ui_name'+(reserve_types_to_show.length >= 1 ? '' : '_reserves_empty')];
    }

    dialog.widgets['arrow'].show = false;

    // RESERVES
    if(!squad_is_deployed) {
        var grid_x = 0, grid_y = 0;
        goog.array.forEach(reserve_types_to_show, function(specname) {
            var wname = 'reserve_unit'+grid_x.toString()+','+grid_y.toString();
            if(!(wname in dialog.widgets)) {
                dialog.widgets[wname] = new SPUI.Dialog(gamedata['dialogs'][dialog.data['widgets']['reserve_unit']['dialog']], dialog.data['widgets']['reserve_unit']);
                dialog.add_after(dialog.widgets['reserve_scroll_right'], dialog.widgets[wname]);
            }
            dialog.widgets[wname].xy = vec_add(vec_add(dialog.data['widgets']['reserve_unit']['xy'], [-dialog.user_data['reserve_scroll_pos'],0]),
                                               vec_mul([grid_x,grid_y], dialog.data['widgets']['reserve_unit']['array_offset']));

            var onclick = (function (_pred_ok, _pred_help, _squad_id, _specname, _cur_squad_space, _max_squad_space) { return function(w, button) {
                    if(!_pred_ok) {
                        if(_pred_help) {
                            _pred_help();
                        }
                        return true; // stop dripper
                    }
                    if(player.squad_is_deployed(_squad_id) || player.squad_is_in_battle(_squad_id)) {
                        var s = gamedata['errors']['CANNOT_ALTER_SQUAD_WHILE_TRAVELING'];
                        invoke_child_message_dialog(s['ui_title'], s['ui_name']);
                        return true; // stop dripper
                    }
                    if(player.squad_is_under_repair(_squad_id)) {
                        var s = gamedata['errors']['CANNOT_ALTER_SQUAD_UNDER_REPAIR'];
                        invoke_child_message_dialog(s['ui_title'], s['ui_name']);
                        return true; // stop dripper
                    }

                    // find healthiest (or unhealthiest) non-pending reserve unit of this type
                    var obj = null, extreme_hp_ratio, no_space = false;
                    if(button == SPUI.RIGHT_MOUSE_BUTTON) {
                        extreme_hp_ratio = 1;
                    } else {
                        extreme_hp_ratio = -1;
                    }
                    goog.object.forEach(player.my_army, function(o) {
                        if(o['squad_id'] === SQUAD_IDS.RESERVES && o['spec'] === _specname && !o['pending']) {
                            var space = get_leveled_quantity(gamedata['units'][o['spec']]['consumes_space']||0, o['level']||1);
                            if(_cur_squad_space+space <= _max_squad_space) {
                                var curmax = army_unit_hp(o);
                                var ratio = curmax[0]/Math.max(curmax[1],1);
                                if((button == SPUI.RIGHT_MOUSE_BUTTON && ratio <= extreme_hp_ratio) ||
                                   (button != SPUI.RIGHT_MOUSE_BUTTON && ratio > extreme_hp_ratio)) {
                                    extreme_hp_ratio = ratio;
                                    obj = o;
                                }
                            } else {
                                no_space = true;
                            }
                        }
                    });

                    if(no_space) {
                        var s = gamedata['errors']['CANNOT_SQUAD_ASSIGN_UNIT_LIMIT_REACHED'+(_squad_id == SQUAD_IDS.BASE_DEFENDERS ? '_BASE_DEFENDERS' : '')];
                        invoke_child_message_dialog(s['ui_title'], s['ui_name']);
                        return true; // stop dripper
                    }
                    if(obj) {
                        send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_ASSIGN_UNIT", _squad_id, obj['obj_id']]);
                        unit_repair_sync_marker = synchronizer.request_sync();

                        if(gamedata['client']['predict_squad_assign']) { // client-side predict
                            obj['squad_id'] = _squad_id;
                        }
                        obj['pending'] = 1;
                        return false; // do not stop dripper
                    }

                    return true; // stop dripper

            }; })(pred_ok, pred_help, dialog.user_data['squad_id'], specname, cur_squad_space, max_squad_space);

            var icon_state = ((!pred_ok || squad_is_under_repair || squad_is_deployed || squad_in_battle) ? 'disabled_clickable' : null);

            var enable_dripper = !!gamedata['client']['squad_manage_dripper'];

            unit_icon_set(dialog.widgets[wname], specname, reserve_units_by_type[specname], null, onclick, icon_state, null, enable_dripper);
            if(!icon_state && dialog.widgets[wname].mouse_enter_time > 0) {
                dialog.widgets['arrow'].show = true;
                dialog.widgets['arrow'].xy = dialog.widgets[wname].xy;
                dialog.widgets['arrow'].asset = dialog.data['widgets']['arrow']['asset_left'];
            }

            grid_x += 1; if(grid_x >= reserve_columns) { grid_y += 1; grid_x = 0; }
        });
    }

    // SQUAD
    if(1) {
        grid_x = grid_y = 0;
        goog.array.forEach(squad_units, function(obj) {
            var wname = 'squad_unit'+grid_x.toString()+','+grid_y.toString();
            if(!(wname in dialog.widgets)) {
                dialog.widgets[wname] = new SPUI.Dialog(gamedata['dialogs'][dialog.data['widgets']['squad_unit']['dialog']], dialog.data['widgets']['squad_unit']);
                dialog.add_after(dialog.widgets['squad_scroll_right'], dialog.widgets[wname]);
            }
            dialog.widgets[wname].xy = vec_add(vec_add(dialog.data['widgets']['squad_unit']['xy'], [-dialog.user_data['squad_scroll_pos'],0]),
                                               vec_mul([grid_x,grid_y], dialog.data['widgets']['squad_unit']['array_offset']));

            var onclick;
            if(obj['pending']) {
                onclick = null;
            } else if(!pred_ok) {
                onclick = pred_help;
            } else {
                onclick = (function (_squad_id, _obj) { return function(w) {
                    if(player.squad_is_deployed(_squad_id) || player.squad_is_in_battle(_squad_id)) {
                        var s = gamedata['errors']['CANNOT_ALTER_SQUAD_WHILE_TRAVELING'];
                        invoke_child_message_dialog(s['ui_title'], s['ui_name']);
                        return;
                    }
                    if(player.squad_is_under_repair(_squad_id)) {
                        var s = gamedata['errors']['CANNOT_ALTER_SQUAD_UNDER_REPAIR'];
                        invoke_child_message_dialog(s['ui_title'], s['ui_name']);
                        return;
                    }
                    send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_UNASSIGN_UNIT", _squad_id, _obj['obj_id']]);
                    unit_repair_sync_marker = synchronizer.request_sync();
                    if(gamedata['client']['predict_squad_assign']) { // client-side predict
                        _obj['squad_id'] = SQUAD_IDS.RESERVES;
                    }
                    _obj['pending'] = 1;
                }; })(dialog.user_data['squad_id'], obj)
            }
            var icon_state = ((obj['pending'] || !pred_ok || squad_is_under_repair || squad_is_deployed || squad_in_battle) ? 'disabled_clickable' : null);
            unit_icon_set(dialog.widgets[wname], obj['spec'], 1, obj, onclick, icon_state,
                          (obj['in_manuf_queue'] ? gamedata['strings']['squads']['in_manuf_queue'] : null)
                         );

            if(!icon_state && dialog.widgets[wname].mouse_enter_time > 0) {
                dialog.widgets['arrow'].show = true;
                dialog.widgets['arrow'].xy = dialog.widgets[wname].xy;
                dialog.widgets['arrow'].asset = dialog.data['widgets']['arrow']['asset_right'];
            }

            var hp_wname = 'squad_hp_bar'+grid_x.toString()+','+grid_y.toString();
            if(!(hp_wname in dialog.widgets)) {
                dialog.widgets[hp_wname] = SPUI.instantiate_widget(dialog.data['widgets']['squad_hp_bar']);
                dialog.add_after(dialog.widgets[wname], dialog.widgets[hp_wname]);
            }
            var curmax = army_unit_hp(obj);
            dialog.widgets[hp_wname].show = true;
            dialog.widgets[hp_wname].progress = curmax[0]/Math.max(curmax[1],1);
            if(curmax[0] < curmax[1] && squad_is_under_repair) { request_unit_repair_update(); }
            dialog.widgets[hp_wname].full_color = SPUI.make_colorv(dialog.data['widgets']['squad_hp_bar']['full_color' + (obj['in_manuf_queue'] ? '_queued' : '')]);
            dialog.widgets[hp_wname].xy = vec_add(vec_add(dialog.data['widgets']['squad_hp_bar']['xy'], [-dialog.user_data['squad_scroll_pos'],0]),
                                                  vec_mul([grid_x,grid_y], dialog.data['widgets']['squad_hp_bar']['array_offset']));
            grid_x += 1; if(grid_x >= squad_columns) { grid_y += 1; grid_x = 0; }
        });
    }

    // BUTTONS

    var is_nosql_region = (session.region.data && session.region.data['storage'] == 'nosql') && session.region.map_enabled();

    dialog.widgets['find_on_map_button'].show = squad_is_deployed;
    dialog.widgets['recall_button'].show = (squad_is_deployed); // && !squad_is_moving);
    dialog.widgets['halt_button'].show = false; // (squad_is_deployed && squad_is_moving);
    dialog.widgets['disband_button'].show = !squad_is_deployed && SQUAD_IDS.is_mobile_squad_id(dialog.user_data['squad_id']);
    dialog.widgets['deploy_button'].show = !squad_is_deployed && (cur_squad_space > 0) && SQUAD_IDS.is_mobile_squad_id(dialog.user_data['squad_id']);
    dialog.widgets['deploy_button'].state = (!is_nosql_region || !deploy_pred_ok || squad_is_under_repair || squad_is_dead ? 'disabled_clickable' : 'normal');

    dialog.widgets['recall_button'].state = ((squad['pending'] || player.squad_get_client_data(squad['id'], 'squad_orders')) ? 'disabled' : 'normal');

    dialog.widgets['halt_button'].state = ((squad['pending'] || player.squad_get_client_data(squad['id'], 'halt_pending')) ? 'disabled' : 'normal');

    dialog.widgets['deploy_button'].tooltip.str = null;
    if(!is_nosql_region) {
        dialog.widgets['deploy_button'].onclick = function() {
            var s = gamedata['errors']['CANNOT_DEPLOY_SQUAD_NO_NOSQL'];
            invoke_child_message_dialog(s['ui_title'], s['ui_name'], {'dialog':'message_dialog_big'});
        };
    } else if(!deploy_pred_ok) {
        dialog.widgets['deploy_button'].onclick = deploy_pred_help;
        dialog.widgets['deploy_button'].tooltip.str = deploy_rpred.ui_describe(player, null);
    } else {
        dialog.widgets['deploy_button'].onclick = function(w) {
            var squad_id = w.parent.user_data['squad_id'];
            var squad_data = w.parent.user_data['squad'];
            var icon_assetname = w.parent.widgets['squad_unit0,0'].widgets['icon'].asset;

            if(player.squad_is_under_repair(squad_id)) {
                var s = gamedata['errors']['CANNOT_DEPLOY_SQUAD_UNDER_REPAIR'];
                invoke_child_message_dialog(s['ui_title'], s['ui_name']);
                return;
            }
            if(player.squad_is_dead(squad_id)) {
                var s = gamedata['errors']['CANNOT_DEPLOY_SQUAD_DEAD'];
                invoke_child_message_dialog(s['ui_title'], s['ui_name']);
                return;
            }

            if(!session.home_base) { return; }
            change_selection_ui(null);
            var map_dialog = invoke_region_map(session.viewing_base.base_map_loc);
            if(map_dialog) {
                map_dialog.widgets['map'].invoke_deploy_cursor(session.viewing_base.base_map_loc, squad_id, icon_assetname);
            }
        };
    }

};
