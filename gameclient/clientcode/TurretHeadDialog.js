goog.provide('TurretHeadDialog');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('goog.array');
goog.require('SPUI');
goog.require('SPText');

// tightly coupled to main.js, sorry!

/** @param {SPUI.Dialog} parent */
TurretHeadDialog.invoke = function(emplacement_obj) {
    var dialog_data = gamedata['dialogs']['turret_head_dialog'];
    dialog = new SPUI.Dialog(dialog_data);
    dialog.user_data['dialog'] = 'turret_head_dialog';
    dialog.user_data['emplacement'] = emplacement_obj;
    dialog.user_data['builder'] = emplacement_obj;
    dialog.widgets['title'].str = dialog.data['widgets']['title']['ui_name'].replace('%s', gamedata['spells']['CRAFT_FOR_FREE']['ui_name_building_context_emplacement']);
    dialog.widgets['flavor_text'].set_text_with_linebreaking(dialog.data['widgets']['flavor_text']['ui_name'].replace('%s', gamedata['buildings'][get_lab_for('turret_heads')]['ui_name']));
    dialog.widgets['close_button'].onclick = close_parent_dialog;
    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;
    dialog.ondraw = TurretHeadDialog.ondraw;
    return dialog;
};

/** @param {TurretHeadDialog} dialog */
TurretHeadDialog.ondraw = function(dialog) {
};
