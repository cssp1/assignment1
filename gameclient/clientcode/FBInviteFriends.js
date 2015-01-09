goog.provide('FBInviteFriends');

// Copyright (c) 2014 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// Facebook Friend Invite Dialog

// this references a ton of stuff from main.js. It's not a self-contained module.

goog.require('SPUI');
goog.require('SPFB');
goog.require('PortraitCache');

// note: assumes player already has user_friends permission on the app
FBInviteFriends.invoke_fb_invite_friends_dialog = function(reason) {
    // I *think* the controlling part of the API for this is actually the oauth login API, but not 100% sure.
    if(SPFB.api_version_number('oauth') >= 2.0) {
        return FBInviteFriends.invoke_fb_invite_friends_dialog_v2(reason);
    } else {
        return FBInviteFriends.invoke_fb_invite_friends_dialog_v1(reason);
    }
};

// legacy Facebook-provided invite dialog
FBInviteFriends.invoke_fb_invite_friends_dialog_v1 = function(reason) {
    var viral = gamedata['virals']['invite_friends'];
    var attempt_id = make_unique_id();
    var props = player.get_denormalized_summary_props('brief');

    metric_event('7103_invite_friends_fb_prompt',
                 {'api': 'apprequests:friend_invite', 'api_version': 1, 'attempt_id': attempt_id, 'method': reason,
                  'sum': player.get_denormalized_summary_props('brief')});

    var cb = (function (_attempt_id, _reason) { return function(response) {
        if(!response || !response['request']) {
            // user cancelled
            metric_event('7105_invite_friends_fb_fail', {'api': 'apprequests:friend_invite', 'api_version': 1, 'attempt_id': _attempt_id,
                                                         'method': _reason,
                                                         'message': (response && response['error_message'] ? response['error_message'] : 'unknown'),
                                                         'sum': player.get_denormalized_summary_props('brief')});
        } else {
            var request_id = response['request'];
            metric_event('7104_invite_friends_fb_success', {'api': 'apprequests:friend_invite', 'api_version': 1, 'attempt_id': _attempt_id,
                                                            'method': _reason,
                                                            'request_id': response['request'], 'batch':(response['to'] ? response['to'].length : 0),
                                                            'sum': player.get_denormalized_summary_props('brief')});
        }
        return true;
    }; })(attempt_id, reason);

    SPFB.ui({'method':'apprequests', // invite friends
             'message': viral['ui_post_message'],
             'filters':['app_non_users'],
             'data':'friend_invite',
             'title': viral['ui_title'],
             'show_error': !spin_secure_mode
            }, cb);
};

FBInviteFriends.FBInviteFriendsDialogV2 = {};

