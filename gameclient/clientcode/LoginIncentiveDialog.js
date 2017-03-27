goog.provide('LoginIncentiveDialog');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    GUI dialog for the login incentive system.
    tightly coupled to main.js, sorry!
*/

goog.require('SPUI');
goog.require('SPFX');

/** @return {SPUI.Dialog|null} */
LoginIncentiveDialog.invoke = function() {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['login_incentive_dialog']);
    dialog.user_data['dialog'] = 'login_incentive_dialog';
    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;

    dialog.ondraw = LoginIncentiveDialog.update;
    return dialog;
};

/** @param {!SPUI.Dialog} dialog */
LoginIncentiveDialog.update = function(dialog) {
};
