goog.provide('FBSendRequests');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// Facebook Friend Request Dialog

// this references a ton of stuff from main.js. It's not a self-contained module.

goog.require('SPUI');
goog.require('SPFB');
goog.require('PortraitCache');
goog.require('goog.object');

/** Start the send-gift process (which uses the Facebook Requests API)
 * @param {(number|null)} to_user - user_id of a friend to auto-select (may be null)
 * @param {string} reason for metrics purposes
 */
FBSendRequests.invoke_send_gifts_dialog = function(to_user, reason) {
    if(SPFB.api_version_number('apprequests') < 2.0) {
        throw Error('apprequests API must be v2.0+');
    }
    return FBSendRequests.invoke_send_gifts_dialog_v2(to_user, reason);
};

FBSendRequests.FBSendRequestsDialogV2 = {};

/** Multi-Friend-Selector request dialog
 * @param {(number|null)} to_user - user_id of a friend to auto-select (may be null)
 * @param {string} reason for metrics purposes
 */
FBSendRequests.invoke_send_gifts_dialog_v2 = function(to_user, reason) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['fb_friend_selector']);
    dialog.user_data['dialog'] = 'fb_friend_selector';
    dialog.user_data['page'] = -1;
    dialog.user_data['rows_per_page'] = dialog.data['widgets']['portrait_user']['array'][1];
    dialog.user_data['cols_per_page'] = dialog.data['widgets']['portrait_user']['array'][0];
    dialog.user_data['rowdata'] = []; // list of PlayerCache entries
    dialog.user_data['rowfunc'] = FBSendRequests.FBSendRequestsDialogV2.setup_row;
    dialog.user_data['reason'] = reason;
    dialog.user_data['attempt_id'] = make_unique_id();
    dialog.user_data['instant'] = player.get_any_abtest_value('fb_send_gifts_v2_instant', gamedata['fb_send_gifts_v2_instant']) || 0;
    dialog.user_data['recipients'] = {}; // map from user_ids -> 1
    dialog.user_data['preselect_user_id'] = to_user;

    dialog.widgets['title'].str = dialog.data['widgets']['title']['ui_name_gift'];

    dialog.widgets['close_button'].onclick = close_parent_dialog;
    scrollable_dialog_change_page(dialog, 0);

    dialog.widgets['select_all'].state = 'disabled';
    dialog.widgets['send_button'].state = 'disabled';

    dialog.widgets['send_button'].onclick = function(w) {
        var dialog = w.parent;
        var rowdata = dialog.user_data['rowdata'];

        var recipient_user_ids = goog.array.map(goog.object.getKeys(dialog.user_data['recipients']),
                                                // this returns strings, so coerce back to integers
                                                function(x) { return parseInt(x, 10); });

        // for NON-Facebook recipients, send gifts immediately via the game server

        // get list of non-Facebook recipient user IDs
        var non_facebook_recipients = goog.array.filter(recipient_user_ids, function(user_id) {
            var info = goog.array.find(dialog.user_data['rowdata'], function(x) { return x['user_id'] == user_id; });
            return !(info['facebook_id']);
        });

        if(non_facebook_recipients.length > 0) {
            goog.array.forEach(non_facebook_recipients, function(user_id) {
                player.cooldown_client_trigger('send_gift:'+user_id.toString(), gamedata['gift_interval']);
            });
            send_to_server.func(["SEND_GIFTS2", null, non_facebook_recipients]);
        }

        // for Facebook receipients, we have to break into batches of 50 and then invoke the Facebook API

        // get list of {facebook_id:'0000', user_id:1234} for Facebook recipients
        var fb_recipients = goog.array.filter(
            // convert user_ids to Facebook IDs (or null)
            goog.array.map(recipient_user_ids, function(user_id) {
                var info = goog.array.find(dialog.user_data['rowdata'], function(x) { return x['user_id'] == user_id; });
                if(info['facebook_id']) {
                    return {facebook_id: info['facebook_id'], user_id: user_id};
                }
                return null;
            }),
            // filter out nulls
            function (data) { return data !== null; });

        GameArt.assets["success_playful_22"].states['normal'].audio.play(client_time);
        close_parent_dialog(w);

        var batches = [];
        // partition recipients into batches of <= 50 for FB API calls
        var batch = [];
        goog.array.forEach(fb_recipients, function(r) {
            batch.push(r);
            if(batch.length >= 50) {
                batches.push(batch);
                batch = [];
            }
        });
        if(batch.length > 0) {
            batches.push(batch);
        }

        var do_send = function (_dialog, _batches, batch_num, _do_send) {
            // Facebook API wants a comma-separated list of the recipient Facebook IDs
            var to_string = goog.array.map(_batches[batch_num], function(r) { return r.facebook_id; }).join(',');

            metric_event((_dialog.user_data['instant'] ? '4103_send_gifts_fb_prompt' : '4102_send_gifts_ingame_fb_prompt'),
                         {'api': 'apprequests', 'api_version': 2, 'attempt_id': _dialog.user_data['attempt_id'], 'method': _dialog.user_data['reason'], 'batch': _batches[batch_num].length,
                          'sum': player.get_denormalized_summary_props('brief')});
            var viral = gamedata['virals']['send_gifts'];
            var params = {'method':'apprequests',
                          'message': viral['ui_post_message'],
                          'action_type': viral['og_action_type'], 'object_id': viral['og_object_id'],
                          'data': 'gift',
                          'title': viral['ui_title'],
                          'frictionlessRequests': true,
                          'to': to_string,
                          'show_error': !spin_secure_mode
                         };

            SPFB.ui(params, (function (__dialog, __batches, _batch_num, __do_send) { return function(response) {
                //console.log("FBSendRequests.FBSendRequestsDialogV2 response"); console.log(response);
                var do_next = true;
                if(response && response['request']) {
                    // success: {'request': 'NNNNNNN', 'to': ['IDIDIDIDID',...]}
                    metric_event('4104_send_gifts_fb_success', {'api':'apprequests', 'api_version': 2, 'attempt_id': __dialog.user_data['attempt_id'], 'method': __dialog.user_data['reason'],
                                                                    'request_id': response['request'].toString(), 'batch':(response['to'] ? response['to'].length : 0),
                                                                    'sum': player.get_denormalized_summary_props('brief')});

                    if(response['to']) {
                        // send gifts to this subset
                        var user_id_list = [];
                        goog.array.forEach(response['to'], function(fbid) {
                            var user_id = goog.array.find(__batches[_batch_num], function(r) { return r.facebook_id.toString() == fbid.toString(); }).user_id;
                            user_id_list.push(user_id);
                            player.cooldown_client_trigger('send_gift:'+user_id.toString(), gamedata['gift_interval']);
                        });

                        send_to_server.func(["SEND_GIFTS2", response['request'].toString(), user_id_list]);
                    }
                } else {
                    // cancel: {'error_code': 4201, 'error_message': 'User canceled the Dialog flow'}
                    metric_event('4105_send_gifts_fb_fail', {'api':'apprequests', 'api_version': 2, 'attempt_id': __dialog.user_data['attempt_id'], 'method': __dialog.user_data['reason'],
                                                                 'message': (response && response['error_message'] ? response['error_message'] : 'unknown'),
                                                                 'sum': player.get_denormalized_summary_props('brief')});
                    do_next = false; // after one cancel, cancel all the rest
                }

                if(_batch_num+1 < __batches.length && do_next) {
                    __do_send(__dialog, __batches, _batch_num+1, __do_send);
                }
            }; })(_dialog, _batches, batch_num, _do_send));
        };

        do_send(dialog, batches, 0, do_send);
    };

    change_selection_ui(dialog);
    dialog.auto_center();
    dialog.modal = true;

    // note: "loading..." will be displayed now
    scrollable_dialog_change_page(dialog, 0);
    FBSendRequests.FBSendRequestsDialogV2.update_send_button(dialog);

    if(!dialog.user_data['instant']) {
        metric_event('4101_send_gifts_ingame_prompt', {'api':'apprequests', 'api_version': 2,
                                                       'attempt_id': dialog.user_data['attempt_id'],
                                                       'method': reason,
                                                       'sum': player.get_denormalized_summary_props('brief')});
    }
    FBSendRequests.FBSendRequestsDialogV2.receive_giftable_friends(dialog, player.get_giftable_friend_info_list());
    return dialog;
};

