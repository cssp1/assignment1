goog.provide('Showcase');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('goog.object');
goog.require('Predicates');
goog.require('SPUI');
goog.require('GameArt');
goog.require('ItemDisplay');
goog.require('PlayerInfoDialog');

// also implicitly references a bunch of stuff from main.js like "player"/"session"/etc

// XXXXXX convert the sale_text/plus_text to SPUI.RichTextWidget and move this function into there
/** @param {SPUI.ScrollingTextField} widget
    @param {string} big_string
    @param {Object} props
    @param {Object} click_handlers
    @param {string} and_more added to end of last line if no more will fit
*/
Showcase.append_bbcode_text_with_line_breaking = function(widget, big_string, props, click_handlers, and_more) {
    // break lines, protecting BBCode
    var broken_s = SPUI.break_lines(big_string, widget.font, widget.wh, {bbcode:true})[0];
    var max_lines = Math.max(1, Math.floor(widget.wh[1] / widget.font.leading));
    goog.array.forEach(broken_s.split('\n'), function(line, n) {
        if(n+1 == max_lines) {
            line += and_more;
        } else if(n+1 > max_lines) {
            return;
        }
        widget.append_text(SPText.cstring_to_ablocks_bbcode(line, props, click_handlers));
    });
    widget.scroll_to_top();
};

