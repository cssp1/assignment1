goog.provide('BHInvites');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// Battlehouse Friend Invites dialogs

// this references a ton of stuff from main.js. It's not a self-contained module.

goog.require('goog.array');
goog.require('SPUI');
goog.require('ItemDisplay');
goog.require('LootTable');

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
    dialog.user_data['metric_sent'] = false;
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
            if(!dialog.user_data['metric_sent']) {
                dialog.user_data['metric_sent'] = true;
                metric_event('7102_invite_friends_ingame_bh_link_copied', {'sum': player.get_denormalized_summary_props('brief')});
            }
        };

    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;

    return dialog;
};


BHInvites.invoke_invite_friends_dialog = function(reason) {
    metric_event('7101_invite_friends_ingame_prompt', {'method': reason,
                                                       'sum': player.get_denormalized_summary_props('brief')});

    return BHInvites.do_invoke_invite_dialog('invite', reason);
};

BHInvites.invoke_send_gifts_dialog = function(reason) {
    metric_event('4101_send_gifts_ingame_prompt', {'api':'bh', 'api_version': 1,
                                                   'method': reason,
                                                   'sum': player.get_denormalized_summary_props('brief')});
    return BHInvites.do_invoke_invite_dialog('gifts', reason);
};

BHInvites.do_invoke_invite_dialog = function(tabname, reason) {
    var complete_pred = gamedata['predicate_library']['bh_invite_complete'];
    if(!complete_pred || !complete_pred['ui_name']) {
        throw Error('unhandled bh_invite_complete predicate');
    }

    var dialog = new SPUI.Dialog(gamedata['dialogs']['bh_invite_dialog']);

    dialog.user_data['dialog'] = 'bh_invite_dialog';
    dialog.user_data['ui_complete_pred'] = gamedata['predicate_library']['bh_invite_complete']['ui_name'];
    dialog.widgets['close_button'].onclick = close_parent_dialog;

    goog.array.forEach(['instructions', 'next_description', 'bonus_description'], function(wname) {
        dialog.widgets['invite_tab'].widgets[wname].set_text_with_linebreaking(
            dialog.widgets['invite_tab'].data['widgets'][wname]['ui_name']
                .replace('%game', gamedata['strings']['game_name'])
                .replace('%req', dialog.user_data['ui_complete_pred']));
    });

    dialog.widgets['invite_tab_button'].onclick = function(w) {
        BHInvites.invite_dialog_change_tab(w.parent, 'invite');
    };
    dialog.widgets['gifts_tab_button'].onclick = function(w) {
        BHInvites.invite_dialog_change_tab(w.parent, 'gifts');
    };

    dialog.widgets['gifts_tab'].user_data['n_giftable'] = 0
    dialog.widgets['gifts_jewel'].ondraw = function(w) {
        w.user_data['count'] = w.parent.widgets['gifts_tab'].user_data['n_giftable'];
        update_notification_jewel(w);
    };

    /** @type {!Array<!Friend>} */
    var trainee_list = [];
    /** @type {Friend|null} */
    var mentor = null;
    goog.array.forEach(player.friends, function(friend) {
        if(friend.is_ai() || !friend.is_real_friend) { return; }
        if(friend.is_mentor()) {
            mentor = friend;
            if(friend.is_giftable()) {
                dialog.widgets['gifts_tab'].user_data['n_giftable'] += 1;
            }
        } else if(friend.is_trainee()) {
            trainee_list.push(friend);
            if(friend.is_giftable()) {
                dialog.widgets['gifts_tab'].user_data['n_giftable'] += 1;
            }
        }
    });
    trainee_list.sort(Friend.compare_by_player_level);

    BHInvites.init_invite_tab(dialog.widgets['invite_tab'], mentor, trainee_list);
    BHInvites.init_gifts_tab(dialog.widgets['gifts_tab'], mentor, trainee_list);
    change_selection_ui(dialog);
    dialog.auto_center();
    dialog.modal = true;

    BHInvites.invite_dialog_change_tab(dialog, tabname || 'invite');
    return dialog;
};

