goog.provide('Consequents');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// for Logic only
goog.require('Predicates');
goog.require('GameArt'); // for client graphics
goog.require('OfferChoice');
goog.require('Leaderboard');
goog.require('LoginIncentiveDialog');
goog.require('Battlehouse');

// depends on global player/selection stuff from clientcode.js
// note: this parallel's Consequents.py on the server side, but
// most consequents are implemented purely on either client or server side

/** @constructor @struct */
function Consequent(data) {
    this.kind = data['consequent'];
}
/** @param {Object=} state */
Consequent.prototype.execute = goog.abstractMethod;

/** @constructor @struct
  * @extends Consequent */
function NullConsequent(data) {
    goog.base(this, data);
}
goog.inherits(NullConsequent, Consequent);
NullConsequent.prototype.execute = function(state) { };

/** @constructor @struct
  * @extends Consequent */
function AndConsequent(data) {
    goog.base(this, data);
    this.subconsequents = [];
    for(var i = 0; i < data['subconsequents'].length; i++) {
        this.subconsequents.push(read_consequent(data['subconsequents'][i]));
    }
}
goog.inherits(AndConsequent, Consequent);
AndConsequent.prototype.execute = function(state) {
    for(var i = 0; i < this.subconsequents.length; i++) {
        this.subconsequents[i].execute(state);
    }
};

/** @constructor @struct
  * @extends Consequent */
function IfConsequent(data) {
    goog.base(this, data);
    this.predicate = read_predicate(data['if']);
    this.then_consequent = read_consequent(data['then']);
    if('else' in data) {
        this.else_consequent = read_consequent(data['else']);
    } else {
        this.else_consequent = null;
    }
}
goog.inherits(IfConsequent, Consequent);
IfConsequent.prototype.execute = function(state) {
    if(this.predicate.is_satisfied(player, state)) {
        return this.then_consequent.execute(state);
    } else if(this.else_consequent) {
        return this.else_consequent.execute(state);
    }
};

/** @constructor @struct
  * @extends Consequent */
function CondConsequent(data) {
    goog.base(this, data);
    this.chain = data['cond'];
}
goog.inherits(CondConsequent, Consequent);
CondConsequent.prototype.execute = function(state) {
    for(var i = 0; i < this.chain.length; i++) {
        if(read_predicate(this.chain[i][0]).is_satisfied(player, null)) {
            read_consequent(this.chain[i][1]).execute(state);
            return;
        }
    }
};

/** @constructor @struct
  * @extends Consequent */
function TutorialArrowConsequent(data) {
    goog.base(this, data);
    this.arrow_type = data['arrow_type'];

    // arrow type 'landscape' only
    this.target_name = data['target_name'] || null;
    this.coordinates = data['coordinates'] || null;

    // arrow type 'button' only
    this.dialog_name = data['dialog_name'] || null;
    this.widget_name = data['widget_name'] || null;

    // arrow type'region_map' only
    this.base_is_my_home = data['my_home'] || null;
    this.squad_id = data['squad_id'] || null;
    this.base_type = data['base_type'] || null;
    this.base_template = data['base_template'] || null;
    this.base_closest_to = data['base_closest_to'] || null;

    this.direction = data['direction'] || 'down';
    this.reticle_size = data['reticle_size'] || null;
    this.buildable = data['buildable'] || null;
    this.child = data['child'] || false;
}
goog.inherits(TutorialArrowConsequent, Consequent);
TutorialArrowConsequent.prototype.execute = function(state) {
    var dialog = make_ui_arrow(this.direction);
    if(this.child) {
        install_child_dialog(dialog);
    } else {
        player.quest_root.add(dialog);
    }
    if(this.arrow_type == 'landscape') {
        if(this.reticle_size) {
            dialog.user_data['override_reticle_size'] = this.reticle_size;
        }
        dialog.ondraw = update_tutorial_arrow_for_landscape(dialog, this.target_name, this.coordinates, this.direction, this.buildable);
        dialog.afterdraw = tutorial_arrow_draw_reticle;
        dialog.ondraw(dialog); // call once here to init position
        player.quest_landscape_arrow = dialog;
    } else if(this.arrow_type == 'button') {
        dialog.ondraw = update_tutorial_arrow_for_button(dialog, this.dialog_name, this.widget_name, this.direction);
    } else if(this.arrow_type == 'region_map') {
        dialog.ondraw = update_tutorial_arrow_for_region_map(dialog, this.base_is_my_home, this.squad_id, this.base_type, this.base_template, this.base_closest_to);
        dialog.afterdraw = tutorial_arrow_draw_reticle;
    }
};

/** @constructor @struct
  * @extends Consequent */
function ForceScrollConsequent(data) {
    goog.base(this, data);
    // 'landscape' only
    this.target_name = data['target_name'] || null;
    this.coordinates = data['coordinates'] || null;
    this.key = data['key'];
    this.speed = data['speed'] || null;
}
goog.inherits(ForceScrollConsequent, Consequent);
ForceScrollConsequent.prototype.execute = function(state) {
    if(player.get_any_abtest_value('force_scroll_enable', gamedata['client']['force_scroll_enable'])) {
        force_scroll(this.target_name, this.coordinates, this.key, this.speed);
    }
};

/** @constructor @struct
  * @extends Consequent */
function StartAIAttackConsequent(data) {
    goog.base(this, data);
    // 'landscape' only
    this.attack_id = data['attack_id'];
}
goog.inherits(StartAIAttackConsequent, Consequent);
StartAIAttackConsequent.prototype.execute = function(state) {
    var id;
    if(typeof(this.attack_id) === 'string' && this.attack_id[0] == '$') {
        id = state[this.attack_id.slice(1)];
    } else {
        id = this.attack_id;
    }
    start_ai_attack(id);
};

