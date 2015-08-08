goog.provide('AGSendRequests');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// Armor Games Friend Request Dialog
// (doesn't use any platform features - this is just a bare-bones friend/alliancemante-sending dialog)

// this references a ton of stuff from main.js. It's not a self-contained module.

goog.require('SPUI');
goog.require('PlayerCache');
goog.require('goog.array');
goog.require('goog.object');

/** Multi-Friend-Selector request dialog
 * @param {(number|null)} to_user - user_id of a friend to auto-select (may be null)
 * @param {string} reason for metrics purposes
 * @param {(!Array.<Object>|null)} info_list - list of PlayerCache entries for giftable friends (if null, we will query)
 */
AGSendRequests.invoke_send_gifts_dialog = function(to_user, reason, info_list) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['fb_friend_selector']);
    dialog.user_data['dialog'] = 'fb_friend_selector';
    dialog.user_data['page'] = -1;
    dialog.user_data['rows_per_page'] = dialog.data['widgets']['portrait_user']['array'][1];
    dialog.user_data['cols_per_page'] = dialog.data['widgets']['portrait_user']['array'][0];
    dialog.user_data['rowdata'] = []; // list of PlayerCache entries
    dialog.user_data['rowfunc'] = AGSendRequests.setup_row;
    dialog.user_data['reason'] = reason;
    dialog.user_data['attempt_id'] = make_unique_id();
    dialog.user_data['recipients'] = {}; // map from user_ids -> 1
    dialog.user_data['preselect_user_id'] = to_user;

    dialog.widgets['title'].str = dialog.data['widgets']['title']['ui_name_gift'];

    dialog.widgets['close_button'].onclick = close_parent_dialog;
    scrollable_dialog_change_page(dialog, 0);

    dialog.widgets['select_all'].state = 'disabled';
    dialog.widgets['send_button'].state = 'disabled';

    dialog.widgets['send_button'].onclick = function(w) {
        var dialog = w.parent;

        if(!dialog) { throw Error('no dialog!'); }
        if(!dialog.user_data['recipients'] || !goog.object.getCount(dialog.user_data['recipients'])) {
            throw Error('no recipients! rowdata '+dialog.user_data['rowdata'].length);
        }

        // grab stuff out of user_data since it is going to disappear
        var recipients = dialog.user_data['recipients'];
        var rowdata = dialog.user_data['rowdata'];
        var attempt_id = dialog.user_data['attempt_id'];
        var reason = dialog.user_data['reason'];

        GameArt.assets["success_playful_22"].states['normal'].audio.play(client_time);
        close_parent_dialog(w);

        var recipient_user_ids = goog.array.map(goog.object.getKeys(recipients),
                                                // this returns strings, so coerce back to integers
                                                function(x) { return parseInt(x, 10); });

        // for NON-Facebook recipients, send gifts immediately via the game server

        // get list of non-Facebook recipient user IDs
        var non_facebook_recipients = goog.array.filter(recipient_user_ids, function(user_id) {
            var info = goog.array.find(rowdata, function(x) { return x['user_id'] == user_id; });
            return !(info['facebook_id']);
        });

        if(non_facebook_recipients.length > 0) {
            goog.array.forEach(non_facebook_recipients, function(user_id) {
                player.cooldown_client_trigger('send_gift:'+user_id.toString(), gamedata['gift_interval']);
            });
            send_to_server.func(["SEND_GIFTS2", null, non_facebook_recipients]);
            invoke_ui_locker();
        }
    };

    change_selection_ui(dialog);
    dialog.auto_center();
    dialog.modal = true;

    // note: "loading..." will be displayed now
    scrollable_dialog_change_page(dialog, 0);
    AGSendRequests.update_send_button(dialog);

    metric_event('4101_send_gifts_ingame_prompt', {'api':'ag',
                                                   'attempt_id': dialog.user_data['attempt_id'],
                                                   'method': reason,
                                                   'sum': player.get_denormalized_summary_props('brief')});

    // query for potential recipients
    if(info_list !== null) {
        // immediate
        AGSendRequests.receive_giftable_friends(dialog, info_list);
    } else {
        // delayed

        // the loading text/spinner is redundant with the ui_locker that the async query is going to show
        dialog.widgets['loading_text'].show = dialog.widgets['loading_spinner'].show = false;

        player.get_giftable_friend_info_list_async((function (_dialog) { return function(ret) {
            AGSendRequests.receive_giftable_friends(_dialog, ret);
        }; })(dialog));
    }

    return dialog;
};