Showcase.apply_showcase_hacks = function(dialog, hack) {
    if('ui_title' in hack) {
        dialog.widgets['mission_title'].str = eval_cond_or_literal(hack['ui_title'], player, null);
    }
    if('ui_subtitle' in hack) {
        dialog.widgets['subtitle'].str = eval_cond_or_literal(hack['ui_subtitle'], player, null);
    }
    if('ui_ok_button' in hack) {
        dialog.widgets['ok_button'].str = eval_cond_or_literal(hack['ui_ok_button'], player, null);
    }
    if('ok_button_consequent' in hack) { // wrap the callback - awkward - default behavior must have been set up first (see create_splash_message()) - and this might get over-ridden later!
        var old_cb = dialog.widgets['ok_button'].onclick;
        dialog.widgets['ok_button'].onclick = (function (_old_cb, _cons) { return function(w) {
            var dialog = w.parent;
            read_consequent(_cons).execute(dialog.user_data['consequent_context'] || null);
            if(_old_cb) {
                _old_cb(w);
            }
        }; })(old_cb, hack['ok_button_consequent']);
    }

    dialog.widgets['ai'].asset = eval_cond_or_literal(hack['villain_asset'], player, null);
    dialog.widgets['ai_text'].str = eval_cond_or_literal(hack['ui_villain_name'], player, null);

    var token_item_name = null;
    if('token_item' in hack) {
        var token_item_spec = ItemDisplay.get_inventory_item_spec(hack['token_item']);
        token_item_name = token_item_spec['ui_name_short'] || ItemDisplay.get_inventory_item_ui_name(token_item_spec);
        dialog.widgets['tokens_text'].show = 1;
        dialog.widgets['tokens_text'].str = dialog.data['widgets']['tokens_text']['ui_name'].replace('%d', pretty_print_number(player.inventory_item_quantity_and_expiration(hack['token_item'])[0])).replace('%s', token_item_name);
    }

    if(hack['corner_token_mode'] && token_item_name) {
        dialog.widgets['corner_token_glow'].show =
            dialog.widgets['corner_token_bg'].show =
            dialog.widgets['corner_token'].show =
            dialog.widgets['corner_token_instr'].show = true;
        var token_item_spec = ItemDisplay.get_inventory_item_spec(hack['token_item']);
        ItemDisplay.set_inventory_item_asset(dialog.widgets['corner_token'], token_item_spec);

        // create a fake token item for use by the tooltip
        var force_expire_by = session.get_item_spec_forced_expiration(token_item_spec);
        var token_item = {'spec': hack['token_item'], 'expire_time': force_expire_by};
        ItemDisplay.attach_inventory_item_tooltip(dialog.widgets['corner_token'], token_item);

        var txt = dialog.data['widgets']['corner_token_instr']['ui_name_'+hack['corner_token_mode']].replace('%AI', hack['ui_villain_name']);
        while(txt.indexOf('%TOKEN') != -1) {
            txt = txt.replace('%TOKEN', token_item_name);
        }
        if(force_expire_by > 0 && txt.indexOf('%EXPIRE_IN') != -1) {
            txt = txt.replace('%EXPIRE_IN', pretty_print_time_brief(force_expire_by - player.get_absolute_time()));
        }
        dialog.widgets['corner_token_instr'].set_text_with_linebreaking(txt);
    }

    if(hack['corner_ai_asset']) {
        dialog.widgets['corner_ai'].show = true;
        dialog.widgets['corner_ai'].asset = hack['corner_ai_asset'];
    }

    if('victory' in hack) {
        dialog.widgets['flash'].show =
            dialog.widgets['glow'].show =
            dialog.widgets['victory_splash_frame'].show =
            dialog.widgets['victory_splash'].show =
            dialog.widgets['victory'].show =
            dialog.widgets['victory_subtitle'].show = true;
        dialog.widgets['victory_subtitle'].str = eval_cond_or_literal(hack['ui_victory_subtitle'] || null, player, null);
    }

    var show_login_splash = false;
    goog.array.forEach(['header','title','body'], function(part) {
        if('ui_login_'+part+'_bbcode' in hack) {
            show_login_splash = true;
            dialog.widgets['login_'+part].show = true;
            var login_str = eval_cond_or_literal(hack['ui_login_'+part+'_bbcode'], player, null);
            if(login_str) {
                dialog.widgets['login_'+part].append_text(SPText.cstring_to_ablocks_bbcode(login_str.replace('%TOKEN', token_item_name)));
            }
        }
    });
    dialog.widgets['login_splash'].show = dialog.widgets['login_splash_bar'].show = show_login_splash;

    var level_map = null; // many-to-one mapping from index in unskipped linear progression to index in skipped progression sequence
    if('level_skip' in hack) {
        level_map = [];
        var unskipped_count = 0;
        for(var i = 0; i < hack['level_skip'].length; i++) {
            level_map.push(unskipped_count);
            if(!hack['level_skip'][i]) {
                unskipped_count += 1;
            }
        }
    } else if('total_levels' in hack) {
        level_map = [];
        for(var i = 0; i < hack['total_levels']; i++) {
            level_map.push(i);
        }
    }

    // "unskipped" is the position in the original progression, "skipped" is the index in the skipped sequence
    var unskipped_level_progress = 0, skipped_level_progress = 0;

    if(('total_levels' in hack) && ('progress_key' in hack)) {
        dialog.widgets['levels_text'].show = 1;
        if(hack['progress_key'] in player.history &&
           (!hack['progress_key_cooldown'] || player.cooldown_active(hack['progress_key_cooldown']))) {
            unskipped_level_progress = player.history[hack['progress_key']];
        } else {
            unskipped_level_progress = 0;
        }
        var total_unskipped_levels = hack['total_levels'];
        var total_skipped_levels = level_map[hack['total_levels']-1]+1;
        if(level_map) {
            if(unskipped_level_progress >= level_map.length) {
                skipped_level_progress = level_map[level_map.length-1]+1; // end of progression
            } else {
                skipped_level_progress = level_map[unskipped_level_progress];
            }
        } else {
            skipped_level_progress = unskipped_level_progress;
        }
        dialog.widgets['levels_text'].str = dialog.data['widgets']['levels_text']['ui_name'].replace('%d1', skipped_level_progress.toString()).replace('%d2', total_skipped_levels.toString());

        if(hack['show_progress_bar']) {
            var bar = hack['show_progress_bar']; // should be "small" or "large"
            dialog.widgets[bar+'_progress_bar'].show = dialog.widgets[bar+'_progress_text'].show = true;
            dialog.widgets[bar+'_progress_bar'].progress = (skipped_level_progress / total_skipped_levels);
            dialog.widgets[bar+'_progress_text'].str = dialog.data['widgets'][bar+'_progress_text']['ui_name'].replace('%d', (100.0*skipped_level_progress/total_skipped_levels).toFixed(0));
        }
    }

    if('achievement_keys' in hack) {
        dialog.widgets['achievements_text'].show = 1;

        var text = dialog.data['widgets']['achievements_text']['ui_name_achievements'];

        var total_complete = Showcase.count_achievements(hack['achievement_keys']);
        text = text.replace('%d1', total_complete[1].toString()).replace('%d2', total_complete[0].toString());

        // find an achievement containing these keys so that we can link to it (preferring incomplete ones)
        var achievement = null;
        for (var name in gamedata['achievements']) {
            var ach = gamedata['achievements'][name];
            var cat = gamedata['achievement_categories'][ach['category']];

            if('activation' in cat && !read_predicate(cat['activation']).is_satisfied(player, null)) { continue; }
            if('show_if' in cat && !read_predicate(cat['show_if']).is_satisfied(player, null)) { continue; }
            if('activation' in ach && !read_predicate(ach['activation']).is_satisfied(player, null)) { continue; }
            if('show_if' in ach && !read_predicate(ach['show_if']).is_satisfied(player, null)) { continue; }

            if(Showcase.predicate_reads_keys(ach['goal'], hack['achievement_keys'])) {
                if (!goog.object.containsKey(player.achievements, name)) {
                    // find the first incomplete achievement
                    achievement = ach;
                    break;
                } else if (achievement == null) {
                    // or fall back to the first completed one if no incomplete ones are found
                    achievement = ach;
                }
            }
        }

        var bbcode_click_handler = {
            'achievements': {
                'onclick': function() {
                    return function() {
                        if (achievement != null) {
                            PlayerInfoDialog.invoke(session.user_id, function(dialog) {
                                PlayerInfoDialog.invoke_achievements_tab(dialog, achievement['category'], achievement['name']);
                            });
                        }
                    }
                }
            }
        };

        dialog.widgets['achievements_text'].set_text(SPText.cstring_to_ablocks_bbcode(text, null, bbcode_click_handler));
    }

    if('conquest_key' in hack) {
        dialog.widgets['map_victory_text'].show = 1;
        var victories = player.history[hack['conquest_key']] || 0;
        dialog.widgets['map_victory_text'].str = dialog.data['widgets']['map_victory_text']['ui_name'].replace('%d', victories.toString());
    }

    if('final_reward_unit' in hack || 'final_reward_items' in hack) {
        dialog.widgets['final_reward_label'].show =
            dialog.widgets['final_reward_title'].show =
            dialog.widgets['final_reward_subtitle'].show =
            dialog.widgets['final_reward_splash'].show =
            dialog.widgets['final_reward_bg'].show = true;

        dialog.widgets['final_reward_label'].str = hack['ui_final_reward_label'].replace('%TOKEN', token_item_name);
        goog.array.forEach(['title', 'subtitle'], function(n) {
            if(hack['ui_final_reward_'+n+'_bbcode']) {
                var s = eval_cond_or_literal(hack['ui_final_reward_'+n+'_bbcode'],player,null);
                if(s) {
                    dialog.widgets['final_reward_'+n].append_text(SPText.cstring_to_ablocks_bbcode(s));
                }
            }
        });

        if('final_reward_unit' in hack) {
            dialog.widgets['final_reward_unit'].show = true;
            var unit_spec = get_spec(hack['final_reward_unit']);
            dialog.widgets['final_reward_unit'].asset = get_leveled_quantity(unit_spec['art_asset'], 1);
            dialog.widgets['final_reward_unit'].bg_image_offset = dialog.data['widgets']['final_reward_unit']['bg_image_offset' + (unit_spec['flying'] ? '_flying' : '')];
        }

        if('final_reward_items' in hack) {
            var item_list = eval_cond_or_literal(hack['final_reward_items'],player,null);
            if(item_list) {
                ItemDisplay.display_item_array(dialog, 'final_reward_item', item_list, {glow: true});
                for(var x = 0; x < dialog.data['widgets']['final_reward_item']['array'][0]; x++) {
                    var is_owned = (x < item_list.length && player.has_item(item_list[x]['spec']))
                    dialog.widgets['final_reward_owned_bg'+x.toString()].show =
                        dialog.widgets['final_reward_owned_text'+x.toString()].show = is_owned;
                    if(is_owned) {
                        dialog.widgets['final_reward_item'+x.toString()].widgets['frame'].state = 'disabled';
                    }
                }
            }
        }
    }

    // find width of capital M of the font that will be used for the bbcode
    SPUI.ctx.save();
    SPUI.ctx.font = dialog.widgets['plus_text'].font.str();
    var em_width = SPUI.ctx.measureText('M').width;
    SPUI.ctx.restore();

    var plus_str = '';
    var plus_store_category_name = null;

    if('ui_plus_bbcode' in hack) { plus_str += hack['ui_plus_bbcode']; }
    if('plus_store_category' in hack) {
        // show links to other sub-categories under this store category, e.g. event_prizes
        // note: ignore any items already shown via final_reward_items
        var cat = goog.array.find(gamedata['store']['catalog'], function(dat) { return dat['name'] == hack['plus_store_category']; });
        if(!cat) { throw Error('cannot find plus_store_category '+hack['plus_store_category']); }
        plus_store_category_name = cat['ui_name'];

        var counts = Showcase.collect_child_sku_counts(cat, goog.array.map(hack['final_reward_items'] || [], function(x) { return x['spec']; }));
        var cat_strs = [];
        var link_color = SPUI.make_colorv(dialog.data['widgets']['plus_text']['link_color']).hex();
        goog.array.forEach(counts, function(count) {
            if(count['count'] > 0) {
                cat_strs.push('[color=#'+link_color+'][u][sku='+hack['plus_store_category']+'/'+count['name']+'/]'+count['ui_name']+'[/sku][/u] ('+count['count'].toString()+')[/color]');
            }
        });

        plus_str += cat_strs.join(', ');
        /* doesn't work, you can't cut a string in the middle of BBCode
        var max_len = 2 * dialog.widgets['plus_item_text'].wh[0] / (em_width/4);
        var trimmed = false;
        while(plus_str.length > max_len) {
            plus_str = plus_str.substr(0, plus_str.lastIndexOf(','));
            trimmed = true;
        }
        if (trimmed) { plus_str += ", ..."; }
        */

    }

    if(plus_str && !('show_plus_text' in hack && !hack['show_plus_text'])) {
        dialog.widgets['plus_label'].show = dialog.widgets['plus_text'].show = 1;

        var plus_and_more = ' ... [color=#'+link_color+'][u][sku='+hack['plus_store_category']+'/]'+
            dialog.data['widgets']['plus_text']['ui_name_more'] +'[/sku][/u][/color]';
        Showcase.append_bbcode_text_with_line_breaking(dialog.widgets['plus_text'], plus_str, null, system_chat_bbcode_click_handlers, plus_and_more);

        var show_active_sales = true;

        if(hack['ui_final_reward_title_bbcode']) {
            var s = eval_cond_or_literal(hack['ui_final_reward_title_bbcode'],player,null);
            if(s && goog.array.contains(s.toLowerCase().split(' '), "sale")) { // XXX hack
                show_active_sales = false;
            }
        }

        if(show_active_sales) {
            var sales = Showcase.collect_active_sales_data({'name':'', 'skus':gamedata['store']['catalog']});
            if(sales.length > 0) {
                var sale_str_list = [];
                var link_color = SPUI.make_colorv(dialog.data['widgets']['sale_text']['link_color']).hex();
                for(var i = 0; i < sales.length; i++) {
                    sale_str_list.push('[color=#'+link_color+'][u][sku=' + sales[i]['path'] + ']' + sales[i]['ui_name'] + '[/sku][/u][/color]');
                }
                var sale_str = sale_str_list.join(', ');
                if(sale_str.length > 0) {
                    dialog.widgets['sale_label'].show = dialog.widgets['sale_text'].show = true;
                    var sale_and_more = ' ... [color=#'+link_color+'][u][sku='+hack['plus_store_category']+'/]'+
                        dialog.data['widgets']['sale_text']['ui_name_more'] +'[/sku][/u][/color]';
                    Showcase.append_bbcode_text_with_line_breaking(dialog.widgets['sale_text'], sale_str, null, system_chat_bbcode_click_handlers, sale_and_more);
                }
            }
        }
    }

    // RANDOM REWARD ITEMS
    if('ui_random_rewards_text' in hack) { dialog.widgets['random_rewards_title'].str = eval_cond_or_literal(hack['ui_random_rewards_text'], player, null); }
    var item_list = ('feature_random_items' in hack ? eval_cond_or_literal(hack['feature_random_items'], player, null) : []);
    if(item_list) {
        ItemDisplay.display_item_array(dialog, 'random_rewards', item_list,
                                       {max_count_limit: ('feature_random_item_count' in hack) ? eval_cond_or_literal(hack['feature_random_item_count'], player, null) : -1,
                                        permute: true, glow: false});
    }

    // PROGRESSION REWARD ITEMS
    if('progression_reward_items' in hack) {
        dialog.widgets['progression_rewards_bg'].show = true;

        // this will be a list of [{"level": N, "loot": {"spec": ...}}, ... ]
        // where "loot" can also be a "multi", "cond", or random-choice array,
        // similar but NOT identical to an actual loot table.
        var progression_item_list = eval_cond_or_literal(hack['progression_reward_items'], player, null) || [];

        var flatten_loot = function(loot) {
            if(loot === null) {
                return [];
            } else if('spec' in loot) {
                return [loot];
            } else if('multi' in loot) {
                return flatten_loot(loot['multi']);
            } else if('cond' in loot) {
                for(var i = 0; i < loot['cond'].length; i++) {
                    if(read_predicate(loot['cond'][i][0]).is_satisfied(player, null)) {
                        return flatten_loot(loot['cond'][i][1]);
                    }
                }
            } else if(loot instanceof Array) {
                var ret = [];

                for(var i = 0; i < loot.length; i++) {
                    ret = ret.concat(flatten_loot(loot[i]));
                }

                return ret;
            } else {
                throw Error('invalid entry in progression_reward_items' + JSON.stringify(loot));
            }
        };

        // returns an array of the form [min, max] where min and max represent the minimum and maximum
        // number of items that will drop from a given loot table
        var get_loot_drop_count = function(loot) {
            if(loot === null) {
                return [0, 0];
            } else if('spec' in loot) {
                return [1, 1];
            } else if('multi' in loot) {
                var ret = [0, 0];

                for(var i = 0; i < loot['multi'].length; i++) {
                    var sub_count = get_loot_drop_count(loot['multi'][i]);

                    ret[0] += sub_count[0];
                    ret[1] += sub_count[1];
                }

                return ret;
            } else if('cond' in loot) {
                for(var i = 0; i < loot['cond'].length; i++) {
                    if(read_predicate(loot['cond'][i][0]).is_satisfied(player, null)) {
                        return get_loot_drop_count(loot['cond'][i][1]);
                    }
                }
            } else if(loot instanceof Array) {
                var ret = [Infinity, 0];

                for(var i = 0; i < loot.length; i++) {
                    var sub_count = get_loot_drop_count(loot[i]);

                    ret[0] = Math.min(ret[0], sub_count[0]);
                    ret[1] = Math.max(ret[1], sub_count[1]);
                }

                return ret;
            } else {
                throw Error('invalid entry in progression_reward_items' + JSON.stringify(loot));
            }
        };

        // simplify each entry in progression_item_list so that entry['item'] is either
        // a single item or an array of items that may drop on that level
        progression_item_list = goog.array.map(progression_item_list,
            function(entry) {
                // we need to get the drop count before we remove the structure of the loot table
                var count = get_loot_drop_count(entry['loot']);
                var flattened = flatten_loot(entry['loot']);

                if(flattened.length < 1) {
                    return null;
                }
                if(entry['level'] > unskipped_level_progress) {
                    return {'level': entry['level'], 'count': count, 'loot': flattened};
                } else { // fake entry that represents an already-obtained loot drop
                    return {'level': entry['level'], 'count': [1, 1], 'loot': {'spec': 'already_collected'}};
                }
            }
        );

        // get rid of null entries
        progression_item_list = goog.array.filter(progression_item_list, function(x) { return x !== null; });

        // create just a list of [{"spec": ...}, ... ]
        var raw_item_list = goog.array.map(progression_item_list,
            function(entry) {
                if(entry['loot'] instanceof Array) {
                    return entry['loot'][0];
                } else {
                    return entry['loot'];
                }
            }
        );

        var array_dims = dialog.data['widgets']['progression_rewards']['array'];

        // space out the widgets nicely
        dialog.update_array_widget_positions('progression_rewards', raw_item_list.length);
        goog.array.forEach(['highlight', 'header', 'level', 'count'], function(n) {
            for(var x = 0; x < array_dims[0]; x++) {
                // copy translation/visibility from "slot" example widget to each individual widget
                // (keeping in mind some art not sized the same as the 50x50 icon!)
                var master = dialog.widgets[SPUI.get_array_widget_name('progression_rewards', array_dims, [x,0])];
                var w = dialog.widgets[SPUI.get_array_widget_name('progression_rewards_'+n, array_dims, [x,0])];
                w.show = master.show = (x < raw_item_list.length);
                if(master.show) {
                    w.xy = vec_add(master.xy, vec_sub(dialog.data['widgets']['progression_rewards_'+n]['xy'],
                                                      dialog.data['widgets']['progression_rewards']['xy']));
                }
            }
        });

        ItemDisplay.display_item_array(dialog, 'progression_rewards', raw_item_list, {glow:true, hide_stack:true});

        // set level numbers below items and DONE/NEXT headers above items
        var next_displayed = false;
        for(var y = 0; y < array_dims[1]; y++) {
            for(var x = 0; x < array_dims[0]; x++) {
                var i = y * array_dims[0] + x;

                if(i < progression_item_list.length) {
                    var header = dialog.widgets[SPUI.get_array_widget_name('progression_rewards_header', array_dims, [x,y])];
                    var level = dialog.widgets[SPUI.get_array_widget_name('progression_rewards_level', array_dims, [x,y])];
                    var highlight = dialog.widgets[SPUI.get_array_widget_name('progression_rewards_highlight', array_dims, [x,y])];
                    var count = dialog.widgets[SPUI.get_array_widget_name('progression_rewards_count', array_dims, [x,y])];

                    var progression_item = progression_item_list[i];

                    level.str = dialog.data['widgets']['progression_rewards_level']['ui_name'].replace('%d', (level_map[progression_item['level']-1]+1).toString());

                    // set headers text and highlight the next reward
                    if(unskipped_level_progress >= progression_item['level']) {
                        header.show = true;
                        highlight.show = false;
                        header.str = dialog.data['widgets']['progression_rewards_header']['ui_name_done'];
                        header.text_color = new SPUI.Color(0, 0, 0, 1);
                        level.text_color = new SPUI.Color(0, 0, 0, 1);
                    } else if(!next_displayed) {
                        header.show = true;
                        highlight.show = true;
                        header.str = dialog.data['widgets']['progression_rewards_header']['ui_name_next'];
                        header.text_color = new SPUI.Color(1, 1, 1, 1);
                        level.text_color = new SPUI.Color(1, 1, 1, 1);
                        next_displayed = true;
                    } else {
                        header.show = true;
                        highlight.show = false;
                    }

                    if(progression_item.count[0] > 1 || progression_item.count[1] > 1) {
                        // there's more than 1 drop from this level, so show the drop count
                        count.show = true;

                        if(progression_item.count[0] == progression_item.count[1]) {
                            // this level drops a set number of items
                            count.str = dialog.data['widgets']['progression_rewards_count']['ui_name_constant'].replace('%d', progression_item.count[0]);
                        } else {
                            // this level can drop a variable number of items
                            count.str = dialog.data['widgets']['progression_rewards_count']['ui_name_range'].replace('%d', progression_item.count[0])
                                                                                                               .replace('%d', progression_item.count[1]);
                        }
                    }
                }
            }
        }

        // set up so we can switch the icon for levels that drop multiple items
        dialog.user_data['anim_start'] = client_time;
        dialog.user_data['progression_item_list'] = progression_item_list;
        dialog.ondraw = update_progression_rewards;
    }

    // PROGRESSION REWARD TEXT
    if('ui_progression_text' in hack) {
        var text = eval_cond_or_literal(hack['ui_progression_text'], player, null);
        if(text) {
            dialog.widgets['progression_text'].show = true;
            var link_color = SPUI.make_colorv(dialog.data['widgets']['progression_text']['link_color']).hex();
            while(text.indexOf('%TOKEN') != -1) { text = text.replace('%TOKEN', token_item_name); }
            if(hack['plus_store_category'] && plus_store_category_name) {
                // make hyperlink to the event_prizes store category, if possible
                text = text.replace('%PLUS_STORE_CATEGORY', '[color=#' + link_color + '][u][sku=' + hack['plus_store_category'] + '/]' + plus_store_category_name + '[/sku][/u][/color]');
            } else {
                text = text.replace('%PLUS_STORE_CATEGORY', token_item_name);
            }
            dialog.widgets['progression_text'].append_text(SPText.cstring_to_ablocks_bbcode(text, null, system_chat_bbcode_click_handlers));
        }
    }

};

