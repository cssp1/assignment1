goog.provide('LoginIncentiveDialog');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    GUI dialog for the login incentive system.
    tightly coupled to main.js, sorry!
*/

goog.require('SPUI');
goog.require('SPFX');

/** @return {SPUI.Dialog|null} */
LoginIncentiveDialog.invoke = function() {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['login_incentive_dialog']);
    dialog.user_data['dialog'] = 'login_incentive_dialog';
    dialog.user_data['pending'] = false;
    dialog.user_data['sync_marker'] = null;
    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;
    dialog.widgets['close_button'].onclick = close_parent_dialog;
    dialog.widgets['claim_button'].onclick = function(w) {
        var dialog = w.parent;
        send_to_server.func(["LOGIN_INCENTIVE_CLAIM"]);
        dialog.user_data['pending'] = true;
        dialog.user_data['sync_marker'] = synchronizer.request_sync();
    };
    dialog.ondraw = LoginIncentiveDialog.update;
    return dialog;
};

/** @param {!SPUI.Dialog} dialog */
LoginIncentiveDialog.update = function(dialog) {
    if(dialog.user_data['sync_marker'] !== null &&
       synchronizer.is_in_sync(dialog.user_data['sync_marker'])) {
        dialog.user_data['pending'] = false;
        dialog.user_data['sync_marker'] = null;
    }

    var ready_aura = goog.array.find(player.player_auras, function(a) {
        return (a['spec'] == 'login_incentive_ready') &&
            (server_time >= a['start_time']) && (server_time < a['end_time']);
        });
    var next_aura = goog.array.find(player.player_auras, function(a) {
        return (a['spec'] == 'login_incentive_next') &&
            (server_time >= a['start_time']) && (server_time < a['end_time']);
        });
    if(!ready_aura && !next_aura) {
        // strange, no auras...
        close_dialog(dialog);
        return;
    }

    // 1-based index of the reward we are going to get next
    var cur_stack = (ready_aura ? (ready_aura['stack']||1) : (next_aura['stack']||1));

    // calculate the time at which we began the current streak
    // (beginning of UTC day when first aura was granted)
    var t_origin;
    if(ready_aura) {
        t_origin = ready_aura['start_time'] - (cur_stack-1)*86400;
    } else {
        t_origin = next_aura['start_time'] - (cur_stack-2)*86400;
    }
    t_origin = 86400 * Math.floor(t_origin / 86400.0);

    for(var i = 0; i < dialog.data['widgets']['rewards']['array'][0]; i++) {
        var r = dialog.widgets['rewards'+i.toString()];
        r.widgets['day'].str = r.data['widgets']['day']['ui_name']
            .replace('%stack', (i+1).toString());
        var color_mode = (i+1 == 7 ? 'day7' :
                          (i+1 < cur_stack ? 'claimed' :
                          ((ready_aura && (i+1 == cur_stack)) ? 'today' :
                           'future')));
        r.widgets['day'].text_color = SPUI.make_colorv(r.data['widgets']['day']['text_color_'+color_mode]);

        var d = new Date((t_origin + i*86400) * 1000);
        var ui_date = gamedata['strings']['months_short'][d.getUTCMonth()]+' '+d.getUTCDate().toString();
        var ui_day_of_week = gamedata['strings']['days_of_week_short'][d.getUTCDay()];
        r.widgets['label'].str = r.data['widgets']['label']['ui_name']
            .replace('%date', ui_date).replace('%dayofweek', ui_day_of_week);
        r.widgets['label'].text_color = SPUI.make_colorv(r.data['widgets']['label']['text_color_'+color_mode]);

        r.widgets['border'].outline_color = SPUI.make_colorv(r.data['widgets']['border']['outline_color_'+color_mode]);

        if(i+1 < cur_stack) {
            // already claimed
            ItemDisplay.display_item(r.widgets['item'], {'spec': 'login_incentive_already_claimed'},
                                     {glow:false,hide_tooltip:true});
        } else {
            // XXX hook this up to the loot table?
            var table = gamedata['loot_tables_client']['login_incentive_'+(i+1).toString()];
            if(!table) { throw Error('login_incentive loot table not found '+(i+1).toString()); }
            var show_item = null;
            var hide_tooltip = true;
            if('item_for_ui' in table) {
                show_item = table['item_for_ui'];
                hide_tooltip = false;
            } else {
                var item_list = session.get_loot_items(player, table['loot']).item_list;
                if(item_list.length < 1) { throw Error('got no items from login_incentive loot table '+(i+1).toString()); }
                show_item = item_list[0];
                hide_tooltip = false;
            }
            ItemDisplay.display_item(r.widgets['item'], show_item,
                                     {glow:(i+1 == cur_stack),
                                      hide_tooltip:hide_tooltip,
                                      context_parent:dialog});
        }
    }

    if(ready_aura) {
        if(dialog.user_data['pending']) {
            dialog.widgets['claim_button'].state = 'disabled';
            dialog.widgets['claim_button'].str = dialog.data['widgets']['claim_button']['ui_name_pending'];
        } else {
            dialog.widgets['claim_button'].state = 'normal';
            dialog.widgets['claim_button'].str = dialog.data['widgets']['claim_button']['ui_name'];
        }
        dialog.widgets['status'].str = dialog.data['widgets']['status']['ui_name'].replace('%togo', pretty_print_time(ready_aura['end_time'] - server_time));
    } else {
        dialog.widgets['claim_button'].state = 'disabled';
        dialog.widgets['claim_button'].str = dialog.data['widgets']['claim_button']['ui_name_cooldown'];
        dialog.widgets['status'].str = dialog.data['widgets']['status']['ui_name_cooldown'].replace('%togo', pretty_print_time(next_aura['end_time'] - server_time));
    }
};
