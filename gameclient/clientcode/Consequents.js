goog.provide('Consequents');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// for Logic only
goog.require('Predicates');
goog.require('GameArt'); // for client graphics

// depends on global player/selection stuff from clientcode.js
// note: this parallel's Consequents.py on the server side, but
// most consequents are implemented purely on either client or server side

/** @constructor */
function Consequent(data) {
    this.kind = data['consequent'];
}
/** @param {Object=} state */
Consequent.prototype.execute = goog.abstractMethod;

/** @constructor
  * @extends Consequent */
function NullConsequent(data) {
    goog.base(this, data);
}
goog.inherits(NullConsequent, Consequent);
NullConsequent.prototype.execute = function(state) { };

/** @constructor
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

/** @constructor
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

/** @constructor
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

/** @constructor
  * @extends Consequent */
function TutorialArrowConsequent(data) {
    goog.base(this, data);
    this.arrow_type = data['arrow_type'];

    // 'landscape' only
    this.target_name = data['target_name'] || null;
    this.coordinates = data['coordinates'] || null;
    // 'button' only
    this.dialog_name = data['dialog_name'] || null;
    this.widget_name = data['widget_name'] || null;

    this.direction = data['direction'] || 'down';
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
        dialog.ondraw = update_tutorial_arrow_for_landscape(dialog, this.target_name, this.coordinates, this.direction, this.buildable);
        dialog.afterdraw = tutorial_arrow_draw_reticle;
        dialog.ondraw(dialog); // call once here to init position
        player.quest_landscape_arrow = dialog;
    } else if(this.arrow_type == 'button') {
        dialog.ondraw = update_tutorial_arrow_for_button(dialog, this.dialog_name, this.widget_name, this.direction);
    }
};

/** @constructor
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

/** @constructor
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

/** @constructor
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

/** @constructor
  * @extends Consequent */
function VisitBaseConsequent(data) {
    goog.base(this, data);
    this.user_id = data['user_id'];
    this.pre_attack = data['pre_attack'] || false;
}
goog.inherits(VisitBaseConsequent, Consequent);
VisitBaseConsequent.prototype.execute = function(state) {
    var options = {};
    if(this.pre_attack) { options.pre_attack = this.pre_attack; }
    do_visit_base(this.user_id, options);
};

/** @constructor
  * @extends Consequent */
function RepairAllConsequent(data) { // client-side only, kind of hacky
    goog.base(this, data);
    this.user_id = data['user_id'];
    this.pre_attack = data['pre_attack'] || false;
}
goog.inherits(RepairAllConsequent, Consequent);
RepairAllConsequent.prototype.execute = function(state) {
    Store.place_user_currency_order(GameObject.VIRTUAL_ID, "REPAIR_ALL_FOR_MONEY", session.viewing_base.base_id);
};

/** @constructor
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

// note: normally this is done server-side for AI base completions,
// resulting in receiving DISPLAY_MESSAGE over the network, but we
// also implement a client-side version for quest "completion"
// consequents, which are only run client-side.

var DisplayMessageConsequent_seen = {};

/** @constructor
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

/** @constructor
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
        GameArt.assets[this.sound].states['normal'].audio.play(client_time);
    }
};

/** @constructor
  * @extends Consequent */
function InviteFriendsPromptConsequent(data) {
    goog.base(this, data);
    this.show_close_button = ('show_close_button' in data ? data['show_close_button'] : true);
}
goog.inherits(InviteFriendsPromptConsequent, Consequent);
InviteFriendsPromptConsequent.prototype.execute = function(state) {
    var dialog = invoke_invite_friends_prompt();
    if(!dialog) { return; }
    dialog.widgets['close_button'].show = this.show_close_button;
    // hack - copy code from tutorial_step_congratulations
    make_tutorial_arrow_for_button('tutorial_congratulations', 'ok_button', 'up');
    GameArt.assets['conquer_sound'].states['normal'].audio.play(client_time);
};

/** @constructor
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


/** @constructor
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

/** @constructor
  * @extends Consequent */
function InvokeStoreConsequent(data) {
    goog.base(this, data);
    this.category = data['category'] || null;
}
goog.inherits(InvokeStoreConsequent, Consequent);
InvokeStoreConsequent.prototype.execute = function(state) {
    change_selection_ui(null);
    if(this.category) {
        for(var i = 0; i < gamedata['store']['catalog'].length; i++) {
            var cat = gamedata['store']['catalog'][i];
            if(cat['name'] === this.category) {
                invoke_new_store_category(cat);
                return;
            }
        }
    }
    invoke_new_store_dialog();
};

