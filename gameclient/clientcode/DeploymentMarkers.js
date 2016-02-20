goog.provide('DeploymentMarkers');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// utilities for showing where units were deployed during an attack
// note: requires a bunch of stuff from main.js

goog.require('goog.array');
goog.require('SPFX');

/** @constructor @struct
    @param {!SPFX.FXWorld} fxworld */
DeploymentMarkers.MarkerList = function(fxworld) {
    this.fxworld = fxworld;
    /** @type {!Array<!SPFX.PhantomUnit>} */
    this.markers = [];
};
DeploymentMarkers.MarkerList.prototype.clear = function() {
    goog.array.forEach(this.markers, function(marker) { this.fxworld.remove(marker); }, this);
    this.markers = [];
};

/** @param {!Array.<number>} pos
    @param {number} altitude
    @param {string} specname
    @param {number} level */
DeploymentMarkers.MarkerList.prototype.add_marker = function(pos, altitude, specname, level) {
    var phantom = new SPFX.PhantomUnit(pos, altitude, [0,1,0],
                                       this.fxworld.now_time(),
                                       {'duration':-1, 'team':'enemy',
                                        'pulse_period': 1.7,
                                        'sprite_scale': 1.2,
                                        'alpha_pulse_amplitude': 0.2,
                                        'scale_pulse_amplitude': 0.55,
                                        'maxvel':0.001, 'alpha':0.8,
                                        'end_at_dest':false},
                                       {'spec':specname, 'level':level,
                                        'path':[vec_copy(pos),vec_add(pos,[1,1])]});
    phantom = this.fxworld.add_phantom(phantom);
    if(phantom) {
        this.markers.push(phantom);
    }
};

/** @param {!SPFX.FXWorld} fxworld
    @param {string} attacker_ui_name
    @param {!Array.<{pos:!Array.<number>, altitude:number, specname:string, level:number}>} unit_data */
DeploymentMarkers.invoke_gui = function(fxworld, attacker_ui_name, unit_data) {
    var markers = new DeploymentMarkers.MarkerList(fxworld);
    goog.array.forEach(unit_data, function(data) {
        markers.add_marker(data.pos, data.altitude, data.specname, data.level);
    });

    var dialog = new SPUI.Dialog(gamedata['dialogs']['deployment_markers_notice']);
    dialog.user_data['dialog'] = 'deployment_markers_notice';
    dialog.user_data['markers'] = markers;
    install_child_dialog(dialog);
    dialog.modal = false;
    dialog.widgets['description'].str = dialog.data['widgets']['description']['ui_name'].replace('%attacker', attacker_ui_name);
    dialog.widgets['close_button'].onclick = close_parent_dialog;
    dialog.on_destroy = function(dialog) {
        var markers = dialog.user_data['markers'];
        markers.clear();
    };
    dialog.ondraw = DeploymentMarkers.update_gui;
};

/** @param {!SPUI.Dialog} dialog */
DeploymentMarkers.update_gui = function(dialog) {
    dialog.xy = [Math.floor((SPUI.canvas_width - dialog.wh[0])/2),
                 Math.floor((0.5*SPUI.canvas_height - dialog.wh[1])/2)];
};
