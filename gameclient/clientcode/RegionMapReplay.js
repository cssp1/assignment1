goog.provide('RegionMapReplay');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('SPUI');
goog.require('SPFX');
goog.require('Region');
goog.require('goog.object');

/** @param {Array.<number>=} target_loc */
RegionMapReplay.invoke = function(region_id, target_loc) {
    var region = new Region.Region(gamedata['regions'][region_id]);
    var dialog = new SPUI.Dialog(gamedata['dialogs']['region_map_replay_dialog']);
    dialog.user_data['dialog'] = 'region_map_replay_dialog';

    change_selection_ui(dialog);
//    dialog.auto_center();
    dialog.modal = false; // !

    dialog.widgets['close_button'].onclick = close_parent_dialog;
    dialog.widgets['map'].set_region(region);
    dialog.widgets['map'].gfx_detail = SPFX.detail;
    dialog.widgets['map'].set_zoom_buttons(dialog.widgets['zoom_in_button'], dialog.widgets['zoom_out_button']);
    dialog.widgets['map'].zoom_limits[0] = -3.1; // allow greater zoom out

    dialog.user_data['pending'] = true;
    dialog.user_data['play_speed'] = 0;
    dialog.user_data['last_play_client_time'] = client_time;

    dialog.user_data['log'] = null; // log events
    dialog.user_data['time_range'] = null; // [first,last] time viewable
    dialog.user_data['time'] = null;
    query_map_log(region_id, [-1,-1], goog.partial(RegionMapReplay.receive_log, dialog));

    dialog.ondraw = RegionMapReplay.update;

    if(target_loc) {
        dialog.widgets['map'].follow_travel = false;
        dialog.widgets['map'].pan_to_cell(target_loc);
    }

    dialog.widgets['progress'].onclick = function(w, button, prog) {
        var dialog = w.parent;
        var time_range = dialog.user_data['time_range'];
        if(time_range === null) { return; }
        var t = time_range[0] + prog*(time_range[1] - time_range[0]);
        RegionMapReplay.seek(dialog, t);
        dialog.user_data['play_speed'] = 0;
    };
    dialog.widgets['play_button'].onclick = function(w) {
        var dialog = w.parent;
        if(dialog.user_data['time_range'] === null) { return; }
        if(dialog.user_data['play_speed'] != 0) {
            dialog.user_data['play_speed'] = 0;
        } else {
            dialog.user_data['play_speed'] = 1;
        }
    };
    dialog.widgets['fast_button'].onclick = function(w) {
        var dialog = w.parent;
        if(dialog.user_data['time_range'] === null) { return; }
        if(dialog.user_data['play_speed'] != 0) {
            dialog.user_data['play_speed'] = Math.min(2*dialog.user_data['play_speed'], 128);
        } else {
            dialog.user_data['play_speed'] = 2;
        }
    };
    return dialog;
};

RegionMapReplay.receive_log = function(dialog, log) {
    // trim off everything before the first snapshot
    var snap_i = goog.array.findIndex(log, (event) => ('feature_snapshot' in event));
    if(snap_i < 0) {
        console.log('no snapshot found!');
        close_dialog(dialog);
        return;
    }
    log.splice(0, snap_i);

    dialog.user_data['pending'] = false;
    dialog.user_data['log'] = log;
    // subset of log with only the snapshots
    dialog.user_data['snapshots'] = goog.array.filter(log, (event) => ('feature_snapshot' in event));

    dialog.user_data['time_range'] = [log[0]['time'], log[log.length-1]['time']];
    dialog.user_data['time'] = -1;
    dialog.user_data['cur_snapshot'] = null; // last *applied* snapshot
    dialog.user_data['cur_event'] = null; // last *applied* event

    // initialize state to beginning of log
    RegionMapReplay.seek(dialog, log[0]['time']);
};