/** @constructor
  * @extends Consequent */
function InvokeBuyGamebucksConsequent(data) {
    goog.base(this, data);
    this.reason = data['reason'] || 'INVOKE_BUY_GAMEBUCKS_DIALOG';
}
goog.inherits(InvokeBuyGamebucksConsequent, Consequent);
InvokeBuyGamebucksConsequent.prototype.execute = function(state) {
    change_selection_ui(null);
    invoke_buy_gamebucks_dialog(this.reason, -1, null);
};

/** @constructor
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

/** @constructor
  * @extends Consequent */
function InvokeBuildDialogConsequent(data) {
    goog.base(this, data);
    this.category = data['category'] || null;
}
goog.inherits(InvokeBuildDialogConsequent, Consequent);
InvokeBuildDialogConsequent.prototype.execute = function(state) {
    invoke_build_dialog(this.category);
};

/** @constructor
  * @extends Consequent */
function InvokeCraftingConsequent(data) {
    goog.base(this, data);
    this.category = data['category'] || null;
}
goog.inherits(InvokeCraftingConsequent, Consequent);
InvokeCraftingConsequent.prototype.execute = function(state) {
    invoke_crafting_dialog(this.category);
};

/** @constructor
  * @extends Consequent */
function InvokeMapConsequent(data) {
    goog.base(this, data);
    this.chapter = data['chapter'] || null;
}
goog.inherits(InvokeMapConsequent, Consequent);
InvokeMapConsequent.prototype.execute = function(state) {
    change_selection_ui(null);
    invoke_map_dialog(this.chapter);
};

/** @constructor
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

/** @constructor
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

/** @constructor
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

/** @constructor
  * @extends Consequent */
function InvokeTopAlliancesDialogConsequent(data) {
    goog.base(this, data);
}
goog.inherits(InvokeTopAlliancesDialogConsequent, Consequent);
InvokeTopAlliancesDialogConsequent.prototype.execute = function(state) {
    var dialog = _invoke_alliance_dialog();
    alliance_list_change_tab(dialog, 'top');
};

/** @constructor
  * @extends Consequent */
function InvokeInventoryDialogConsequent(data) {
    goog.base(this, data);
}
goog.inherits(InvokeInventoryDialogConsequent, Consequent);
InvokeInventoryDialogConsequent.prototype.execute = function(state) {
    invoke_inventory_dialog();
};

/** @constructor
  * @extends Consequent */
function OpenURLConsequent(data) {
    goog.base(this, data);
    this.url = data['url'];
}
goog.inherits(OpenURLConsequent, Consequent);
OpenURLConsequent.prototype.execute = function(state) {
    url_open_in_new_tab(this.url);
};

/** @constructor
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

/** @constructor
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

/** @constructor
  * @extends Consequent */
function DisplayDailyTipConsequent(data) {
    goog.base(this, data);
    this.name = data['name'] || null;
    this.skip_notification_queue = data['skip_notification_queue'] || null;
}
goog.inherits(DisplayDailyTipConsequent, Consequent);
DisplayDailyTipConsequent.prototype.execute = function(state) {
    invoke_daily_tip(this.name, this.skip_notification_queue);
};

/** @constructor
  * @extends Consequent */
function EnableCombatResourceBarsConsequent(data) {
    goog.base(this, data);
    this.enabled = data['enable'];
}
goog.inherits(EnableCombatResourceBarsConsequent, Consequent);
EnableCombatResourceBarsConsequent.prototype.execute = function(state) {
    session.enable_combat_resource_bars = this.enabled;
};

/** @constructor
  * @extends Consequent */
function EnableDialogCompletionConsequent(data) {
    goog.base(this, data);
    this.enabled = data['enable'];
}
goog.inherits(EnableDialogCompletionConsequent, Consequent);
EnableDialogCompletionConsequent.prototype.execute = function(state) {
    session.enable_dialog_completion_buttons = this.enabled;
};

/** @constructor
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

/** @constructor
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

/** @constructor
  * @extends Consequent */
function ClearUIConsequent(data) {
    goog.base(this, data);
}
goog.inherits(ClearUIConsequent, Consequent);
ClearUIConsequent.prototype.execute = function(state) {
    change_selection_ui(null); // get rid of any existing GUI
    player.quest_tracked_dirty = true; // update quest tips
};

/** @constructor
  * @extends Consequent */
function ClearNotificationsConsequent(data) {
    goog.base(this, data);
}
goog.inherits(ClearNotificationsConsequent, Consequent);
ClearNotificationsConsequent.prototype.execute = function(state) {
    change_selection(null); // get rid of any existing GUI
    notification_queue.clear();
};