BHInvites.invite_dialog_change_tab = function(dialog, tabname) {
    dialog.widgets['invite_tab_button'].state = (tabname == 'invite' ? 'active': 'normal');
    dialog.widgets['gifts_tab_button'].state = (tabname == 'gifts' ? 'active': 'normal');
    dialog.widgets['invite_tab'].show = (tabname == 'invite');
    dialog.widgets['gifts_tab'].show = (tabname == 'gifts');
};

BHInvites.init_invite_tab = function(dialog, mentor, trainee_list) {
    dialog.widgets['subtitle'].str = dialog.data['widgets']['subtitle']['ui_name'].replace('%game', gamedata['strings']['game_name']);
    dialog.widgets['get_link_button'].onclick = function(w) {
        BHInvites.invoke_invite_code_dialog();
    }
    var n_complete = player.history['bh_invite_trainee_count'] || 0;
    // 1-based index of the next trainee that would come in
    var n_next = n_complete + 1;

    dialog.widgets['next_label'].str = dialog.data['widgets']['next_label']['ui_name'].replace('%d', pretty_print_number(n_next));
    var next_rewards = BHInvites.get_nth_trainee_rewards(n_next);

    ItemDisplay.display_item_array(dialog, 'next_items', next_rewards, {glow: false});

    var breakpoint = BHInvites.get_next_trainee_breakpoint(n_next);
    console.log('n_complete '+n_complete.toString()+' breakpoint '+breakpoint.toString());
    if(breakpoint > 0) {
        var bonus_rewards = BHInvites.get_nth_trainee_rewards(breakpoint);
        var delta = breakpoint - n_complete;
        // note: this will always be plural, since breakpoint - n_complete >= 2
        dialog.widgets['bonus_description'].set_text_with_linebreaking(
            dialog.data['widgets']['bonus_description']['ui_name'].replace('%more', pretty_print_number(delta)));
        dialog.widgets['bonus_label'].str = dialog.data['widgets']['bonus_label']['ui_name'].replace('%d', pretty_print_number(breakpoint));
        ItemDisplay.display_item_array(dialog, 'bonus_items', bonus_rewards, {glow: false});
    } else {
        dialog.widgets['bonus_label'].show =
            dialog.widgets['bonus_description'].show = false;
    }
};