FBSendRequests.test_send_gifts_dialog_v2 = function(to_user) {
    return FBSendRequests.invoke_send_gifts_dialog_v2(to_user, 'test');
};

// response is a list of PlayerCache info entries
FBSendRequests.FBSendRequestsDialogV2.receive_giftable_friends = function(dialog, response) {
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
            FBSendRequests.FBSendRequestsDialogV2.update_send_button(dialog);
        }
    }

    scrollable_dialog_change_page(dialog, 0);
    FBSendRequests.FBSendRequestsDialogV2.update_send_button(dialog);

    // do what Throne Rush does and just immediately go with the first 50 people!
    var instant = dialog.user_data['instant'];
    if(response.length && instant > 0) {
        for(var i = 0; i < Math.min(instant, response.length); i++) {
            dialog.user_data['recipients'][response[i]['user_id']] = 1;
        }
        dialog.widgets['send_button'].onclick(dialog.widgets['send_button']);
    }
};

FBSendRequests.FBSendRequestsDialogV2.setup_row = function(dialog, row_col, rowdata) {
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
            FBSendRequests.FBSendRequestsDialogV2.setup_row(dialog, _row_col, _rowdata); // set portrait outline
            FBSendRequests.FBSendRequestsDialogV2.update_send_button(dialog);
        }; })(row_col, rowdata);
    }
};

FBSendRequests.FBSendRequestsDialogV2.update_send_button = function(dialog) {
    var count = goog.object.getCount(dialog.user_data['recipients']);
    dialog.widgets['send_button'].state = (count > 0 ? 'normal' : 'disabled');
    dialog.widgets['send_button'].str = dialog.data['widgets']['send_button'][(count < 1 ? 'ui_name_gift' : (count == 1 ? 'ui_name_gift_one': 'ui_name_gift_many'))].replace('%d', pretty_print_number(count));
};