/** Switches the icons used for progression rewards on levels with multiple potential drops
    @param dialog
    @private
 */
function update_progression_rewards(dialog) {
    // blink progression item icons for levels that drop multiple rewards
    if('progression_item_list' in dialog.user_data) {
        var progression_item_list = dialog.user_data['progression_item_list'];
        var period = dialog.data['widgets']['progression_rewards']['blink_period'];

        for(var i = 0; i < Math.min(progression_item_list.length, dialog.data['widgets']['progression_rewards']['array'][0]); i++) {
            var loot = progression_item_list[i]['loot'];

            // only change the item displayed if the level drops multiple items
            if(loot instanceof Array && loot.length > 1) {
                var index = (Math.floor(((client_time - dialog.user_data['anim_start'] + period/2)/period) % loot.length) + loot.length) % loot.length;
                var wname = SPUI.get_array_widget_name('progression_rewards', dialog.data['widgets']['progression_rewards']['array'], [i, 0]);
                ItemDisplay.display_item(dialog.widgets[wname], loot[index], {glow:true, hide_stack:true});
            }
        }
    }
}

// return true if the predicate 'pred' reads a player history key string that is in the list 'keylist'
Showcase.predicate_reads_keys = function(pred, keylist) {
    if(pred['predicate'] == 'PLAYER_HISTORY') {
        if(goog.array.find(keylist, function (key) { return pred['key'] == key; }) != null) {
            return true;
        }
    } else if('subpredicates' in pred) {
        if(goog.array.find(pred['subpredicates'], function(sub) { return Showcase.predicate_reads_keys(sub, keylist); }) != null) {
            return true;
        }
    }
    return false;
};

