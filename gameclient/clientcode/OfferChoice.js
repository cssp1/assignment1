goog.provide('OfferChoice');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    GUI dialog to give player the choice between some special offers.
    tightly coupled to main.js, sorry!
*/

goog.require('SPUI');
goog.require('SPFX');

/** @param {function()|null} then_cb
    @return {SPUI.Dialog|null} */
OfferChoice.invoke_offer_choice = function(then_cb) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['offer_choice_dialog']);
    dialog.user_data['dialog'] = 'offer_choice_dialog';
    dialog.user_data['then_cb'] = then_cb;
    dialog.user_data['open_time'] = client_time;
    dialog.user_data['start_time'] = -1;
    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;

    var trigger = function(w) {
        var choice = w.parent;
        var dialog = choice.parent;
        dialog.user_data['start_time'] = client_time;

        dialog.widgets['glow'].show = true; dialog.widgets['glow'].reset_fx();
        choice.widgets['glow'].reset_fx();

        if(gamedata['client']['vfx']['lottery_scan']) {
            SPFX.add_visual_effect_at_time([0,0], 0, [0,1,0], client_time, gamedata['client']['vfx']['lottery_scan'], true, null);
        }
    };

    for(var x = 0; x < dialog.data['widgets']['choice']['array'][0]; x++) {
        var choice = dialog.widgets['choice'+x.toString()];
        choice.user_data['cycle'] = -1;
        choice.user_data['asset_n'] = -1;
        choice.widgets['bg_glow'].onclick = trigger;
    }

    dialog.ondraw = OfferChoice.update_offer_choice;
    return dialog;
};

/** @param {!SPUI.Dialog} dialog */
OfferChoice.update_offer_choice = function(dialog) {
    var open_time = dialog.user_data['open_time'];

    for(var x = 0; x < dialog.data['widgets']['choice']['array'][0]; x++) {
        var choice = dialog.widgets['choice'+x.toString()];
        choice.widgets['border'].outline_color = SPUI.make_colorv(choice.data['widgets']['border'][(choice.mouse_enter_time > 0 ? 'outline_color_active': 'outline_color')]);
        var cycle_num = Math.floor((client_time + 0.7*x - open_time) / choice.data['cycle_period']);
        if(cycle_num != choice.user_data['cycle']) {
            choice.widgets['label'].str = choice.data['widgets']['label']['ui_name'].replace('%random', Math.floor(10000*Math.random()).toString());

            // ensure the icon asset changes every time
            var asset_list = choice.data['widgets']['icon']['asset_list'];
            var asset_n;
            do {
                asset_n = Math.floor(asset_list.length * Math.random());
            } while(asset_n === choice.user_data['asset_n']);
            choice.widgets['icon'].asset = asset_list[asset_n];
            choice.user_data['asset_n'] = asset_n;

            choice.user_data['cycle'] = cycle_num;
            choice.widgets['glow'].show = true; choice.widgets['glow'].reset_fx();
        }
    }

    var start_time = dialog.user_data['start_time'];
    if(start_time > 0) {
        var t = client_time - start_time;
        if(t > 1) {
            var then_cb = dialog.user_data['then_cb'];
            close_dialog(dialog);
            if(then_cb) {
                then_cb();
            }
        }
    }
};