/** @constructor @struct
  * @extends Consequent */
function LoadAIBaseConsequent(data) { // client-side only, kind of hacky
    goog.base(this, data);
    this.base_id = data['base_id'];
}
goog.inherits(LoadAIBaseConsequent, Consequent);
LoadAIBaseConsequent.prototype.execute = function(state) {
    var id;
    if(typeof(this.base_id) === 'string' && this.base_id[0] == '$') {
        id = state[this.base_id.slice(1)];
// pure numbers should be sent to load_ai_base() as numbers (?)
//        if(typeof(id) === 'string' && !isNaN(id)) {
//            id = parseInt(id);
//        }
    } else {
        id = this.base_id;
    }
    load_ai_base(id);
};

/** @constructor @struct
  * @extends Consequent */
function VisitBaseConsequent(data) {
    goog.base(this, data);
    this.user_id = data['user_id'];
    this.pre_attack = data['pre_attack'] || null;
}
goog.inherits(VisitBaseConsequent, Consequent);
VisitBaseConsequent.prototype.execute = function(state) {
    var options = {};
    if(this.pre_attack) { options.pre_attack = this.pre_attack; }
    do_visit_base(this.user_id, options);
};

/** @constructor @struct
  * @extends Consequent */
function RepairAllConsequent(data) { // client-side only, kind of hacky
    goog.base(this, data);
    this.user_id = data['user_id'];
}
goog.inherits(RepairAllConsequent, Consequent);
RepairAllConsequent.prototype.execute = function(state) {
    Store.place_user_currency_order(GameObject.VIRTUAL_ID, "REPAIR_ALL_FOR_MONEY", session.viewing_base.base_id);
};

/** @constructor @struct
  * @extends Consequent */
function CastClientSpellConsequent(data) {
    goog.base(this, data);
    this.spellname = data['spellname'];
}
goog.inherits(CastClientSpellConsequent, Consequent);
CastClientSpellConsequent.prototype.execute = function(state) {
    if(!state || !state['source_obj']) { throw Error('no source_obj provided'); }
    var spell = gamedata['spells'][this.spellname];
    state['source_obj'].cast_client_spell(this.spellname, spell, state['source_obj'], state['xy'] || null);
};

/** Client-side only - set all mobile objects on same team to aggressive
    @constructor @struct
    @extends Consequent */
function AllAggressiveConsequent(data) {
    goog.base(this, data);
}
goog.inherits(AllAggressiveConsequent, Consequent);
AllAggressiveConsequent.prototype.execute = function(state) {
    if(!state || !state['source_obj']) { throw Error('no source_obj provided'); }
    var source_obj = state['source_obj'];
    var world = session.get_real_world();
    session.for_each_real_object(function(obj) {
        if(obj.is_mobile() && obj.team === source_obj.team) {
            // note: we don't want to persist this aggro to the server for subsequent attacks!
            // so just set the AI mode without going through the "orders" path
            //do_unit_command_make_aggressive(world, obj);
            obj.ai_aggressive = true;
        }
    });
};

/** @constructor @struct
  * @extends Consequent */
function UINotifyConsequent(data) {
    goog.base(this, data);
    this.notification_params = data['notification_params'] || {};
    this.action = read_consequent(data['action']);
    this.name = data['name'] || null;
}
goog.inherits(UINotifyConsequent, Consequent);
UINotifyConsequent.prototype.execute = function(state) {
    notification_queue.push(goog.bind(function() {
        this.action.execute(); // note: drops state
    }, this), this.notification_params);
};


// note: normally this is done server-side for AI base completions,
// resulting in receiving DISPLAY_MESSAGE over the network, but we
// also implement a client-side version for quest "completion"
// consequents, which are only run client-side.

var DisplayMessageConsequent_seen = {};

/** @constructor @struct
  * @extends Consequent */
function DisplayMessageConsequent(data) {
    goog.base(this, data);
    this.data = data;
}
goog.inherits(DisplayMessageConsequent, Consequent);
DisplayMessageConsequent.prototype.execute = function(state) {
    var tag = null;
    if(this.data['frequency'] == "session") {
        tag = this.data['tag'] || 'unknown';
    } else if(this.data['frequency'] == "base_id") {
        tag = (session.region.data ? session.region.data['id'] : 'noregion') + '.' + session.viewing_base.base_id.toString();
    }

    if(tag !== null) {
        if(tag in DisplayMessageConsequent_seen) { return; }
        DisplayMessageConsequent_seen[tag] = 1;
    }

    var cb = (function (dat, _state) { return function() { invoke_splash_message(dat, _state); }; })(this.data, state);
    var params = this.data['notification_params'] || {};
    notification_queue.push(cb, params);
};

/** @constructor @struct
  * @extends Consequent */
