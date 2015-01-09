goog.provide('QuestBar');

// vertical bar that shows icons for each active or claimable quest
// tightly coupled to main.js, sorry!

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
    dialog.ondraw = QuestBar.update;
    return dialog;
};

QuestBar.update = function(dialog) {
    var quest_list = player.active_quests;
    if(quest_list.length < 1) {
        dialog.show = false;
        return;
    } else {
        dialog.show = true;
    }

    var n_shown = Math.min(quest_list.length, dialog.data['widgets']['icon']['array'][0]*dialog.data['widgets']['icon']['array'][1]);
    dialog.wh[1] = n_shown * dialog.data['widgets']['icon']['array_offset'][1] + dialog.data['widgets']['icon']['xy'][1];
    while(dialog.wh[1] > canvas_height && n_shown > 1) {
        n_shown -= 1;
        dialog.wh[1] -=  dialog.data['widgets']['icon']['array_offset'][1];
    }
    dialog.widgets['bgrect'].wh[1] = dialog.wh[1];

    // center vertically, and attach to left-hand side
    dialog.xy = vec_add(dialog.data['xy'], [get_console_shift(), canvas_height_half - Math.floor(dialog.wh[1]/2)]);
    dialog.xy[1] = Math.max(dialog.xy[1], 0); // don't go off the top of the screen

    for(var y = 0; y < dialog.data['widgets']['icon']['array'][1]; y++) {
        for(var x = 0; x < dialog.data['widgets']['icon']['array'][0]; x++) {
            var wname = SPUI.get_array_widget_name('', dialog.data['widgets']['icon']['array'], [x,y]);

            var i = y * dialog.data['widgets']['icon']['array'][0] + x;

            dialog.widgets['slot'+wname].show =
                dialog.widgets['icon'+wname].show =
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
