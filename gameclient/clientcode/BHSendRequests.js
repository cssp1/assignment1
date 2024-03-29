goog.provide('BHSendRequests');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// Facebook Friend Request Dialog

// this references a ton of stuff from main.js. It's not a self-contained module.

goog.require('SPUI');
goog.require('PlayerCache');
goog.require('goog.array');
goog.require('goog.object');

 /** Multi-Friend-Selector request dialog
  * @param {(number|null)} to_user - user_id of a friend to auto-select (may be null)
  * @param {string} reason for metrics purposes
  * @param {(!Array.<Object>|null)=} info_list - list of PlayerCache entries for giftable friends (if null, we will query)
  */
BHSendRequests.invoke_send_gifts_dialog = function(to_user, reason, info_list) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['fb_friend_selector']);
    dialog.user_data['dialog'] = 'fb_friend_selector';
    dialog.user_data['page'] = -1;
    dialog.user_data['rows_per_page'] = dialog.data['widgets']['portrait_user']['array'][1];
    dialog.user_data['cols_per_page'] = dialog.data['widgets']['portrait_user']['array'][0];
    dialog.user_data['rowdata'] = []; // list of PlayerCache entries
    dialog.user_data['rowfunc'] = BHSendRequests.BHSendRequestsDialog.setup_row;
    dialog.user_data['reason'] = reason;
    dialog.user_data['attempt_id'] = make_unique_id();
    dialog.user_data['instant'] = player.get_any_abtest_value('send_gifts_instant', gamedata['send_gifts_instant']) || 0;
    dialog.user_data['recipients'] = {}; // map from user_ids -> 1
    dialog.user_data['preselect_user_id'] = to_user;

    dialog.widgets['title'].str = dialog.data['widgets']['title']['ui_name_gift'];
    dialog.widgets['recent_alliance_logins_only'].show = (gamedata['gift_alliancemates'] && session.is_in_alliance());

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
        var is_instant = dialog.user_data['instant'];
        var attempt_id = dialog.user_data['attempt_id'];
        var reason = dialog.user_data['reason'];

        GameArt.play_canned_sound('success_playful_22');
        close_parent_dialog(w);

        var recipient_user_ids = goog.array.map(goog.object.getKeys(recipients),
                                                // this returns strings, so coerce back to integers
                                                function(x) { return parseInt(x, 10); });
        if(recipient_user_ids.length > 0) {
            goog.array.forEach(recipient_user_ids, function(user_id) {
                player.cooldown_client_trigger('send_gift:'+user_id.toString(), gamedata['gift_interval']);
            });
            send_to_server.func(["SEND_GIFTS2", null, recipient_user_ids]);
            invoke_ui_locker();
        }
    };

    change_selection_ui(dialog);
    dialog.auto_center();
    dialog.modal = true;

    // note: "loading..." will be displayed now
    scrollable_dialog_change_page(dialog, 0);
    BHSendRequests.BHSendRequestsDialog.update_send_button(dialog);

    // query for potential recipients
    if(info_list !== null) {
        // immediate
        BHSendRequests.BHSendRequestsDialog.receive_giftable_friends(dialog, info_list);
    } else {
        // delayed

        // the loading text/spinner is redundant with the ui_locker that the async query is going to show
        dialog.widgets['loading_text'].show = dialog.widgets['loading_spinner'].show = false;

        player.get_giftable_friend_info_list_async((function (_dialog) { return function(ret) {
            BHSendRequests.BHSendRequestsDialog.receive_giftable_friends(_dialog, ret);
        }; })(dialog));
    }

    return dialog;
};

BHSendRequests.BHSendRequestsDialog = {};

/** Keep track of user IDs that have caused dialog failures, and don't retry them
    @type {Object.<string,number>} */
BHSendRequests.user_id_blacklist = {};

BHSendRequests.test_send_gifts_dialog = function(to_user) {
    return BHSendRequests.invoke_send_gifts_dialog(to_user, 'test', null);
};