function MessageBoxConsequent(data) {
    goog.base(this, data);
    this.dialog_template = data['dialog_template'] || 'quest_tip_valentina_nonmodal_message';
    this.modal = data['modal'] || false;
    this.child = data['child'] || false;
    this.y_position = data['y_position'] || 0.18;
    this.black_bar = data['black_bar'] || false;
    this.widget_data = data['widgets'];
    this.sound = data['sound'] || null;
    this.data = data;
}
goog.inherits(MessageBoxConsequent, Consequent);
MessageBoxConsequent.prototype.execute = function(state) {
    var dialog = new SPUI.Dialog(gamedata['dialogs'][this.dialog_template]);
    dialog.modal = this.modal;

    dialog.user_data['y_position'] = this.y_position;
    dialog.user_data['black_bar'] = this.black_bar;
    for(var name in this.widget_data) {
        var wdat = this.widget_data[name];
        for(var key in wdat) {
            var val = wdat[key];
            if(key == 'ui_name') {
                dialog.widgets[name].set_text_with_linebreaking(val);
            } else if(key == 'xy') {
                dialog.widgets[name].xy = val;
            } else if(key == 'asset') {
                dialog.widgets[name].asset = val;
            } else if(key == 'show') {
                dialog.widgets[name].show = val;
            } else if(typeof(val) == 'object') {
                // sometimes we have to reach into a child dialog
                for(var k in val) {
                    if(k == 'asset') {
                        dialog.widgets[name].widgets[key].asset = val[k];
                    }
                }
            }
        }
    }

    var go_away = function() { change_selection(null); };

    if('ai_threat_hack' in this.data) {
        go_away = function() {
            change_selection(null);
            invoke_daily_tip('new_ai_threat');
        };
    }

    if('ok_button' in dialog.widgets) { dialog.widgets['ok_button'].onclick = go_away; }
    if('close_button' in dialog.widgets) { dialog.widgets['close_button'].onclick = go_away; }

    if(this.modal) {
        change_selection_ui(dialog);
        dialog.auto_center();
    } else {
        if(this.child) {
            install_child_dialog(dialog);
        } else {
            player.quest_root.add(dialog);
        }
        dialog.ondraw = update_valentina_nonmodal_message; // from main.js
        dialog.ondraw(dialog);
    }

    if(this.sound) {
        GameArt.play_canned_sound(this.sound);
    }
};

/** @constructor @struct
  * @extends Consequent */
function InviteFriendsPromptConsequent(data) {
    goog.base(this, data);
    this.show_close_button = ('show_close_button' in data ? data['show_close_button'] : true);
    this.show_arrow = ('show_arrow' in data ? data['show_arrow'] : true);
    this.reason = ('reason' in data ? data['reason'] : 'client_consequent');
}
goog.inherits(InviteFriendsPromptConsequent, Consequent);
InviteFriendsPromptConsequent.prototype.execute = function(state) {
    var dialog = invoke_invite_friends_prompt(this.reason);
    if(!dialog) { return; }
    dialog.widgets['close_button'].show = this.show_close_button;
    // hack - copy code from tutorial_step_congratulations
    if(this.show_arrow) {
        make_tutorial_arrow_for_button('tutorial_congratulations', 'ok_button', 'up');
        make_tutorial_arrow_for_button('tutorial_congratulations', 'fb_share_button', 'up');
    }
    GameArt.play_canned_sound('conquer_sound');
};

/** @constructor @struct
  * @extends Consequent */
function InvokeFullscreenPromptConsequent(data) {
    goog.base(this, data);
    this.notification_params = data['notification_params'] || {};
}
goog.inherits(InvokeFullscreenPromptConsequent, Consequent);
InvokeFullscreenPromptConsequent.prototype.execute = function(state) {
    // note: the enabled() check must be run inside the notification queue,
    // because otherwise it might execute before player.preferences is received
    // from the server.
    notification_queue.push(function() {
        if(!auto_fullscreen_prompt_enabled()) { return; }
        invoke_fullscreen_prompt();
    }, this.notification_params);
};

/** @constructor @struct
  * @extends Consequent */
function BHBookmarkPromptConsequent(data) {
    goog.base(this, data);
}
goog.inherits(BHBookmarkPromptConsequent, Consequent);
BHBookmarkPromptConsequent.prototype.execute = function(state) {
    if(spin_frame_platform !== 'bh') { return; }
    Battlehouse.show_how_to_bookmark();
};

/** @constructor @struct
  * @extends Consequent */
function BHWebPushInitConsequent(data) {
    goog.base(this, data);
    /** @type {Object|null} */
    this.notification_params = data['notification_params'] || null;
    /** @type {string|null} */
    this.prompt_cooldown_name = data['prompt_cooldown_name'] || null;
    /** @type {number|null} */
    this.prompt_cooldown_duration = data['prompt_cooldown_duration'] || null;
}
goog.inherits(BHWebPushInitConsequent, Consequent);

/** @private
    Run the actual browser prompt flow.
    Returns Promise yielding same result as web_push_subscription_ensure().
    @return {!Promise} */
BHWebPushInitConsequent.prototype.do_bh_prompt = function() {
    return Battlehouse.web_push_subscription_ensure()
        .then(function(result) {
            // result === 'ok'
            // new subscription!
            metric_event('6401_web_push_sub_prompt_ok', {});
            send_to_server.func(["BH_WEB_PUSH_PROMPT_OK", result]);
            return result;
        }.bind(this), function(error) {
            // permission was denied (error == 'bh_web_push_subscription_error')
            metric_event('6402_web_push_sub_prompt_fail', {'method': error});

            // client-side predict
            if(this.prompt_cooldown_name) {
                player.cooldown_client_trigger(this.prompt_cooldown_name, this.prompt_cooldown_duration);
            }

            send_to_server.func(["BH_WEB_PUSH_PROMPT_FAILED", error,
                                 this.prompt_cooldown_name, this.prompt_cooldown_duration]);
            return error;
        }.bind(this));
};

/** @private
    Run the in-game GUI flow, which will lead to the browser flow. */
