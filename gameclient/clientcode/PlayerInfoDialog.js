goog.provide('PlayerInfoDialog');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
    Player Info dialog with Profile, Statistics, and Alliance History, and Achievements tabs.
    This references a ton of stuff from main.js. It's not a self-contained module.
*/

goog.require('SPUI');
goog.require('SPHTTP');
goog.require('SPText');
goog.require('FBShare');
goog.require('PlayerCache');
goog.require('AllianceCache');
goog.require('goog.array');
goog.require('goog.object');

/** @return {boolean} */
PlayerInfoDialog.player_alliance_membership_history_enabled = function(player) {
    var val = player.get_any_abtest_value('enable_player_alliance_membership_history', gamedata['client']['enable_player_alliance_membership_history']);
    return eval_cond_or_literal(val, player, null);
};

/** @typedef {!Object.<string,?>} */
PlayerInfoDialog.CachedInfo;

/** @param {number} uid
    @param {function(!SPUI.Dialog)|null=} cb
    @return {?SPUI.Dialog} - can be null if this goes asynchronous */
PlayerInfoDialog.invoke = function(uid, cb) {
    if(!cb) { cb = function(x) { return x; } }

    var after_query = (function (_uid, _cb) { return function() {
        var info = PlayerCache.query_sync(_uid);
        if(!info || (!info['social_id'] && !info['facebook_id'])) {
            var s = gamedata['errors']['CANNOT_GET_INFO_PLAYER_NOT_FOUND'];
            invoke_child_message_dialog(s['ui_title'], s['ui_name'].replace('%d', _uid.toString()), {'dialog':'message_dialog_big'});
            return null;
        }
        return _cb(PlayerInfoDialog._invoke(info['user_id'], info));
    }; })(uid, cb);

    if(PlayerCache.query_sync_fetch(uid)) {
        return after_query();
    } else {
        PlayerCache.launch_batch_queries(client_time, true); // force query to go out before request_sync
        invoke_ui_locker(synchronizer.request_sync(), after_query);
        return null;
    }
};

/** @private
    @param {number} user_id
    @param {!PlayerInfoDialog.CachedInfo} info
    @return {!SPUI.Dialog} */
PlayerInfoDialog._invoke = function(user_id, info) {
    var dialog = new SPUI.Dialog(gamedata['dialogs']['player_info_frame']);
    dialog.user_data['dialog'] = 'player_info_frame';
    dialog.user_data['user_id'] = user_id;
    dialog.user_data['info'] = info;

    install_child_dialog(dialog);
    dialog.auto_center();
    dialog.modal = true;

    dialog.widgets['close_button'].onclick = close_parent_dialog;
    dialog.widgets['screenshot_button'].show = post_screenshot_enabled();
    dialog.widgets['screenshot_button'].onclick = function(w) {
        var dialog = w.parent;
        invoke_post_screenshot(dialog, /* reason = */ dialog.widgets['tab'].user_data['dialog'],
                               make_post_screenshot_caption(dialog.data['widgets']['screenshot_button']['ui_caption'], dialog.user_data['info']));
    };

    dialog.widgets['alliance_history_button'].onclick = function(w) { PlayerInfoDialog.invoke_alliance_history_tab(w.parent); };
    dialog.widgets['statistics_button'].onclick = function(w) { PlayerInfoDialog.invoke_statistics_tab(w.parent); };
    dialog.widgets['achievements_button'].onclick = function(w) { PlayerInfoDialog.invoke_achievements_tab(w.parent); };
    dialog.widgets['profile_button'].onclick = function(w) { PlayerInfoDialog.invoke_profile_tab(w.parent); };
    dialog.widgets['profile_button'].onclick(dialog.widgets['profile_button']);
    return dialog;
};

/** @param {!PlayerInfoDialog.CachedInfo} info
    @return {string} */
PlayerInfoDialog.format_name_with_level = function(info) {
    var ret = PlayerCache.get_ui_name(info);
    if('player_level' in info) {
        ret += ' L'+info['player_level'].toString();
    }
    return ret;
};

/** @param {!SPUI.Dialog} parent
    @param {Object|null=} preselect this {'time': ['season',3]}
    @return {!SPUI.Dialog} */
PlayerInfoDialog.invoke_statistics_tab = function(parent, preselect) {
    var user_id = parent.user_data['user_id'];
    var knowledge = parent.user_data['info'];

    player.record_feature_use(user_id === session.user_id ? 'own_statistics' : 'other_statistics');

    if('tab' in parent.widgets) {
        if(parent.widgets['tab'].user_data['dialog'] == 'player_info_statistics_tab') {
            // we're already up
            return parent.widgets['tab'];
        }
        parent.remove(parent.widgets['tab']);
        delete parent.widgets['tab'];
    }

    parent.widgets['statistics_button'].state = 'pressed';
    parent.widgets['profile_button'].state = 'normal';
    parent.widgets['achievements_button'].state = 'normal';
    parent.widgets['alliance_history_button'].state = 'normal';
    parent.widgets['alliance_history_button'].show = PlayerInfoDialog.player_alliance_membership_history_enabled(player);

    var dialog = new SPUI.Dialog(gamedata['dialogs']['player_info_statistics_tab']);
    dialog.transparent_to_mouse = true;
    dialog.user_data['dialog'] = 'player_info_statistics_tab';
    dialog.user_data['user_id'] = user_id;

    dialog.widgets['player_name'].str = PlayerInfoDialog.format_name_with_level(knowledge);
    dialog.widgets['player_id'].str = dialog.data['widgets']['player_id']['ui_name'].replace('%d', user_id.toString());

    var url = player.get_any_abtest_value('score_history_show_other_url', gamedata['client']['score_history_show_other_url'] || null);
    if(url) {
        url = url_put_info(url, session.user_id, player.history['money_spent']||0);
        dialog.widgets['show_other_button'].show = true;
        dialog.widgets['show_other_button'].onclick = (function (_url) { return function(w) {
            url_open_in_new_tab(_url);
        }; })(url);
    }

    parent.widgets['tab'] = dialog;
    parent.add(dialog);

    // which time scope to show - pretty much only works with "season"
    dialog.user_data['time_scope'] = 'season'; // gamedata['matchmaking']['ladder_point_frequency'];
    if(!goog.array.contains(['week','season'], dialog.user_data['time_scope'])) { throw Error('unknown time scope '+dialog.user_data['time_scope']); }

    // time_loc we're at right now
    dialog.user_data['time_cur'] = {'week': current_pvp_week(), 'season': current_pvp_season()}[dialog.user_data['time_scope']];

    // how far back in time we offer queries for
    if(dialog.user_data['time_scope'] == 'week') {
        dialog.user_data['time_limit'] = Math.max(1, dialog.user_data['time_cur']-5); // limit query to 5 historical entries
    } else if(dialog.user_data['time_scope'] == 'season') {
        dialog.user_data['time_limit'] = Math.min(dialog.user_data['time_cur'], Math.max(1, -(gamedata['matchmaking']['season_ui_offset']||0) + 1));
    }

    // which time_loc is actually displayed
    // -1 means "ignore time_scope, use ALL scope and 0 loc", i.e. All Time
    dialog.user_data['time_displayed'] = null;

    // since queries are asynchronous, make sure that only the last one to arrive actually updates the GUI
    dialog.user_data['query_gen'] = 0;

    dialog.user_data['show_rank'] = true;

    // show "all time" by default
    var default_loc = -1; // dialog.user_data['time_cur']);
    if(preselect && ('time' in preselect)) {
        if(preselect['time'][0] == 'ALL') {
            default_loc = -1;
        } else {
            default_loc = preselect['time'][1];
        }
    }

    PlayerInfoDialog.statistics_tab_select(dialog, default_loc);
    return dialog;
};

/** select a new time_loc
    @param {!SPUI.Dialog} dialog
    @param {number} new_loc */
