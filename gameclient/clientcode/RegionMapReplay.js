goog.provide('RegionMapReplay');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('SPUI');
goog.require('SPFX');

/** @param {Array.<number>=} target_loc */
RegionMapReplay.invoke = function(region_id, target_loc) {
    var region = new Region(gamedata['regions'][region_id]);
    var dialog = new SPUI.Dialog(gamedata['dialogs']['region_map_replay_dialog']);
    dialog.user_data['dialog'] = 'region_map_replay_dialog';

    change_selection_ui(dialog);
//    dialog.auto_center();
    dialog.modal = false; // !

    dialog.widgets['close_button'].onclick = close_parent_dialog;
    dialog.widgets['map'].set_region(region);
    dialog.widgets['map'].gfx_detail = SPFX.detail;
    dialog.widgets['map'].set_zoom_buttons(dialog.widgets['zoom_in_button'], dialog.widgets['zoom_out_button']);

    dialog.user_data['pending'] = true;
    dialog.user_data['log'] = null; // log events
    dialog.user_data['time_range'] = null; // [first,last] time viewable
    dialog.user_data['time'] = null;
    query_map_log(region_id, [-1,-1], goog.partial(RegionMapReplay.receive_log, dialog));

    dialog.ondraw = RegionMapReplay.update;

    if(target_loc) {
        dialog.widgets['map'].follow_travel = false;
        dialog.widgets['map'].pan_to_cell(target_loc);
    }
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
    dialog.user_data['time_range'] = [log[0]['time'], log[log.length-1]['time']];
    dialog.user_data['time'] = dialog.user_data['time_range'][0];
};

RegionMapReplay.update = function(dialog) {
    dialog.widgets['loading_rect'].show =
        dialog.widgets['loading_text'].show =
        dialog.widgets['loading_spinner'].show = dialog.user_data['pending'];

    var t = dialog.user_data['time'];
    var time_range = dialog.user_data['time_range'];

    // update header/footer
    var region_name = dialog.widgets['map'].region.data['ui_name'];
    var cursor_coords = (dialog.widgets['map'].hovercell ? '('+dialog.widgets['map'].hovercell[0].toString()+','+dialog.widgets['map'].hovercell[1].toString()+')' : '');

    var ui_time_unix, ui_time_date;
    if(t !== null) {
        ui_time_unix = t.toFixed(0);
        ui_time_date = pretty_print_date_and_time(t);
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
