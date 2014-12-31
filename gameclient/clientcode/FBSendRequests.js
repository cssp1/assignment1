goog.provide('FBSendRequests');

// Copyright (c) 2014 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// Facebook Friend Request Dialog

// this references a ton of stuff from main.js. It's not a self-contained module.

goog.require('SPUI');
goog.require('SPFB');
goog.require('PortraitCache');

/** start the send-gift process (which uses the Facebook Requests API)
 * @param {(string|null)=} to_fbid Facebook ID of friend to auto-select (may be null)
 * @param {string=} reason for metrics purposes
 */
FBSendRequests.invoke_send_gifts_dialog = function(to_fbid, reason) {
    if((player.get_any_abtest_value('resource_gifts_fb_api_version', gamedata['resource_gifts_fb_api_version'] || 1) >= 2) &&
       SPFB.api_version_number('apprequests') >= 2.0) {
        return FBSendRequests.invoke_send_gifts_dialog_v2(to_fbid, reason);
    } else {
        return FBSendRequests.invoke_send_gifts_dialog_v1(to_fbid, reason);
    }
};

// legacy pure-Facebook-API reuest dialog
FBSendRequests.invoke_send_gifts_dialog_v1 = function(to_fbid, reason) {
    reason = reason || null; // get rid of undefined reasons
    var attempt_id = make_unique_id();
    var viral = gamedata['virals']['send_gifts'];

    to_fbid = null; // disable specific preselection since current Facebook API does not support it

    var cb = (function (_attempt_id, _reason) { return function(response) {
        var success = (response && !response['error_message']);
        var metric_props = {'api':'apprequests', 'api_version': 1,
                            'attempt_id': _attempt_id, 'method': _reason,
                            'sum': player.get_denormalized_summary_props('brief')};
        if(response && response['error_message']) { metric_props['message'] = response['error_message']; }
        if(response && response['to']) { metric_props['batch'] = response['to'].length; }

        metric_event((success ? '4104_send_gifts_fb_success' : '4105_send_gifts_fb_fail'), metric_props);

        if(!response || response['error_message']) {
            // user cancelled
        } else {
            var request_id = response['request'];
            var fb_id_list = response['to'];

            // mark recipients as non-giftable
            for(var f = 0; f < player.friends.length; f++) {
                var friend = player.friends[f];
                for(var i = 0; i < fb_id_list.length; i++) {
                    if(friend.get_facebook_id() == fb_id_list[i].toString()) {
                        player.cooldown_client_trigger('send_gift:'+friend.user_id.toString(), gamedata['gift_interval']);
                        break;
                    }
                }
            }

            send_to_server.func(["SEND_GIFTS", request_id, fb_id_list]);
        }
        return true;
    }; })(attempt_id, reason);

    var giftable_friends = goog.array.map(player.get_giftable_friend_info_list(), function(info) { return info['facebook_id']; });

    if(giftable_friends.length < 1) {
        var err = viral['ui_error_nofriends'];
        invoke_message_dialog(err['ui_title'], err['ui_description']);
        return;
    }

    var props = {};
    if(to_fbid) { props['recipient_fb_id'] = to_fbid; }

    metric_event('4103_send_gifts_fb_prompt',
                 {'api': 'apprequests', 'api_version': 1,
                  'attempt_id': attempt_id, 'method': reason,
                  'sum': player.get_denormalized_summary_props('brief')});

    var args = {'method':'apprequests',
                'message': viral['ui_post_message'],
                'action_type': viral['og_action_type'], 'object_id': viral['og_object_id'],
                'data':'gift',
                'title': viral['ui_title'],
                'frictionlessRequests': true,
                'show_error': !spin_secure_mode
               };
    if(to_fbid) {
        // specify one recipient
        args['to'] = to_fbid;
    } else {
        args['filters'] = [{'name': viral['ui_giftable_filter'], 'user_ids': giftable_friends}];
    }

    if(!spin_facebook_enabled) {
        console.log('invoke_send_gifts_dialog('+(to_fbid ? to_fbid : 'null')+')');
        cb({'request':'test', 'to':giftable_friends});
    } else {
        SPFB.ui(args, cb); // send gifts
    }
};

FBSendRequests.FBSendRequestsDialogV2 = {};

// new Multi-Friend-Selector request dialog
FBSendRequests.invoke_send_gifts_dialog_v2 = function(to_fbid, reason) {
    reason = reason || null; // get rid of undefined reasons

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
    dialog.user_data['preselect_fbid'] = to_fbid || null;

    dialog.widgets['title'].str = dialog.data['widgets']['title']['ui_name_gift'];

    dialog.widgets['close_button'].onclick = close_parent_dialog;
    scrollable_dialog_change_page(dialog, 0);

    dialog.widgets['select_all'].state = 'disabled';
    dialog.widgets['send_button'].state = 'disabled';

    dialog.widgets['send_button'].onclick = function(w) {
        var dialog = w.parent;
        var rowdata = dialog.user_data['rowdata'];

        var recip_fbids = []; // list of facebook IDs
        goog.object.forEach(dialog.user_data['recipients'], function(unused, user_id) {
            var info = goog.array.find(dialog.user_data['rowdata'], function(x) { return x['user_id'] == user_id; });
            recip_fbids.push(info['facebook_id']);
        });

        GameArt.assets["success_playful_22"].states['normal'].audio.play(client_time);
        close_parent_dialog(w);

        var batches = [];
        // partition recipients into batches of <= 50 for FB API calls
        var batch = [];
        for(var i = 0; i < recip_fbids.length; i++) {
            batch.push(recip_fbids[i]);
            if(batch.length >= 50) {
                batches.push(batch);
                batch = [];
            }
        }
        if(batch.length > 0) {
            batches.push(batch);
        }

        var do_send = function (_dialog, _batches, batch_num, _do_send) {
            var to_string = _batches[batch_num].join(',');
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
                console.log("FBSendRequests.FBSendRequestsDialogV2 response");
                console.log(response);
                var do_next = true;
                if(response && response['request']) {
                    // success: {'request': 'NNNNNNN', 'to': ['IDIDIDIDID',...]}
                    metric_event('4104_send_gifts_fb_success', {'api':'apprequests', 'api_version': 2, 'attempt_id': __dialog.user_data['attempt_id'], 'method': __dialog.user_data['reason'],
                                                                    'request_id': response['request'].toString(), 'batch':(response['to'] ? response['to'].length : 0),
                                                                    'sum': player.get_denormalized_summary_props('brief')});

                    if(response['to']) {
                        // mark friends as non-giftable
                        goog.array.forEach(response['to'], function(fbid) {
                            var friend = goog.array.find(player.friends, function(f) { return f.get_facebook_id() == fbid.toString(); });
                            if(friend) {
                                player.cooldown_client_trigger('send_gift:'+friend.user_id.toString(), gamedata['gift_interval']);
                            }
                        });
                        send_to_server.func(["SEND_GIFTS", response['request'].toString(), response['to']]);
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

FBSendRequests.test_send_gifts_dialog_v2 = function(to_fbid) {
    return FBSendRequests.invoke_send_gifts_dialog_v2(to_fbid, 'test');
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
                if(a['ui_name'] < b['ui_name']) {
                    return -1;
                } else if(a['ui_name'] > b['ui_name']) {
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
        if(dialog.user_data['preselect_fbid']) {
            preselect_info = goog.array.find(dialog.user_data['rowdata'],
                                             function(x) { return x['facebook_id'] == dialog.user_data['preselect_fbid']; });
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
