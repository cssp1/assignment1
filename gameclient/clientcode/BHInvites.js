goog.provide('BHInvites');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// Battlehouse Friend Invites dialogs

// this references a ton of stuff from main.js. It's not a self-contained module.

goog.require('SPUI');

/** Obtain and display the invite code to send to others */
BHInvites.invoke_invite_code_dialog = function() {
    // lock GUI and retrieve code
    var locker = invoke_ui_locker_until_closed();
    BHSDK.bh_invite_code_get(gamedata['game_id'], (function (_locker) { return function(result) {
        close_dialog(_locker);
        BHInvites.do_invoke_invite_code_dialog(result['code'], result['url']);
    }; })(locker));
};

/** Display the invite code
    @param {string} code
    @param {string} url */
BHInvites.do_invoke_invite_code_dialog = function(code, url) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['bh_invite_code_dialog']);
    dialog.user_data['dialog'] = 'bh_invite_code_dialog';
    dialog.user_data['url'] = url;
    dialog.widgets['close_button'].onclick =
        dialog.widgets['ok_button'].onclick = close_parent_dialog;

    // strip prefix on visible URL to shorten it
    var ui_url = url.replace('http://','').replace('https://','');
    dialog.widgets['link'].str = ui_url;
    dialog.widgets['link'].onclick =
        dialog.widgets['copied'].onclick = function(w) {
            var dialog = w.parent;
            SPUI.copy_text_to_clipboard(dialog.user_data['url']);
            dialog.widgets['copied'].str = dialog.data['widgets']['copied']['ui_name_after'];
        };

    change_selection_ui(dialog);
    dialog.auto_center();
    dialog.modal = true;

    metric_event('7101_invite_friends_ingame_prompt', {'sum': player.get_denormalized_summary_props('brief')});

    return dialog;
};