BHInvites.init_gifts_tab = function(dialog, mentor, trainee_list) {
    dialog.widgets['subtitle'].str = dialog.data['widgets']['subtitle']['ui_name']
        .replace('%req', dialog.parent.user_data['ui_complete_pred']);

    var max_trainee_num = BHInvites.get_max_trainee_num();
    dialog.widgets['your_trainees_label'].str = dialog.data['widgets']['your_trainees_label']['ui_name']
        .replace('%cur', trainee_list.length.toString())
        .replace('%req', dialog.parent.user_data['ui_complete_pred'])
        .replace('%complete', (player.history['bh_invite_trainee_count'] || 0).toString())
        .replace('%max', max_trainee_num.toString())
        .replace('%max', max_trainee_num.toString());

    if(mentor) {
        var is_complete = mentor.is_bh_invite_complete();
        dialog.widgets['mentor_friend_icon'].set_user(mentor.user_id);
        dialog.widgets['mentor_friend_icon'].state = (mentor.is_giftable() && is_complete ? 'normal' : 'disabled');
        dialog.widgets['mentor_send_gift_button'].show = is_complete;
        dialog.widgets['mentor_friend_status'].show = !is_complete;
        if(is_complete) {
            dialog.widgets['mentor_send_gift_button'].state = mentor.is_giftable() ? 'normal' : 'disabled';
            dialog.widgets['mentor_send_gift_button'].onclick = (function (_mentor) { return function(w) {
                GameArt.play_canned_sound('harvest_sound');
                send_to_server.func(["SEND_GIFTS_BH", [_mentor.user_id]]);
                var dialog = w.parent;
                BHInvites.send_gift_effects(dialog, _mentor.user_id);
            }; })(mentor);
        } else {
            dialog.widgets['mentor_friend_status'].set_text_with_linebreaking(dialog.data['widgets']['mentor_friend_status']['ui_name'].replace('%s', dialog.parent.user_data['ui_complete_pred']));

        }
    } else {
        dialog.widgets['mentor_friend_icon'].show =
            dialog.widgets['mentor_friend_status'].show =
            dialog.widgets['mentor_send_gift_button'].show =
            dialog.widgets['your_mentor_label'].show = false;
    }
    dialog.user_data['mentor'] = mentor;

    dialog.widgets['send_all_button'].state = (dialog.user_data['n_giftable'] >= 1 ? 'normal' : 'disabled');
    dialog.widgets['send_all_button'].onclick = function(w) {
        w.state = 'disabled';
        var dialog = w.parent;
        var id_list = [];
        if(dialog.user_data['mentor'] && dialog.user_data['mentor'].is_giftable()) {
            id_list.push(dialog.user_data['mentor'].user_id);
        }
        goog.array.forEach(dialog.user_data['rowdata'], function(friend) {
            if(friend.is_giftable()) {
                id_list.push(friend.user_id);
            }
        });
        GameArt.play_canned_sound('harvest_sound');
        send_to_server.func(["SEND_GIFTS_BH", id_list]);
        goog.array.forEach(id_list, function(id) { BHInvites.send_gift_effects(dialog, id); });
    };
    dialog.user_data['page'] = -1;
    dialog.user_data['rows_per_page'] = dialog.data['widgets']['friend_icon']['array'][1];
    dialog.user_data['cols_per_page'] = dialog.data['widgets']['friend_icon']['array'][0];
    dialog.user_data['rowdata'] = trainee_list;
    dialog.user_data['rowfunc'] = BHInvites.trainee_rowfunc;
    scrollable_dialog_change_page(dialog, dialog.user_data['page']);
};

BHInvites.trainee_rowfunc = function(dialog, row_coord, rowdata) {
    var row = SPUI.get_array_widget_name('', dialog.data['widgets']['friend_icon']['array'], row_coord);
    if(rowdata !== null) {
        dialog.widgets['friend_icon'+row].set_user(rowdata.user_id);
        dialog.widgets['friend_icon'+row].state = (rowdata.is_giftable() && is_complete ? 'normal' : 'disabled');
        var is_complete = rowdata.is_bh_invite_complete();
        dialog.widgets['send_gift_button'+row].show = is_complete;
        dialog.widgets['friend_status'+row].show = !is_complete;
        if(is_complete) {
            dialog.widgets['send_gift_button'+row].state = rowdata.is_giftable() ? 'normal' : 'disabled';
            dialog.widgets['friend_icon'+row].onclick =
                dialog.widgets['send_gift_button'+row].onclick = (function (_friend) { return function(w) {
                    GameArt.play_canned_sound('harvest_sound');
                    send_to_server.func(["SEND_GIFTS_BH", [_friend.user_id]]);
                    BHInvites.send_gift_effects(w.parent, _friend.user_id);
                }; })(rowdata);
        } else {
            dialog.widgets['friend_status'+row].set_text_with_linebreaking(dialog.data['widgets']['friend_status']['ui_name'].replace('%s', dialog.parent.user_data['ui_complete_pred']));
        }
    } else {
        dialog.widgets['friend_icon'+row].set_user(null);
        dialog.widgets['friend_icon'+row].state = 'disabled';
        dialog.widgets['send_gift_button'+row].show =
            dialog.widgets['friend_status'+row].show = false;
    }
};