// response is a list of PlayerCache info entries
AGSendRequests.receive_giftable_friends = function(dialog, response) {
    if(!dialog.parent) { return; } // dialog was killed
    dialog.widgets['loading_rect'].show = dialog.widgets['loading_text'].show = dialog.widgets['loading_spinner'].show = false;

    if(response.length < 1) {
        // no friends to gift
        dialog.widgets['no_friends'].show = true;
        dialog.widgets['no_friends'].str = dialog.data['widgets']['no_friends']['ui_name_gift'];
    } else {
        dialog.widgets['separator0,0'].show = dialog.widgets['separator1,0'].show = true;
        dialog.widgets['scroll_text'].show = true;

        dialog.user_data['rowdata'] = response.slice(0, 9999); // should there be a length limit?

        // sort alphabetically
        dialog.user_data['rowdata'].sort(function (a,b) {
            var aname = PlayerCache.get_ui_name(a), bname = PlayerCache.get_ui_name(b);
            if(aname < bname) {
                return -1;
            } else if(aname > bname) {
                return 1;
            } else if(a['user_id'] < b['user_id']) {
                return -1;
            } else if(a['user_id'] > b['user_id']) {
                return 1;
            } else {
                return 0;
            }
        });

        var preselect_info = null;
        if(dialog.user_data['preselect_user_id']) {
            preselect_info = goog.array.find(dialog.user_data['rowdata'],
                                             function(x) { return x['user_id'] == dialog.user_data['preselect_user_id']; });
        }
        if(preselect_info) {
            dialog.user_data['recipients'][preselect_info['user_id']] = 1;
        }

        dialog.widgets['select_all'].state = (goog.object.getCount(dialog.user_data['recipients']) >= dialog.user_data['rowdata'].length ? 'active' : 'normal');
        dialog.widgets['select_all'].onclick = function(w) {
            var dialog = w.parent;
            if(w.state == 'active') {
                w.state = 'normal';
                goog.array.forEach(dialog.user_data['rowdata'], function(rowdata) {
                    if(rowdata['user_id'] in dialog.user_data['recipients']) { delete dialog.user_data['recipients'][rowdata['user_id']]; }
                });
            } else {
                w.state = 'active';
                goog.array.forEach(dialog.user_data['rowdata'], function(rowdata) {
                    dialog.user_data['recipients'][rowdata['user_id']] = 1;
                });
            }
            scrollable_dialog_change_page(dialog, dialog.user_data['page']);
            AGSendRequests.update_send_button(dialog);
        }
    }

    scrollable_dialog_change_page(dialog, 0);
    AGSendRequests.update_send_button(dialog);
};

AGSendRequests.setup_row = function(dialog, row_col, rowdata) {
    var wname = row_col[0].toString()+','+row_col[1].toString();
    dialog.widgets['separator'+row_col[0].toString()+','+(row_col[1]+1).toString()].show =
        dialog.widgets['portrait_user'+wname].show =
        dialog.widgets['portrait_outline'+wname].show =
        dialog.widgets['name'+wname].show =
        dialog.widgets['button'+wname].show = (rowdata !== null);

    if(rowdata !== null) {
        var user_id = rowdata['user_id'];
        var info = rowdata;
        dialog.widgets['portrait_user'+wname].set_user(user_id);
        dialog.widgets['name'+wname].str = PlayerCache.get_ui_name(info);
        dialog.widgets['button'+wname].state = (user_id in dialog.user_data['recipients'] ? 'active': 'normal');
        dialog.widgets['portrait_outline'+wname].outline_color = SPUI.make_colorv(dialog.data['widgets']['portrait_outline'][user_id in dialog.user_data['recipients'] ? 'outline_color_active': 'outline_color']);
        dialog.widgets['name'+wname].text_color = SPUI.make_colorv(dialog.data['widgets']['name'][user_id in dialog.user_data['recipients'] ? 'text_color_active': 'text_color']);

        dialog.widgets['button'+wname].onclick = (function (_row_col, _rowdata) { return function(w) {
            var dialog = w.parent;
            var _user_id = _rowdata['user_id'];
            if(w.state == 'active') {
                w.state = 'normal';
                if(_user_id in dialog.user_data['recipients']) { delete dialog.user_data['recipients'][_user_id]; }
            } else {
                w.state = 'active';
                dialog.user_data['recipients'][_user_id] = 1;
            }
            AGSendRequests.setup_row(dialog, _row_col, _rowdata); // set portrait outline
            AGSendRequests.update_send_button(dialog);
        }; })(row_col, rowdata);
    }
};

AGSendRequests.update_send_button = function(dialog) {
    var count = goog.object.getCount(dialog.user_data['recipients']);
    dialog.widgets['send_button'].state = (count > 0 ? 'normal' : 'disabled');
    dialog.widgets['send_button'].str = dialog.data['widgets']['send_button'][(count < 1 ? 'ui_name_gift' : (count == 1 ? 'ui_name_gift_one': 'ui_name_gift_many'))].replace('%d', pretty_print_number(count));
};

