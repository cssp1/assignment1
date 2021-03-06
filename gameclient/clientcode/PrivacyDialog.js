goog.provide('PrivacyDialog');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    GUI dialog for the login incentive system.
    tightly coupled to main.js, sorry!
*/

goog.require('SPUI');

/** @return {SPUI.Dialog|null} */
PrivacyDialog.invoke = function() {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['privacy_dialog']);
    dialog.user_data['dialog'] = 'privacy_dialog';
    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;

    dialog.widgets['description'].set_text_bbcode(dialog.data['widgets']['description']['ui_name_prompt'], {}, system_chat_bbcode_click_handlers);

    metric_event('0060_privacy_prompt', add_demographics({}));

    dialog.widgets['deny_button'].onclick = function(w) {
        var dialog = w.parent;
        invoke_child_message_dialog(dialog.data['widgets']['description']['ui_title_deny'], dialog.data['widgets']['description']['ui_name_deny'].replace('%s', gamedata['strings']['game_name']),
                                    {'dialog':'message_dialog',
                                     'cancel_button': true,
                                     'on_ok': function(w) {
                                         metric_event('0061_privacy_prompt_fail', add_demographics({}));
                                         // dead-end redirect
                                         window.setTimeout(function() { location.href = spin_user_denied_auth_landing; }, 100);
                                     }
                                    });
    };
    dialog.widgets['ok_button'].onclick = function(w) {
        var dialog = w.parent;
        metric_event('0062_privacy_prompt_success', add_demographics({}));
        close_dialog(dialog);
        var accept_description;
        // check for platform-specific "Accept" message
        if(('ui_name_accept_'+spin_frame_platform) in dialog.data['widgets']['description']) {
            accept_description = dialog.data['widgets']['description']['ui_name_accept_'+spin_frame_platform];
        } else {
            accept_description = dialog.data['widgets']['description']['ui_name_accept'];
        }
        invoke_child_message_dialog(dialog.data['widgets']['description']['ui_title_accept'], accept_description,
                                    {'dialog': 'message_dialog_big'});
    };
    return dialog;
};