PlayerInfoDialog.statistics_tab_select = function(dialog, new_loc) {
    if(dialog.user_data['time_displayed'] == new_loc) {
        // nothing to do
        return;
    }
    if(dialog.widgets['loading_text'].show) { return; } // don't overlap

    dialog.user_data['time_displayed'] = new_loc;

    // update BBCode for time-loc selection bar
    var selector = [[]];
    selector[0] = selector[0].concat(SPText.cstring_to_ablocks_bbcode(dialog.data['widgets']['selector']['ui_name'])[0]);

    // ALL TIME
    var ui_current = dialog.data['widgets']['selector']['ui_name_alltime'].replace('%scope', gamedata['strings']['leaderboard']['periods'][dialog.user_data['time_scope']]['name']);
    var is_selected = (dialog.user_data['time_displayed'] == -1);
    ui_current = dialog.data['widgets']['selector'][(is_selected ? 'ui_format_selected' : 'ui_format_unselected')].replace('%thing', ui_current);
    selector[0] = selector[0].concat(SPText.cstring_to_ablocks_bbcode(ui_current, {onclick:
                                                                                   (function(_dialog) { return function() {
                                                                                       PlayerInfoDialog.statistics_tab_select(_dialog, -1);
                                                                                   }; })(dialog)})[0]);

    // CURRENT LOC
    selector[0] = selector[0].concat(SPText.cstring_to_ablocks_bbcode(dialog.data['widgets']['selector']['ui_separator'])[0]);
    ui_current = dialog.data['widgets']['selector']['ui_name_current'].replace('%scope', gamedata['strings']['leaderboard']['periods'][dialog.user_data['time_scope']]['name']);
    is_selected = (dialog.user_data['time_displayed'] == dialog.user_data['time_cur']);
    ui_current = dialog.data['widgets']['selector'][(is_selected ? 'ui_format_selected' : 'ui_format_unselected')].replace('%thing', ui_current);
    selector[0] = selector[0].concat(SPText.cstring_to_ablocks_bbcode(ui_current, {onclick:
                                                                                   (function(_dialog) { return function() {
                                                                                       PlayerInfoDialog.statistics_tab_select(_dialog, _dialog.user_data['time_cur']);
                                                                                   }; })(dialog)})[0]);
    // HISTORICAL LOCS
    for(var time_loc = dialog.user_data['time_cur'] - 1; time_loc >= dialog.user_data['time_limit']; time_loc -= 1) {
        selector[0] = selector[0].concat(SPText.cstring_to_ablocks_bbcode(dialog.data['widgets']['selector']['ui_separator'])[0]);
        var ui_prev = dialog.data['widgets']['selector']['ui_name_prev'].replace('%scope', gamedata['strings']['leaderboard']['periods'][dialog.user_data['time_scope']]['name']).replace('%loc', (time_loc + (dialog.user_data['time_scope'] == 'season' ? (gamedata['matchmaking']['season_ui_offset']||0) : 0)).toFixed(0));
        is_selected = (dialog.user_data['time_displayed'] == time_loc);
        ui_prev = dialog.data['widgets']['selector'][(is_selected ? 'ui_format_selected' : 'ui_format_unselected')].replace('%thing', ui_prev);
        selector[0] = selector[0].concat(SPText.cstring_to_ablocks_bbcode(ui_prev, {onclick:
                                                                                    (function(_dialog, _time_loc) { return function() {
                                                                                        PlayerInfoDialog.statistics_tab_select(_dialog, _time_loc);
                                                                                    }; })(dialog, time_loc)})[0]);
    }

    dialog.widgets['selector'].clear_text();
    dialog.widgets['selector'].append_text(selector);

    // perform the query

    // which stats to query - for now, hard-coded to be a subset of the ones recorded in Scores2
    dialog.user_data['stats'] = goog.array.filter(['trophies_pvp','trophies_pvv','tokens_looted','achievement_points','resources_looted',
                                                   'damage_inflicted','havoc_caused','hive_kill_points','quarry_resources','strongpoint_resources'],
                                                  function(stat) { return (stat in gamedata['strings']['leaderboard']['categories']) &&
                                                                   ('group' in gamedata['strings']['leaderboard']['categories'][stat]) &&
                                                                   ('statistics_show_if' in gamedata['strings']['leaderboard']['categories'][stat]) &&
                                                                   read_predicate(gamedata['strings']['leaderboard']['categories'][stat]['statistics_show_if']).is_satisfied(player,null); });

    // list of queries to send
    var qls = [];
    var scope = (dialog.user_data['time_displayed'] == -1 ? 'ALL' : dialog.user_data['time_scope']);
    var loc = (dialog.user_data['time_displayed'] == -1 ? 0 : dialog.user_data['time_displayed']);
    goog.array.forEach(dialog.user_data['stats'], function(stat) {
        qls.push([stat, scope, loc]);
    });
    dialog.user_data['query_gen'] += 1;
    query_player_scores([dialog.user_data['user_id']], qls, (function(_dialog, _query_gen) { return function(user_ids, data, status_code) {
        PlayerInfoDialog.statistics_tab_receive(_dialog, data, status_code, _query_gen);
    }; })(dialog, dialog.user_data['query_gen']), {get_rank:dialog.user_data['show_rank']});

    dialog.widgets['loading_rect'].show =
        dialog.widgets['loading_text'].show =
        dialog.widgets['loading_spinner'].show = true;
    dialog.widgets['share_button'].show = false;
    dialog.widgets['output'].clear_text();
    dialog.widgets['scroll_up'].onclick = function (w) { PlayerInfoDialog.statistics_tab_scroll(w.parent, -1); };
    dialog.widgets['scroll_down'].onclick = function (w) { PlayerInfoDialog.statistics_tab_scroll(w.parent, 1); };
    PlayerInfoDialog.statistics_tab_scroll(dialog, 0);
    return dialog;
};

/** @param {!SPUI.Dialog} dialog
    @param {number} incr */
PlayerInfoDialog.statistics_tab_scroll = function(dialog, incr) {
    if(incr < 0) {
        dialog.widgets['output'].scroll_up();
    } else if(incr > 0) {
        dialog.widgets['output'].scroll_down();
    }

    // set clickability of scroll arrows
    dialog.widgets['scroll_up'].state = (dialog.widgets['output'].can_scroll_up() ? 'normal' : 'disabled');
    dialog.widgets['scroll_down'].state = (dialog.widgets['output'].can_scroll_down() ? 'normal' : 'disabled');
};

/** @param {!SPUI.Dialog} dialog
    @param {string} stat
    @param {number} val
    @param {number} rank
    @param {!Object.<string, !Object<string, !SPText.ABlockParagraphs> >} by_group */
PlayerInfoDialog.statistics_tab_format_stat = function(dialog, stat, val, rank, by_group) {
    var catdata = gamedata['strings']['leaderboard']['categories'][stat];
    var display_mode = catdata['display'] || 'integer';
    var ui_val;
    if(display_mode == 'integer') {
        ui_val = pretty_print_number(val);
    } else if(display_mode == 'seconds') {
        ui_val = pretty_print_time_brief(val);
    } else if(display_mode == 'days') {
        ui_val = (val/86400).toFixed(0);
    } else {
        throw Error('unknown display_mode '+display_mode);
    }
    var ui_stat = dialog.data['widgets']['output'][(rank >= 0 ? 'ui_stat_ranked' : 'ui_stat')].replace('%stat', catdata['title']).replace('%val', ui_val);
    if(rank >= 0) { ui_stat = ui_stat.replace('%rank', pretty_print_number(rank+1)); }

    var result = SPText.cstring_to_ablocks_bbcode(ui_stat, {tooltip_func:
                                                            (function (_catdata) { return function() {
                                                                return _catdata['description'];
                                                            }; })(catdata)
                                                           });
    // append the result to the proper entry in by_group
    if(!(catdata['group'] in by_group)) {
        by_group[catdata['group']] = {};
    }
    by_group[catdata['group']][stat] = result;
};

/** @param {!SPUI.Dialog} dialog
    @param {?} data
    @param {?string} status_code
    @param {number} query_gen */
