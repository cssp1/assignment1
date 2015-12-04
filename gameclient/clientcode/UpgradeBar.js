goog.provide('UpgradeBar');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('SPUI');
goog.require('SPText');

// displays what you get when you upgrade a building or tech
// tightly coupled to main.js, sorry!

/** @param {SPUI.Dialog} parent */
UpgradeBar.invoke = function(parent, kind, specname, new_level, obj_id) {
    if(parent.clip_children) { throw Error('parent must not clip children'); }

    var dialog;

    if('upgrade_bar' in parent.widgets) { // re-use existing instance
        dialog = parent.widgets['upgrade_bar'];
        UpgradeBar.update_contents(dialog, kind, specname, new_level, obj_id);
        return dialog;
    }

    var dialog_data = gamedata['dialogs']['upgrade_bar'];
    dialog = new SPUI.Dialog(dialog_data);
    dialog.user_data['dialog'] = 'upgrade_bar';
    // special case hack - if parented to the main "Upgrade" dialog, do not show a redundant upgrade button
    dialog.user_data['show_button'] = !(parent.user_data['dialog'] == 'upgrade_dialog');
    dialog.user_data['scroll_pos'] = 0;
    dialog.user_data['is_applicable'] = false; // true if there is any meaningful data to show (otherwise dialog is permanently hidden)
    dialog.widgets['scroll_up'].onclick = function (w) { UpgradeBar.scroll(w.parent, -1); };
    dialog.widgets['scroll_down'].onclick = function (w) { UpgradeBar.scroll(w.parent, 1); };
    dialog.widgets['output'].scroll_up_button = dialog.widgets['scroll_up'];
    dialog.widgets['output'].scroll_down_button = dialog.widgets['scroll_down'];
    dialog.ondraw = UpgradeBar.ondraw;
    parent.widgets['upgrade_bar'] = dialog;
    parent.add(dialog);
    UpgradeBar.update_contents(dialog, kind, specname, new_level, obj_id);
    dialog.ondraw(dialog);
    return dialog;
};
UpgradeBar.scroll = function(dialog, incr) {
    if(incr === -2) { // reset to top
        dialog.widgets['output'].scroll_to_top();
    } else if(incr === 2) { // reset to bottom
        dialog.widgets['output'].scroll_to_bottom();
    } else if(incr < 0) {
        dialog.widgets['output'].scroll_up();
    } else if(incr > 0) {
        dialog.widgets['output'].scroll_down();
    }
    dialog.user_data['scroll_pos'] = dialog.widgets['output'].get_scroll_pos_from_head_to_bot();
    var has_scrolling = dialog.widgets['output'].can_scroll_up() || dialog.widgets['output'].can_scroll_down();
    dialog.widgets['output'].scroll_up_button.show =
        dialog.widgets['output'].scroll_down_button.show = has_scrolling;
};
UpgradeBar.ondraw = function(dialog) {

    // hide the bar if the parent dialog is not the front-most dialog being shown right now
    // (otherwise the bar can "show through" a parent dialog onto the child)
    if(!dialog.parent.is_frontmost()) {
        dialog.show = false;
    } else {
        dialog.show = dialog.user_data['is_applicable'];
    }
    if(!dialog.show) { return; }

    var border = dialog.data['xy'];
    var show_button = dialog.user_data['show_button'];
    dialog.xy = [border[0], dialog.parent.wh[1]];
    dialog.wh = [dialog.parent.wh[0] - 2*border[0], dialog.data['dimensions'][1]];
    dialog.widgets['bgrect'].wh = dialog.wh;

    // resize output widget
    // note: might interfere with "layout" directives, so output widget does not use layout
    var output_dims = (show_button ? 'dimensions' : 'dimensions_nobutton');
    dialog.widgets['output'].wh = [
        dialog.data['widgets']['output'][output_dims][0] + (dialog.wh[0] - dialog.data['dimensions'][0]),
        dialog.data['widgets']['output'][output_dims][1]];
    dialog.widgets['output'].xy = dialog.data['widgets']['output'][show_button ? 'xy' : 'xy_nobutton'];

    dialog.apply_layout();
    var is_hover = (dialog.mouse_enter_time > 0);
    goog.array.forEach(['upgrade_button', 'output'], function(wname) {
        dialog.widgets[wname].alpha = (is_hover ? 1 : dialog.data['widgets'][wname]['alpha_nonhover']);
    });
};
UpgradeBar.update_contents = function(dialog, kind, specname, new_level, obj_id) {
    var prev_kind = dialog.user_data['kind'] || null; dialog.user_data['kind'] = kind;
    var prev_specname = dialog.user_data['specname'] || null; dialog.user_data['specname'] = specname;
    var prev_new_level = dialog.user_data['new_level'] || null; dialog.user_data['new_level'] = new_level;
    var prev_obj_id = dialog.user_data['obj_id'] || null; dialog.user_data['obj_id'] = obj_id;
    var prev_scroll_pos = dialog.user_data['scroll_pos'];

    if(kind === null || specname === null) { dialog.user_data['is_applicable'] = false; return; }
    dialog.user_data['is_applicable'] = true;

    var spec;
    if(kind == 'building') {
        spec = gamedata['buildings'][specname];
        dialog.widgets['upgrade_button'].onclick = (function (_obj_id) { return function(w) {
            invoke_upgrade_building_dialog(session.cur_objects.get_object(_obj_id));
        }; })(obj_id);
    } else if(kind == 'tech') {
        spec = gamedata['tech'][specname];
        dialog.widgets['upgrade_button'].onclick = (function (_specname) { return function(w) {
            invoke_upgrade_tech_dialog(_specname);
        }; })(specname);
    } else {
        throw Error('unknown kind '+kind);
    }
    if(new_level > get_max_level(spec)) { dialog.user_data['is_applicable'] = false; return; } // maxed out

    dialog.widgets['upgrade_button'].show = dialog.user_data['show_button'];

    var s = dialog.data['widgets']['output'][(dialog.user_data['show_button'] ? 'ui_name' : 'ui_name_nobutton')];

    var self = dialog.data['widgets']['output']['ui_self'].replace('%THING', spec['ui_name']).replace('%LEVEL', pretty_print_number(new_level));

    // add hyperlink to "Next..."
    self = '['+kind+'='+specname+']'+self+'[/'+kind+']';
    // note: second replacement of THING/LEVEL because they may occur either inside or outside the SELF replacement
    s = s.replace('%SELF', self).replace('%THING', spec['ui_name']).replace('%LEVEL', pretty_print_number(new_level));

    var ui_goodies_list = [];
    var goodies_list = null;
    if(specname in gamedata['inverse_requirements'][kind]) {
        goodies_list = get_leveled_quantity(gamedata['inverse_requirements'][kind][specname], new_level);
    }
    if(goodies_list === null) { goodies_list = []; }

    // XXX eventualy, we want to be able to inject predicates into BBCode, e.g. [predicate="{\"predicate\":\"BUILDING_LEVEL\",...
    // but this will require careful updating of the SPText BBCode parser/quoter. For now, just track predicates by giving
    // them a number and referring to them via this map attached to the onclick handler
    var predicate_map = {}; // map from integer index -> raw predicate dict
    var predicate_index = 0;

    goog.array.forEach(goodies_list, function(goody) {
        var level = ('level' in goody ? goody['level'] : 1);
        var linkcode = null;
        var temp = dialog.data['widgets']['output'][(level > 1 ? 'ui_goody_leveled' : 'ui_goody_unleveled')];
        if('tech' in goody) {
            var tech_spec = gamedata['tech'][goody['tech']];
            if(tech_spec['developer_only'] && !player.is_developer()) { return; }
            if(('show_if' in tech_spec) && !read_predicate(tech_spec['show_if']).is_satisfied(player,null)) { return; }
            temp = temp.replace('%THING', tech_spec['ui_name']);
            linkcode = 'tech='+goody['tech'];
        } else if('building' in goody) {
            var building_spec = gamedata['buildings'][goody['building']];
            if(building_spec['developer_only'] && !player.is_developer()) { return; }
            if(('show_if' in building_spec) && !read_predicate(building_spec['show_if']).is_satisfied(player,null)) { return; }
            temp = temp.replace('%THING', building_spec['ui_name']);
            linkcode = 'building='+goody['building'];
        } else if('crafting_recipe' in goody) {
            var recipe = gamedata['crafting']['recipes'][goody['crafting_recipe']];
            if(recipe['developer_only'] && !player.is_developer()) { return; }
            if(('show_if' in recipe) && !read_predicate(recipe['show_if']).is_satisfied(player,null)) { return; }

            // skip turret head crafting recipes, because there isn't a natural destination for the click,
            // and it's redundant to say "MG Tower L2 (tech) unlocks MG Tower L2 (crafting recipe)"
            if(recipe['crafting_category'] === 'turret_heads') { return; }

            var n;
            if('ui_name' in recipe) {
                n = recipe['ui_name'];
            } else {
                n = ItemDisplay.get_inventory_item_ui_name(ItemDisplay.get_crafting_recipe_product_spec(recipe));
            }
            temp = temp.replace('%THING', n);
            linkcode = 'crafting_recipe='+goody['crafting_recipe'];
        } else {
            throw Error('unknown goody '+JSON.stringify(goody));
        }
        if(level > 1) {
            temp = temp.replace('%LEVEL', pretty_print_number(level));
        }

        if(linkcode) {
            temp = '['+linkcode+']'+temp+'[/'+linkcode.split('=')[0]+']';
        }
        // parse additional required predicates
        if('with' in goody) {
            var with_list = [];
            goog.array.forEach(goody['with'], function(other_pred) {
                var p = read_predicate(other_pred);
                var ui_pred = p.ui_describe(player);
                if(ui_pred) {
                    predicate_map[predicate_index] = other_pred;
                    with_list.push('[predicate='+predicate_index.toString()+']'+dialog.data['widgets']['output']['ui_goody_with_pred'].replace('%PRED', ui_pred)+'[/predicate]');
                    predicate_index += 1;
                }
            });
            if(with_list.length > 0) {
                temp += dialog.data['widgets']['output']['ui_goody_with'].replace('%PRED_LIST', with_list.join(', '));
            }
        }
        ui_goodies_list.push(temp);
    });

    if(ui_goodies_list.length < 1) { // nothing to talk about!
        dialog.user_data['is_applicable'] = false; return;
    }

    s = s.replace('%GOODIES', ui_goodies_list.join(', '));

    // hyperlink handlers for goodies and also "with ..." unsatisfied predicates
    var click_handlers = {
        'building': {'onclick': (function (_obj_id) { return function(specname) { return function(w, mloc) {
            // if it's the same type as the object upon which the upgrade bar was invoked, prefer selecting that one
            var sel_obj = session.cur_objects.get_object(_obj_id);
            if(!sel_obj || sel_obj.spec['name'] != specname) {
                sel_obj = find_object_by_type(specname);
            }
            if(sel_obj) {
                invoke_upgrade_building_dialog(sel_obj);
            } else {
                invoke_build_dialog(gamedata['buildings'][specname]['build_category']);
            }
        }; }; })(obj_id) },
        'tech': {'onclick': function(specname) { return function(w, mloc) {
            invoke_upgrade_tech_dialog(specname);
        }; } },
        'crafting_recipe': {'onclick': function(specname) { return function(w, mloc) {
            var recipe = gamedata['crafting']['recipes'][specname];
            var catdata = gamedata['crafting']['categories'][recipe['crafting_category']];
            var dialog;
            if(catdata['table_of_contents']) {
                if(!recipe['associated_item_set']) { throw Error('recipe category requires table_of_contents but no item set is associated'); }
                dialog = invoke_crafting_dialog(recipe['crafting_category'], recipe['associated_item_set']);
            } else {
                dialog = invoke_crafting_dialog(recipe['crafting_category']);
            }
            if(dialog) {
                var rec = goog.array.find(dialog.user_data['recipes'] || [], function(entry) {
                    return (entry['spec'] === specname); // (ignore level)
                });
                if(rec) {
                    crafting_dialog_select_recipe(dialog.widgets['recipe'], rec);
                }
            }
        }; } },
        'predicate': {'onclick': (function (_predicate_map) { return function(sindex) { return function(w, mloc) {
            var pred = _predicate_map[parseInt(sindex,10)];
            var helper = get_requirements_help(read_predicate(pred), null, {short_circuit:true});
            if(helper) { helper(); }
        }; }; })(predicate_map) }
    };

    dialog.widgets['output'].clear_text();
    dialog.widgets['output'].append_text_with_linebreaking_bbcode(s, {}, click_handlers);

    // if contents changed, then reset scroll
    if(kind != prev_kind || specname != prev_specname || new_level != prev_new_level || obj_id != prev_obj_id) {
        UpgradeBar.scroll(dialog, -2);
    } else {
        // otherwise, return to previous scroll position
        UpgradeBar.scroll(dialog, 2);
        for(var i = 0; i < prev_scroll_pos; i++) {
            UpgradeBar.scroll(dialog, -1);
        }
    }
};
