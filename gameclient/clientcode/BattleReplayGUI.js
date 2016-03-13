goog.provide('BattleReplayGUI');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('BattleReplay');
goog.require('SPUI');

/** Copy text to clipboard - may want to move this into a separate library
    @param {string} s */
BattleReplayGUI.copy_text_to_clipboard = function(s) {

    // See https://github.com/zenorocha/clipboard.js (MIT license)
    var isRTL = document.documentElement.getAttribute('dir') === 'rtl';

    var fakeElem = document.createElement('textarea');
    // Prevent zooming on iOS
    fakeElem.style.fontSize = '12pt';
    // Reset box model
    fakeElem.style.border = '0';
    fakeElem.style.padding = '0';
    fakeElem.style.margin = '0';
    // Move element out of screen horizontally
    fakeElem.style.position = 'fixed';
    fakeElem.style[isRTL ? 'right' : 'left'] = '-9999px';
    // Move element to the same position vertically
    fakeElem.style.top = (window.pageYOffset || document.documentElement.scrollTop) + 'px';
    fakeElem.setAttribute('readonly', '');
    fakeElem.value = s;

    document.body.appendChild(fakeElem);

    fakeElem.focus();
    fakeElem.setSelectionRange(0, fakeElem.value.length);

    document.execCommand('copy');

    document.body.removeChild(fakeElem);
};

/** @param {!BattleReplay.Player} player
    @param {string|null} link_url
    @return {!SPUI.Dialog} */
BattleReplayGUI.invoke = function(player, link_url) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['replay_overlay']);
    dialog.user_data['dialog'] = 'replay_overlay';
    dialog.user_data['player'] = player;
    dialog.user_data['link_url'] = link_url;
    install_child_dialog(dialog);
    dialog.modal = false;
    dialog.widgets['close_button'].onclick = close_parent_dialog;
    dialog.ondraw = function(dialog) {
        var player = dialog.user_data['player'];
        dialog.xy = [Math.floor((SPUI.canvas_width - dialog.wh[0])/2),
                     Math.floor((0.3*SPUI.canvas_height - dialog.wh[1])/2)];
        var s = dialog.data['widgets']['description']['ui_name'];
        dialog.widgets['description'].str = s.replace('%cur_tick', pretty_print_number(player.cur_tick())).replace('%num_ticks', pretty_print_number(player.num_ticks()));

    };
    if(link_url) {
        dialog.widgets['share_button'].show = true;
        dialog.widgets['share_button'].onclick = function(w) {
            var dialog = w.parent;
            var link_url = dialog.user_data['link_url'];
            var s = gamedata['strings']['copy_replay_link_success'];
            BattleReplayGUI.copy_text_to_clipboard(link_url);
            invoke_child_message_dialog(s['ui_title'],
                                        s['ui_description'].replace('%URL', link_url)
                                       // {'dialog': 'message_dialog_big'}
                                       );
            return;
        };
    } else {
        dialog.widgets['share_button'].show = false;
    }
    return dialog;
};