BHWebPushInitConsequent.prototype.do_gui = function() {
    send_to_server.func(["BH_WEB_PUSH_PROMPT"]);
    metric_event('6400_web_push_sub_prompt', {});

    // start GUI here
    var s = player.get_any_abtest_value('bh_web_push_prompt_text',
                                        gamedata['strings']['bh_web_push_prompt_text']);

    change_selection_ui(null);

    var prompt_mode = player.get_any_abtest_value('bh_web_push_prompt_mode',
                                                  gamedata['client']['bh_web_push_prompt_mode']);
    var lock_gui = player.get_any_abtest_value('bh_web_push_prompt_lock_gui',
                                               gamedata['client']['bh_web_push_prompt_lock_gui']);

    if(prompt_mode === 'sequential') { // sequential in-game dialog
        invoke_child_message_dialog(s['ui_title'], s['ui_description'],
                                    {'dialog': 'message_dialog_big',
                                     'use_bbcode': true,
                                     'close_button': false,
                                     'ok_button_ui_name': s['ui_button_sequential'],
                                     'on_ok': function() {
                                         var locker = (lock_gui ? invoke_ui_locker_until_closed() : null);
                                         this.do_bh_prompt()
                                             .then(function(_) {
                                                 if(locker) { close_dialog(locker); }
                                             });
                                     }.bind(this)
                                    });
    } else if(prompt_mode === 'parallel') { // parallel in-game dialog
        var dialog = invoke_child_message_dialog(s['ui_title'], s['ui_description'],
                                                 {'dialog': 'message_dialog_big',
                                                  'close_button': false,
                                                  'ok_button': !lock_gui,
                                                  'ok_button_ui_name': s['ui_button_parallel']});
        this.do_bh_prompt()
            .then(function(_) {
                // clear GUI here
                close_dialog(dialog);
            });
    } else {
        throw Error('unexpected bh_web_push_prompt_mode '+prompt_mode);
    }
};

BHWebPushInitConsequent.prototype.execute = function(state) {
    if(spin_frame_platform !== 'bh') { return; }
    if(!Battlehouse.web_push_supported()) { return; }

    Battlehouse.web_push_subscription_check()
        .then(function(result) {
            if(result === 'denied') {
                return;
            } else if(result === 'granted') {
                // silently ping
                Battlehouse.web_push_subscription_ensure();
            } else if(result === 'prompt') {
                // GUI prompt

                if(this.prompt_cooldown_name && player.cooldown_active(this.prompt_cooldown_name)) {
                    return;
                }

                if(this.notification_params) {
                    notification_queue.push(goog.bind(this.do_gui, this), this.notification_params);
                } else {
                    this.do_gui();
                }
            } else {
                throw Error('unexpected web_push_subscription_check() status '+result);
            }
        }.bind(this));
};

/** @constructor @struct
  * @extends Consequent */
function FacebookPermissionsPromptConsequent(data) {
    // Ask for new facebook permissions. Do nothing if the player has already granted these permissions.
    goog.base(this, data);
    this.scope = data['scope'];
}
goog.inherits(FacebookPermissionsPromptConsequent, Consequent);
FacebookPermissionsPromptConsequent.prototype.execute = function(state) {
    if(!player.has_facebook_permissions(this.scope)) {
        invoke_facebook_permissions_dialog(this.scope);
    }
};


/** @constructor @struct
  * @extends Consequent */
function InvokeMissionsDialogConsequent(data) {
    goog.base(this, data);
    this.select_mission = data['select_mission'] || null;
}
goog.inherits(InvokeMissionsDialogConsequent, Consequent);
InvokeMissionsDialogConsequent.prototype.execute = function(state) {
    change_selection_ui(null);
    var dialog = invoke_missions_dialog(false);
    if(dialog.user_data['quest_list']) {
        for(var i = 0; i < dialog.user_data['quest_list'].length; i++) {
            if(dialog.user_data['quest_list'][i]['name'] === this.select_mission) {
                missions_dialog_select_mission(dialog, i);
                break;
            }
        }
    }
};

/** @constructor @struct
  * @extends Consequent */
