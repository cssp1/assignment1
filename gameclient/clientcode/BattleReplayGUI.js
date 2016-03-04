goog.provide('BattleReplayGUI');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('BattleReplay');
goog.require('SPUI');

/** @param {!BattleReplay.Player} player
    @return {!SPUI.Dialog} */
BattleReplayGUI.invoke = function(player) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['replay_overlay']);
    dialog.user_data['dialog'] = 'replay_overlay';
    dialog.user_data['player'] = player;
    install_child_dialog(dialog);
    dialog.modal = false;
    dialog.widgets['close_button'].onclick = close_parent_dialog;
    dialog.ondraw = function(dialog) {
        var player = dialog.user_data['player'];
        dialog.xy = [Math.floor((SPUI.canvas_width - dialog.wh[0])/2),
                     Math.floor((0.5*SPUI.canvas_height - dialog.wh[1])/2)];
        var s = dialog.data['widgets']['description']['ui_name'];
        dialog.widgets['description'].str = s.replace('%cur_tick', pretty_print_number(player.cur_tick())).replace('%num_ticks', pretty_print_number(player.num_ticks()));

    };
    return dialog;
};
