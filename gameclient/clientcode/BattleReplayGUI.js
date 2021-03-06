goog.provide('BattleReplayGUI');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('BattleReplay');
goog.require('FBShare');
goog.require('SPUI');

/** @param {!BattleReplay.Player} replay_player
    @param {string|null} link_url
    @param {Object<string,string>|null} link_qs
    @return {!SPUI.Dialog} */
BattleReplayGUI.invoke = function(replay_player, link_url, link_qs) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['replay_overlay_dialog']);
    dialog.user_data['dialog'] = 'replay_overlay_dialog';
    dialog.user_data['player'] = replay_player;
    dialog.user_data['link_url'] = link_url;
    dialog.user_data['link_qs'] = link_qs;
    install_child_dialog(dialog);
    dialog.modal = false;
    dialog.widgets['close_button'].onclick = close_parent_dialog;

    if(player.tutorial_state != "COMPLETE") {
        make_tutorial_arrow_for_button('replay_overlay_dialog', 'close_button', 'up');
    }

    // Get Link button
    if(link_url) {
        dialog.widgets['get_link_button'].show = true;
        dialog.widgets['get_link_button'].onclick = function(w) {
            var dialog = w.parent;
            var link_url = dialog.user_data['link_url'];
            var s = gamedata['strings']['copy_replay_link_success'];
            SPUI.copy_text_to_clipboard(link_url);
            var child = invoke_child_message_dialog(s['ui_title'],
                                                    s['ui_description'].replace('%URL', link_url)
                                                    // {'dialog': 'message_dialog_big'}
                                                   );
            child.xy = vec_add(child.xy, [0,100]);
            return;
        };
    } else {
        dialog.widgets['get_link_button'].show = false;
    }

    // FB share button
    if(link_qs && FBShare.supported()) {
        dialog.widgets['fb_share_button'].show =
            dialog.widgets['fb_share_icon'].show = true;
        dialog.widgets['fb_share_button'].onclick = function(w) {
            var dialog = w.parent;
            FBShare.invoke({link_qs: dialog.user_data['link_qs'],
                            name: gamedata['virals']['replay']['ui_post_headline']
                            .replace('%ATTACKER', replay_player.header['attacker_name'] || '?')
                            .replace('%DEFENDER', replay_player.header['defender_name'] || '?'),
                            ref: 'replay',
                           });
        };
    } else {
        dialog.widgets['fb_share_button'].show =
            dialog.widgets['fb_share_icon'].show = false;
    }

    dialog.ondraw = BattleReplayGUI.update;
    return dialog;
};

/** @param {!SPUI.Dialog} dialog */
BattleReplayGUI.update = function(dialog) {
    var replay_player = dialog.user_data['player'];
    dialog.xy = [Math.floor((SPUI.canvas_width - dialog.wh[0])/2),
                 Math.max(10, Math.floor(0.04*SPUI.canvas_height))];
    // update description text
    var total_seconds = Math.max(replay_player.num_ticks()-1, 1) * TICK_INTERVAL;
    var total_minutes = Math.floor(total_seconds/60.0);
    var total_time = total_minutes.toFixed(0) + ':' + pad_with_zeros(Math.floor(total_seconds%60.0).toFixed(0), 2); // +'.'+pad_with_zeros(((total_seconds*100)%100).toFixed(0), 2);;


    var cur_tick = Math.max(replay_player.cur_tick(),0); // display -1 uninitialized state as 0

    var cur_seconds, cur_minutes;
    // snap to end time at final tick for UI friendliness
    if(cur_tick >= replay_player.num_ticks()-1) {
        cur_seconds = total_seconds;
        cur_minutes = total_minutes;
    } else {
        cur_seconds = cur_tick * TICK_INTERVAL;
        cur_minutes = Math.floor(cur_seconds/60.0);
    }
    var cur_time = cur_minutes.toFixed(0) + ':' + pad_with_zeros(Math.floor(cur_seconds%60.0).toFixed(0), 2); // +'.'+pad_with_zeros(((cur_seconds*100)%100).toFixed(0), 2);
    var s = dialog.data['widgets']['description']['ui_name'];
    dialog.widgets['description'].set_text_bbcode(s
                                                  .replace('%cur_tick', pretty_print_number(cur_tick))
                                                  .replace('%num_ticks', pretty_print_number(replay_player.num_ticks()-1))
                                                  .replace('%cur_time', cur_time)
                                                  .replace('%total_time', total_time)
                                                  .replace('%attacker', replay_player.header['attacker_name'] || '?')
                                                  .replace('%defender', replay_player.header['defender_name'] || '?'),
                                                  null, system_chat_bbcode_click_handlers); // for [url] handling
    dialog.widgets['description'].clip_to_max_lines(2, '');
};