PlayerInfoDialog.statistics_tab_receive = function(dialog, data, status_code, query_gen) {
    if(!dialog.parent) { return; } // dialog got closed asynchronously
    if(query_gen != dialog.user_data['query_gen']) { return; } // over-ridden by a later query

    var stats = dialog.user_data['stats'];

    if(data !== null && data.length == 1) {
        dialog.widgets['loading_rect'].show =
            dialog.widgets['loading_text'].show =
            dialog.widgets['loading_spinner'].show = false;

        dialog.widgets['output'].clear_text();

        if(status_code == 'SCORES_OFFLINE') {
            dialog.widgets['output'].append_text([]); // add a blank line
            dialog.widgets['output'].append_text(SPText.cstring_to_ablocks(gamedata['errors']['SCORES_OFFLINE']['ui_name']));
            dialog.widgets['output'].append_text([]); // add a blank line
        }

        var has_top_rank = false; // controls appearance of "Share" button
        var by_group = {}; // mapping from group name -> stat name -> string to display
        var player_data = data[0];

        goog.array.forEach(stats, function(stat, i) {
            if(player_data[i]) {
                var val = player_data[i]['absolute'] || 0;
                var rank = ('rank' in player_data[i] ? player_data[i]['rank'] : -1);
                if(rank >= 0 && rank < 100) {
                    has_top_rank = true;
                }
                PlayerInfoDialog.statistics_tab_format_stat(dialog, stat, val, rank, by_group);
            }
        });

        // if looking at your own "all time" data, add some "fake" stats that are just player history keys
        if(dialog.user_data['user_id'] == session.user_id && dialog.user_data['time_displayed'] == -1) {
            goog.object.forEach({
                'resources_looted_from_human': player.history['resources_looted_from_human'] || 0,
                'resources_stolen_by_human': player.history['resources_stolen_by_human'] || 0,
                'attacks_launched_vs_human': player.history['attacks_launched_vs_human'] || 0,
                // time_in_game is updated on logout, so add current session time
                'time_in_game': player.history['time_in_game'] + (client_time - session.connect_time),
                'account_age': server_time - player.creation_time},
                                function(val, stat) {
                                    if((stat in gamedata['strings']['leaderboard']['categories']) &&
                                       ('group' in gamedata['strings']['leaderboard']['categories'][stat]) &&
                                       ('statistics_show_if' in gamedata['strings']['leaderboard']['categories'][stat]) &&
                                       read_predicate(gamedata['strings']['leaderboard']['categories'][stat]['statistics_show_if']).is_satisfied(player, null)) {
                                        PlayerInfoDialog.statistics_tab_format_stat(dialog, stat, val, -1, by_group);
                                    }
                                });
        }

        if(goog.object.getCount(by_group) < 1) {
            dialog.widgets['output'].append_text([]); // add a blank line
            dialog.widgets['output'].append_text(SPText.cstring_to_ablocks_bbcode(dialog.data['widgets']['output']['ui_name_nostats']));
        } else {
            var delay_warn = null;
            if(dialog.user_data['time_displayed'] >= 0 && dialog.user_data['time_displayed'] < dialog.user_data['time_cur']-1) {
                // technically past-time queries are not "hot", but they can't be affected by players anymore, so don't show delay warning
                delay_warn = 'history';
            } else {
                // note: please keep in sync with gameserver/server.py: is_hot_point
                var is_hot = (dialog.user_data['time_displayed'] == dialog.user_data['time_cur'] ||
                              (dialog.user_data['time_displayed'] == -1 && gamedata['scores2_time_all_is_hot']));
                delay_warn = (is_hot ? 'hot' : 'cold');
            }
            if(delay_warn) {
                var s = dialog.data['widgets']['output']['ui_name_delay_'+delay_warn];
                if(s) {
                    dialog.widgets['output'].append_text(SPText.cstring_to_ablocks_bbcode(s));
                }
            }
            dialog.widgets['output'].append_text([]); // add a blank line

            // sort groups by priority, then alphabet
            var sort_by_priority = function (db) { return function(a,b) {
                var pa = db[a]['priority'] || 0, pb = db[b]['priority'] || 0;
                var na = db[a]['title'], nb = db[b]['title'];
                if(pa > pb) { return -1; }
                else if(pa < pb) { return 1; }
                else if(na > nb) { return 1; }
                else if(na < nb) { return -1; }
                else { return 0; }
            }; };

            var group_keys = goog.object.getKeys(by_group).sort(sort_by_priority(gamedata['strings']['leaderboard']['stat_groups']));
            goog.array.forEach(group_keys, function(group_name, i) {
                var group_data = gamedata['strings']['leaderboard']['stat_groups'][group_name];
                var ui_group = group_data['title'].toUpperCase();
                if(i > 0) { dialog.widgets['output'].append_text([]); } // add a blank line
                dialog.widgets['output'].append_text(SPText.cstring_to_ablocks_bbcode(dialog.data['widgets']['output']['ui_group_header'].replace('%group', ui_group)));

                // sort stats
                var stat_keys = goog.object.getKeys(by_group[group_name]).sort(sort_by_priority(gamedata['strings']['leaderboard']['categories']));
                goog.array.forEach(stat_keys, function(stat_name) {
                    dialog.widgets['output'].append_text(by_group[group_name][stat_name]);
                });
            });
        }
        dialog.widgets['output'].scroll_to_top();
        PlayerInfoDialog.statistics_tab_scroll(dialog, 0);
        PlayerInfoDialog.statistics_tab_setup_share_button(dialog, has_top_rank);
    } else {
        dialog.widgets['share_button'].show = false;
        dialog.widgets['loading_text'].str = dialog.data['widgets']['loading_text']['ui_name_unavailable'];
        dialog.widgets['loading_spinner'].show = false;
    }
};

/** @param {!SPUI.Dialog} dialog */
PlayerInfoDialog.statistics_tab_setup_share_button = function(dialog, has_top_rank) {
    if(spin_frame_platform != 'fb' || !gamedata['virals']['stats_share'] ||
       !player.get_any_abtest_value('enable_player_info_statistics_share_button',
                                    gamedata['client']['enable_player_info_statistics_share_button'])) {
        return;
    }
    dialog.widgets['share_button'].show = true;
    dialog.widgets['share_button'].str = dialog.data['widgets']['share_button'][(has_top_rank ? 'ui_name_top' : 'ui_name')];
    if(post_screenshot_enabled()) {
        dialog.widgets['share_button'].onclick = function(w) {
            if(w.parent && w.parent.parent) {
                w.parent.parent.widgets['screenshot_button'].onclick(w.parent.parent.widgets['screenshot_button']);
            }
        };
    } else {
        dialog.widgets['share_button'].onclick = function(w) {
            var dialog = w.parent;
            var viral = gamedata['virals']['stats_share'];
            var val = {'user_id': dialog.user_data['user_id'],
                       'preselect': {'time': [dialog.user_data['time_displayed'] == -1 ? 'ALL' : dialog.user_data['time_scope'],
                                              dialog.user_data['time_displayed']]}};
            FBShare.invoke({link_qs: {'player_info_statistics': JSON.stringify(val)},
                            name: viral['ui_post_headline'],
                            ref: 'stats_share', // 15-char limit
                           });
        };
    }
};


