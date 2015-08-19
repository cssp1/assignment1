goog.provide('QuestBar');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// vertical bar that shows icons for each active or claimable quest
// tightly coupled to main.js, sorry!

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

QuestBar.init = function() {
    if(!('quest_bar' in desktop_dialogs)) {
        var dialog = QuestBar.invoke();
        if(dialog) {
            desktop_dialogs['quest_bar'] = dialog;
            SPUI.root.add_under(dialog);
        }
    }
};

QuestBar.invoke = function() {
    var dialog_data = gamedata['dialogs']['quest_bar'];
    var dialog = new SPUI.Dialog(dialog_data);
    dialog.user_data['dialog'] = 'quest_bar';
    if('quest_bar_minimized' in player.preferences && player.preferences['quest_bar_minimized']) {
        dialog.user_data['maximized'] = false;
    } else {
        dialog.user_data['maximized'] = !!player.get_any_abtest_value('quest_bar_default_maximized', gamedata['client']['quest_bar_default_maximized']);
    }
    dialog.user_data['start_time'] = -1; // for animation
    dialog.user_data['start_height'] = -1;
    dialog.widgets['maximize'].widgets['scroll_right'].onclick = function(w) { QuestBar.maximize(w.parent.parent); };
    dialog.widgets['minimize'].widgets['scroll_left'].onclick = function(w) { QuestBar.minimize(w.parent.parent); };
    dialog.ondraw = QuestBar.update;
    return dialog;
};

QuestBar.maximize = function(dialog) {
    if(dialog.user_data['maximized']) { return; }
    dialog.user_data['maximized'] = true;
    dialog.user_data['start_time'] = client_time;
    dialog.user_data['start_height'] = dialog.wh[1];
    player.preferences['quest_bar_minimized'] = false;
    send_to_server.func(["UPDATE_PREFERENCES", player.preferences]);
};

QuestBar.minimize = function(dialog) {
    if(!dialog.user_data['maximized']) { return; }
    dialog.user_data['maximized'] = false;
    dialog.user_data['start_time'] = client_time;
    dialog.user_data['start_height'] = dialog.wh[1];
    player.preferences['quest_bar_minimized'] = true;
    send_to_server.func(["UPDATE_PREFERENCES", player.preferences]);
};

