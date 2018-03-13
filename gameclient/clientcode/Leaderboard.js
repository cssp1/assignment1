goog.provide('Leaderboard');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    Utilities for in-game leaderboard. Some parts remain in main.js.
 */

goog.require('SPUI');
goog.require('PlayerCache');

/** @param {string} stat_name
    @param {string} challenge_key
    */
Leaderboard.invoke_skill_challenge_standings_dialog = function(stat_name, challenge_key) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['skill_challenge_standings_dialog']);
    dialog.user_data['dialog'] = 'skill_challenge_standings_dialog';
    dialog.user_data['stat_name'] = stat_name;
    dialog.user_data['challenge_key'] = challenge_key;
    dialog.widgets['close_button'].onclick = close_parent_dialog;

    desktop_dialogs['skill_challenge_standings_dialog'] = dialog;
    SPUI.root.add_under(dialog);

    dialog.on_destroy = function(dialog) {
        if(desktop_dialogs['skill_challenge_standings_dialog'] === dialog) {
            delete desktop_dialogs['skill_challenge_standings_dialog'];
        }
    };

    query_score_leaders(stat_name, 'week', {'challenge': ['key', challenge_key]}, 5,
                        (function (_dialog) { return function(cat, period, data) {
                            Leaderboard.skill_challenge_standings_dialog_receive_scores(_dialog, data);
                        }; })(dialog));

    dialog.ondraw = Leaderboard.update_skill_challenge_standings_dialog;
    dialog.ondraw(dialog);

    return dialog;
};

Leaderboard.update_skill_challenge_standings_dialog = function(dialog) {
    // anchor under the enemy_portrait_dialog
    var top = desktop_dialogs['enemy_portrait_dialog'];
    if(top) {
        dialog.xy = vec_add(top.get_absolute_xy(),
                            [0,
                             top.wh[1] + 10]);
    }
};

Leaderboard.skill_challenge_standings_dialog_receive_scores = function(dialog, data) {
    dialog.widgets['loading_spinner'].show = false;

    for(var y = 0; y < /** number */ (dialog.data['widgets']['row_score']['array'][1]); y++) {
        if(y < data.length) {
            dialog.widgets['row_score'+y.toString()].show =
                dialog.widgets['row_name'+y.toString()].show = true;

            var ui_score = pretty_print_time(data[y]['absolute']);

            dialog.widgets['row_score'+y.toString()].str =
                dialog.data['widgets']['row_score']['ui_name']
                .replace('%rank', (y+1).toString())
                .replace('%score', ui_score);

            var ui_name = PlayerCache.get_ui_name(data[y]);
            if('player_level' in data[y]) {
                ui_name += ' L'+data[y]['player_level'].toString();
            }
            dialog.widgets['row_name'+y.toString()].str = ui_name;

        } else {
            dialog.widgets['row_score'+y.toString()].show =
                dialog.widgets['row_name'+y.toString()].show = false;
        }
    }
};

// to test:
// Leaderboard.invoke_skill_challenge_standings_dialog('battle_duration', 'skill_challenge:246')