/** @param {!SPUI.Dialog} parent */
PlayerInfoDialog.invoke_profile_tab = function(parent) {
    var user_id = parent.user_data['user_id'];
    var knowledge = parent.user_data['info'];

    var z_index = -1;
    if('tab' in parent.widgets) {
        z_index = parent.get_z_index(parent.widgets['tab']);
        parent.remove(parent.widgets['tab']);
        delete parent.widgets['tab'];
    }

    parent.widgets['profile_button'].state = 'pressed';
    parent.widgets['achievements_button'].state = 'normal';
    parent.widgets['achievements_button'].show = player.get_any_abtest_value('enable_ingame_achievements', gamedata['client']['enable_ingame_achievements'] || false);
    parent.widgets['alliance_history_button'].state = 'normal';
    parent.widgets['alliance_history_button'].show = PlayerInfoDialog.player_alliance_membership_history_enabled(player);

    parent.widgets['statistics_button'].state = 'normal';
    parent.widgets['statistics_button'].show = player.get_any_abtest_value('enable_score_history', gamedata['client']['enable_score_history']);

    var dialog = new SPUI.Dialog(gamedata['dialogs']['player_info_profile_tab']);
    dialog.transparent_to_mouse = true;
    dialog.user_data['dialog'] = 'player_info_profile_tab';
    dialog.user_data['user_id'] = user_id;
    dialog.user_data['alliance_query_sent'] = false;
    dialog.user_data['open_time'] = client_time;
    dialog.user_data['categories'] = goog.array.filter(['conquests', 'resources_looted', 'havoc_caused', 'damage_inflicted'],
                                                       function(stat) { return (stat in gamedata['strings']['leaderboard']['categories']) &&
                                                                        ('leaderboard_show_if' in gamedata['strings']['leaderboard']['categories'][stat]) &&
                                                                        read_predicate(gamedata['strings']['leaderboard']['categories'][stat]['leaderboard_show_if']).is_satisfied(player, null); });
    dialog.user_data['periods'] = ['week', 'season'];
    dialog.user_data['period'] = 'week';
    dialog.user_data['score_query_sent'] = {};
    dialog.user_data['tournament_end_time'] = -1;
    dialog.user_data['scores'] = [];
    dialog.user_data['cache'] = null; // stores result of player cache query
    parent.widgets['tab'] = dialog;
    if(z_index >= 0) {
        parent.add_at_index(dialog, z_index);
    } else {
        parent.add(dialog);
    }

    dialog.widgets['id_number'].str = user_id.toString();

    dialog.widgets['name'].str = PlayerCache.get_ui_name(knowledge);
    if('real_name' in knowledge && knowledge['real_name'] != dialog.widgets['name'].str) {
        dialog.widgets['name'].str += ' ('+knowledge['real_name']+')';
        dialog.widgets['name_label'].str = dialog.data['widgets']['name_label']['ui_name_alias'];
    } else {
        dialog.widgets['name_label'].str = dialog.data['widgets']['name_label']['ui_name'];
    }

    // set alias button
    if(('SET_ALIAS' in gamedata['spells']) && user_id == session.user_id) {
        var spell = gamedata['spells']['SET_ALIAS'];
        if(!('show_if' in spell) || read_predicate(spell['show_if']).is_satisfied(player, null)) {
            var req = read_predicate(spell['requires'] || {'predicate':'ALWAYS_TRUE'});
            if(req.is_satisfied(player, null)) {
                dialog.widgets['set_alias_button'].show = true;
                dialog.widgets['set_alias_button'].tooltip.str = dialog.data['widgets']['set_alias_button']['ui_tooltip'];
                dialog.widgets['set_alias_button'].tooltip.text_color = SPUI.default_text_color;
                dialog.widgets['set_alias_button'].onclick = function(w) {
                    var parent = w.parent.parent;
                    invoke_change_alias_dialog(
                        (function (_parent) { return function(spellarg) {
                            send_to_server.func(["SET_ALIAS", spellarg]);
                            invoke_ui_locker(null,
                                             // update when the response comes back
                                             (function (__parent) { return function() {
                                                 if(__parent.is_visible()) {
                                                     PlayerInfoDialog.invoke_profile_tab(__parent);
                                                 }
                                             }; })(_parent)
                                            );
                        }; })(parent),
                        'SET_ALIAS'
                    );
                };
            } else {
                //dialog.widgets['set_alias_button'].show = false;
                dialog.widgets['set_alias_button'].show = true;
                dialog.widgets['set_alias_button'].tooltip.text_color = SPUI.error_text_color;
                dialog.widgets['set_alias_button'].tooltip.str = req.ui_describe(player);
                dialog.widgets['set_alias_button'].onclick = get_requirements_help(req);
            }
        } else {
            dialog.widgets['set_alias_button'].show = false;
        }
    }

    // change title button
    if(('CHANGE_TITLE' in gamedata['spells']) && user_id == session.user_id) {
        var spell = gamedata['spells']['CHANGE_TITLE'];
        if(!('show_if' in spell) || read_predicate(spell['show_if']).is_satisfied(player, null)) {
            var req = read_predicate(spell['requires'] || {'predicate':'ALWAYS_TRUE'});
            dialog.widgets['change_title_button'].show = true;
            dialog.widgets['change_title_button'].str = spell['ui_name'];
            if(req.is_satisfied(player, null)) {
                dialog.widgets['change_title_button'].state = 'normal';
                dialog.widgets['change_title_button'].tooltip.str = null;
                dialog.widgets['change_title_button'].onclick = function(w) {
                    var parent = w.parent.parent;
                    invoke_change_title_dialog(
                        (function (_parent) { return function(spellarg) {
                            send_to_server.func(["CHANGE_TITLE", spellarg]);
                            invoke_ui_locker(null,
                                             // update when the response comes back
                                             (function (__parent) { return function() {
                                                 if(__parent.is_visible()) {
                                                     PlayerInfoDialog.invoke_profile_tab(__parent);
                                                 }
                                             }; })(_parent)
                                            );
                        }; })(parent),
                        'CHANGE_TITLE'
                    );
                };
            } else {
                dialog.widgets['change_title_button'].state = 'disabled_clickable';
                dialog.widgets['change_title_button'].onclick = get_requirements_help(req);
                dialog.widgets['change_title_button'].tooltip.str = req.ui_describe(player);
                dialog.widgets['change_title_button'].tooltip.text_color = SPUI.error_text_color;
            }
        } else {
            dialog.widgets['change_title_button'].show = false;
        }
    }

    dialog.widgets['level'].str = (knowledge['player_level'] ? knowledge['player_level'].toString() : '??');
    dialog.widgets['friend_icon'].set_user(user_id);

    var show_coords = gamedata['enable_region_map'] && gamedata['territory']['show_coords_in_player_info'] && (session.region.data && session.region.data['storage'] == 'nosql' && session.region.map_enabled());
    dialog.widgets['battle_count_label'].show = dialog.widgets['battle_count'].show =
        dialog.widgets['battle_age_label'].show = dialog.widgets['battle_age'].show = false; // no longer supported
    dialog.widgets['home_region_label'].show = dialog.widgets['home_region_value'].show =
        dialog.widgets['home_base_loc_label'].show = dialog.widgets['home_base_loc_value'].show = show_coords;

    if(show_coords) {
        // these are set from update_player_info_profile_tab
        dialog.widgets['spy_button'].state = 'disabled';
    }

    dialog.widgets['alliance'].onclick = null;

    if(user_id == session.user_id) {
        // looking at yourself
        dialog.widgets['spy_button'].show = false;
        dialog.widgets['friend_icon'].state = 'disabled';
    } else {
        dialog.widgets['spy_button'].onclick = (function(uid) { return function() {
            visit_base(uid);
        }; })(user_id);
        dialog.widgets['friend_icon'].state = 'normal';
        dialog.widgets['friend_icon'].onclick = function(w) {
            // same behavior as "Spy" button
            var spy = w.parent.widgets['spy_button'];
            if(spy.show && spy.state != 'disabled') { spy.onclick(spy); }
        };

        // see all battles from OPPONENT'S perspective (developer only)
        dialog.widgets['dev_battles_button'].show = !gamedata['battle_logs_public'] && player.is_developer();
        dialog.widgets['dev_battles_button'].onclick = (function(_uid) { return function() {
            invoke_battle_history_dialog(_uid, -1, -1, '(DEV-ALL)', -1);
        }; })(user_id);
    }

    PlayerInfoDialog.update_blockstate(dialog);

    dialog.widgets['report_button'].onclick = (function(uid) { return function() {
        if(player.has_advanced_chat_reporting()) {
            return invoke_report_abuse_dialog(uid);
        }

        // come up with a fake chat name for the report confirmation
        var fake_chat_name = dialog.widgets['name'].str;
        send_to_server.func(["CHAT_REPORT", uid, SPHTTP.wrap_string(fake_chat_name)]);
        player.block_user(uid);
        invoke_ui_locker(synchronizer.request_sync(), function() {
            change_selection(null);
            var s = gamedata['strings']['report_sent'];
            invoke_message_dialog(s['ui_title'], s['ui_description'], {'dialog':'message_dialog_big'});
        });
    }; })(user_id);

    if(knowledge['messageable'] && spin_frame_platform == 'fb' && user_id != session.user_id && knowledge['facebook_id']) { // XXXXXX nneed to search friend list
        dialog.widgets['message_button'].show = true;
        dialog.widgets['message_button'].onclick = (function (_fbid, _uid) { return function() {
            change_selection(null);
            invoke_facebook_message_dialog(_fbid, _uid);
        } })(knowledge['facebook_id'], user_id);
    }

    if(!dialog.widgets['message_button'].show &&
       user_id != session.user_id &&
       player.get_any_abtest_value('enable_player_fbpage_button', gamedata['client']['enable_player_fbpage_button']) &&
       knowledge['facebook_id']) {
        dialog.widgets['fbpage_button'].show = true;
        dialog.widgets['fbpage_button'].onclick = (function(_fbid) { return function(w) {
            url_open_in_new_tab('https://www.facebook.com/'+_fbid.toString());
        }; })(knowledge['facebook_id']);
    }

    // set up scores display
    var header_ui_names = dialog.data['widgets']['leaderboard_header']['ui_names'];
    for(var i = 0; i < header_ui_names.length; i++) {
        dialog.widgets['leaderboard_header'+i.toString()].str = header_ui_names[i];
    }

    dialog.widgets['show_week'].onclick = function(w) { var dlg = w.parent; if(dlg) { dlg.user_data['period']='week'; PlayerInfoDialog.update_scores(dlg); } };
    dialog.widgets['show_season'].onclick = function(w) { var dlg = w.parent; if(dlg) { dlg.user_data['period']='season'; PlayerInfoDialog.update_scores(dlg); } };
    PlayerInfoDialog.update_scores(dialog);


    // send player score queries
    var qls = [];
    var qkinds = [];
    var event = player.current_stat_tournament_event();
    if(event) {
        // send tournament query
        qls.push([event['stat']['name'], event['stat']['time_scope']]);
        dialog.user_data['score_query_sent']['stat_tournament'] = 1;
        qkinds.push('stat_tournament');
    }

    // send trophy query
    var trophy_type = player.current_trophy_type();
    if(!trophy_type && player.is_ladder_player()) { trophy_type = 'pvp'; }
    if(trophy_type) {
        var trophy_freq = (trophy_type == 'pvp' ? gamedata['matchmaking']['ladder_point_frequency'] : 'week');
        qls.push(['trophies_'+trophy_type, trophy_freq]);
        dialog.user_data['score_query_sent']['trophies'] = 1;
        qkinds.push('trophies');
        if(event) {
            // this is going to the backup display instead of the primary display
            dialog.widgets['backup_trophy_spinner'].show = true;
        }
    }

    if(qls.length > 0) {
        query_player_scores([user_id], qls, (function (_dialog, _qls, _qkinds) { return function(user_ids, data) {
            PlayerInfoDialog.scores_result(_dialog, _qls, _qkinds, data[0]);
        }; })(dialog, qls, qkinds));
    }


    dialog.ondraw = PlayerInfoDialog.update_profile_tab;
    return dialog;
};