// response is a list of PlayerCache info entries
BHSendRequests.BHSendRequestsDialog.receive_giftable_friends = function(dialog, response) {
    if(!dialog.parent) { return; } // dialog was killed
    dialog.widgets['loading_rect'].show = dialog.widgets['loading_text'].show = dialog.widgets['loading_spinner'].show = false;

    if(!response || response.length < 1) {
        // no friends to gift
        dialog.widgets['no_friends'].show = true;
        dialog.widgets['no_friends'].str = dialog.data['widgets']['no_friends']['ui_name_gift'];
    } else {
        dialog.widgets['separator0,0'].show = dialog.widgets['separator1,0'].show = true;
        dialog.widgets['scroll_text'].show = true;

        dialog.user_data['rowdata'] = response.slice(0, 9999); // should there be a length limit?

        if(!dialog.user_data['instant']) { // sort alphabetically
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
        }

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
            BHSendRequests.BHSendRequestsDialog.update_send_button(dialog);
        }
    }

    scrollable_dialog_change_page(dialog, 0);
    BHSendRequests.BHSendRequestsDialog.update_send_button(dialog);

    // do what Throne Rush does and just immediately go with the first 50 people!
    var instant = dialog.user_data['instant'];
    if(response && response.length >= 1 && instant >= 1) {
        for(var i = 0; i < Math.min(instant, response.length); i++) {
            dialog.user_data['recipients'][response[i]['user_id']] = 1;
        }
        dialog.widgets['send_button'].onclick(dialog.widgets['send_button']);
    }
};

BHSendRequests.BHSendRequestsDialog.setup_row = function(dialog, row_col, rowdata) {
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
            BHSendRequests.BHSendRequestsDialog.setup_row(dialog, _row_col, _rowdata); // set portrait outline
            BHSendRequests.BHSendRequestsDialog.update_send_button(dialog);
        }; })(row_col, rowdata);
    }
};

BHSendRequests.BHSendRequestsDialog.update_send_button = function(dialog) {
    var count = goog.object.getCount(dialog.user_data['recipients']);
    dialog.widgets['send_button'].state = (count > 0 ? 'normal' : 'disabled');
    dialog.widgets['send_button'].str = dialog.data['widgets']['send_button'][(count < 1 ? 'ui_name_gift' : (count == 1 ? 'ui_name_gift_one': 'ui_name_gift_many'))].replace('%d', pretty_print_number(count));
};

/** Invoke Facebook prompt to send a single request.
    @param {string} viral_name
    @param {string} viral_replace_s
    @param {number} to_user_id
    @param {string} to_facebook_id
    @param {function()} cb */
BHSendRequests.invoke_send_single_dialog = function(viral_name, viral_replace_s, to_user_id, to_facebook_id, cb) {
    var viral = gamedata['virals'][viral_name];
    if(!viral) { return; }

    // Facebook API wants a comma-separated list of the recipient Facebook IDs
    var to_string = to_facebook_id.toString();
    var attempt_id = make_unique_id();

    metric_event('4102_send_gifts_ingame_fb_prompt',
                 {'api': 'apprequests', 'api_version': 2, 'attempt_id': attempt_id, 'method': viral_name, 'batch': 1,
                  'sum': player.get_denormalized_summary_props('brief')});

    var params = {'method':'apprequests',
                  'message': viral['ui_post_message'].replace('%s', viral_replace_s),
                  'data': 'gift',
                  'title': viral['ui_title'],
                  'frictionlessRequests': true,
                  'to': to_string,
                  'show_error': (player.is_developer() || !spin_secure_mode)
                 };

    SPFB.ui(params, (function (_to_user_id, _attempt_id, _viral_name, _cb) { return function(response) {
        if(response && response['request'] && response['to']) {
            // success: {'request': 'NNNNNNN', 'to': ['IDIDIDIDID',...]}
            metric_event('4104_send_gifts_fb_success', {'api':'apprequests', 'api_version': 2, 'attempt_id': _attempt_id, 'method': _viral_name,
                                                        'request_id': response['request'].toString(), 'batch':(response['to'] ? response['to'].length : 0),
                                                        'sum': player.get_denormalized_summary_props('brief')});
            // success
            if(_cb) { _cb(); }
        } else {
            // cancel: {'error_code': 4201, 'error_message': 'User canceled the Dialog flow'}
            if(response && response['error_message'] && response['error_message'].indexOf('Can only send requests to friends') == 0) {
                BHSendRequests.user_id_blacklist[_to_user_id.toString()] = 1;
            } else {
                metric_event('4105_send_gifts_fb_fail', {'api':'apprequests', 'api_version': 2, 'attempt_id': _attempt_id, 'method': _viral_name,
                                                         'message': (response && response['error_message'] ? response['error_message'] : 'unknown'),
                                                         'sum': player.get_denormalized_summary_props('brief')});
            }
        }
    }; })(to_user_id, attempt_id, viral_name, cb));
};