RegionMapReplay.seek = function(dialog, new_t) {
    new_t = Math.min(Math.max(new_t, dialog.user_data['time_range'][0]), dialog.user_data['time_range'][1]);

    if(new_t === dialog.user_data['time']) { return; }
    var old_t = dialog.user_data['time'];

    var snap_index = goog.array.binarySelect(dialog.user_data['snapshots'],
                                             function(entry, index) {
                                                 if(entry['time'] > new_t) {
                                                     return -1;
                                                 } else if(entry['time'] < new_t) {
                                                     return 1;
                                                 } else {
                                                     return 0;
                                                 }
                                             });
    //console.log('search for '+new_t.toString()+' in '+JSON.stringify(goog.array.map(dialog.user_data['snapshots'], (entry) => entry['time']))+' returned '+snap_index.toString());
    if(snap_index < 0) { // no exact match
        snap_index = Math.max(0, Math.min(-(snap_index + 1) - 1, dialog.user_data['snapshots'].length-1));
    }
    //console.log('snap_index '+snap_index.toString());

    var region = dialog.widgets['map'].region;
    var snapshot = dialog.user_data['snapshots'][snap_index];
    // apply snapshot if it's not the one we are on now, or if we need to go backwards in time
    if(dialog.user_data['cur_snapshot'] !== snapshot || new_t < dialog.user_data['time']) {
        region.receive_update(snapshot['time'], goog.object.getValues(snapshot['feature_snapshot']), -1);
        dialog.user_data['cur_snapshot'] = snapshot;
        dialog.user_data['cur_event'] = snapshot;
    }

    // apply events following the snapshot
    var cur_event_index = goog.array.binarySearch(dialog.user_data['log'], dialog.user_data['cur_event'],
                                                  (a,b) => (a['time'] < b['time'] ? -1 :
                                                            (a['time'] > b['time'] ? 1 :
                                                             (a['_id'] < b['_id'] ? -1 :
                                                              (a['_id'] > b['_id'] ? 1 :
                                                               0)))));
    cur_event_index += 1; // next event after the previous cur_event we just applied
    //console.log('cur_event_index '+cur_event_index.toString());
    while(cur_event_index < dialog.user_data['log'].length-1) {
        var event = dialog.user_data['log'][cur_event_index];
        if(event['time'] > new_t) { // in the future
            break;
        }
        // apply the event
        //console.log('applying event '+JSON.stringify(event));
        if(event['feature_snapshot']) {
            region.receive_update(event['time'], goog.object.getValues(event['feature_snapshot']), -1);
        } else if(event['feature_update']) {
            region.receive_feature_update(event['feature_update'], !!event['incremental']);
        }
        dialog.user_data['cur_event'] = event;
        cur_event_index += 1;
    }

    dialog.user_data['time'] = new_t;
};

RegionMapReplay.update = function(dialog) {
    dialog.widgets['loading_rect'].show =
        dialog.widgets['loading_text'].show =
        dialog.widgets['loading_spinner'].show = dialog.user_data['pending'];

    if(dialog.user_data['play_speed'] != 0) {
        RegionMapReplay.seek(dialog, dialog.user_data['time'] + dialog.user_data['play_speed'] * (client_time - dialog.user_data['last_play_client_time']));
    }
    dialog.user_data['last_play_client_time'] = client_time;

    var t = dialog.user_data['time'];
    var time_range = dialog.user_data['time_range'];

    // update map view time
    dialog.widgets['map'].time = t;

    // update header/footer
    var region_name = dialog.widgets['map'].region.data['ui_name'];
    var cursor_coords = (dialog.widgets['map'].hovercell ? '('+dialog.widgets['map'].hovercell[0].toString()+','+dialog.widgets['map'].hovercell[1].toString()+')' : '');

    var ui_time_unix, ui_time_date;
    if(t !== null) {
        ui_time_unix = Math.floor(t).toFixed(0);
        // add seconds manually
        ui_time_date = pretty_print_date_and_time(t) + ':' + pad_with_zeros(Math.floor(t % 60).toFixed(0), 2);
    } else {
        ui_time_unix = ui_time_date = '-';
    }

    dialog.widgets['region_info'].str = dialog.data['widgets']['region_info']['ui_name'].replace('%REGION', region_name).replace('%CURSOR', cursor_coords).replace('%UNIX', ui_time_unix).replace('%DATE', ui_time_date);



    if(dialog.user_data['time_range'] !== null && time_range[1] > time_range[0]) {
        dialog.widgets['progress'].show = true;
        dialog.widgets['progress'].progress = (t - time_range[0]) / (time_range[1] - time_range[0]);
    } else {
        dialog.widgets['progress'].show = false;
    }

    // dynamic resizing, making room for chat
    var console_shift = get_console_shift();
    dialog.wh = vec_max(vec_floor(vec_scale(0.9, [canvas_width-console_shift, canvas_height])), dialog.data['min_dimensions']);
    dialog.widgets['bg'].wh = dialog.wh;
    dialog.apply_layout();
//    dialog.auto_center();
    dialog.xy = vec_floor(vec_add(vec_scale(0.05, [canvas_width,canvas_height]), [Math.floor(console_shift),0]));
    dialog.on_resize();
};