/** @param {!SPUI.Dialog} dialog */
PlayerInfoDialog.update_profile_tab = function(dialog) {
    // update leaderboard display
    dialog.widgets['leaderboard_loading'].show = (dialog.user_data['score_query_sent'][dialog.user_data['period']]||0) < 2;
    if(!dialog.user_data['score_query_sent'][dialog.user_data['period']]) { PlayerInfoDialog.scores_query(dialog, dialog.user_data['period']); }

    // update playercache info
    var user_id = dialog.user_data['user_id'];
    if(!is_ai_user_id_range(user_id)) {
        var r = PlayerCache.query_sync_fetch(user_id);
        if(r) {
            if('last_defense_time' in r) {
                dialog.widgets['defense_time'].str = pretty_print_time(server_time - r['last_defense_time']);
            }

            var region_ok = false, loc_ok = false;
            if(dialog.widgets['home_region_label'].show) {
                if('home_region' in r && r['home_region'] && r['home_region'] in gamedata['regions']) {
                    dialog.widgets['home_region_value'].str = gamedata['regions'][r['home_region']]['ui_name'];
                    region_ok = true;
                } else {
                    dialog.widgets['home_region_value'].str = dialog.data['widgets']['home_region_value']['ui_name_unknown'];
                }
                if('home_base_loc' in r && r['home_base_loc'] && r['home_base_loc'].length == 2 && region_ok) {
                    dialog.widgets['home_base_loc_value'].str = dialog.data['widgets']['home_base_loc_value']['ui_name_coords'].replace('%X',r['home_base_loc'][0].toString()).replace('%Y',r['home_base_loc'][1].toString());
                    dialog.widgets['home_base_loc_value'].text_color = SPUI.make_colorv(dialog.data['widgets']['home_base_loc_value']['text_color_link']);
                    dialog.widgets['home_base_loc_value'].onclick = (function (_region,_loc) { return function(w) { invoke_find_on_map(_region, _loc); }; })(r['home_region'], r['home_base_loc']);
                    loc_ok = true;
                } else {
                    dialog.widgets['home_base_loc_value'].str = dialog.data['widgets']['home_base_loc_value']['ui_name_unknown'];
                }

                if(user_id != session.user_id) {
                    // Facebook friend or alliancemate?
                    var friend = find_friend_by_user_id(user_id);
                    if((friend && friend.is_real_friend) || (session.is_in_alliance() && session.alliance_id == r['alliance_id'])) {
                        // direct spying is possible
                        dialog.widgets['spy_button'].state = 'normal';
                    } else if(region_ok && loc_ok && session.region.data && r['home_region'] == session.region.data['id'] && session.region.map_enabled()) {
                        // same region - change to Find button
                        dialog.widgets['spy_button'].state = 'normal';
                        dialog.widgets['spy_button'].str = dialog.data['widgets']['spy_button']['ui_name_find_on_map'];
                        dialog.widgets['spy_button'].onclick = (function (_loc) { return function(w) {
                            change_selection_ui(null);
                            invoke_region_map(_loc);
                        }; })(r['home_base_loc']);
                    } else {
                        // different region - leave button disabled, change tooltip
                        dialog.widgets['spy_button'].tooltip.str = dialog.data['widgets']['spy_button']['ui_tooltip_other_region'].replace('%REGION', dialog.widgets['home_region_value'].str);
                    }
                }
            }

            // BATTLE HISTORY button
            dialog.widgets['battles_button'].show = true;
            if(user_id === session.user_id) {
                dialog.widgets['battles_button'].onclick = function() { invoke_battle_history_dialog(session.user_id, -1, session.alliance_id, '', -1); };
            } else if(gamedata['battle_logs_public']) {
                dialog.widgets['battles_button'].onclick = (function (_uid, _alliance_id) { return function() {
                    invoke_battle_history_dialog(_uid, -1, _alliance_id, '', -1);
                }; })(user_id, r['alliance_id'] || -1);
            } else {
                if(session.is_in_alliance() && session.alliance_id === r['alliance_id']) {
                    // same alliance: see battles involving this player (while they were in the alliance)
                    dialog.widgets['battles_button'].onclick = (function(_uid, _name, _level) { return function() {
                        invoke_battle_history_dialog(_uid, -1, session.alliance_id, _name, _level);
                    }; })(user_id, PlayerCache.get_ui_name(r), r['player_level'] || 1);
                } else {
                    // not same alliance: see battles from MY perspective against this opponent
                    dialog.widgets['battles_button'].onclick = (function(_uid, _name, _level) { return function() {
                        invoke_battle_history_dialog(session.user_id, _uid, -1, _name, _level);
                    }; })(user_id, PlayerCache.get_ui_name(r), r['player_level'] || 1);
                }
            }

            // SEND GIFT button
            if(user_id != session.user_id &&
               player.resource_gifts_enabled() &&
               ((session.is_in_alliance() && session.alliance_id == r['alliance_id']) /* is same alliance */ ||
                find_friend_by_user_id(user_id))) {
                var is_giftable = !player.cooldown_active('send_gift:'+user_id.toString());
                dialog.widgets['gift_button'].show = true;
                dialog.widgets['gift_button'].state = is_giftable ? 'normal' : 'disabled';
                dialog.widgets['gift_button'].onclick = (function (_uid) { return function() {
                    change_selection(null);
                    invoke_send_gifts(_uid, 'player_info_profile_tab');
                }; })(user_id);
                dialog.widgets['gift_button'].tooltip.str = is_giftable ? null : dialog.data['widgets']['gift_button']['ui_tooltip_already_sent'];
            } else {
                dialog.widgets['gift_button'].show = false;
            }

            if(player.get_any_abtest_value('enable_alliances', gamedata['client']['enable_alliances'])) {
                if(!('alliance_id' in r) || r['alliance_id'] <= 0) {
                    // player is not currently in an alliance
                    dialog.widgets['alliance'].str = dialog.data['widgets']['alliance']['ui_name_none'];

                    // show "send invite" button
                    if(session.is_in_alliance() && user_id != session.user_id) {
                        dialog.widgets['alliance_invite_button'].show = true;
                        if(session.check_alliance_perm('invite')) {
                            if(player.cooldown_active('alliance_invite:'+user_id.toString())) {
                                dialog.widgets['alliance_invite_button'].state = 'disabled';
                                dialog.widgets['alliance_invite_button'].tooltip.str = dialog.data['widgets']['alliance_invite_button']['ui_tooltip_cooldown'].replace('%s', pretty_print_time(player.cooldown_togo('alliance_invite:'+user_id.toString())));
                            } else {
                                var invite_cb = (function (w) { return function() {
                                    var _dialog = w.parent;
                                    w.state = 'disabled';
                                    w.str = _dialog.data['widgets']['alliance_invite_button']['ui_name_sending'];
                                    var cb = (function (__dialog) { return function(success) {
                                        __dialog.widgets['alliance_invite_button'].str = __dialog.data['widgets']['alliance_invite_button']['ui_name_sent'];
                                    }; })(_dialog);
                                    AllianceCache.send_invite(session.alliance_id, _dialog.user_data['user_id'], cb);
                                }; })(dialog.widgets['alliance_invite_button']);

                                if(region_ok && session.region.data && r['home_region'] != session.region.data['id'] &&
                                   ('requires' in gamedata['regions'][r['home_region']]) && !read_predicate(gamedata['regions'][r['home_region']]['requires']).is_satisfied(player, null)) {
                                    // different continent
                                    var bridge = continent_bridge_available();
                                    if(bridge) {
                                        invite_cb = (function (_dialog, _r, _invite_cb) { return function() {
                                            var s = gamedata['strings']['find_in_different_region_locked_bridge'];
                                            invoke_child_message_dialog(s['ui_title'], s['ui_description'].replace('%region', gamedata['regions'][_r['home_region']]['ui_name']),
                                                                        {'dialog': 'message_dialog_big', 'close_button':true, 'cancel_button': true,
                                                                         'ok_button_ui_name': _dialog.data['widgets']['alliance_invite_button']['ui_name'], 'on_ok': _invite_cb});
                                        }; })(dialog, r, invite_cb);
                                    } else {
                                        invite_cb = (function (_dialog, _r, _invite_cb) { return function() {
                                            var s = gamedata['strings']['find_in_different_region_locked'];
                                            invoke_child_message_dialog(s['ui_title'], s['ui_description'].replace('%region', gamedata['regions'][_r['home_region']]['ui_name']),
                                                                        {'dialog': 'message_dialog_big', 'close_button': true, 'cancel_button': true,
                                                                         'ok_button_ui_name': _dialog.data['widgets']['alliance_invite_button']['ui_name'], 'on_ok': _invite_cb});
                                        }; })(dialog, r, invite_cb);
                                    }
                                }
                                dialog.widgets['alliance_invite_button'].onclick = invite_cb;
                            }
                        } else {
                            dialog.widgets['alliance_invite_button'].state = 'disabled';
                            dialog.widgets['alliance_invite_button'].tooltip.str = gamedata['dialogs']['alliance_member_row']['widgets']['manage_button']['ui_tooltip_no_permission'];
                        }
                    }

                } else {
                    // player is already in an alliance
                    dialog.widgets['alliance'].onclick = (function (_id) { return function(w) {
                        invoke_alliance_info(_id);
                    }; })(r['alliance_id']);

                    if(!dialog.user_data['alliance_query_sent']) {
                        dialog.user_data['alliance_query_sent'] = true;
                        AllianceCache.query_info(r['alliance_id'], (function (_dialog) { return function(r) {
                            if(r) {
                                if('ui_name' in r) {
                                    _dialog.widgets['alliance'].str = alliance_display_name(r);
                                    // XXX future: add "Manage" button here
                                }
                            }
                        }; })(dialog));
                    }
                }
            }
        }
        PlayerInfoDialog.update_blockstate(dialog);
    }

    // update expiry timer
    if(dialog.widgets['trophy_expires'].show) {
        dialog.widgets['trophy_expires'].str = dialog.data['widgets']['trophy_expires']['ui_name'].replace('%expiry',gamedata['strings']['trophies_expire_in']).replace('%s', pretty_print_time_brief(dialog.user_data['tournament_end_time'] - player.get_absolute_time()));
    }
};

/** @param {!SPUI.Dialog} dialog
    @param {string} frequency */
PlayerInfoDialog.scores_query = function(dialog, frequency) {
    if(is_ai_user_id_range(dialog.user_data['user_id'])) { return; } // no AIs
    if(dialog.user_data['score_query_sent'][frequency] > 0) { return; } // already in flight or landed
    dialog.user_data['score_query_sent'][frequency] = 1; // mark in flight
    var qls = [];
    for(var j = 0; j < dialog.user_data['categories'].length; j++) {
        qls.push([dialog.user_data['categories'][j], frequency]);
    }
    var cb = (function (_dialog, _qls, _frequency) { return function(user_ids, data) {
        PlayerInfoDialog.scores_result(_dialog, _qls, [_frequency], data[0]);
    }; })(dialog, qls, frequency);
    query_player_scores([dialog.user_data['user_id']], qls, cb, {get_rank:1});
};

/** @param {!SPUI.Dialog} dialog
    @param {?} qls
    @param {Array.<string>} kinds
    @param {?} data */