/** @constructor
  * @extends Consequent */
function DevEditModeConsequent(data) {
    goog.base(this, data);
}
goog.inherits(DevEditModeConsequent, Consequent);
DevEditModeConsequent.prototype.execute = function(state) {
    player.is_cheater = 1;
    send_to_server.func(["CAST_SPELL", 0, "CHEAT_REMOVE_LIMITS", player.is_cheater]);
};

/** @constructor
  * @extends Consequent */
function GiveGamebucksConsequent(data) { // client-side only, kind of hacky - for debugging only, DO NOT USE FOR GAMEPLAY
    goog.base(this, data);
    this.amount = data['amount'];
}
goog.inherits(GiveGamebucksConsequent, Consequent);
GiveGamebucksConsequent.prototype.execute = function(state) {
    send_to_server.func(["CAST_SPELL", 0, "CHEAT_GIVE_GAMEBUCKS", this.amount]);
};

/** @constructor
  * @extends Consequent */
function FPSCounterConsequent(data) {
    goog.base(this, data);
    this.show = ('show' in data ? data['show'] : true);
}
goog.inherits(FPSCounterConsequent, Consequent);
FPSCounterConsequent.prototype.execute = function(state) {
    fps_counter.show = this.show;
};

/** @constructor
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
    else if(kind === 'INVOKE_MISSIONS_DIALOG') { return new InvokeMissionsDialogConsequent(data); }
    else if(kind === 'INVOKE_STORE_DIALOG') { return new InvokeStoreConsequent(data); }
    else if(kind === 'INVOKE_BUY_GAMEBUCKS_DIALOG') { return new InvokeBuyGamebucksConsequent(data); }
    else if(kind === 'INVOKE_UPGRADE_DIALOG') { return new InvokeUpgradeConsequent(data); }
    else if(kind === 'INVOKE_BUILD_DIALOG') { return new InvokeBuildDialogConsequent(data); }
    else if(kind === 'INVOKE_CRAFTING_DIALOG') { return new InvokeCraftingConsequent(data); }
    else if(kind === 'INVOKE_MAP_DIALOG') { return new InvokeMapConsequent(data); }
    else if(kind === 'INVOKE_MANUFACTURE_DIALOG') { return new InvokeManufactureDialogConsequent(data); }
    else if(kind === 'INVOKE_BLUEPRINT_CONGRATS') { return new InvokeBlueprintCongratsConsequent(data); }
    else if(kind === 'INVOKE_CHANGE_REGION_DIALOG') { return new InvokeChangeRegionDialogConsequent(data); }
    else if(kind === 'INVOKE_TOP_ALLIANCES_DIALOG') { return new InvokeTopAlliancesDialogConsequent(data); }
    else if(kind === 'INVOKE_INVENTORY_DIALOG') { return new InvokeInventoryDialogConsequent(data); }
    else if(kind === 'INVITE_FRIENDS_PROMPT') { return new InviteFriendsPromptConsequent(data); }
    else if(kind === 'FACEBOOK_PERMISSIONS_PROMPT') { return new FacebookPermissionsPromptConsequent(data); }
    else if(kind === 'OPEN_URL') { return new OpenURLConsequent(data); }
    else if(kind === 'FOCUS_CHAT_GUI') { return new FocusChatGUIConsequent(data); }
    else if(kind === 'DAILY_TIP_UNDERSTOOD') { return new DailyTipUnderstoodConsequent(data); }
    else if(kind === 'DISPLAY_DAILY_TIP') { return new DisplayDailyTipConsequent(data); }
    else if(kind === 'ENABLE_COMBAT_RESOURCE_BARS') { return new EnableCombatResourceBarsConsequent(data); }
    else if(kind === 'ENABLE_DIALOG_COMPLETION') { return new EnableDialogCompletionConsequent(data); }
    else if(kind === 'PRELOAD_ART_ASSET') { return new PreloadArtAssetConsequent(data); }
    else if(kind === 'METRIC_EVENT') { return new MetricEventConsequent(data); }
    else if(kind === 'CLEAR_UI') { return new ClearUIConsequent(data); }
    else if(kind === 'CLEAR_NOTIFICATIONS') { return new ClearNotificationsConsequent(data); }
    else if(kind === 'DEV_EDIT_MODE') { return new DevEditModeConsequent(data); }
    else if(kind === 'GIVE_GAMEBUCKS') { return new GiveGamebucksConsequent(data); }
    else if(kind === 'FPS_COUNTER') { return new FPSCounterConsequent(data); }
    else if(kind === 'LIBRARY') { return new LibraryConsequent(data); }
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