/** after transmittin SEND_GIFTS_BH to server, fire cooldowns, adjust widgets, etc */
BHInvites.send_gift_effects = function(dialog, user_id) {
    player.cooldown_client_trigger('send_gift:'+user_id.toString(), gamedata['gift_interval']);

    var friend = goog.array.find(player.friends, function(friend) { return friend.user_id === user_id; });
    if(!friend) { return; };

    var widget = null;
    if(friend.is_mentor()) {
        widget = dialog.widgets['mentor_friend_icon'];
        dialog.widgets['mentor_send_gift_button'].state = 'disabled';
    } else {
        var row_coord = scrollable_dialog_find_row(dialog, friend);
        if(row_coord === null) { return; }
        var row = SPUI.get_array_widget_name('', dialog.data['widgets']['friend_icon']['array'], row_coord);
        widget = dialog.widgets['friend_icon'+row];
        dialog.widgets['send_gift_button'+row].state = 'disabled';
    }
    widget.state = 'disabled';
    dialog.user_data['n_giftable'] -= 1;
    if(dialog.user_data['n_giftable'] <= 0) {
        dialog.widgets['send_all_button'].state = 'disabled';
    }

    var str = gamedata['strings']['combat_messages']['gift_sent'];
    ItemDisplay.add_inventory_item_effect(session.get_draw_world().fxworld, widget, str, [1,1,1,1]);
};

/** Server confirmed gift sending is complete */
BHInvites.gifts_complete = function(dialog, id_list) {
    // not actually used, since we client-side predict the sending
};

/** Parse the bh_invite_mentor_onetime loot table to find the highest trainee count that gives a reward
    @return {number} */
BHInvites.get_max_trainee_num = function() {
    var max_num = 1;
    var multi_array = gamedata['loot_tables_client']['bh_invite_mentor_onetime']['loot'][0]['multi'];
    goog.array.forEach(multi_array, function(maybe_cond) {
        if(typeof(maybe_cond) === 'object' && 'cond' in maybe_cond) {
            var cond_pairs = maybe_cond['cond'];
            goog.array.forEach(cond_pairs, function(pair) {
                var pred = pair[0];
                if(pred['predicate'] === 'PLAYER_HISTORY' && pred['key'] === 'bh_invite_trainee_count' &&
                   pred['method'] === '==') {
                    max_num = Math.max(max_num, pred['value']+1);
                }
            });
        }
    });
    return max_num;
};
/** @param {number} n - starts counting from 1 for first trainee recruited
    @return {number} next trainee number at which there is a special reward*/
BHInvites.get_next_trainee_breakpoint = function(n) {
    var ret = -1;
    var multi_array = gamedata['loot_tables_client']['bh_invite_mentor_onetime']['loot'][0]['multi'];
    goog.array.forEach(multi_array, function(maybe_cond) {
        if(ret > 0) { return; }
        if(typeof(maybe_cond) === 'object' && 'cond' in maybe_cond) {
            var cond_pairs = maybe_cond['cond'];
            goog.array.forEach(cond_pairs, function(pair) {
                if(ret > 0) { return; }
                var pred = pair[0];
                if(pred['predicate'] === 'PLAYER_HISTORY' && pred['key'] === 'bh_invite_trainee_count' &&
                   pred['method'] === '==') {
                    if(pred['value']+1 > n) {
                        ret = pred['value']+1;
                    }
                }
            });
        }
    });
    return ret;
};

/** @param {number} n - starts counting from 1 for first trainee recruited */
BHInvites.get_nth_trainee_rewards = function(n) {
    var ret = LootTable.get_loot(gamedata['loot_tables_client'],
                       gamedata['loot_tables_client']['bh_invite_mentor_onetime']['loot'],
                       function(pred) {
                           // override trainee count check
                           if(pred['predicate'] === 'PLAYER_HISTORY' && pred['key'] === 'bh_invite_trainee_count' &&
                              pred['method'] === '==') {
                               return n == pred['value']+1;
                           }
                           return read_predicate(pred).is_satisfied(player, null);
                       }).item_list;
    return ret;
};