// returns the number of (total, complete) achievements that involve any of the passed-in list of player history keys
Showcase.count_achievements = function(keylist) {
    var total = 0, completed = 0;
    goog.object.forEach(gamedata['achievements'], function(ach) {
        var cat = gamedata['achievement_categories'][ach['category']];
        if('activation' in cat && !read_predicate(cat['activation']).is_satisfied(player,null)) { return; }
        if('show_if' in cat && !read_predicate(cat['show_if']).is_satisfied(player,null)) { return; }
        if('activation' in ach && !read_predicate(ach['activation']).is_satisfied(player,null)) { return; }
        if('show_if' in ach && !read_predicate(ach['show_if']).is_satisfied(player,null)) { return; }
        if(Showcase.predicate_reads_keys(ach['goal'], keylist)) {
            total += 1;
            if(ach['name'] in player.achievements) {
                completed += 1;
            }
        }
    });
    return [total, completed];
};

// count how many active SKUs are for sale in a part of the store catalog, recursively
Showcase.collect_active_sku_count = function(sku, ignore_list) { // note: sku can be an individual sku or a folder with a 'skus' member
    if(('show_if' in sku) && !(read_predicate(sku['show_if']).is_satisfied(player, null))) { return 0; }
    if('skus' in sku) {
        var total = 0;
        goog.array.forEach(sku['skus'], function(child) {
            total += Showcase.collect_active_sku_count(child, ignore_list);
        });
        return total;
    } else if (('item' in sku) || ('spell' in sku)) {
        if(goog.array.contains(ignore_list, sku['item'] || sku['spell'])) { return 0; }
        return 1;
    }
    return 0;
};
// count how many active SKUs are for sale in each top-level child of a given folder
// ignore any SKUs with 'item' or 'spell' in ignore_list
Showcase.collect_child_sku_counts = function(sku, ignore_list) { // note: sku must be a folder with a 'skus' member
    var ret = [];
    goog.array.forEach(sku['skus'], function(child) {
        if(!('skus' in child)) { return; } // not a folder
        ret.push({'name': child['name'], 'ui_name': child['ui_name'], 'count': Showcase.collect_active_sku_count(child, ignore_list)});
    });
    return ret;
};

