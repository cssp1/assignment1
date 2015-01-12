goog.provide('UpgradeBar');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('goog.array');
goog.require('SPUI');
goog.require('SPText');

// displays what you get when you upgrade a building or tech
// tightly coupled to main.js, sorry!

/** @param {SPUI.Dialog} parent */
UpgradeBar.invoke = function(parent, kind, specname, new_level, obj_id) {
    if(parent.clip_children) { throw Error('parent must not clip children'); }
    var dialog_data = gamedata['dialogs']['upgrade_bar'];
    var dialog = new SPUI.Dialog(dialog_data);
    dialog.user_data['dialog'] = 'upgrade_bar';
    dialog.widgets['scroll_up'].onclick = function (w) { UpgradeBar.scroll(w.parent, -1); };
    dialog.widgets['scroll_down'].onclick = function (w) { UpgradeBar.scroll(w.parent, 1); };
    dialog.ondraw = UpgradeBar.ondraw;
    parent.widgets['upgrade_bar'] = dialog;
    parent.add(dialog);
    UpgradeBar.update_contents(dialog, kind, specname, new_level, obj_id);
    return dialog;
};
UpgradeBar.scroll = function(dialog, incr) {
    if(incr < 0) {
        if(incr < -1) {
            dialog.widgets['output'].scroll_to_top();
        } else {
            dialog.widgets['output'].scroll_up();
        }
    } else if(incr > 0) {
        dialog.widgets['output'].scroll_down();
    }
    // set clickability of scroll arrows
    dialog.widgets['scroll_up'].state = (dialog.widgets['output'].can_scroll_up() ? 'normal' : 'disabled');
    dialog.widgets['scroll_down'].state = (dialog.widgets['output'].can_scroll_down() ? 'normal' : 'disabled');
};
UpgradeBar.ondraw = function(dialog) {
    var border = dialog.data['xy'];
    dialog.xy = [border[0], dialog.parent.wh[1]];
    dialog.wh = [dialog.parent.wh[0] - 2*border[0], dialog.data['dimensions'][1]];
    dialog.widgets['bgrect'].wh = dialog.wh;
    dialog.widgets['output'].wh = [
        dialog.data['widgets']['output']['dimensions'][0] + (dialog.wh[0] - dialog.data['dimensions'][0]),
        dialog.data['widgets']['output']['dimensions'][1]];
    dialog.apply_layout();
    var is_hover = (dialog.mouse_enter_time > 0);
    goog.array.forEach(['upgrade_button', 'output'], function(wname) {
        dialog.widgets[wname].alpha = (is_hover ? 1 : dialog.data['widgets'][wname]['alpha_nonhover']);
    });
};
UpgradeBar.update_contents = function(dialog, kind, specname, new_level, obj_id) {
    dialog.widgets['output'].clear_text();
    if(kind === null) { dialog.show = false; return; }
    dialog.show = true;

    var spec;
    if(kind == 'building') {
        spec = gamedata['buildings'][specname];
        dialog.widgets['upgrade_button'].onclick = (function (_obj_id) { return function(w) {
            change_selection_unit(session.cur_objects.get_object(_obj_id));
            invoke_upgrade_building_dialog();
        }; })(obj_id);
    } else if(kind == 'tech') {
        spec = gamedata['tech'][specname];
        dialog.widgets['upgrade_button'].onclick = (function (_specname) { return function(w) {
            invoke_upgrade_tech_dialog(_specname);
        }; })(specname);
    } else {
        throw Error('unknown kind '+kind);
    }
    if(new_level > get_max_level(spec)) { dialog.show = false; return; } // maxed out

    var s = dialog.data['widgets']['output']['ui_name'];
    s = s.replace('%THING', spec['ui_name']);
    s = s.replace('%LEVEL', pretty_print_number(new_level));

    // XXXXXX
    var ui_goodies_list = [];
    var goodies_list = [{'tech':'archer_production','level':1},{'tech':'orc_production','level':2},{'building':'barracks','level':2},{'crafting_recipe':'make_dragons_breath_magic_L1'}];
    goog.array.forEach(goodies_list, function(goody) {
        var temp = dialog.data['widgets']['output'][('level' in goody && goody['level'] > 1 ? 'ui_goody_leveled' : 'ui_goody_unleveled')];
        if('tech' in goody) {
            temp = temp.replace('%THING', gamedata['tech'][goody['tech']]['ui_name']);
        } else if('building' in goody) {
            temp = temp.replace('%THING', gamedata['buildings'][goody['building']]['ui_name']);
        } else if('crafting_recipe' in goody) {
            var recipe = gamedata['crafting']['recipes'][goody['crafting_recipe']];
            var n;
            if('ui_name' in recipe) {
                n = recipe['ui_name'];
            } else {
                n = ItemDisplay.get_inventory_item_ui_name(recipe['products'][0]['spec']);
            }
            temp = temp.replace('%THING', n);
        } else {
            throw Error('unknown goody '+JSON.stringify(goody));
        }
        if('level' in goody) {
            temp = temp.replace('%LEVEL', pretty_print_number(goody['level']));
        }
        ui_goodies_list.push(temp);
    });
    if(ui_goodies_list.length < 1) { // nothing to talk about!
        dialog.show = false; return;
    }
    s = s.replace('%GOODIES', ui_goodies_list.join(', '));
    if(0) {
        dialog.widgets['output'].append_text(SPText.cstring_to_ablocks_bbcode(broken_s));
    } else {
        // probably unsafe, because it can break inside BBCode
        var broken_s = SPUI.break_lines(s, dialog.widgets['output'].font, dialog.widgets['output'].wh, {bbcode:true})[0];
        console.log(broken_s);
        goog.array.forEach(broken_s.split('\n'), function(line) {
            dialog.widgets['output'].append_text(SPText.cstring_to_ablocks_bbcode(line));
        });
    }

    UpgradeBar.scroll(dialog, -2);
};