PlayerInfoDialog.scores_result = function(dialog, qls, kinds, data) {
    if(!dialog.parent) { return; } // dialog was destroyed
    goog.array.forEach(kinds, function(kind) {
        dialog.user_data['score_query_sent'][kind] = 2; // mark landed
        if(kind == 'trophies') {
            dialog.widgets['backup_trophy_spinner'].show = false;
        }
    });

    for(var i = 0 ; i < data.length; i++) {
        if(data[i] && ('absolute' in data[i])) {
            data[i]['field'] = qls[i][0]; data[i]['frequency'] = qls[i][1];
            dialog.user_data['scores'].push(data[i]);
        }
    }
    PlayerInfoDialog.update_scores(dialog);
};

/** @param {!SPUI.Dialog} dialog */
PlayerInfoDialog.update_scores = function(dialog) {
    var period = dialog.user_data['period'];
    dialog.widgets['show_week'].state = (period == 'week' ? 'active' : 'normal');
    dialog.widgets['show_season'].state = (period == 'season' ? 'active' : 'normal');

    var scores = dialog.user_data['scores']; // may be empty

    var trophy_type = player.current_trophy_type();
    var trophy_challenge_name = player.current_trophy_challenge_name();
    if(!trophy_type && player.is_ladder_player()) {
        trophy_type = 'pvp';
        trophy_challenge_name = 'challenge_pvp_ladder';
    }

    var point_stat = null, point_icon = null, point_time_scope = null, point_ui_name = null, point_icon_state = null;
    var event = player.current_stat_tournament_event();
    if(event) { // show stat tournament points on primary display
        point_stat = event['stat']['name'];
        point_ui_name = event['ui_name'];
        point_time_scope = event['stat']['time_scope'];
        point_icon = event['icon'];
        point_icon_state = 'icon_30x30';
        dialog.user_data['tournament_end_time'] = player.current_stat_tournament_end_time();
    } else if(trophy_type) { // show pvp points on primary display
        point_ui_name = gamedata['events'][trophy_challenge_name]['ui_name'];
        point_stat = 'trophies_'+trophy_type;
        point_icon = 'trophy_30x30';
        point_icon_state = trophy_type;
        point_time_scope = gamedata['matchmaking']['ladder_point_frequency'];
        dialog.user_data['tournament_end_time'] = player.get_absolute_time() + player.current_trophy_challenge_togo();
    }

    var point_count = null, trophy_count = 0;
    for(var i = 0; i < scores.length; i++) {
        if(scores[i]['field'] == point_stat && ('absolute' in scores[i])) {
            point_count = scores[i]['absolute'];
            if(!event) { // legacy
                var cur_trophy_type = player.current_trophy_type();
                if(cur_trophy_type) {
                    point_count = display_trophy_count(point_count, cur_trophy_type);
                }
            }
        }
        if(trophy_type && event && scores[i]['field'] == 'trophies_'+trophy_type && ('absolute' in scores[i])) {
            trophy_count = display_trophy_count(scores[i]['absolute'], trophy_type);
        }
    }

    if(point_stat !== null && point_count !== null) {
        //dialog.widgets['trophy_label'].show =
            dialog.widgets['trophy_bg'].show =
            dialog.widgets['trophy_shine'].show =
            dialog.widgets['trophy_icon'].show =
            dialog.widgets['trophy_amount'].show = true;
        dialog.widgets['trophy_expires'].show = (point_time_scope !== 'season' && dialog.user_data['tournament_end_time'] > player.get_absolute_time());
        dialog.widgets['trophy_icon'].asset = point_icon;
        dialog.widgets['trophy_icon'].state = point_icon_state;
        dialog.widgets['trophy_bg'].tooltip.str = dialog.data['widgets']['trophy_bg']['ui_tooltip'].replace('%type', point_ui_name);
        if(point_stat in gamedata['strings']['leaderboard']['categories']) {
            dialog.widgets['trophy_bg'].tooltip.str += '\n' + gamedata['strings']['leaderboard']['categories'][point_stat]['description'];
        }
        dialog.widgets['trophy_label'].str = dialog.data['widgets']['trophy_label']['ui_name'];
        dialog.widgets['trophy_amount'].str = pretty_print_number(point_count);
        dialog.widgets['trophy_amount'].color = SPUI.make_colorv(dialog.data['widgets']['trophy_amount']['text_color_'+(point_count>=0 ? 'plus':'minus')]);
    }

    if(event && trophy_type && trophy_challenge_name && trophy_count !== null) { // backup trophy display when primary display is something other than trophies
        dialog.widgets['backup_trophy_icon'].show =
            dialog.widgets['backup_trophy_count'].show = true;
        dialog.widgets['backup_trophy_icon'].state = trophy_type;
        dialog.widgets['backup_trophy_count'].str = pretty_print_number(trophy_count);
        dialog.widgets['backup_trophy_count'].color = SPUI.make_colorv(dialog.data['widgets']['backup_trophy_count']['text_color_'+(trophy_count>=0 ? 'plus':'minus')]);
        dialog.widgets['backup_trophy_count'].tooltip.str = dialog.data['widgets']['backup_trophy_count']['ui_tooltip'].replace('%type', gamedata['events'][trophy_challenge_name]['ui_name']);
    }

    // only show the 3 categories with top-most player ranking
    var shown_categories = [];

    for(var i = 0; i < scores.length; i++) {
        if(scores[i]['frequency'] == dialog.user_data['period'] && ('rank' in scores[i])) {
            shown_categories.push(scores[i]);
        }
    }

    var compare_by_rank = function(a,b) {
        if(a['rank'] > b['rank'])  {
            return 1;
        } else if(a['rank'] < b['rank']) {
            return -1;
        } return 0;
    };
    shown_categories.sort(compare_by_rank);

    // only show first 3 rows
    shown_categories = shown_categories.slice(0,3);

    var i;
    for(i = 0; i < shown_categories.length; i++) {
        var data = shown_categories[i];
        var cat = data['field'];
        var pct = 1.0-data['percentile'];
        var rank = data['rank']+1; // server numbering starts at 0

        dialog.widgets['leaderboard_accent'+i.toString()].show = (pct >= 0.5);
        dialog.widgets['leaderboard_accent'+i.toString()].state = (pct >= 0.99 ? 'top' : 'normal');

        var status = percentile_ui_status(rank, pct, true);

        dialog.widgets['leaderboard_data0,'+i.toString()].str = gamedata['strings']['leaderboard']['categories'][cat]['short_title'];
        dialog.widgets['leaderboard_data0,'+i.toString()].tooltip.str = gamedata['strings']['leaderboard']['categories'][cat]['description'];
        dialog.widgets['leaderboard_data1,'+i.toString()].str = status;
        dialog.widgets['leaderboard_data2,'+i.toString()].str = pretty_print_number(rank);
        dialog.widgets['leaderboard_data3,'+i.toString()].str = pretty_print_number(data['absolute']);
        dialog.widgets['leaderboard_data4,'+i.toString()].str = (data['absolute'] > 0 ? (100.0*pct).toFixed(1)+'%' : '-');
        for(var m = 0; m < 5; m++) {
            dialog.widgets['leaderboard_data'+m.toString()+','+i.toString()].show = true;
        }
    }

    // clear remaining rows
    while(i < 3) {
        dialog.widgets['leaderboard_accent'+i.toString()].show = false;
        for(var m = 0; m < 5; m++) {
            dialog.widgets['leaderboard_data'+m.toString()+','+i.toString()].show = false;
        }
        i++;
    }
};

/** @param {!SPUI.Dialog} dialog */
PlayerInfoDialog.update_blockstate = function(dialog) {
    var user_id = dialog.user_data['user_id'];
    if(user_id == session.user_id) {
        // yourself
        dialog.widgets['ignore_button'].show =
            dialog.widgets['report_button'].show = false;
    }

    // gag buttons
    if(player.is_chat_mod && user_id != session.user_id) {
        var mutecb = function(_uid, cmd) { return function() { send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, cmd, _uid]);
                                                               change_selection(null); }; };
        dialog.widgets['dev_mute_button'].onclick = mutecb(user_id, "CHAT_GAG");
        dialog.widgets['dev_unmute_button'].onclick = mutecb(user_id, "CHAT_UNGAG");
        var info = PlayerCache.query_sync(user_id);
        if(info) {
            var gagged = info && (('chat_gagged' in info) && info['chat_gagged']);
            dialog.widgets['dev_mute_button'].show = !gagged;
            dialog.widgets['dev_unmute_button'].show = gagged;
        } else {
            dialog.widgets['dev_mute_button'].show =
                dialog.widgets['dev_unmute_button'].show = false;
        }
    }

    if(player.has_blocked_user(user_id)) {
        dialog.widgets['report_button'].state = 'disabled';
        dialog.widgets['report_button'].tooltip.str = dialog.data['widgets']['report_button']['ui_tooltip_already_reported'];
        dialog.widgets['ignore_button'].str = dialog.data['widgets']['ignore_button']['ui_name_unblock'];
        dialog.widgets['ignore_button'].tooltip.str = dialog.data['widgets']['ignore_button']['ui_tooltip_unblock'];
        dialog.widgets['ignore_button'].onclick = (function(d, uid) { return function() {
            invoke_ui_locker();
            player.unblock_user(uid);
            PlayerInfoDialog.update_blockstate(d);
        }; })(dialog, user_id);
    } else {
        dialog.widgets['report_button'].state = 'normal';
        dialog.widgets['report_button'].tooltip.str = dialog.data['widgets']['report_button']['ui_tooltip'];
        dialog.widgets['ignore_button'].str = dialog.data['widgets']['ignore_button']['ui_name'];
        dialog.widgets['ignore_button'].tooltip.str = dialog.data['widgets']['ignore_button']['ui_tooltip'];
        dialog.widgets['ignore_button'].onclick = (function(d, uid) { return function() {
            invoke_ui_locker();
            player.block_user(uid);
            PlayerInfoDialog.update_blockstate(d);
        }; })(dialog, user_id);
    }
};