// new Invitable Friends Multi-Friend-Selector invite dialog
// see https://developers.facebook.com/docs/games/invitable-friends/v2.1
FBInviteFriends.invoke_fb_invite_friends_dialog_v2 = function(reason) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['fb_friend_selector']);
    dialog.user_data['dialog'] = 'fb_friend_selector';
    dialog.user_data['page'] = -1;
    dialog.user_data['rows_per_page'] = dialog.data['widgets']['portrait_raw']['array'][1];
    dialog.user_data['cols_per_page'] = dialog.data['widgets']['portrait_raw']['array'][0];
    dialog.user_data['rowdata'] = [];
    dialog.user_data['rowfunc'] = FBInviteFriends.FBInviteFriendsDialogV2.setup_row;
    dialog.user_data['reason'] = reason;
    dialog.user_data['attempt_id'] = make_unique_id();
    dialog.user_data['instant'] = player.get_any_abtest_value('fb_friend_invite_v2_instant', gamedata['fb_friend_invite_v2_instant']) || 0;
    dialog.user_data['invites'] = {}; // map from invitable_friend ID -> 1

    dialog.widgets['title'].str = dialog.data['widgets']['title']['ui_name_invite'];


    dialog.widgets['close_button'].onclick = close_parent_dialog;
    scrollable_dialog_change_page(dialog, 0);

    dialog.widgets['select_all'].state = 'disabled';
    dialog.widgets['send_button'].state = 'disabled';

    dialog.widgets['send_button'].onclick = function(w) {
        var dialog = w.parent;
        var invitees = goog.object.getKeys(dialog.user_data['invites']);

        GameArt.assets["success_playful_22"].states['normal'].audio.play(client_time);
        close_parent_dialog(w);

        var batches = [];
        // partition invitees into batches of <= 50 for FB API calls
        var batch = [];
        for(var i = 0; i < invitees.length; i++) {
            batch.push(invitees[i]);
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
            metric_event((_dialog.user_data['instant'] ? '7103_invite_friends_fb_prompt' : '7102_invite_friends_ingame_fb_prompt'),
                         {'api': 'apprequests', 'api_version': 2, 'attempt_id': _dialog.user_data['attempt_id'], 'method': _dialog.user_data['reason'], 'batch': _batches[batch_num].length,
                          'sum': player.get_denormalized_summary_props('brief')});
            var viral = gamedata['virals']['invite_friends'];
            var params = {'method':'apprequests',
                          'message': viral['ui_post_message'],
                          'to': to_string,
                          'show_error': !spin_secure_mode
                         };

            SPFB.ui(params, (function (__dialog, __batches, _batch_num, __do_send) { return function(response) {
                console.log("FBInviteFriends.FBInviteFriendsDialogV2 response");
                console.log(response);
                var do_next = true;
                if(response && response['request']) {
                    // success: {'request': 'NNNNNNN', 'to': ['IDIDIDIDID',...]}
                    metric_event('7104_invite_friends_fb_success', {'api':'apprequests', 'api_version': 2, 'attempt_id': __dialog.user_data['attempt_id'], 'method': __dialog.user_data['reason'],
                                                                    'request_id': response['request'].toString(), 'batch':(response['to'] ? response['to'].length : 0),
                                                                    'sum': player.get_denormalized_summary_props('brief')});

                    // links look like this: https://apps.facebook.com/tablettransform/?fb_source=notification&request_ids=269052739960978&ref=notif&app_request_type=user_to_user&notif_t=app_invite

                } else {
                    // cancel: {'error_code': 4201, 'error_message': 'User canceled the Dialog flow'}
                    metric_event('7105_invite_friends_fb_fail', {'api':'apprequests', 'api_version': 2, 'attempt_id': __dialog.user_data['attempt_id'], 'method': __dialog.user_data['reason'],
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
    FBInviteFriends.FBInviteFriendsDialogV2.update_send_button(dialog);

    if(reason != 'test') {
        SPFB.api('/me/invitable_friends', (function (_dialog) { return function(response) {
            FBInviteFriends.FBInviteFriendsDialogV2.receive_invitable_friends(_dialog, response);
        }; })(dialog));
    }
    if(!dialog.user_data['instant']) {
        metric_event('7101_invite_friends_ingame_prompt', {'api':'invitable_friends', 'api_version': 2, 'attempt_id': dialog.user_data['attempt_id'], 'method': reason, 'sum': player.get_denormalized_summary_props('brief')});
    }

    return dialog;
};

FBInviteFriends.test_fb_invite_friends_dialog_v2 = function(has_friends) {
    var dialog = FBInviteFriends.invoke_fb_invite_friends_dialog_v2('test');
    window.setTimeout((function (_dialog) { return function() {
        var props = {'data': []};
        if(has_friends) {
            for(var i = 0; i < 47; i++) {
                props['data'].push({'id': 'friend'+i.toString(), 'name': 'Test Friend '+i.toString(), 'picture': {'data': {'url': SPFB.versioned_graph_endpoint('user/picture', '20531316728/picture')}}});
            }
        }
        FBInviteFriends.FBInviteFriendsDialogV2.receive_invitable_friends(_dialog, props);
    }; })(dialog), 1000);
}

FBInviteFriends.FBInviteFriendsDialogV2.receive_invitable_friends = function(dialog, response) {
   if(!dialog.parent) { return; } // dialog was killed
    dialog.widgets['loading_rect'].show = dialog.widgets['loading_text'].show = dialog.widgets['loading_spinner'].show = false;

    if(!response || response['error'] || !response['data']) { throw Error('/me/invitable_friends returned invalid response'); }
    if(response['data'].length < 1) {
        // no friends to invite
        dialog.widgets['no_friends'].show = true;
        dialog.widgets['no_friends'].str = dialog.data['widgets']['no_friends']['ui_name_invite'];
    } else {
        dialog.widgets['separator0,0'].show = dialog.widgets['separator1,0'].show = true;
        dialog.widgets['scroll_text'].show = true;

        dialog.user_data['rowdata'] = response['data'].slice(0, 9999); // should there be a length limit?

        if(!dialog.user_data['instant']) { // sort alphabetically
            dialog.user_data['rowdata'].sort(function (a,b) {
                if(a['name'] < b['name']) {
                    return -1;
                } else if(a['name'] > b['name']) {
                    return 1;
                } else if(a['id'] < b['id']) {
                    return -1;
                } else if(a['id'] > b['id']) {
                    return 1;
                } else {
                    return 0;
                }
            });
        }

        dialog.widgets['select_all'].state = 'normal';
        dialog.widgets['select_all'].onclick = function(w) {
            var dialog = w.parent;
            if(w.state == 'active') {
                w.state = 'normal';
                goog.array.forEach(dialog.user_data['rowdata'], function(rowdata) {
                    if(rowdata['id'] in dialog.user_data['invites']) { delete dialog.user_data['invites'][rowdata['id']]; }
                });
            } else {
                w.state = 'active';
                goog.array.forEach(dialog.user_data['rowdata'], function(rowdata) {
                    dialog.user_data['invites'][rowdata['id']] = 1;
                });
            }
            scrollable_dialog_change_page(dialog, dialog.user_data['page']);
            FBInviteFriends.FBInviteFriendsDialogV2.update_send_button(dialog);
        }
    }

    scrollable_dialog_change_page(dialog, 0);

    // do what Throne Rush does and just immediately go with the first 50 people!
    var instant = dialog.user_data['instant'];
    if(response['data'].length >= 1 && instant > 0) {
        for(var i = 0; i < Math.min(instant, response['data'].length); i++) {
            dialog.user_data['invites'][response['data'][i]['id']] = 1;
        }
        dialog.widgets['send_button'].onclick(dialog.widgets['send_button']);
    }
};

FBInviteFriends.FBInviteFriendsDialogV2.setup_row = function(dialog, row_col, rowdata) {
    var wname = row_col[0].toString()+','+row_col[1].toString();
    dialog.widgets['separator'+row_col[0].toString()+','+(row_col[1]+1).toString()].show =
        dialog.widgets['portrait_raw'+wname].show =
        dialog.widgets['portrait_outline'+wname].show =
        dialog.widgets['name'+wname].show =
        dialog.widgets['button'+wname].show = (rowdata !== null);

    if(rowdata !== null) {
        dialog.widgets['portrait_raw'+wname].raw_image = PortraitCache.get_raw_image(rowdata['picture']['data']['url']);
        dialog.widgets['name'+wname].str = rowdata['name'];
        dialog.widgets['button'+wname].state = (rowdata['id'] in dialog.user_data['invites'] ? 'active': 'normal');
        dialog.widgets['portrait_outline'+wname].outline_color = SPUI.make_colorv(dialog.data['widgets']['portrait_outline'][(rowdata['id'] in dialog.user_data['invites'] ? 'outline_color_active': 'outline_color')]);
        dialog.widgets['name'+wname].text_color = SPUI.make_colorv(dialog.data['widgets']['name'][(rowdata['id'] in dialog.user_data['invites'] ? 'text_color_active': 'text_color')]);

        dialog.widgets['button'+wname].onclick = (function (_row_col, _rowdata) { return function(w) {
            var dialog = w.parent;
            if(w.state == 'active') {
                w.state = 'normal';
                if(_rowdata['id'] in dialog.user_data['invites']) { delete dialog.user_data['invites'][_rowdata['id']]; }
            } else {
                w.state = 'active';
                dialog.user_data['invites'][_rowdata['id']] = 1;
            }
            FBInviteFriends.FBInviteFriendsDialogV2.setup_row(dialog, _row_col, _rowdata); // set portrait outline
            FBInviteFriends.FBInviteFriendsDialogV2.update_send_button(dialog);
        }; })(row_col, rowdata);
    }
};

FBInviteFriends.FBInviteFriendsDialogV2.update_send_button = function(dialog) {
    var count = goog.object.getCount(dialog.user_data['invites']);
    dialog.widgets['send_button'].state = (count > 0 ? 'normal' : 'disabled');
    dialog.widgets['send_button'].str = dialog.data['widgets']['send_button'][(count < 1 ? 'ui_name_invite' : (count == 1 ? 'ui_name_invite_one': 'ui_name_invite_many'))].replace('%d', pretty_print_number(count));
};
