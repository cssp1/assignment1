goog.provide('TurretHeadDialog');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('goog.array');
goog.require('SPUI');
goog.require('SPText');
goog.require('ItemDisplay');

// tightly coupled to main.js, sorry!

/** @param {SPUI.Dialog} parent */
TurretHeadDialog.invoke = function(emplacement_obj) {
    var dialog_data = gamedata['dialogs']['turret_head_dialog'];
    dialog = new SPUI.Dialog(dialog_data);
    dialog.user_data['dialog'] = 'turret_head_dialog';
    dialog.user_data['emplacement'] = emplacement_obj;
    dialog.user_data['builder'] = emplacement_obj;
    dialog.user_data['selected'] = null;
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
    var emplacement_obj = dialog.user_data['emplacement'];
    var current_name = emplacement_obj.turret_head_item();

    dialog.widgets['no_current'].show = !current_name;
    dialog.widgets['current'].show = !!current_name;

    if(current_name) {
        TurretHeadDialog.set_head_info(dialog.widgets['current'], current_name);
    }

    dialog.widgets['click_to_select_arrow'].show =
        dialog.widgets['click_to_select'].show = !dialog.user_data['selected'];

};

// operates on turret_head_dialog_current
/** @param {string} name of the turret head item */
TurretHeadDialog.set_head_info = function(dialog, name) {
    var emplacement_obj = dialog.parent.user_data['emplacement'];
    var spec = ItemDisplay.get_inventory_item_spec(name);

    dialog.widgets['name'].str = ItemDisplay.get_inventory_item_ui_name(spec);
    // main icon
    ItemDisplay.set_inventory_item_asset(dialog.widgets['icon'], spec);

    var spell = gamedata['spells'][spec['equip']['effects'][0]['strength']];

    // fill in damage_vs icons
    init_damage_vs_icons(dialog, {'kind':'building', 'ui_damage_vs':{}}, // fake building spec to fool init_damage_vs_icons()
                         spell);

    // set up stats display
    var statlist = get_weapon_spell_features2(emplacement_obj.spec, spell);

    goog.array.forEach([['descriptionL0', 'descriptionR0'], ['descriptionL1', 'descriptionR1']], function(wnames, i) {
        var left = dialog.widgets[wnames[0]], right = dialog.widgets[wnames[1]];
        if(i < statlist.length) {
            left.show = right.show = true;
            var stat = statlist[i];
            var modchain = null;
            ModChain.display_label_widget(left, stat, spell);
            ModChain.display_widget(right, stat, modchain,
                                    spec, // ??? emplacement_obj.spec
                                    spec['level'] || 1, // ???
                                    spell, spec['level'] || 1);
        } else {
            left.show = right.show = false;
        }
    });
};