/** @param {!SPUI.Dialog} parent
    @param {?string=} preselect_category
    @param {?string=} preselect_name */
PlayerInfoDialog.invoke_achievements_tab = function(parent, preselect_category, preselect_name) {
    var user_id = parent.user_data['user_id'];
    var knowledge = parent.user_data['info'];

    player.record_feature_use(user_id === session.user_id ? 'own_achievements' : 'other_achievements');

    if('tab' in parent.widgets) {
        if(parent.widgets['tab'].user_data['dialog'] == 'player_info_achievements_tab' && !preselect_category) {
            // we're already up
            return;
        }
        parent.remove(parent.widgets['tab']);
        delete parent.widgets['tab'];
    }

    parent.widgets['statistics_button'].state = 'normal';
    parent.widgets['statistics_button'].show = player.get_any_abtest_value('enable_score_history', gamedata['client']['enable_score_history']);
    parent.widgets['profile_button'].state = 'normal';
    parent.widgets['alliance_history_button'].state = 'normal';
    parent.widgets['alliance_history_button'].show = PlayerInfoDialog.player_alliance_membership_history_enabled(player);
    parent.widgets['achievements_button'].state = 'pressed';

    var dialog = new SPUI.Dialog(gamedata['dialogs']['player_info_achievements_tab']);
    dialog.transparent_to_mouse = true;
    dialog.user_data['dialog'] = 'player_info_achievements_tab';
    dialog.user_data['user_id'] = user_id;

    dialog.widgets['cat_list'].user_data['page'] = -1;
    dialog.widgets['cat_list'].user_data['rows_per_page'] = dialog.widgets['cat_list'].data['widgets']['category']['array'][1];
    dialog.widgets['cat_list'].user_data['rowfunc'] = PlayerInfoDialog.achievement_category_rowfunc;
    dialog.widgets['cat_list'].user_data['rowdata'] = [];

    dialog.widgets['ach_list'].user_data['page'] = -1;
    dialog.widgets['ach_list'].user_data['rows_per_page'] = dialog.widgets['ach_list'].data['widgets']['ach']['array'][1];
    dialog.widgets['ach_list'].user_data['rowfunc'] = PlayerInfoDialog.achievement_rowfunc;
    dialog.widgets['ach_list'].user_data['rowdata'] = [];
    dialog.user_data['player_achievements'] = null;

    dialog.widgets['lag_note'].show = (user_id != session.user_id);

    // create and sort cateory list
    var ach_cats = [];
    for(var name in gamedata['achievement_categories']) {
        var data = gamedata['achievement_categories'][name];
        if(('show_if' in data) && !read_predicate(data['show_if']).is_satisfied(player, null)) { continue; }
        if(('activation' in data) && !read_predicate(data['activation']).is_satisfied(player, null)) { continue; }
        ach_cats.push(name);
    }
    var compare_by_ui_priority = function(a,b) {
        var pa = gamedata['achievement_categories'][a]['ui_priority'] || 0;
        var pb = gamedata['achievement_categories'][b]['ui_priority'] || 0;
        if(pa > pb) {
            return -1;
        } else if(pa < pb) {
            return 1;
        } return 0;
    };
    ach_cats.sort(compare_by_ui_priority);

    dialog.widgets['cat_list'].user_data['rowdata'] = ach_cats;

    parent.widgets['tab'] = dialog;
    parent.add(dialog);

    dialog.user_data['category'] = (preselect_category || ach_cats[0]);
    dialog.user_data['preselect_name'] = preselect_name || null;
    PlayerInfoDialog.achievements_tab_set_category(dialog, dialog.user_data['category']);

    if(user_id === session.user_id) {
        PlayerInfoDialog.achievements_tab_receive(dialog, player.achievements);
    } else {
        query_achievements(user_id, (function (_dialog) { return function(achdata) { PlayerInfoDialog.achievements_tab_receive(_dialog, achdata); }; })(dialog));
    }

    return dialog;
};

/** @param {!SPUI.Dialog} dialog
    @param {string} catname */
PlayerInfoDialog.achievements_tab_set_category = function(dialog, catname) {
    // update category list
    dialog.user_data['category'] = catname;
    scrollable_dialog_change_page(dialog.widgets['cat_list'], dialog.widgets['cat_list'].user_data['page']);

    // update achievement list
    var achdata = dialog.user_data['player_achievements'];
    var ach_list = [], total = 0, completed = 0;

    if(achdata !== null) {
        for(var name in gamedata['achievements']) {
            var data = gamedata['achievements'][name];
            if(data['category'] !== catname) { continue; }
            if(('show_if' in data) && !read_predicate(data['show_if']).is_satisfied(player, null)) { continue; }
            if(('activation' in data) && !read_predicate(data['activation']).is_satisfied(player, null)) { continue; }
            ach_list.push(data);
            total += 1;
            if(name in achdata) { completed += 1; }
        }
    }
    ach_list.sort(compare_achievements(achdata));

    if(total > 0) {
        dialog.widgets['cat_progress'].progress = completed / total;
        if(gamedata['client']['show_achievement_complete_pct']) {
            dialog.widgets['cat_progress_text'].str = dialog.data['widgets']['cat_progress_text']['ui_name'].replace('%cat', gamedata['achievement_categories'][catname]['ui_name']).replace('%pct', Math.floor(100.0*dialog.widgets['cat_progress'].progress+0.5).toFixed(0));
        }
    } else {
        dialog.widgets['cat_progress'].progress = 0;
        dialog.widgets['cat_progress_text'].str = null;
    }

    dialog.widgets['ach_list'].user_data['rowdata'] = ach_list;
    scrollable_dialog_change_page(dialog.widgets['ach_list'], 0);
};

/** @param {!SPUI.Dialog} dialog
    @param {?} achdata */
PlayerInfoDialog.achievements_tab_receive = function(dialog, achdata) {
    if(!dialog.parent) { return; } // dialog got closed asynchronously

    dialog.user_data['player_achievements'] = achdata;

    var achievement_points = get_achievement_points(achdata);

    dialog.widgets['player_name'].str = PlayerInfoDialog.format_name_with_level(dialog.parent.user_data['info']);
    if(achievement_points > 0 && player.get_any_abtest_value('enable_achievement_points', gamedata['client']['enable_achievement_points'])) {
        dialog.widgets['player_name'].str += ' - '+dialog.data['widgets']['player_name'][(achievement_points == 1 ? 'ui_name_points' : 'ui_name_points_plural')].replace('%d', pretty_print_number(achievement_points));
    }

    dialog.widgets['cat_progress_bg'].show =
        dialog.widgets['cat_progress'].show =
        dialog.widgets['cat_progress_text'].show = (achdata !== null);

    if(achdata !== null) {
        dialog.widgets['loading_rect'].show =
            dialog.widgets['loading_text'].show =
            dialog.widgets['loading_spinner'].show = false;
        PlayerInfoDialog.achievements_tab_set_category(dialog, dialog.user_data['category']);

        // show preselected achievement
        if(dialog.user_data['preselect_name']) {
            var idx = goog.array.findIndex(dialog.widgets['ach_list'].user_data['rowdata'], function(cheeve) { return cheeve['name'] == dialog.user_data['preselect_name']; });
            if(idx >= 0) {
                scrollable_dialog_change_page(dialog.widgets['ach_list'], Math.floor(idx / dialog.widgets['ach_list'].user_data['rows_per_page']));
            }
            dialog.user_data['preselect_name'] = null;
        }
    } else {
        dialog.widgets['loading_text'].str = dialog.data['widgets']['loading_text']['ui_name_unavailable'];
        dialog.widgets['loading_spinner'].show = false;
    }
};

/** @param {!SPUI.Dialog} dialog
    @param {number} row
    @param {string} rowdata */