function InvokeMailDialogConsequent(data) {
    goog.base(this, data);
}
goog.inherits(InvokeMailDialogConsequent, Consequent);
InvokeMailDialogConsequent.prototype.execute = function(state) {
    change_selection_ui(null);
    invoke_mail_dialog(false);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeStoreConsequent(data) {
    goog.base(this, data);
    this.category = data['category'] || null;
    this.notification_params = data['notification_params'] || null;
}
goog.inherits(InvokeStoreConsequent, Consequent);
InvokeStoreConsequent.prototype.execute = function(state) {
    var cb = (function(_this) { return function() {
        if(_this.category) {
            for(var i = 0; i < gamedata['store']['catalog'].length; i++) {
                var cat = gamedata['store']['catalog'][i];
                if(cat['name'] === _this.category) {
                    invoke_new_store_category(cat);
                    return;
                }
            }
        }
        invoke_new_store_dialog();
    }; })(this);
    if(this.notification_params) {
        notification_queue.push(cb, this.notification_params);
    } else {
        change_selection_ui(null);
        cb();
    }
};

/** @constructor @struct
  * @extends Consequent */
function InvokeBuyGamebucksConsequent(data) {
    goog.base(this, data);
    this.reason = data['reason'] || 'INVOKE_BUY_GAMEBUCKS_DIALOG';
    this.highlight_only = data['highlight_only'] || false;
    this.notification_params = data['notification_params'] || null;
}

goog.inherits(InvokeBuyGamebucksConsequent, Consequent);
InvokeBuyGamebucksConsequent.prototype.execute = function(state) {
    var cb = (function (_this) { return function() {
        invoke_buy_gamebucks_dialog(_this.reason, -1, null, {'highlight_only': _this.highlight_only});
    }; })(this);
    if(this.notification_params) {
        notification_queue.push(cb, this.notification_params);
    } else {
        change_selection_ui(null);
        cb();
    }
};

/** @constructor @struct
  * @extends Consequent */
function InvokeLotteryConsequent(data) {
    goog.base(this, data);
    this.reason = data['reason'] || 'INVOKE_LOTTERY_DIALOG';
    this.force = ('force' in data? data['force'] : false);
}
goog.inherits(InvokeLotteryConsequent, Consequent);
InvokeLotteryConsequent.prototype.execute = function(state) {
    var cb = (function (_this) { return function() {
        var scanner = session.for_each_real_object(function(obj) {
            if(obj.team === 'player' && obj.is_building() && obj.is_lottery_building() && !obj.is_under_construction()) {
                var state = player.get_lottery_state(/** @type {!Building} */ (obj));
                if(this.force || state.can_scan) {
                    return obj;
                }
            }
        }, _this);
        if(scanner) {
            invoke_lottery_dialog(scanner, _this.reason);
        }
    }; })(this);
    notification_queue.push(cb);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeUpgradeConsequent(data) {
    goog.base(this, data);
    this.tech = data['tech'] || null;
    this.building = data['building'] || null;
}
goog.inherits(InvokeUpgradeConsequent, Consequent);
InvokeUpgradeConsequent.prototype.execute = function(state) {
    if(this.tech) {
        invoke_upgrade_tech_dialog(this.tech);
    } else if(this.building) {
        var target_obj = find_highest_level_object_by_type(this.building);
        if(target_obj) {
            invoke_upgrade_building_dialog(target_obj);
        } else {
            invoke_build_dialog(gamedata['buildings'][this.building]['build_category']);
        }
    }
};

/** @constructor @struct
  * @extends Consequent */
function InvokeBuildDialogConsequent(data) {
    goog.base(this, data);
    this.category = data['category'] || null;
}
goog.inherits(InvokeBuildDialogConsequent, Consequent);
InvokeBuildDialogConsequent.prototype.execute = function(state) {
    invoke_build_dialog(this.category);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeCraftingConsequent(data) {
    goog.base(this, data);
    this.category = data['category'] || null;
}
goog.inherits(InvokeCraftingConsequent, Consequent);
InvokeCraftingConsequent.prototype.execute = function(state) {
    invoke_crafting_dialog(this.category);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeMapConsequent(data) {
    goog.base(this, data);
    this.chapter = data['chapter'] || null;
    this.map_loc = data['map_loc'] || null;
}
goog.inherits(InvokeMapConsequent, Consequent);
InvokeMapConsequent.prototype.execute = function(state) {
    change_selection_ui(null);

    // special case when coordinates are provided
    // this skips any "region map might be disabled" logic
    // in invoke_map_dialog()
    if(this.chapter === 'quarries') {
        var map_loc = this.map_loc;
        if(typeof(map_loc) === 'string' && map_loc[0] == '$') {
            map_loc = (state ? state[map_loc.slice(1)] : null);
        }
        if(map_loc) {
            invoke_region_map(map_loc);
            return;
        }
    }

    invoke_map_dialog(this.chapter);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeLeaderboardConsequent(data) {
    goog.base(this, data);
    self.period = data['period'] || null;
    self.mode = data['mode'] || null;
    self.chapter = data['chapter'] || null;
}
goog.inherits(InvokeLeaderboardConsequent, Consequent);
InvokeLeaderboardConsequent.prototype.execute = function(state) {
    change_selection_ui(null);
    invoke_leaderboard(self.period, self.mode, self.chapter);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeSkillChallengeStandingsConsequent(data) {
    goog.base(this, data);
    self.stat_name = data['stat_name'];
    self.challenge_key = data['challenge_key'];
}
goog.inherits(InvokeSkillChallengeStandingsConsequent, Consequent);
InvokeSkillChallengeStandingsConsequent.prototype.execute = function(state) {
    Leaderboard.invoke_skill_challenge_standings_dialog(self.stat_name, self.challenge_key);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeManufactureDialogConsequent(data) {
    goog.base(this, data);
    this.category = data['category'] || null;
    this.specname = data['specname'] || null;
}
goog.inherits(InvokeManufactureDialogConsequent, Consequent);
InvokeManufactureDialogConsequent.prototype.execute = function(state) {
    invoke_manufacture_dialog('consequent', this.category, this.specname);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeBlueprintCongratsConsequent(data) {
    goog.base(this, data);
    this.item = data['item'];
    this.tech = data['tech'];
}
goog.inherits(InvokeBlueprintCongratsConsequent, Consequent);
InvokeBlueprintCongratsConsequent.prototype.execute = function(state) {
    change_selection_ui(null);
    invoke_blueprint_congrats(this.item, this.tech);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeChangeRegionDialogConsequent(data) {
    goog.base(this, data);
}
goog.inherits(InvokeChangeRegionDialogConsequent, Consequent);
InvokeChangeRegionDialogConsequent.prototype.execute = function(state) {
    // reuse the code from the building context menu
    var btn = [];
    add_change_region_button(btn);
    if(btn[0][2] == 'normal' || btn[0][2] == 'disabled_clickable' && btn[0][1]) {
        btn[0][1]();
    }
};

/** @constructor @struct
  * @extends Consequent */
function InvokeTopAlliancesDialogConsequent(data) {
    goog.base(this, data);
}
goog.inherits(InvokeTopAlliancesDialogConsequent, Consequent);
InvokeTopAlliancesDialogConsequent.prototype.execute = function(state) {
    var dialog = _invoke_alliance_dialog();
    alliance_list_change_tab(dialog, 'top');
};

/** @constructor @struct
  * @extends Consequent */
function InvokeInventoryDialogConsequent(data) {
    goog.base(this, data);
}
goog.inherits(InvokeInventoryDialogConsequent, Consequent);
InvokeInventoryDialogConsequent.prototype.execute = function(state) {
    invoke_inventory_dialog();
};

/** @constructor @struct
  * @extends Consequent */
function OpenURLConsequent(data) {
    goog.base(this, data);
    this.url = data['url'];
}
goog.inherits(OpenURLConsequent, Consequent);
OpenURLConsequent.prototype.execute = function(state) {
    url_open_in_new_tab(this.url);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeVideoWidgetConsequent(data) {
    goog.base(this, data);
    this.youtube_id = data['youtube_id'];
    this.notification_params = data['notification_params'] || null;
}
goog.inherits(InvokeVideoWidgetConsequent, Consequent);
InvokeVideoWidgetConsequent.prototype.execute = function(state) {
    var cb = (function(_this) { return function() {
        SPVideoWidget.init(SPVideoWidget.make_youtube_url(_this.youtube_id), function() {});
    }; })(this);
    if(this.notification_params !== null) {
        notification_queue.push(cb, this.notification_params);
    } else {
        cb();
    }
};

/** @constructor @struct
  * @extends Consequent */
function FocusChatGUIConsequent(data) {
    goog.base(this, data);
    this.tab = data['tab'] || null;
}
goog.inherits(FocusChatGUIConsequent, Consequent);
FocusChatGUIConsequent.prototype.execute = function(state) {
    if('chat_frame' in desktop_dialogs) {
        chat_frame_size(desktop_dialogs['chat_frame'], true, true);
        if(this.tab) {
            change_chat_tab(desktop_dialogs['chat_frame'], this.tab);
        }
    }
};

/** @constructor @struct
  * @extends Consequent */
function DailyTipUnderstoodConsequent(data) {
    goog.base(this, data);
    this.name_from_context = data['name_from_context'] || null;
    this.name = data['name'] || null;
    this.status = ('status' in data ? data['status'] : true);
}
goog.inherits(DailyTipUnderstoodConsequent, Consequent);
DailyTipUnderstoodConsequent.prototype.execute = function(state) {
    var name;
    if(this.name_from_context) {
        if(state && this.name_from_context in state) {
            name = state[this.name_from_context];
        } else {
            throw Error('name_from_context not found in '+JSON.stringify(state));
        }
    } else {
        name = this.name;
    }
    send_to_server.func(["DAILY_TIP_UNDERSTOOD", name, this.status]);
};

/** @constructor @struct
  * @extends Consequent */
function DisplayDailyTipConsequent(data) {
    goog.base(this, data);
    this.name = data['name'] || null;
    this.skip_notification_queue = data['skip_notification_queue'] || null;
    this.notification_params = data['notification_params'] || null;
}
goog.inherits(DisplayDailyTipConsequent, Consequent);
DisplayDailyTipConsequent.prototype.execute = function(state) {
    invoke_daily_tip(this.name, this.skip_notification_queue, this.notification_params);
};

/** @constructor @struct
  * @extends Consequent */
function InvokeIngameTipConsequent(data) {
    goog.base(this, data);
    this.tip_name = data['tip_name'] || null;
    this.notification_params = data['notification_params'] || null;
}
goog.inherits(InvokeIngameTipConsequent, Consequent);
InvokeIngameTipConsequent.prototype.execute = function(state) {
    var cb = (function(_this) { return function() {
        invoke_ingame_tip(_this.tip_name, {frequency: GameTipFrequency.ALWAYS_UNLESS_IGNORED});
    }; })(this);
    if(this.notification_params !== null) {
        notification_queue.push(cb, this.notification_params);
    } else {
        cb();
    }
};

/** @constructor @struct
  * @extends Consequent */
function InvokeOfferChoiceConsequent(data) {
    goog.base(this, data);
    this.then_cons = read_consequent(data['then']);
}
goog.inherits(InvokeOfferChoiceConsequent, Consequent);
InvokeOfferChoiceConsequent.prototype.execute = function(state) {
    var then_cb = (function (_this) { return function() {
        _this.then_cons.execute(state);
    }; })(this);
    var invoker = (function (_then_cb) { return function() {
        OfferChoice.invoke_offer_choice(_then_cb);
    }; })(then_cb);
    notification_queue.push(invoker);
};

/** @constructor @struct
  * @extends Consequent */
function HelpRequestReminderConsequent(data) {
    goog.base(this, data);
}
goog.inherits(HelpRequestReminderConsequent, Consequent);
HelpRequestReminderConsequent.prototype.execute = function(state) {
    notification_queue.push(help_request_reminder);
};


/** @constructor @struct
  * @extends Consequent */
function InvokeLoginIncentiveDialogConsequent(data) {
    goog.base(this, data);
}
goog.inherits(InvokeLoginIncentiveDialogConsequent, Consequent);
InvokeLoginIncentiveDialogConsequent.prototype.execute = function(state) {
    var invoker = (function () { return function() {
        LoginIncentiveDialog.invoke();
    }; })();
    notification_queue.push(invoker);
};

/** @constructor @struct
  * @extends Consequent */
function EnableCombatResourceBarsConsequent(data) {
    goog.base(this, data);
    this.enabled = data['enable'];
}
goog.inherits(EnableCombatResourceBarsConsequent, Consequent);
EnableCombatResourceBarsConsequent.prototype.execute = function(state) {
    session.enable_combat_resource_bars = this.enabled;
};

/** @constructor @struct
  * @extends Consequent */
function EnableProgressTimersConsequent(data) {
    goog.base(this, data);
    this.enabled = data['enable'];
}
goog.inherits(EnableProgressTimersConsequent, Consequent);
EnableProgressTimersConsequent.prototype.execute = function(state) {
    session.enable_progress_timers = this.enabled;
};

/** @constructor @struct
  * @extends Consequent */
function EnableDialogCompletionConsequent(data) {
    goog.base(this, data);
    this.enabled = data['enable'];
}
goog.inherits(EnableDialogCompletionConsequent, Consequent);
EnableDialogCompletionConsequent.prototype.execute = function(state) {
    session.enable_dialog_completion_buttons = this.enabled;
};

/** @constructor @struct
  * @extends Consequent */
function PreloadArtAssetConsequent(data) {
    goog.base(this, data);
    this.asset = data['asset'] || null;
    this.state = data['state'] || 'normal';
    this.unit_name = data['unit_name'] || null;
    this.level = data['level'] || 1;
}
goog.inherits(PreloadArtAssetConsequent, Consequent);
PreloadArtAssetConsequent.prototype.execute = function(state) {
    var asset;
    if(this.unit_name) {
        asset = get_leveled_quantity(gamedata['units'][this.unit_name]['art_asset'], this.level);
    } else {
        asset = this.asset;
    }
    GameArt.assets[asset].prep_for_draw([0,0],0,0,this.state);
};

// keep track of once-per-session metrics that we've sent already
var MetricEventConsequent_sent = {};

/** @constructor @struct
  * @extends Consequent */
function MetricEventConsequent(data) {
    goog.base(this, data);
    this.event_name = data['event_name'] || null;
    this.props = data['props'] || {};
    this.frequency = data['frequency'] || null;
    this.tag = data['tag'] || this.event_name;
    this.summary_key = ('summary_key' in data ? data['summary_key'] : 'sum');
}
goog.inherits(MetricEventConsequent, Consequent);
MetricEventConsequent.prototype.execute = function(state) {
    if(this.frequency === 'session') {
        if(MetricEventConsequent_sent[this.tag]) {
            return; // already sent
        }
        MetricEventConsequent_sent[this.tag] = true;
    }
    var props = goog.object.clone(this.props);
    if(state) {
        for(var k in state) { props[k] = state[k]; }
    }
    if(this.summary_key) {
        props[this.summary_key] = player.get_denormalized_summary_props('brief');
    }
    metric_event(this.event_name, props);
};

/** @constructor @struct
  * @extends Consequent */
function ClearUIConsequent(data) {
    goog.base(this, data);
}
goog.inherits(ClearUIConsequent, Consequent);
ClearUIConsequent.prototype.execute = function(state) {
    change_selection_ui(null); // get rid of any existing GUI
    player.quest_tracked_dirty = true; // update quest tips
};

/** @constructor @struct
  * @extends Consequent */
function ClearNotificationsConsequent(data) {
    goog.base(this, data);
}
goog.inherits(ClearNotificationsConsequent, Consequent);
ClearNotificationsConsequent.prototype.execute = function(state) {
    change_selection(null); // get rid of any existing GUI
    notification_queue.clear();
};

/** @constructor @struct
  * @extends Consequent */
function DevEditModeConsequent(data) {
    goog.base(this, data);
}
goog.inherits(DevEditModeConsequent, Consequent);
DevEditModeConsequent.prototype.execute = function(state) {
    player.is_cheater = true;
    send_to_server.func(["CAST_SPELL", 0, "CHEAT_REMOVE_LIMITS", player.is_cheater]);
};

/** @constructor @struct
  * @extends Consequent */
function GiveGamebucksConsequent(data) { // client-side only, kind of hacky - for debugging only, DO NOT USE FOR GAMEPLAY
    goog.base(this, data);
    this.amount = data['amount'];
}
goog.inherits(GiveGamebucksConsequent, Consequent);
GiveGamebucksConsequent.prototype.execute = function(state) {
    send_to_server.func(["CAST_SPELL", 0, "CHEAT_GIVE_GAMEBUCKS", this.amount]);
};

/** @constructor @struct
  * @extends Consequent */
function FPSCounterConsequent(data) {
    goog.base(this, data);
    this.show = ('show' in data ? data['show'] : true);
}
goog.inherits(FPSCounterConsequent, Consequent);
FPSCounterConsequent.prototype.execute = function(state) {
    fps_counter.show = this.show;
};

/** @constructor @struct
  * @extends Consequent */
function LibraryConsequent(data) {
    goog.base(this, data);
    if(!(data['name'] in gamedata['consequent_library'])) {
        throw Error('invalid library consequent "'+data['name']+'"');
    }
    this.cons = read_consequent(gamedata['consequent_library'][data['name']]);
}
goog.inherits(LibraryConsequent, Consequent);
LibraryConsequent.prototype.execute = function(state) {
    return this.cons.execute(state);
};

function read_consequent(data) {
    var kind = data['consequent'];
    if(kind === 'NULL') { return new NullConsequent(data); }
    else if(kind === 'AND') { return new AndConsequent(data); }
    else if(kind === 'IF') { return new IfConsequent(data); }
    else if(kind === 'COND') { return new CondConsequent(data); }
    else if(kind === 'TUTORIAL_ARROW') { return new TutorialArrowConsequent(data); }
    else if(kind === 'FORCE_SCROLL') { return new ForceScrollConsequent(data); }
    else if(kind === 'MESSAGE_BOX') { return new MessageBoxConsequent(data); }
    else if(kind === 'DISPLAY_MESSAGE') { return new DisplayMessageConsequent(data); }
    else if(kind === 'START_AI_ATTACK') { return new StartAIAttackConsequent(data); }
    else if(kind === 'LOAD_AI_BASE') { return new LoadAIBaseConsequent(data); }
    else if(kind === 'REPAIR_ALL') { return new RepairAllConsequent(data); }
    else if(kind === 'VISIT_BASE') { return new VisitBaseConsequent(data); }
    else if(kind === 'CAST_CLIENT_SPELL') { return new CastClientSpellConsequent(data); }
    else if(kind === 'ALL_AGGRESSIVE') { return new AllAggressiveConsequent(data); }
    else if(kind === 'INVOKE_MISSIONS_DIALOG') { return new InvokeMissionsDialogConsequent(data); }
    else if(kind === 'INVOKE_MAIL_DIALOG') { return new InvokeMailDialogConsequent(data); }
    else if(kind === 'INVOKE_STORE_DIALOG') { return new InvokeStoreConsequent(data); }
    else if(kind === 'INVOKE_BUY_GAMEBUCKS_DIALOG') { return new InvokeBuyGamebucksConsequent(data); }
    else if(kind === 'INVOKE_LOTTERY_DIALOG') { return new InvokeLotteryConsequent(data); }
    else if(kind === 'INVOKE_UPGRADE_DIALOG') { return new InvokeUpgradeConsequent(data); }
    else if(kind === 'INVOKE_BUILD_DIALOG') { return new InvokeBuildDialogConsequent(data); }
    else if(kind === 'INVOKE_CRAFTING_DIALOG') { return new InvokeCraftingConsequent(data); }
    else if(kind === 'INVOKE_MAP_DIALOG') { return new InvokeMapConsequent(data); }
    else if(kind === 'INVOKE_LEADERBOARD_DIALOG') { return new InvokeLeaderboardConsequent(data); }
    else if(kind === 'INVOKE_SKILL_CHALLENGE_STANDINGS_DIALOG') { return new InvokeSkillChallengeStandingsConsequent(data); }
    else if(kind === 'INVOKE_MANUFACTURE_DIALOG') { return new InvokeManufactureDialogConsequent(data); }
    else if(kind === 'INVOKE_BLUEPRINT_CONGRATS') { return new InvokeBlueprintCongratsConsequent(data); }
    else if(kind === 'INVOKE_CHANGE_REGION_DIALOG') { return new InvokeChangeRegionDialogConsequent(data); }
    else if(kind === 'INVOKE_TOP_ALLIANCES_DIALOG') { return new InvokeTopAlliancesDialogConsequent(data); }
    else if(kind === 'INVOKE_INVENTORY_DIALOG') { return new InvokeInventoryDialogConsequent(data); }
    else if(kind === 'INVITE_FRIENDS_PROMPT') { return new InviteFriendsPromptConsequent(data); }
    else if(kind === 'INVOKE_FULLSCREEN_PROMPT') { return new InvokeFullscreenPromptConsequent(data); }
    else if(kind === 'BH_BOOKMARK_PROMPT') { return new BHBookmarkPromptConsequent(data); }
    else if(kind === 'BH_WEB_PUSH_INIT') { return new BHWebPushInitConsequent(data); }
    else if(kind === 'HELP_REQUEST_REMINDER') { return new HelpRequestReminderConsequent(data); }
    else if(kind === 'FACEBOOK_PERMISSIONS_PROMPT') { return new FacebookPermissionsPromptConsequent(data); }
    else if(kind === 'OPEN_URL') { return new OpenURLConsequent(data); }
    else if(kind === 'INVOKE_VIDEO_WIDGET') { return new InvokeVideoWidgetConsequent(data); }
    else if(kind === 'FOCUS_CHAT_GUI') { return new FocusChatGUIConsequent(data); }
    else if(kind === 'DAILY_TIP_UNDERSTOOD') { return new DailyTipUnderstoodConsequent(data); }
    else if(kind === 'DISPLAY_DAILY_TIP') { return new DisplayDailyTipConsequent(data); }
    else if(kind === 'INVOKE_INGAME_TIP') { return new InvokeIngameTipConsequent(data); }
    else if(kind === 'INVOKE_OFFER_CHOICE') { return new InvokeOfferChoiceConsequent(data); }
    else if(kind === 'INVOKE_LOGIN_INCENTIVE_DIALOG') { return new InvokeLoginIncentiveDialogConsequent(data); }
    else if(kind === 'ENABLE_COMBAT_RESOURCE_BARS') { return new EnableCombatResourceBarsConsequent(data); }
    else if(kind === 'ENABLE_PROGRESS_TIMERS') { return new EnableProgressTimersConsequent(data); }
    else if(kind === 'ENABLE_DIALOG_COMPLETION') { return new EnableDialogCompletionConsequent(data); }
    else if(kind === 'PRELOAD_ART_ASSET') { return new PreloadArtAssetConsequent(data); }
    else if(kind === 'METRIC_EVENT') { return new MetricEventConsequent(data); }
    else if(kind === 'CLEAR_UI') { return new ClearUIConsequent(data); }
    else if(kind === 'CLEAR_NOTIFICATIONS') { return new ClearNotificationsConsequent(data); }
    else if(kind === 'DEV_EDIT_MODE') { return new DevEditModeConsequent(data); }
    else if(kind === 'GIVE_GAMEBUCKS') { return new GiveGamebucksConsequent(data); }
    else if(kind === 'FPS_COUNTER') { return new FPSCounterConsequent(data); }
    else if(kind === 'LIBRARY') { return new LibraryConsequent(data); }
    else if(kind === 'UI_NOTIFY') { return new UINotifyConsequent(data); }
    else { throw Error('unknown consequent type '+kind); }
}

/** @param {Object} data
    @param {Object=} state */
function execute_logic(data, state) {
    if('if' in data && 'then' in data) {
        var pred_true = read_predicate(data['if']).is_satisfied(player, null);
        if(pred_true) {
            execute_logic(data['then'], state);
        } else if('else' in data) {
            execute_logic(data['else'], state);
        }
    } else if('consequent' in data) {
        read_consequent(data).execute(state);
    } else if('null' in data) {
    } else {
        console.log(data);
        throw Error('bad logic' + data.toString());
    }
};