// returns list of [{'path':'event_prizes/etc', 'ui_name':''}] of any SKU sales that are currently on
/** @param {!Object} sku - can be an individual sku or a folder with a 'skus' member
    @param {string=} path */
Showcase.collect_active_sales_data = function(sku, path) {
    if(!path) { path = ''; }
    if(('show_if' in sku) && !(read_predicate(sku['show_if']).is_satisfied(player, null))) { return []; }

    if('skus' in sku) {
        var sales = [];
        goog.array.forEach(sku['skus'], function(child) {
            // do not duplicate entries when they are duplicated in the store under different paths
            var child_sales = Showcase.collect_active_sales_data(child, path+(sku['name'] ? sku['name']+'/' : ''));
            goog.array.forEach(child_sales, function(cs) {
                if(!goog.array.find(sales, function(x) { return x['ui_name'] == cs['ui_name']; })) {
                    sales.push(cs);
                }
            });
            //sales = sales.concat();
        });
        return sales;
    } else if (('item' in sku) && ('ui_banner' in sku) && (eval_cond_or_literal(sku['ui_banner'], player, null)||'').toUpperCase().indexOf("SALE") != -1) {
        if(('show_if' in sku) && !(read_predicate(sku['show_if']).is_satisfied(player, null))) { return []; }
        var sale = {'path': path + sku['item']};
        var item_ui_name = ItemDisplay.get_inventory_item_ui_name(ItemDisplay.get_inventory_item_spec(sku['item']));
        var sale_ui_name = null;
        if('ui_name' in sku) { // SKU has a name override
            sale_ui_name = ''+sku['ui_name'];
            while(sale_ui_name.indexOf('\n') != -1) { // get rid of newlines
                sale_ui_name = sale_ui_name.replace('\n', ' ');
            }
        }
        // SKU name overrides item name
        // but, special case - if the SKU name is too long to fit the dialog, and the item name is shorter, then use the item name
        if(sale_ui_name && ((sale_ui_name.length < item_ui_name.length) || sale_ui_name.length < 33)) {
            sale['ui_name'] = sale_ui_name;
        } else {
            sale['ui_name'] = item_ui_name;
        }
        return [sale];
    }
    return [];
};