QuestBar.update = function(dialog) {
    var quest_list = player.active_quests;
    if(quest_list.length < 1) {
        dialog.show = false;
        return;
    } else {
        dialog.show = true;
    }

    // attach to left-hand side (but shift by chat frame width)
    dialog.xy[0] = dialog.data['xy'][0] + get_console_shift();

    var margin = dialog.data['margin'];

    var top = 0;

    // move down below aura bar to prevent overlap
    if(('aura_bar' in desktop_dialogs) && (dialog.xy[0] + dialog.wh[0] >= desktop_dialogs['aura_bar'].get_absolute_xy()[0] - 4 * margin)) {
        // use height of aura_timer widget to judge top since aura_bar has artificially large height
        top = desktop_dialogs['aura_bar'].get_absolute_xy()[1] + desktop_dialogs['aura_bar'].data['widgets']['aura_timer']['xy'][1] +
            desktop_dialogs['aura_bar'].data['widgets']['aura_timer']['dimensions'][1];
    }

    var space = canvas_height - 2*margin - top;

    var max_shown = Math.min(quest_list.length, dialog.data['widgets']['icon']['array'][1]);
    var want_height;
    // minimized?
    if(!dialog.user_data['maximized']) {
        want_height = 1 * dialog.data['widgets']['icon']['array_offset'][1] + dialog.data['dimensions'][1];
    } else {
        want_height = max_shown * dialog.data['widgets']['icon']['array_offset'][1] + dialog.data['dimensions'][1];
        // drop icons until we fit in the vertical space, but don't go below 1
        while(want_height > Math.max(space, dialog.data['widgets']['icon']['array_offset'][1] + dialog.data['dimensions'][1])) {
            want_height -= dialog.data['widgets']['icon']['array_offset'][1];
        }
    }

    // grow/shrink animation
    var t = (dialog.user_data['start_time'] > 0 ? (client_time - dialog.user_data['start_time']) / dialog.data['anim_time'] : 1);

    if(t >= 1) {
        dialog.wh[1] = want_height;
    } else {
        dialog.wh[1] = dialog.user_data['start_height'] + Math.floor((want_height - dialog.user_data['start_height']) * t);
    }

    // limit number shown to available vertical space
    var n_shown = max_shown;
    while(n_shown > 1 && (dialog.data['widgets']['maximize']['xy'][1] + dialog.data['widgets']['maximize']['dimensions'][1] +
                          n_shown * dialog.data['widgets']['icon']['array_offset'][1]) > dialog.wh[1]) {
        n_shown -= 1;
    }

    if(dialog.data['vjustify'] == 'center') {
        // center vertically
        dialog.xy[1] = canvas_height_half - Math.floor(dialog.wh[1]/2);

        // don't go off the top of the screen
        dialog.xy[1] = Math.max(dialog.xy[1], top + margin);
    } else {
        // attach to top-left
        dialog.xy[1] = top + margin;
    }

    // cut off vertically before missions button (Valentina)
    if('desktop_bottom' in desktop_dialogs) {
        var missions_pos = desktop_dialogs['desktop_bottom'].widgets['missions_button'].get_absolute_xy();
        if(dialog.xy[0] + dialog.wh[0] >= missions_pos[0] - 2 * margin) {
            while(dialog.xy[1] + dialog.wh[1] >= missions_pos[1] && n_shown > 1) {
                n_shown -= 1;
                dialog.wh[1] -= dialog.data['widgets']['icon']['array_offset'][1];
            }
        }
    }

    dialog.widgets['bgrect'].wh[1] = dialog.wh[1];

    goog.array.forEach(['maximize','minimize'], function(wname) {
        dialog.widgets[wname].xy = vec_add(dialog.data['widgets'][wname]['xy'], [0, n_shown * dialog.data['widgets']['icon']['array_offset'][1]]);
    });
    dialog.widgets['maximize'].show = !dialog.user_data['maximized'];
    dialog.widgets['minimize'].show = dialog.user_data['maximized'];

    for(var y = 0; y < dialog.data['widgets']['icon']['array'][1]; y++) {
        for(var x = 0; x < dialog.data['widgets']['icon']['array'][0]; x++) {
            var wname = SPUI.get_array_widget_name('', dialog.data['widgets']['icon']['array'], [x,y]);

            var i = y * dialog.data['widgets']['icon']['array'][0] + x;

            dialog.widgets['slot'+wname].show =
                dialog.widgets['icon'+wname].show =
                dialog.widgets['icon_gamebucks'+wname].show =
                dialog.widgets['icon_gamebucks_amount'+wname].show =
                dialog.widgets['checkmark'+wname].show =
                dialog.widgets['frame'+wname].show = (i < n_shown);
            if(i >= n_shown) { continue; } // after final quest

            var quest = quest_list[i];
            var can_complete = player.can_complete_quest(quest);

            var tip = dialog.data['widgets']['frame'][(can_complete ? 'ui_tooltip_complete' : 'ui_tooltip_available')].replace('%s', quest['ui_name']);
            var show_text = 'ui_description'; // 'ui_instructions';
            if(!can_complete && quest[show_text]) {
                var instr = eval_cond_or_literal(quest[show_text], player, null);
                if(instr) {
                    instr = SPUI.break_lines(instr, dialog.widgets['frame'+wname].tooltip.font, [dialog.data['widgets']['frame']['tooltip_width_'+show_text],0])[0];
                    tip += '\n\n' + instr;
                }
            }
            dialog.widgets['frame'+wname].tooltip.str = tip;
            dialog.widgets['frame'+wname].state = (player.quest_tracked == quest ? 'highlight' : dialog.data['widgets']['frame']['state']);
            dialog.widgets['icon'+wname].asset = quest['icon'] || 'inventory_unknown';

            var bucks = quest['reward_gamebucks'] || 0;

            dialog.widgets['icon_gamebucks'+wname].show = dialog.widgets['icon_gamebucks_amount'+wname].show = (bucks > 0);
            if(bucks > 0) {
                dialog.widgets['icon_gamebucks'+wname].asset = player.get_any_abtest_value('gamebucks_resource_icon', gamedata['store']['gamebucks_resource_icon']);
                dialog.widgets['icon_gamebucks_amount'+wname].str = Store.display_user_currency_amount(bucks, 'compact');
            }

            dialog.widgets['checkmark'+wname].show = can_complete;
            if(can_complete) {
                var amp = dialog.data['widgets']['checkmark']['pulse_amplitude'];
                var off = dialog.data['widgets']['checkmark']['pulse_offset'];
                dialog.widgets['checkmark'+wname].alpha = (1-amp) + amp * (0.5*(Math.sin((2*Math.PI/dialog.data['widgets']['checkmark']['pulse_period'])*(client_time + off*i))+1));
            } else if(dialog.widgets['frame'+wname].state != 'highlight' && dialog.widgets['frame'+wname].mouse_enter_time < 0) {
                var amp = dialog.data['widgets']['frame']['pulse_amplitude'];
                var off = dialog.data['widgets']['frame']['pulse_offset'];
                dialog.widgets['frame'+wname].alpha = (1-amp) + amp * (0.5*(Math.sin((2*Math.PI/dialog.data['widgets']['frame']['pulse_period'])*(client_time + off*i))+1));
            } else {
                dialog.widgets['frame'+wname].alpha = 1;
            }
            dialog.widgets['frame'+wname].onclick = (function (_quest) { return function(w) {
                player.record_feature_use('quest_bar');
                var mis = invoke_missions_dialog(true, _quest);
                if(mis) {
                    if(player.can_complete_quest(_quest)) {
                        // trigger claim
                        if(0 && mis.widgets['claim_button'].state != 'disabled') {
                            mis.widgets['claim_button'].onclick(mis.widgets['claim_button']);
                        }
                    } else {
                        // trigger tracker
                        tutorial_opt_in(_quest);
                    }
                }
            }; })(quest);
        }
    }
};