PlayerInfoDialog.achievement_category_rowfunc = function(dialog, row, rowdata) {
    dialog.widgets['category'+row.toString()].show = (rowdata !== null);
    if(rowdata !== null) {
        dialog.widgets['category_status'+row.toString()].show = dialog.data['widgets']['category_status']['show'] &&
            (dialog.parent.user_data['player_achievements'] != null);
        if(dialog.widgets['category_status'+row.toString()].show) {
            var stat = dialog.data['widgets']['category_status']['ui_name'];
            var total = 0, complete = 0;
            for(var achname in gamedata['achievements']) {
                var data = gamedata['achievements'][achname];
                if(data['category'] != rowdata) { continue; }
                if(('show_if' in data) && !read_predicate(data['show_if']).is_satisfied(player, null)) { continue; }
                if(('activation' in data) && !read_predicate(data['activation']).is_satisfied(player, null)) { continue; }
                if(achname in dialog.parent.user_data['player_achievements']) {
                    complete += 1;
                }
                total += 1;
            }
            stat = stat.replace('%complete', complete.toString());
            stat = stat.replace('%total', total.toString());
            stat = stat.replace('%pct', (total <= 0 ? '-' : Math.floor((100.0*complete/total)+0.5).toFixed(0)));
            dialog.widgets['category_status'+row.toString()].str = stat;
            var clr = (complete >= total ? 'complete' : (complete > 0 ? 'inprogress' : 'zero'));
            dialog.widgets['category_status'+row.toString()].text_color = SPUI.make_colorv(dialog.data['widgets']['category_status']['text_color_'+clr]);
        }

        var white = new SPUI.Color(1,1,1,1), light_gray = new SPUI.Color(0.75, 0.75, 0.75, 1);
        if(rowdata == dialog.parent.user_data['category']) {
            dialog.widgets['category'+row.toString()].highlight_text_color = dialog.widgets['category'+row.toString()].text_color = white;
        } else {
            dialog.widgets['category'+row.toString()].highlight_text_color = light_gray;
            dialog.widgets['category'+row.toString()].text_color = SPUI.disabled_text_color;
        }

        dialog.widgets['category'+row.toString()].str = gamedata['achievement_categories'][rowdata]['ui_name'];
        dialog.widgets['category'+row.toString()].onclick = (function (_catname) { return function(w) {
            PlayerInfoDialog.achievements_tab_set_category(w.parent.parent, _catname);
        }; })(rowdata);
    } else {
        dialog.widgets['category_status'+row.toString()].show = false;
    }
};

/** @param {!SPUI.Dialog} dialog
    @param {number} row
    @param {?Object} rowdata */
PlayerInfoDialog.achievement_rowfunc = function(dialog, row, rowdata) {
    // blank out display if data has not been received yet
    if(dialog.parent.user_data['player_achievements'] === null) { rowdata = null; }

    dialog.widgets['ach'+row.toString()].show = (rowdata !== null);

    if(rowdata !== null) {
        achievement_widget_setup(dialog.widgets['ach'+row], rowdata, dialog.parent.user_data['player_achievements'],
                                 (dialog.parent.user_data['user_id'] == session.user_id ? player.history : null));
    }
};

/** @param {!SPUI.Dialog} parent
    @return {!SPUI.Dialog} */
PlayerInfoDialog.invoke_alliance_history_tab = function(parent) {
    var user_id = parent.user_data['user_id'];
    var knowledge = parent.user_data['info'];

    player.record_feature_use(user_id === session.user_id ? 'own_alliance_history' : 'other_alliance_history');

    if('tab' in parent.widgets) {
        if(parent.widgets['tab'].user_data['dialog'] == 'player_info_alliance_history_tab') {
            // we're already up
            return parent.widgets['tab'];
        }
        parent.remove(parent.widgets['tab']);
        delete parent.widgets['tab'];
    }

    parent.widgets['statistics_button'].state = 'normal';
    parent.widgets['profile_button'].state = 'normal';
    parent.widgets['achievements_button'].state = 'normal';
    parent.widgets['alliance_history_button'].state = 'pressed';

    var dialog = new SPUI.Dialog(gamedata['dialogs']['player_info_alliance_history_tab']);
    dialog.transparent_to_mouse = true;
    dialog.user_data['dialog'] = 'player_info_alliance_history_tab';
    dialog.user_data['user_id'] = user_id;

    dialog.widgets['player_name'].str = PlayerInfoDialog.format_name_with_level(knowledge);
    dialog.widgets['player_id'].str = dialog.data['widgets']['player_id']['ui_name'].replace('%d', user_id.toString());

    parent.widgets['tab'] = dialog;
    parent.add(dialog);

    dialog.widgets['loading_rect'].show =
        dialog.widgets['loading_text'].show =
        dialog.widgets['loading_spinner'].show = true;

    dialog.widgets['output'].clear_text();

    // note: it's OK to use the statistics_tab_scroll() functions since the widget names are the same
    dialog.widgets['scroll_up'].onclick = function (w) { PlayerInfoDialog.statistics_tab_scroll(w.parent, -1); };
    dialog.widgets['scroll_down'].onclick = function (w) { PlayerInfoDialog.statistics_tab_scroll(w.parent, 1); };
    PlayerInfoDialog.statistics_tab_scroll(dialog, 0);

    query_player_alliance_membership_history(user_id, (function (_dialog) { return function(data) {
        PlayerInfoDialog.alliance_history_tab_receive(_dialog, data);
    }; })(dialog));

    return dialog;
};

/** @param {!SPUI.Dialog} dialog
    @param {?} data */
PlayerInfoDialog.alliance_history_tab_receive = function(dialog, data) {
    if(!dialog.parent) { return; } // dialog got closed asynchronously

    // data is {'result':event_list} or {'error': ...}
    if(!data || data['error']) {
        dialog.widgets['loading_text'].str = dialog.data['widgets']['loading_text']['ui_name_unavailable'];
        dialog.widgets['loading_spinner'].show = false;
        return;
    }

    var event_list = data['result'];

    dialog.widgets['loading_rect'].show =
        dialog.widgets['loading_text'].show =
        dialog.widgets['loading_spinner'].show = false;

    dialog.widgets['output'].clear_text();

    // newest events first
    event_list.sort(function(a, b) {
        if(a['time'] < b['time']) { return 1; }
        if(a['time'] > b['time']) { return -1;}
        return 0;
    });

    var user_id = dialog.parent.user_data['user_id'];
    var pcache_info = dialog.parent.user_data['info'];

    goog.array.forEach(event_list, function(ev) {
        if(!('ui_'+ev['event_name'] in dialog.widgets['output'].data['events'])) { return; }

        if(ev['event_name'] == '4625_alliance_member_kicked' ||
           ev['event_name'] == '4650_alliance_member_join_request_accepted') {
            // exclude events that don't apply to the player
            if(user_id != ev['target_id']) { return; }
        } else {
            if(user_id != ev['user_id']) { return; }
        }

        var msg = dialog.widgets['output'].data['events']['ui_'+ev['event_name']];

        function format_alliance(alliance_id, name, tag) {
            var bb_text = gamedata['strings']['chat_templates']['alliance']
                .replace('%alliance_name', name)
                .replace('%alliance_id', alliance_id.toString());
            if(tag) {
                bb_text += gamedata['strings']['chat_templates']['alliance_tag'].replace('%alliance_tag', tag).replace('%alliance_id', alliance_id.toString());
            }
            return bb_text;
        }

        var alliance_id = ev['alliance_id'];
        var alliance_info = AllianceCache.query_info_sync(alliance_id);

        // get former alliance name/tag from event
        var alliance_ui_name_former = ev['alliance_ui_name'] || null;
        var alliance_chat_tag_former = ev['alliance_chat_tag'] || null;

        var alliance_ui_name = (alliance_info ? alliance_info['ui_name'] : dialog.widgets['output'].data['ui_alliance_disbanded']);
        var alliance_chat_tag = (alliance_info ? (alliance_info['chat_tag'] || null) : null);

        var ui_alliance;

        // alliance has different name now
        if(alliance_ui_name_former && (alliance_ui_name != alliance_ui_name_former || alliance_chat_tag != alliance_chat_tag_former)) {
            ui_alliance = dialog.widgets['output'].data['ui_alliance_former']
                .replace('%now', format_alliance(alliance_id, alliance_ui_name, alliance_chat_tag))
                .replace('%former', format_alliance(alliance_id, alliance_ui_name_former, alliance_chat_tag_former));
        } else {
            ui_alliance = format_alliance(alliance_id, alliance_ui_name, alliance_chat_tag);
        }

        msg = msg.replace('%alliance', ui_alliance);

        var line = dialog.widgets['output'].data['ui_event_line'];
        line = line.replace('%date', pretty_print_date_and_time_utc(ev['time']));
        line = line.replace('%event', msg);
        line = line.replace('%alliance', ui_alliance);

        dialog.widgets['output'].append_text(SPText.cstring_to_ablocks_bbcode(line, null, system_chat_bbcode_click_handlers));
    });

    if(event_list.length < 1) {
        dialog.widgets['output'].append_text(SPText.cstring_to_ablocks_bbcode(dialog.widgets['output'].data['events']['ui_data_none']));
    }

    // tack on account creation event at the end
    if(pcache_info && 'account_creation_time' in pcache_info) {
        var account_creation_time = pcache_info['account_creation_time'];

        // for very old accounts, add a note that early history won't be in the database
        if(account_creation_time < 1427846400) {
            dialog.widgets['output'].append_text(SPText.cstring_to_ablocks_bbcode(dialog.widgets['output'].data['events']['ui_data_incomplete']));
        }

        var ui_account_creation = dialog.widgets['output'].data['ui_event_line']
            .replace('%date', pretty_print_date_utc(account_creation_time))
            .replace('%event', dialog.widgets['output'].data['events']['ui_0110_created_new_account']
                     .replace('%game', gamedata['strings']['game_name']));
        dialog.widgets['output'].append_text(SPText.cstring_to_ablocks_bbcode(ui_account_creation));
    }

    dialog.widgets['output'].scroll_to_top();
    PlayerInfoDialog.statistics_tab_scroll(dialog, 0);
};
