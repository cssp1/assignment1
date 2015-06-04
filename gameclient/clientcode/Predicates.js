goog.provide('Predicates');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');

// depends on Player stuff from clientcode.js
// note: this is functionally identical to the server's Predicates.py,
// except for a handful of client-only predicates that are for GUI stuff.

/** @constructor */
function Predicate(data) {
    this.data = data;
    this.kind = data['predicate'];
}

/** Encapsulates the info extracted for ui_describe() and variants
    @constructor
    @struct
    @param {string} descr
    @param {{already_obtained: (boolean|undefined)}=} options */
function PredicateUIDescription(descr, options) {
    this.descr = descr;
    this.options = options || null;
    this.already_obtained = (options && options.already_obtained) || false;
};

/** @private version of ui_describe for subclasses to override
    @param {?} player
    @return {PredicateUIDescription|null} - can be null if we don't want to alert the player about something (e.g. show_if is false)
*/
Predicate.prototype.do_ui_describe = goog.abstractMethod;

/** If predicate is unsatisfied, return a PredicateUIDescription. Otherwise return null.
    @return {PredicateUIDescription|null} */
Predicate.prototype.ui_describe_detail = function(player) {
    if(this.is_satisfied(player, null)) {
        return null;
    }
    // allow manual override of UI description
    if('ui_name' in this.data) {
        return new PredicateUIDescription(this.data['ui_name'], {already_obtained: this.data['ui_already_obtained']||false});
    }
    // allow override with an entirely different predicate
    if('help_predicate' in this.data) {
        // note: use the do_ version here since we already know the predicate is false
        return read_predicate(this.data['help_predicate']).do_ui_describe(player);
    }
    return this.do_ui_describe(player);
};

/** If predicate is unsatisfied, return a user-readable string explaining the completion goal. Otherwise return null.
    @return {string|null} */
Predicate.prototype.ui_describe = function(player) {
    var d = this.ui_describe_detail(player);
    if(d) {
        return d.descr;
    }
    return null;
};

/** @private version of ui_help() for subclasses to override */
Predicate.prototype.do_ui_help = function(player) { return null; };

/** Used by get_requirements_help() to query for actions the player could take to satisfy the predicate */
Predicate.prototype.ui_help = function(player) {
    // allow override with an entirely different predicate
    if('help_predicate' in this.data) {
        return read_predicate(this.data['help_predicate']).ui_help(player);
    }
    var ret = this.do_ui_help(player);
    if(ret) {
        if('ui_name' in this.data) { ret['ui_name'] = this.data['ui_name']; }
        if('ui_title' in this.data) { ret['ui_title'] = this.data['ui_title']; }
    } else if(!ret && !this.is_satisfied(player, null) && ('ui_name' in this.data)) {
        // fall back to a generic message
        ret = {'noun': 'generic', 'verb': 'generic',
               'ui_arg_s': this.data['ui_name'] };
    }
    return ret;
};

// for GUI purposes, return the UNIX timestamp at which this predicate will turn false
// (only applies to predicates that have some sort of time dependency)
Predicate.prototype.ui_expire_time = function(player) { throw Error('ui_expire_time not implemented for this predicate: '+this.kind); }

// return a user-readable string explaining progress towards goal (e.g. "4/5 Bear Asses Collected")
// null if description is unavailable (not all predicates have these)
Predicate.prototype.ui_progress = function(player, qdata) { return null; }

/** @constructor
  * @extends Predicate */
function AlwaysTruePredicate(data) { goog.base(this, data); }
goog.inherits(AlwaysTruePredicate, Predicate);
AlwaysTruePredicate.prototype.is_satisfied = function(player, qdata) { return true; };

/** @constructor
  * @extends Predicate */
function AlwaysFalsePredicate(data) { goog.base(this, data); }
goog.inherits(AlwaysFalsePredicate, Predicate);
AlwaysFalsePredicate.prototype.is_satisfied = function(player, qdata) { return false; };
AlwaysFalsePredicate.prototype.do_ui_describe = function(player) { return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name']); };

/** @constructor
  * @extends Predicate */
function RandomPredicate(data) { goog.base(this, data); this.chance = data['chance']; }
goog.inherits(RandomPredicate, Predicate);
RandomPredicate.prototype.is_satisfied = function(player, qdata) { return Math.random() < this.chance; };

/** @constructor
  * @extends Predicate */
function ComboPredicate(data) {
    goog.base(this, data);
    this.subpredicates = [];
    for(var i = 0; i < data['subpredicates'].length; i++) {
        this.subpredicates.push(read_predicate(data['subpredicates'][i]));
    }
}
goog.inherits(ComboPredicate, Predicate);

/** @constructor
  * @extends ComboPredicate */
function AndPredicate(data) {
    goog.base(this, data);
}
goog.inherits(AndPredicate, ComboPredicate);
AndPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var i = 0; i < this.subpredicates.length; i++) {
        if(!this.subpredicates[i].is_satisfied(player, qdata)) {
            return false;
        }
    }
    return true;
};
AndPredicate.prototype.do_ui_describe = function(player) {
    var descr_ls = [];
    var opts = {};
    for(var i = 0; i < this.subpredicates.length; i++) {
        var p = this.subpredicates[i].ui_describe_detail(player);
        if(p) {
            descr_ls.push(p.descr);
            if(p.options) {
                goog.object.extend(opts, p.options);
            }
        }
    }
    return new PredicateUIDescription(descr_ls.join(',\n'), opts);
};
AndPredicate.prototype.do_ui_help = function(player) {
    for(var i = 0; i < this.subpredicates.length; i++) {
        var h = this.subpredicates[i].ui_help(player);
        if(h) { return h; }
    }
    return null;
};
AndPredicate.prototype.ui_expire_time = function(player) {
    var etime = -1;
    for(var i = 0; i < this.subpredicates.length; i++) {
        // return the min expire time out of all subpredicates
        var t = this.subpredicates[i].ui_expire_time(player);
        etime = (etime > 0 ? Math.min(etime, t) : t);
    }
    return etime;
}

/** @constructor
  * @extends ComboPredicate */
function OrPredicate(data) {
    goog.base(this, data);
}
goog.inherits(OrPredicate, ComboPredicate);
OrPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var i = 0; i < this.subpredicates.length; i++) {
        if(this.subpredicates[i].is_satisfied(player, qdata)) {
            return true;
        }
    }
    return false;
};
OrPredicate.prototype.do_ui_describe = function(player) {
    var descr_ls = [];
    var opts = {};
    for(var i = 0; i < this.subpredicates.length; i++) {
        var p = this.subpredicates[i].ui_describe_detail(player);
        if(p) {
            descr_ls.push(p.descr);
            if(p.options) {
                goog.object.extend(opts, p.options);
            }
        }
    }
    return new PredicateUIDescription(descr_ls.join(' OR\n'), opts);
};
OrPredicate.prototype.do_ui_help = function(player) {
    for(var i = 0; i < this.subpredicates.length; i++) {
        var h = this.subpredicates[i].ui_help(player);
        if(h) { return h; }
    }
    return null;
};
OrPredicate.prototype.ui_expire_time = function(player) {
    var etime = -1;
    for(var i = 0; i < this.subpredicates.length; i++) {
        // return the max expire time out of all TRUE subpredicates
        if(this.subpredicates[i].is_satisfied(player, null)) {
            var t = this.subpredicates[i].ui_expire_time(player);
            etime = (etime > 0 ? Math.max(etime, t) : t);
        }
    }
    return etime;
}

/** @constructor
  * @extends ComboPredicate */
function NotPredicate(data) {
    goog.base(this, data);
}
goog.inherits(NotPredicate, ComboPredicate);
NotPredicate.prototype.is_satisfied = function(player, qdata) {
    return !(this.subpredicates[0].is_satisfied(player, qdata));
};
NotPredicate.prototype.do_ui_describe = function(player) {
    var sub = this.subpredicates[0].ui_describe_detail(player);
    return new PredicateUIDescription('NOT '+ (sub ? sub.descr : 'unknown'), (sub ? sub.options : {}));
};
NotPredicate.prototype.ui_expire_time = function(player) { return -1; }; // not sure on this one

/** @constructor
  * @extends Predicate */
function TutorialCompletePredicate(data) { goog.base(this, data); }
goog.inherits(TutorialCompletePredicate, Predicate);
TutorialCompletePredicate.prototype.is_satisfied = function(player, qdata) { return (player.tutorial_state === "COMPLETE"); };

/** @constructor
  * @extends Predicate */
function AllBuildingsUndamagedPredicate(data) { goog.base(this, data); }
goog.inherits(AllBuildingsUndamagedPredicate, Predicate);
AllBuildingsUndamagedPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.is_building() && obj.is_damaged() && obj.team === 'player') {
            return false;
        }
    }
    return true;
};
AllBuildingsUndamagedPredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name']);
};

/** @constructor
  * @extends Predicate */
function ObjectUndamagedPredicate(data) {
    goog.base(this, data);
    this.spec_name = data['spec'];
}
goog.inherits(ObjectUndamagedPredicate, Predicate);
ObjectUndamagedPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.spec['name'] == this.spec_name && !obj.is_damaged() && obj.team === 'player') {
            return true;
        }
    }
    return false;
};
ObjectUndamagedPredicate.prototype.do_ui_describe = function(player) {
    var spec = gamedata['units'][this.spec_name] || gamedata['buildings'][this.spec_name];
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%s', spec['ui_name']));
};
ObjectUndamagedPredicate.prototype.do_ui_help = function(player) {
    var obj = null;
    for(var id in session.cur_objects.objects) {
        var o = session.cur_objects.objects[id];
        if(o.spec['name'] === this.spec_name && o.team === 'player' && o.is_damaged()) {
            obj = o;
        }
    }
    if(obj) {
        return {'noun': 'building', 'verb': 'repair', 'target': obj,
                'ui_arg_s': gamedata['buildings'][this.spec_name]['ui_name'] };
    }
    return null;
};

/** @constructor
  * @extends Predicate */
function ObjectUnbusyPredicate(data) {
    goog.base(this, data);
    this.spec_name = data['spec'];
}
goog.inherits(ObjectUnbusyPredicate, Predicate);
ObjectUnbusyPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.spec['name'] == this.spec_name && !obj.is_damaged() && !obj.is_busy() && obj.team === 'player') {
            return true;
        }
    }
    return false;
};
ObjectUnbusyPredicate.prototype.do_ui_describe = function(player) {
    var spec = gamedata['buildings'][this.spec_name];
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%s', spec['ui_name']));
};
ObjectUnbusyPredicate.prototype.do_ui_help = function(player) {
    var obj = null;
    for(var id in session.cur_objects.objects) {
        var o = session.cur_objects.objects[id];
        if(o.spec['name'] === this.spec_name && o.team === 'player' && (o.is_damaged() || (o.time_until_finish() > 0))) {
            obj = o;
        }
    }
    if(obj) {
        return {'noun': 'building', 'verb': ((obj.is_damaged() && !obj.is_repairing()) ? 'repair' : 'speedup'), 'target': obj,
                'ui_arg_s': gamedata['buildings'][this.spec_name]['ui_name'] };
    }
    return null;
};

/** @constructor
  * @extends Predicate */
function BuildingDestroyedPredicate(data) {
    goog.base(this, data);
    this.spec_name = data['spec'];
}
goog.inherits(BuildingDestroyedPredicate, Predicate);
BuildingDestroyedPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.spec['name'] == this.spec_name && obj.is_destroyed()) {
            return true;
        }
    }
    return false;
};


/** @constructor
  * @extends Predicate */
function BuildingQuantityPredicate(data) {
    goog.base(this, data);
    this.building_type = data['building_type'];
    this.trigger_qty = data['trigger_qty'];
    this.under_construction_ok = data['under_construction_ok'] || false;
}
goog.inherits(BuildingQuantityPredicate, Predicate);
BuildingQuantityPredicate.prototype.is_satisfied = function(player, qdata) {
    var howmany = 0;
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.spec['name'] === this.building_type && (this.under_construction_ok || !obj.is_under_construction()) && obj.team === 'player') {
            howmany += 1;
        }
    }
    return (howmany >= this.trigger_qty);
};
BuildingQuantityPredicate.prototype.do_ui_describe = function(player) {
    var building_spec = gamedata['buildings'][this.building_type];
    if(('show_if' in building_spec) && !read_predicate(building_spec['show_if']).is_satisfied(player, null)) {
        return null;
    }
    var ret = gamedata['strings']['predicates'][this.kind]['ui_name'];
    ret = ret.replace('%s', building_spec['ui_name']);
    var qty_string;
    if(this.trigger_qty > 1) {
        qty_string = this.trigger_qty.toString()+'x ';
    } else {
        qty_string = '';
    }
    ret = ret.replace('%d ', qty_string);
    return new PredicateUIDescription(ret);
};
BuildingQuantityPredicate.prototype.ui_progress = function(player, qdata) {
    var ret = gamedata['strings']['predicates'][this.kind]['ui_progress'];
    var howmany = 0;
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.spec['name'] === this.building_type && (this.under_construction_ok || !obj.is_under_construction()) && obj.team === 'player') {
            howmany += 1;
        }
    }
    ret = ret.replace('%d1', howmany.toString());
    ret = ret.replace('%d2', this.trigger_qty.toString());
    return ret;
};
BuildingQuantityPredicate.prototype.do_ui_help = function(player) {
    var building_spec = gamedata['buildings'][this.building_type];
    // do not return help for hidden buildings
    if(('show_if' in building_spec) && !read_predicate(building_spec['show_if']).is_satisfied(player, null)) {
        return null;
    }

    var count = 0;
    var under_construction_obj = null;
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.spec['name'] === this.building_type && obj.team === 'player') {
            if(this.under_construction_ok || !obj.is_under_construction()) {
                count += 1;
            } else if(obj.is_under_construction()) {
                under_construction_obj = obj;
            }
        }
    }
    if(count < this.trigger_qty) {
        if(under_construction_obj) {
            return {'noun': 'building', 'verb': 'speedup', 'target': under_construction_obj,
                    'ui_arg_s': gamedata['buildings'][this.building_type]['ui_name']};
        } else {
            return {'noun': 'building', 'verb': (count < 1 ? 'build_first' : 'build_more'), 'target': this.building_type,
                    'ui_arg_s': (count < 1 ? gamedata['buildings'][this.building_type]['ui_name_indefinite'] || gamedata['buildings'][this.building_type]['ui_name'] : gamedata['buildings'][this.building_type]['ui_name']),
                    'ui_arg_d': this.trigger_qty};
        }
    }
    return null;
};

/** @constructor
  * @extends Predicate */
function BuildingLevelPredicate(data) {
    goog.base(this, data);
    this.building_spec = gamedata['buildings'][data['building_type']];
    this.trigger_level = data['trigger_level'];
    this.trigger_qty = data['trigger_qty'] || 1;
    this.upgrading_ok = data['upgrading_ok'] || false;
}
goog.inherits(BuildingLevelPredicate, Predicate);
BuildingLevelPredicate.prototype.is_satisfied = function(player, qdata) {
    var count = 0;
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.spec === this.building_spec &&
           obj.team === 'player' &&
           !obj.is_under_construction()) {
            if(obj.level >= this.trigger_level) {
                count += 1;
            } else if(this.upgrading_ok && obj.is_upgrading() && (obj.level + 1) >= this.trigger_level) {
                count += 1;
            } else if(this.trigger_qty < 0) {
                return false; // require ALL buildings to be at this level
            }
        }
    }
    return (count >= this.trigger_qty);
};
BuildingLevelPredicate.prototype.do_ui_describe = function(player) {
    if(('show_if' in this.building_spec) && !read_predicate(this.building_spec['show_if']).is_satisfied(player, null)) {
        return null;
    }
    var ret = gamedata['strings']['predicates'][this.kind]['ui_name' + (this.trigger_qty != 1 ? (this.trigger_qty < 0 ? '_all' : '_multiple') : '')];
    if(this.trigger_qty != 1 && this.trigger_qty > 0) {
        ret = ret.replace('%qty', this.trigger_qty.toString());
    }
    ret = ret.replace('%s', this.building_spec['ui_name']);
    ret = ret.replace('%d', this.trigger_level.toString());
    return new PredicateUIDescription(ret);
};
BuildingLevelPredicate.prototype.do_ui_help = function(player) {
    // do not return help for hidden buildings
    if(('show_if' in this.building_spec) && !read_predicate(this.building_spec['show_if']).is_satisfied(player, null)) {
        return null;
    }

    var raw_count = 0;
    var level_count = 0;
    var min_level = 999, need_to_upgrade_obj = null, need_to_speedup_obj = null;
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.spec === this.building_spec &&
           obj.team === 'player') {
            if(obj.is_under_construction()) {
                need_to_speedup_obj = obj;
            } else {
                raw_count += 1;
                if(obj.level >= this.trigger_level) {
                    level_count += 1;
                } else if(this.upgrading_ok && obj.is_upgrading() && (obj.level + 1) >= this.trigger_level) {
                    level_count += 1;
                } else {
                    if((obj.level < this.trigger_level) &&
                       (!obj.is_upgrading() || gamedata['enable_multiple_foremen'])) { // note: it may be safe to omit this check even if multiple_foreman are off
                            if(obj.level < min_level) {
                                need_to_upgrade_obj = obj;
                                min_level = obj.level;
                            }
                    }
                }
            }
        }
    }
    if(raw_count < this.trigger_qty) {
        if(need_to_speedup_obj) {
            return {'noun': 'building', 'verb': 'speedup', 'target': need_to_speedup_obj,
                    'ui_arg_s': this.building_spec['ui_name']};
        } else {
            return {'noun': 'building', 'verb': (raw_count < 1 ? 'build_first' : 'build_more'), 'target': this.building_spec['name'],
                    'ui_arg_s': (raw_count < 1 ? (this.building_spec['ui_name_indefinite'] || this.building_spec['ui_name']) : this.building_spec['ui_name']),
                    'ui_arg_d': this.trigger_qty};
        }
    } else if(level_count < this.trigger_qty && need_to_upgrade_obj) {
        return {'noun': 'building', 'verb': 'upgrade', 'target': need_to_upgrade_obj,
                'ui_arg_s': this.building_spec['ui_name'], 'ui_arg_d': this.trigger_level};
    }
    return null;
};

/** @constructor
  * @extends Predicate */
function UnitQuantityPredicate(data) {
    goog.base(this, data);
    this.unit_spec = gamedata['units'][data['unit_type']];
    this.trigger_qty = data['trigger_qty'];
    this.include_queued = data['include_queued'] || false;
    this.method = data['method'] || ">=";
}
goog.inherits(UnitQuantityPredicate, Predicate);
UnitQuantityPredicate.prototype.is_satisfied = function(player, qdata) {
    var howmany = 0;

    // add existing units
    for(var id in player.my_army) {
        var obj = player.my_army[id];
        if(obj['spec'] === this.unit_spec['name']) {
            howmany += 1;
        }
    }

    // add units that are currently under construction
    if(this.include_queued) {
        for(var id in session.cur_objects.objects) {
            var obj = session.cur_objects.objects[id];
            if(obj.is_building() && obj.is_manufacturing()) {
                for(var j = 0; j < obj.manuf_queue.length; j++) {
                    var item = obj.manuf_queue[j];
                    if(item['spec_name'] === this.unit_spec['name']) {
                        howmany += 1;
                    }
                }
            }
        }
    }

    if(this.method == '>=') {
        return howmany >= this.trigger_qty;
    } else if(this.method == '==') {
        return howmany == this.trigger_qty;
    } else if(this.method == '<') {
        return howmany < this.trigger_qty;
    } else {
        throw Error('unknown method '+this.method);
    }
};
UnitQuantityPredicate.prototype.do_ui_describe = function(player) {
    var ret = gamedata['strings']['predicates'][this.kind]['ui_name'];
    ret = ret.replace('%s', this.unit_spec['ui_name']);
    ret = ret.replace('%d', this.trigger_qty.toString());
    return new PredicateUIDescription(ret);
};

/** @constructor
  * @extends Predicate */
function TechLevelPredicate(data) {
    goog.base(this, data);
    this.tech = data['tech'];
    this.min_level = data['min_level'];
    this.max_level = ('max_level' in data ? data['max_level'] : -1);
    this.researching_ok = data['researching_ok'] || false;
}
goog.inherits(TechLevelPredicate, Predicate);
TechLevelPredicate.prototype.is_satisfied = function(player, qdata) {
    if((player.tech[this.tech] || 0) >= this.min_level) {
        if((this.max_level < 0) || ((player.tech[this.tech] || 0) <= this.max_level)) {
            return true;
        }
    }
    if(this.researching_ok) {
        var cur = (this.tech in player.tech ? player.tech[this.tech] : 0);
        if((cur+1) >= this.min_level) {
            for(var id in session.cur_objects.objects) {
                var obj = session.cur_objects.objects[id];
                if(obj.team === 'player' && obj.is_building() && obj.research_item == this.tech) {
                    return true;
                }
            }
        }
    }
    return false;
};
TechLevelPredicate.prototype.do_ui_describe = function(player) {
    var spec = gamedata['tech'][this.tech];
    // do not return help for hidden techs
    if(('show_if' in spec) && !read_predicate(spec['show_if']).is_satisfied(player, null)) {
        return null;
    }
    var ret = gamedata['strings']['predicates'][this.kind]['ui_name'];
    ret = ret.replace('%s', spec['ui_name']);
    ret = ret.replace('%d', this.min_level.toString());
    return new PredicateUIDescription(ret);
};
TechLevelPredicate.prototype.do_ui_help = function(player) {
    var spec = gamedata['tech'][this.tech];
    // do not return help for hidden techs
    if(('show_if' in spec) && !read_predicate(spec['show_if']).is_satisfied(player, null)) {
        return null;
    }
    if(!this.is_satisfied(player, null)) {
        return {'noun': 'tech', 'verb': 'research', 'target': this.tech,
                'ui_arg_s': gamedata['tech'][this.tech]['ui_name'], 'ui_arg_d': this.min_level};
    }
    return null;
};

/** @type {(Object.<string,boolean>|null)} special cache just for QuestCompletedPredicate to avoid O(N^2) behavior */
var quest_completed_predicate_cache = null;
function predicate_cache_on() {
    quest_completed_predicate_cache = {};
}
function predicate_cache_off() {
    quest_completed_predicate_cache = null;
}

/** @constructor
  * @extends Predicate */
function QuestCompletedPredicate(data) {
    goog.base(this, data);
    this.quest = gamedata['quests'][data['quest_name']];
    this.must_claim = data['must_claim'] || false;
}
goog.inherits(QuestCompletedPredicate, Predicate);
QuestCompletedPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!this.must_claim && !this.quest['force_claim']) {
        // check recursively without requiring the other quest to be claimed

        if(quest_completed_predicate_cache !== null && (this.quest['name'] in quest_completed_predicate_cache)) {
            //console.log('HIT '+this.quest['name']);
            return quest_completed_predicate_cache[this.quest['name']];
        } else {
            //console.log('MISS '+this.quest['name']);
        }

        var ret = true;
        if(('activation' in this.quest) && !read_predicate(this.quest['activation']).is_satisfied(player, null)) {
            ret = false;
        }
        if(ret && !read_predicate(this.quest['goal']).is_satisfied(player, null)) {
            ret = false;
        }
        if(quest_completed_predicate_cache !== null) {
            quest_completed_predicate_cache[this.quest['name']] = ret;
        }
        return ret;
    } else {
        return (this.quest['name'] in player.completed_quests);
    }
};
QuestCompletedPredicate.prototype.do_ui_describe = function(player) {
    var ret = gamedata['strings']['predicates'][this.kind]['ui_name'];
    ret = ret.replace('%s', this.quest['ui_name']);
    return new PredicateUIDescription(ret);
};
QuestCompletedPredicate.prototype.ui_expire_time = function(player) { return -1; }

/** @constructor
  * @extends Predicate */
function AuraActivePredicate(data) {
    goog.base(this, data);
    this.aura_name = data['aura_name'];
    this.min_stack = data['min_stack'] || 1;
}
goog.inherits(AuraActivePredicate, Predicate);
AuraActivePredicate.prototype.is_satisfied = function(player, qdata) {
    for(var i = 0; i < player.player_auras.length; i++) {
        var aura = player.player_auras[i];
        if(aura['spec'] == this.aura_name && ((aura['stack']||1) >= this.min_stack)) {
            if(('end_time' in aura) && (aura['end_time'] > 0) && (aura['end_time'] < server_time)) { continue; }
            return true;
        }
    }
    return false;
};
AuraActivePredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%s', gamedata['auras'][this.aura_name]['ui_name']));
};

/** @constructor
  * @extends Predicate */
function AuraInactivePredicate(data) {
    goog.base(this, data);
    this.act_pred = new AuraActivePredicate(data);
}
goog.inherits(AuraInactivePredicate, Predicate);
AuraInactivePredicate.prototype.is_satisfied = function(player, qdata) { return !this.act_pred.is_satisfied(player, qdata); };
AuraInactivePredicate.prototype.do_ui_describe = function(player) {
    var togo = -1;
    for(var i = 0; i < player.player_auras.length; i++) {
        var aura = player.player_auras[i];
        if(aura['spec'] == this.act_pred.aura_name && ((aura['stack']||1) >= this.act_pred.min_stack)) {
            if(('end_time' in aura) && (aura['end_time'] > 0) && (aura['end_time'] < server_time)) { continue; }
            togo = ('end_time' in aura ? aura['end_time'] - server_time : -1);
        }
    }
    var template = gamedata['strings']['predicates'][this.kind][(togo > 0 ? 'ui_name_togo' : 'ui_name')];
    return new PredicateUIDescription(template.replace('%s', gamedata['auras'][this.act_pred.aura_name]['ui_name']).replace('%togo', pretty_print_time(togo)));
};
AuraInactivePredicate.prototype.do_ui_help = function(player) {
    var aura_spec = gamedata['auras'][this.act_pred.aura_name];
    if(aura_spec && aura_spec['speedupable']) {
        return {'noun': 'player_aura', 'verb': 'speedup', 'target': this.act_pred.aura_name, 'ui_arg_s': aura_spec['ui_name'] };
    }
    return null;
};

/** @constructor
  * @extends Predicate */
function CooldownActivePredicate(data) {
    goog.base(this, data);
    this.name = data['name'];
    this.match_data = data['match_data'] || null;
}
goog.inherits(CooldownActivePredicate, Predicate);
CooldownActivePredicate.prototype.is_satisfied = function(player, qdata) { return player.cooldown_active(this.name, this.match_data); };
CooldownActivePredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%s', this.name));
};

/** @constructor
  * @extends Predicate */
function CooldownInactivePredicate(data) {
    goog.base(this, data);
    this.act_pred = new CooldownActivePredicate(data);
}
goog.inherits(CooldownInactivePredicate, Predicate);
CooldownInactivePredicate.prototype.is_satisfied = function(player, qdata) { return !this.act_pred.is_satisfied(player, qdata); };
CooldownInactivePredicate.prototype.do_ui_describe = function(player) {
    var template = ('ui_cooldown_name' in this.data ? this.data['ui_cooldown_name'] : gamedata['strings']['predicates'][this.kind]['ui_name']);
    return new PredicateUIDescription(template.replace('%s', this.act_pred.name).replace('%togo', pretty_print_time(player.cooldown_togo(this.act_pred.name))));
};

/** @constructor
  * @extends Predicate */
function PlayerHistoryPredicate(data, key, minvalue, ui_name_s, ui_name_d, method) {
    goog.base(this, data);
    this.key = key;
    this.minvalue = minvalue;
    this.relative = data['relative'] || false;
    this.ui_name_s = ui_name_s;
    this.ui_name_d = ui_name_d;
    this.method = method;
}
goog.inherits(PlayerHistoryPredicate, Predicate);
PlayerHistoryPredicate.prototype.is_satisfied = function(player, qdata) {
    var test_value;
    if(this.key in player.history) {
        test_value = player.history[this.key];
    } else {
        test_value = 0;
    }
    if(qdata && this.relative) {
        var old_value = (this.key in qdata) ? qdata[this.key] : 0;
        test_value -= old_value;
    }
    if(this.method == '>=') {
        return test_value >= this.minvalue;
    } else if(this.method == '==') {
        return test_value == this.minvalue;
    } else if(this.method == '<') {
        return test_value < this.minvalue;
    } else {
        throw Error('unknown method '+this.method);
    }
};
PlayerHistoryPredicate.prototype.do_ui_describe = function(player) {
    var ret;
    if('ui_name' in this.data) {
        ret = this.data['ui_name'];
    } else {
        ret = gamedata['strings']['predicates'][this.kind]['ui_name'];
    }
    ret = ret.replace('%s', this.ui_name_s);
    ret = ret.replace('%d', this.ui_name_d);
    return new PredicateUIDescription(ret);
};
PlayerHistoryPredicate.prototype.ui_progress = function(player, qdata) {
    var ret;
    if(this.kind in gamedata['strings']['predicates'] && ('ui_progress' in gamedata['strings']['predicates'][this.kind])) {
        // this is used for the child classes like FRIENDS_JOINED
        ret = gamedata['strings']['predicates'][this.kind]['ui_progress'];
    } else if('player_history' in gamedata['strings'] && this.key in gamedata['strings']['player_history'] &&
              'ui_progress' in gamedata['strings']['player_history'][this.key]) {
        ret = gamedata['strings']['player_history'][this.key]['ui_progress'];
    } else {
        return null;
    }

    var old_value = (this.relative && qdata && this.key in qdata) ? qdata[this.key] : 0;
    var cur_value = (this.key in player.history) ? player.history[this.key] : 0;
    ret = ret.replace('%d1', pretty_print_number(cur_value - old_value));
    ret = ret.replace('%d2', pretty_print_number(this.minvalue));
    return ret;
};
PlayerHistoryPredicate.prototype.ui_expire_time = function(player) { return -1; }


/** @constructor
  * @extends Predicate */
function PlayerPreferencePredicate(data) {
    goog.base(this, data);
    this.key = data['key'];
    this.value = data['value'];
}
goog.inherits(PlayerPreferencePredicate, Predicate);
PlayerPreferencePredicate.prototype.is_satisfied = function(player, qdata) {
    // hack - allow temporary settings_dialog settings to override the actual player.preferences
    var prefs;
    var dialog = find_dialog('settings_dialog');
    prefs = (dialog ? dialog.user_data['preferences'] : player.preferences);
    var test_value = get_preference_setting(prefs, this.key);
    return test_value === this.value;
};

/** @constructor
  * @extends PlayerHistoryPredicate */
function FriendsJoinedPredicate(data, key, minvalue, ui_name_s, ui_name_d, method) {
    goog.base(this, data, key, minvalue, ui_name_s, ui_name_d, method);
}
goog.inherits(FriendsJoinedPredicate, PlayerHistoryPredicate);
FriendsJoinedPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!('initial_friends_in_game' in player.history)) {
        return false;
    }
    var delta = (player.history[this.key] || 0) - player.history['initial_friends_in_game'];
    if(this.method == '>=') {
        return delta >= this.minvalue;
    } else {
        throw Error('unknown method '+this.method);
    }
};
FriendsJoinedPredicate.prototype.ui_progress = function(player, qdata) {
    var ret = gamedata['strings']['predicates'][this.kind]['ui_progress'];
    var delta;
    if(!('initial_friends_in_game' in player.history)) {
        delta = 0;
    } else {
        delta = (player.history[this.key] || 0) - player.history['initial_friends_in_game'];
    }
    ret = ret.replace('%d1', Math.min(delta, this.minvalue).toString());
    ret = ret.replace('%d2', this.minvalue.toString());
    return ret;
};

/** @constructor
  * @extends Predicate */
function ABTestPredicate(data) {
    goog.base(this, data);
    this.test = data['test'];
    this.key = data['key'];
    this.value = data['value'];
    this.def = data['default'];
}
goog.inherits(ABTestPredicate, Predicate);
ABTestPredicate.prototype.do_ui_describe = function(player) { return null; } // internal use only
ABTestPredicate.prototype.is_satisfied = function(player, qdata) {
    var cur_value = player.get_abtest_value(this.test, this.key, this.def);
    return cur_value == this.value;
};

/** @constructor
  * @extends Predicate */
function AnyABTestPredicate(data) {
    goog.base(this, data);
    this.key = data['key'];
    this.value = data['value'];
    this.def = ('default' in data ? data['default'] : 0);
}
goog.inherits(AnyABTestPredicate, Predicate);
AnyABTestPredicate.prototype.do_ui_describe = function(player) { return null; } // internal use only
AnyABTestPredicate.prototype.is_satisfied = function(player, qdata) {
    var cur_value = player.get_any_abtest_value(this.key, this.def);
    return cur_value == this.value;
};

/** @constructor
  * @extends Predicate */
function LibraryPredicate(data) {
    goog.base(this, data);
    if(!(data['name'] in gamedata['predicate_library'])) {
        throw Error('invalid library predicate "'+data['name']+'"');
    }
    this.pred = read_predicate(gamedata['predicate_library'][data['name']]);
}
goog.inherits(LibraryPredicate, Predicate);
LibraryPredicate.prototype.do_ui_describe = function(player) {
    return this.pred.ui_describe_detail(player);
}
LibraryPredicate.prototype.is_satisfied = function(player, qdata) {
    return this.pred.is_satisfied(player, qdata);
};
LibraryPredicate.prototype.do_ui_help = function(player) {
    return this.pred.ui_help(player);
};
LibraryPredicate.prototype.ui_expire_time = function(player) {
    return this.pred.ui_expire_time(player);
};

/** @constructor
  * @extends Predicate */
function AIBaseActivePredicate(data) {
    goog.base(this, data);
    this.user_id = data['user_id'];
}
goog.inherits(AIBaseActivePredicate, Predicate);
AIBaseActivePredicate.prototype.is_satisfied = function(player, qdata) {
    var base = gamedata['ai_bases_client']['bases'][this.user_id.toString()] || null;
    if(!base) { return false; }
    if('activation' in base) {
        return read_predicate(base['activation']).is_satisfied(player, qdata);
    }
    return true;
};
AIBaseActivePredicate.prototype.do_ui_describe = function(player) {
    var base = gamedata['ai_bases_client']['bases'][this.user_id.toString()] || null;
    if(!base) { return new PredicateUIDescription("Unknown AI base active"); }
    var pred = base['activation'] || null;
    if(pred) {
        return read_predicate(pred).ui_describe_detail(player);
    }
    var s = gamedata['strings']['predicates'][this.kind]['ui_name'];
    return new PredicateUIDescription(s.replace('%d', this.user_id.toString()));
};

/** @constructor
  * @extends Predicate */
function AIBaseShownPredicate(data) {
    goog.base(this, data);
    this.user_id = data['user_id'];
}
goog.inherits(AIBaseShownPredicate, Predicate);
AIBaseShownPredicate.prototype.is_satisfied = function(player, qdata) {
    var base = gamedata['ai_bases_client']['bases'][this.user_id.toString()];
    if(!base) { return false; }
    var pred = ('show_if' in base ? base['show_if'] : ('activation' in base ? base['activation'] : null));
    if(pred) {
        return read_predicate(pred).is_satisfied(player, qdata);
    }
    return true;
};
AIBaseShownPredicate.prototype.do_ui_describe = function(player) {
    var base = gamedata['ai_bases_client']['bases'][this.user_id.toString()];
    if(!base) { return null; }
    var pred = ('show_if' in base ? base['show_if'] : ('activation' in base ? base['activation'] : null));
    if(pred) {
        return read_predicate(pred).ui_describe_detail(player);
    }
    var s = gamedata['strings']['predicates'][this.kind]['ui_name'];
    return new PredicateUIDescription(s.replace('%d', this.user_id.toString()));
};

/** @constructor
  * @extends Predicate */
function UserIDPredicate(data) {
    goog.base(this, data);
    this.allow = data['allow'];
}
goog.inherits(UserIDPredicate, Predicate);
UserIDPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var i = 0; i < this.allow.length; i++) {
        if(session.user_id === this.allow[i]) {
            return true;
        }
    }
    return false;
};


/** @constructor
  * @extends Predicate */
function PriceRegionPredicate(data) {
    goog.base(this, data);
    this.regions = data['regions'];
}
goog.inherits(PriceRegionPredicate, Predicate);
PriceRegionPredicate.prototype.is_satisfied = function(player, qdata) {
    return goog.array.contains(this.regions, player.price_region);
};

/** @constructor
  * @extends Predicate */
function CountryTierPredicate(data) {
    goog.base(this, data);
    this.tiers = data['tiers'];
}
goog.inherits(CountryTierPredicate, Predicate);
CountryTierPredicate.prototype.is_satisfied = function(player, qdata) {
    return goog.array.contains(this.tiers, player.country_tier);
};

/** @constructor
  * @extends Predicate */
function CountryPredicate(data) {
    goog.base(this, data);
    this.countries = data['countries'];
}
goog.inherits(CountryPredicate, Predicate);
CountryPredicate.prototype.is_satisfied = function(player, qdata) {
    return goog.array.contains(this.countries, player.country);
};

/** @constructor
  * @extends Predicate */
function EventTimePredicate(data) {
    goog.base(this, data);
    this.name = data['event_name'] || null;
    this.kind = data['event_kind'] || 'current_event';
    this.method = data['method'];
    this.range = ('range' in data ? data['range'] : null);
    this.ignore_activation = ('ignore_activation' in data ? data['ignore_activation'] : false);
    this.t_offset = ('time_offset' in data ? data['time_offset'] : 0);
}
goog.inherits(EventTimePredicate, Predicate);
EventTimePredicate.prototype.is_satisfied = function(player, qdata) {
    var et = player.get_event_time(this.kind, this.name, this.method, this.ignore_activation, this.t_offset);
    if(et === null) { return false; }
    if(this.range) {
        return (et >= this.range[0] && et < this.range[1]);
    } else {
        return !!et;
    }
};
EventTimePredicate.prototype.ui_expire_time = function(player) {
    var ref_time = player.get_absolute_time() + this.t_offset;
    var event_data = player.get_event(this.kind, this.name, ref_time, this.ignore_activation);
    if(!event_data) {
        throw Error('event '+this.name+' is not active');
    }
    return event_data['end_time'];
};

/** @constructor
  * @extends Predicate */
function AbsoluteTimePredicate(data) {
    goog.base(this, data);
    this.range = data['range'];
    this.mod = ('mod' in data ? data['mod'] : -1);
    this.shift = data['shift'] || 0;
}
goog.inherits(AbsoluteTimePredicate, Predicate);
AbsoluteTimePredicate.prototype.is_satisfied = function(player, qdata) {
    var et = player.get_absolute_time();
    if(!et) { return false; }
    et += this.shift;
    if(this.mod > 0) {
        et = et % this.mod;
    }
    if(this.range[0] >= 0 && et < this.range[0]) { return false; }
    if(this.range[1] >= 0 && et >= this.range[1]) { return false; }
    return true;
};
AbsoluteTimePredicate.prototype.do_ui_describe = function(player) {
    var s = gamedata['strings']['predicates'][this.kind]['ui_name'];
    return new PredicateUIDescription(s.replace('%d1', this.range[0].toString()).replace('%d2',this.range[1].toString()));
};
AbsoluteTimePredicate.prototype.ui_expire_time = function(player) {
    return this.range[1];
};


/** @constructor
  * @extends Predicate */
function AccountCreationTimePredicate(data) {
    goog.base(this, data);
    this.range = data['range'];
}
goog.inherits(AccountCreationTimePredicate, Predicate);
AccountCreationTimePredicate.prototype.is_satisfied = function(player, qdata) {
    var creat = player.creation_time;
    if(this.range[0] >= 0 && creat < this.range[0]) { return false; }
    if(this.range[1] >= 0 && creat >= this.range[1]) { return false; }
    return true;
};
AccountCreationTimePredicate.prototype.do_ui_describe = function(player) {
    var s = gamedata['strings']['predicates'][this.kind]['ui_name'];
    return new PredicateUIDescription(s.replace('%d1', this.range[0].toString()).replace('%d2',this.range[1].toString()));
};
AccountCreationTimePredicate.prototype.ui_expire_time = function(player) { return -1; };

/** @constructor
  * @extends Predicate */
function BrowserNamePredicate(data) {
    goog.base(this, data);
    this.names = data['names'];
}
goog.inherits(BrowserNamePredicate, Predicate);
BrowserNamePredicate.prototype.is_satisfied = function(player, qdata) {
    for(var i = 0; i < this.names.length; i++) {
        if(this.names[i] == spin_demographics['browser_name']) {
            return true;
        }
    }
    return false;
};

/** @constructor
  * @extends Predicate */
function BrowserVersionPredicate(data) {
    goog.base(this, data);
    this.versions = data['versions'];
}
goog.inherits(BrowserVersionPredicate, Predicate);
BrowserVersionPredicate.prototype.is_satisfied = function(player, qdata) {
    if(this.versions[0] >= 0 && spin_demographics['browser_version'] < this.versions[0]) { return false; }
    if(this.versions[1] >= 0 && spin_demographics['browser_version'] > this.versions[1]) { return false; }
    return true;
};

/** @constructor
  * @extends Predicate */
function BrowserOSPredicate(data) {
    goog.base(this, data);
    this.names = data['os'];
}
goog.inherits(BrowserOSPredicate, Predicate);
BrowserOSPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var i = 0; i < this.names.length; i++) {
        if(this.names[i] == spin_demographics['browser_OS']) {
            return true;
        }
    }
    return false;
};

/** @constructor
  * @extends Predicate */
function BrowserHardwarePredicate(data) {
    goog.base(this, data);
    this.hardware = data['hardware'];
}
goog.inherits(BrowserHardwarePredicate, Predicate);
BrowserHardwarePredicate.prototype.is_satisfied = function(player, qdata) {
    return goog.array.contains(this.hardware, spin_demographics['browser_hardware']);
};

/** @constructor
  * @extends Predicate */
function FramePlatformPredicate(data) {
    goog.base(this, data);
    this.platform = data['platform'];
}
goog.inherits(FramePlatformPredicate, Predicate);
FramePlatformPredicate.prototype.is_satisfied = function(player, qdata) {
    return spin_frame_platform == this.platform;
};

/** @constructor
  * @extends Predicate */
function FacebookAppNamespacePredicate(data) {
    goog.base(this, data);
    this.namespace = data['namespace'];
}
goog.inherits(FacebookAppNamespacePredicate, Predicate);
FacebookAppNamespacePredicate.prototype.is_satisfied = function(player, qdata) {
    return spin_app_namespace == this.namespace;
};

///////////////////////////
//// CLIENT SIDE PREDICATES
///////////////////////////

/** @constructor
  * @extends Predicate */
function ClientFacebookLikesPredicate(data) {
    goog.base(this, data);
    this.id = data['id'];
}
goog.inherits(ClientFacebookLikesPredicate, Predicate);
ClientFacebookLikesPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!spin_facebook_enabled || spin_frame_platform != 'fb') { return false; }
    return SPFB.likes(this.id);
};

/** @constructor
  * @extends Predicate */
function SelectedPredicate(data) {
    goog.base(this, data);
    this.object_type = data['type'];
    this.spellname = data['spellname'] || null;
    this.spellkind = data['spellkind'] || null;
    this.state = data['state'] || null;
}
goog.inherits(SelectedPredicate, Predicate);
SelectedPredicate.prototype.is_satisfied = function(player, qdata) {
    if(this.object_type == "NOTHING") {
        return (selection.unit == null);
    } else if(this.object_type == "CURSOR") {
        if(this.spellname && selection.spellname != this.spellname) { return false; }
        if(this.spellkind && selection.spellkind != this.spellkind) { return false; }
        return (selection.ui && selection.ui.user_data && selection.ui.user_data['cursor']);
    } else {
        if(selection.unit && ((this.object_type == "ANY") || (selection.unit.spec['name'] == this.object_type))) {
            if(this.state == 'upgrading' && (!selection.unit.is_building() || !selection.unit.is_upgrading())) {
                return false;
            }
            if(this.state == 'under_construction' && (!selection.unit.is_building() || !selection.unit.is_under_construction())) {
                return false;
            }
            return true;
        }
        return false;
    }
};

/** @constructor
  * @extends Predicate */
function UIClearPredicate(data) {
    goog.base(this, data);
}
goog.inherits(UIClearPredicate, Predicate);
UIClearPredicate.prototype.is_satisfied = function(player, qdata) {
    return (selection.ui==null) && (client_time - selection.ui_change_time >= gamedata['client']['ui_quiet_time']);
};

/** @constructor
  * @extends Predicate */
function QuestClaimablePredicate(data) {
    goog.base(this, data);
}
goog.inherits(QuestClaimablePredicate, Predicate);
QuestClaimablePredicate.prototype.is_satisfied = function(player, qdata) {
    return player.claimable_quests > 0;
};

/** @constructor
  * @extends Predicate */
function HomeBasePredicate(data) {
    goog.base(this, data);
}
goog.inherits(HomeBasePredicate, Predicate);
HomeBasePredicate.prototype.is_satisfied = function(player, qdata) {
    return session.home_base;
};

/** @constructor
  * @extends Predicate */
function HasAttackedPredicate(data) {
    goog.base(this, data);
}
goog.inherits(HasAttackedPredicate, Predicate);
HasAttackedPredicate.prototype.is_satisfied = function(player, qdata) {
    return session.has_attacked;
};
HasAttackedPredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name']);
};

/** @constructor
  * @extends Predicate */
function HasDeployedPredicate(data) {
    goog.base(this, data);
    this.qty = data['qty'] || 1;
    this.method = data['method'] || '>=';
}
goog.inherits(HasDeployedPredicate, Predicate);
HasDeployedPredicate.prototype.is_satisfied = function(player, qdata) {
    // when quests check this predicate they are looking to see if units are deployed, not that combat is initiated,
    // so return false unless there are deployed units
    if(session.has_deployed) {
        var deployed_units = session.count_post_deploy_units();
        if(this.method == '>=') {
            return deployed_units >= this.qty;
        } else if(this.method == '==') {
            return deployed_units == this.qty;
        } else if(this.method == '<') {
            return deployed_units < this.qty;
        } else {
            throw Error('unknown method '+this.method);
        }
    } else {
        return false;
    }
};
HasDeployedPredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name']);
};

/** @constructor
  * @extends Predicate */
function PreDeployUnitsPredicate(data) {
    goog.base(this, data);
    this.spec_name = data['spec'];
    this.qty = data['qty'];
}
goog.inherits(PreDeployUnitsPredicate, Predicate);
PreDeployUnitsPredicate.prototype.is_satisfied = function(player, qdata) {
    var spec = gamedata['units'][this.spec_name];
    var available_qty = session.count_deployable_units_of_spec(this.spec_name);
    var selected_qty = session.count_pre_deploy_units_of_spec(this.spec_name);

    if(this.qty == "ALL") {
        var full = (selected_qty >= available_qty);
        if(!full) {
            // check if we're out of space
            if(!session.using_squad_deployment() && (session.deployed_unit_space+spec['consumes_space'] > get_player_stat(player.stattab,'deployable_unit_space'))) {
                full = true; // still consider this "full"
            }
        }
        return full;
    } else {
        throw Error('unhandled qty '+this.qty);
    }
};

/** @constructor
  * @extends Predicate */
function HostileUnitNearPredicate(data) {
    goog.base(this, data);
}
goog.inherits(HostileUnitNearPredicate, Predicate);
HostileUnitNearPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!qdata || !('source_obj' in qdata)) { throw Error('no source_obj provided'); }
    var obj = qdata['source_obj'];
    if(obj.ai_target) {
        return vec_distance(obj.interpolate_pos(), obj.ai_target.interpolate_pos()) < this.data['distance'];
    }
    var obj_list = query_objects_within_distance(obj.interpolate_pos(), this.data['distance'],
                                                 { ignore_object: obj,
                                                   exclude_invul: true,
                                                   only_team: (obj.team == 'enemy' ? 'player' : 'enemy'),
                                                   exclude_barriers: false,
                                                   mobile_only: false,
                                                   exclude_flying: this.data['exclude_flying'],
                                                   flying_only: false,
                                                   exclude_invisible_to: obj.team,
                                                   tag: 'HOSTILE_UNIT_NEAR'
                                                 });
    return obj_list.length > 0;
};

/** @constructor
  * @extends Predicate */
function ForemanIsBusyPredicate(data) {
    goog.base(this, data);
}
goog.inherits(ForemanIsBusyPredicate, Predicate);
ForemanIsBusyPredicate.prototype.is_satisfied = function(player, qdata) {
    return !!player.foreman_is_busy();
};

/** @constructor
  * @extends Predicate */
function DialogOpenPredicate(data) {
    goog.base(this, data);
    this.dialog_name = data['dialog_name'];
    this.page_name = data['dialog_page'] || null;
    this.chapter_name = data['dialog_chapter'] || null;
    this.category_name = data['dialog_category'] || null;
}
goog.inherits(DialogOpenPredicate, Predicate);

DialogOpenPredicate.prototype.is_satisfied = function(player, qdata) {
    var d = selection.ui;
    while(d) {
        if(d.user_data && d.user_data['dialog']) {
            if(match_dialog_name(this.dialog_name, d.user_data['dialog'])) {
                if(this.page_name && d.user_data['page'] != this.page_name) { return false; }
                if(this.chapter_name && d.user_data['chapter'] != this.chapter_name) { return false; }
                if(this.category_name && d.user_data['category'] != this.category_name) { return false; }
                return true;
            } else {
                if(d.children && d.children.length > 0) {
                    d = d.children[d.children.length-1];
                } else {
                    d = null;
                }
            }
        } else {
            d = null;
        }
    }
    return false;
};

/** @constructor
  * @extends Predicate */
function BaseSizePredicate(data) {
    goog.base(this, data);
    this.method = data['method'];
    this.value = data['value'];
}
goog.inherits(BaseSizePredicate, Predicate);
BaseSizePredicate.prototype.is_satisfied = function(player, qdata) {
    // note: this evaluates viewing_base, not necessarily player's home base
    var cur = session.viewing_base.base_size;
    if(this.method == '>=') {
        return cur >= this.value;
    } else if(this.method == '<') {
        return cur < this.value;
    } else if(this.method == '==') {
        return cur == this.value;
    } else {
        throw Error('unknown method '+this.method);
    }
};

/** @constructor
  * @extends Predicate */
function HomeRegionPredicate(data) {
    goog.base(this, data);
    this.regions = data['regions'] || null;
    this.require_nosql = data['is_nosql'] || false;
}
goog.inherits(HomeRegionPredicate, Predicate);
HomeRegionPredicate.prototype.is_satisfied = function(player, qdata) {
    if(this.regions !== null) {
        if(goog.array.contains(this.regions, 'ANY')) {
            return !!session.region.data;
        } else {
            for(var i = 0; i < this.regions.length; i++) {
                if(session.region.data && session.region.data['id'] === this.regions[i]) {
                    return true;
                }
            }
            return false;
        }
    }

    if(this.require_nosql) {
        return (session.region.data && session.region.data['storage'] == 'nosql');
    }
    return false;
};

/** @constructor
  * @extends Predicate */
function RegionPropertyPredicate(data) {
    goog.base(this, data);
    this.key = data['key'];
    this.value = data['value'];
    this.def = ('default' in data ? data['default'] : 0);
}
goog.inherits(RegionPropertyPredicate, Predicate);
RegionPropertyPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!session.region.data) { return false; }
    var val = (this.key in session.region.data ? session.region.data[this.key] : this.def);
    return val == this.value;
};

/** @constructor
  * @extends Predicate */
function InventoryPredicate(data) {
    goog.base(this, data);
    this.num = data['num'];
}
goog.inherits(InventoryPredicate, Predicate);
InventoryPredicate.prototype.is_satisfied = function(player, qdata) {
    return (player.inventory.length >= this.num);
};

/** @constructor
  * @extends Predicate */
function HasItemPredicate(data) {
    goog.base(this, data);
    this.item_name = data['item_name'];
    this.min_count = data['min_count'] || 1;
    this.level = data['level'] || null;
    this.check_mail = data['check_mail'] || false;
    this.check_crafting = data['check_crafting'] || false;
}
goog.inherits(HasItemPredicate, Predicate);
HasItemPredicate.prototype.is_satisfied = function(player, qdata) {
    return player.has_item(this.item_name, this.min_count, this.check_mail, this.check_crafting, this.level);
};
HasItemPredicate.prototype.ui_progress = function(player, qdata) {
    var ret = gamedata['strings']['predicates'][this.kind]['ui_progress'];
    ret = ret.replace('%d1', player.count_item(this.item_name, this.check_mail, this.check_crafting, this.level).toString());
    ret = ret.replace('%d2', this.min_count.toString());
    return ret;
};
HasItemPredicate.prototype.ui_expire_time = function(player) { return -1; }; // not sure on this one

/** @constructor
  * @extends Predicate */
function HasItemSetPredicate(data) {
    goog.base(this, data);
    this.item_set = data['item_set'];
    this.min_count = ('min' in data ? data['min'] : -1);
}
goog.inherits(HasItemSetPredicate, Predicate);
HasItemSetPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!(this.item_set in player.stattab['item_sets'])) { return false; }
    var min_count = this.min_count;
    if(min_count < 0) {
        min_count = gamedata['item_sets'][this.item_set]['members'].length;
    }
    return (player.stattab['item_sets'][this.item_set] >= min_count);
};

/** @constructor
  * @extends Predicate */
function IsInAlliancePredicate(data) {
    goog.base(this, data);
}
goog.inherits(IsInAlliancePredicate, Predicate);
IsInAlliancePredicate.prototype.is_satisfied = function(player, qdata) {
    return session.is_in_alliance();
};

/** @constructor
  * @extends Predicate */
function HasAliasPredicate(data) {
    goog.base(this, data);
}
goog.inherits(HasAliasPredicate, Predicate);
HasAliasPredicate.prototype.is_satisfied = function(player, qdata) {
    return !!player.alias;
};
HasAliasPredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name']);
};
HasAliasPredicate.prototype.do_ui_help = function(player) {
    return {'noun': 'alias', 'verb': 'set' };
};

/** @constructor
  * @extends Predicate */
function HasTitlePredicate(data) {
    goog.base(this, data);
    this.name = data['name'];
}
goog.inherits(HasTitlePredicate, Predicate);
HasTitlePredicate.prototype.is_satisfied = function(player, qdata) {
    var show_if = gamedata['titles'][this.name]['show_if'];
    if(show_if && !read_predicate(show_if).is_satisfied(player, qdata)) { return false; }
    var requires = gamedata['titles'][this.name]['requires'];
    if(requires && !read_predicate(requires).is_satisfied(player, qdata)) { return false; }
    return true;
};
HasTitlePredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%s', gamedata['titles'][this.name]['ui_name']));
};

/** @constructor
  * @extends Predicate */
function UsingTitlePredicate(data) {
    goog.base(this, data);
    this.name = data['name'] || null;
}
goog.inherits(UsingTitlePredicate, Predicate);
UsingTitlePredicate.prototype.is_satisfied = function(player, qdata) {
    if(this.name === null) { // true if player is using any valid title
        return player.title && (player.title in gamedata['titles']);
    } else {
        return player.title === this.name;
    }
};

/** @constructor
  * @extends Predicate */
function PlayerLevelPredicate(data) {
    goog.base(this, data);
    this.level = data['level'];
}
goog.inherits(PlayerLevelPredicate, Predicate);
PlayerLevelPredicate.prototype.is_satisfied = function(player, qdata) {
    return (player.level() >= this.level);
};
PlayerLevelPredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%d', this.level.toString()));
};

/** @constructor
  * @extends Predicate */
function LadderPlayerPredicate(data) {
    goog.base(this, data);
}
goog.inherits(LadderPlayerPredicate, Predicate);
LadderPlayerPredicate.prototype.is_satisfied = function(player, qdata) {
    return player.is_ladder_player();
};

/** @constructor
  * @extends Predicate */
function MailAttachmentsPredicate(data) {
    goog.base(this, data);
}
goog.inherits(MailAttachmentsPredicate, Predicate);
MailAttachmentsPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var i = 0; i < player.mailbox.length; i++) {
        if(player.mailbox[i]['attachments'] && player.mailbox[i]['attachments'].length > 0) {
            return true;
        }
    }
    return false;
};

/** @constructor
  * @extends Predicate */
function ArmySizePredicate(data) {
    goog.base(this, data);
    this.trigger_qty = data['trigger_qty'];
    this.method = data['method'] || ">=";
    this.include_queued = 'include_queued' in data ? data['include_queued'] : true;
}
goog.inherits(ArmySizePredicate, Predicate);
ArmySizePredicate.prototype.is_satisfied = function(player, qdata) {
    var army_size = player.get_army_space_usage_by_squad()['ALL'];

    if(!this.include_queued) {
        army_size -= player.get_manufacture_queue_space_usage();
    }

    if(this.method == '>=') {
        return army_size >= this.trigger_qty;
    } else if(this.method == '==') {
        return army_size == this.trigger_qty;
    } else if(this.method == '<') {
        return army_size < this.trigger_qty;
    } else {
        throw Error('unknown method '+this.method);
    }
};

/** @constructor
  * @extends Predicate */
function ViewingBaseDamagePredicate(data) {
    goog.base(this, data);
    this.value = data['value'];
    this.method = data['method'] || '>=';
}
goog.inherits(ViewingBaseDamagePredicate, Predicate);
ViewingBaseDamagePredicate.prototype.is_satisfied = function(player, qdata) {
    var base_damage = calc_base_damage();
    if(this.method == '>=') {
        return base_damage >= this.value;
    } else {
        throw Error('unknown method '+this.method);
    }
};

/** @constructor
  * @extends Predicate */
function ViewingBaseObjectDestroyedPredicate(data) {
    goog.base(this, data);
    this.spec = data['spec'];
}
goog.inherits(ViewingBaseObjectDestroyedPredicate, Predicate);
ViewingBaseObjectDestroyedPredicate.prototype.is_satisfied = function(player, qdata) {
    for(var id in session.cur_objects.objects) {
        var obj = session.cur_objects.objects[id];
        if(obj.is_destroyed() && obj.spec['name'] === this.spec) {
            return true;
        }
    }
    return false;
};

function read_predicate(data) {
    var kind = data['predicate'];
    if(kind === 'AND') { return new AndPredicate(data); }
    else if(kind === 'OR') { return new OrPredicate(data); }
    else if(kind === 'NOT') { return new NotPredicate(data); }
    else if(kind === 'ALWAYS_TRUE') { return new AlwaysTruePredicate(data); }
    else if(kind === 'ALWAYS_FALSE') { return new AlwaysFalsePredicate(data); }
    else if(kind === 'RANDOM') { return new RandomPredicate(data); }
    else if(kind === 'TUTORIAL_COMPLETE') { return new TutorialCompletePredicate(data); }
    else if(kind === 'ACCOUNT_CREATION_TIME') { return new AccountCreationTimePredicate(data); }
    else if(kind === 'ALL_BUILDINGS_UNDAMAGED') { return new AllBuildingsUndamagedPredicate(data); }
    else if(kind === 'OBJECT_UNDAMAGED') { return new ObjectUndamagedPredicate(data); }
    else if(kind === 'OBJECT_UNBUSY') { return new ObjectUnbusyPredicate(data); }
    else if(kind === 'BUILDING_DESTROYED') { return new BuildingDestroyedPredicate(data); }
    else if(kind === 'BUILDING_QUANTITY') { return new BuildingQuantityPredicate(data); }
    else if(kind === 'BUILDING_LEVEL') { return new BuildingLevelPredicate(data); }
    else if(kind === 'UNIT_QUANTITY') { return new UnitQuantityPredicate(data); }
    else if(kind === 'TECH_LEVEL') { return new TechLevelPredicate(data); }
    else if(kind === 'QUEST_COMPLETED') { return new QuestCompletedPredicate(data); }
    else if(kind === 'AURA_ACTIVE') { return new AuraActivePredicate(data); }
    else if(kind === 'AURA_INACTIVE') { return new AuraInactivePredicate(data); }
    else if(kind === 'COOLDOWN_ACTIVE') { return new CooldownActivePredicate(data); }
    else if(kind === 'COOLDOWN_INACTIVE') { return new CooldownInactivePredicate(data); }
    else if(kind === 'ABTEST') { return new ABTestPredicate(data); }
    else if(kind === 'ANY_ABTEST') { return new AnyABTestPredicate(data); }
    else if(kind === 'LIBRARY') { return new LibraryPredicate(data); }
    else if(kind === 'AI_BASE_ACTIVE') { return new AIBaseActivePredicate(data); }
    else if(kind === 'AI_BASE_SHOWN') { return new AIBaseShownPredicate(data); }
    else if(kind === 'PLAYER_HISTORY') { return new PlayerHistoryPredicate(data, data['key'], data['value'], data['key'], data['value'].toString(), data['method']); }
    else if(kind === 'ATTACKS_LAUNCHED') { return new PlayerHistoryPredicate(data, 'attacks_launched', data['number'], '', data['number'].toString(), '>='); }
    else if(kind === 'ATTACKS_VICTORY') { return new PlayerHistoryPredicate(data, 'attacks_victory', data['number'], '', data['number'].toString(), '>='); }
    else if(kind === 'CONQUESTS') { return new PlayerHistoryPredicate(data, data['key'], data['value'], data['key'], data['value'].toString(), data['method']); }
    else if(kind === 'UNITS_MANUFACTURED') { return new PlayerHistoryPredicate(data, 'units_manufactured', data['number'], '', data['number'].toString(), '>='); }
    else if(kind === 'LOGGED_IN_TIMES') { return new PlayerHistoryPredicate(data, 'logged_in_times', data['number'], '', data['number'].toString(), '>='); }
    else if(kind === 'RESOURCES_HARVESTED_TOTAL') {
        var resource_type = data['resource_type'];
        return new PlayerHistoryPredicate(data, 'harvested_'+resource_type+'_total', data['amount'], resource_type, data['amount'].toString(), '>=');
    }
    else if(kind === 'RESOURCES_HARVESTED_AT_ONCE') {
        var resource_type = data['resource_type'];
        return new PlayerHistoryPredicate(data, 'harvested_'+resource_type+'_at_once', data['amount'], resource_type, data['amount'].toString(), '>=');
    } else if(kind === 'FRIENDS_JOINED') {
        return new FriendsJoinedPredicate(data, 'friends_in_game', data['number'], '', data['number'].toString(), '>=');
    } else if(kind === 'FRAME_PLATFORM') {
        return new FramePlatformPredicate(data);
    } else if(kind === 'FACEBOOK_LIKES_SERVER') {
        return new AlwaysFalsePredicate(data);
    } else if(kind === 'FACEBOOK_LIKES_CLIENT') {
        return new ClientFacebookLikesPredicate(data);
    } else if(kind === 'FACEBOOK_APP_NAMESPACE') {
        return new FacebookAppNamespacePredicate(data);
    } else if(kind === 'PRICE_REGION') {
        return new PriceRegionPredicate(data);
    } else if(kind === 'COUNTRY_TIER') {
        return new CountryTierPredicate(data);
    } else if(kind === 'USER_ID') {
        return new UserIDPredicate(data);
    } else if(kind === 'COUNTRY') {
        return new CountryPredicate(data);
    } else if(kind === 'EVENT_TIME') {
        return new EventTimePredicate(data);
    } else if(kind === 'ABSOLUTE_TIME') {
        return new AbsoluteTimePredicate(data);
    } else if(kind === 'BROWSER_NAME') {
        return new BrowserNamePredicate(data);
    } else if(kind === 'BROWSER_VERSION') {
        return new BrowserVersionPredicate(data);
    } else if(kind === 'BROWSER_OS') {
        return new BrowserOSPredicate(data);
    } else if(kind === 'BROWSER_HARDWARE') {
        return new BrowserHardwarePredicate(data);
    } else if(kind === 'SELECTED') {
        return new SelectedPredicate(data);
    } else if(kind === 'UI_CLEAR') {
        return new UIClearPredicate(data);
    } else if(kind === 'QUEST_CLAIMABLE') {
        return new QuestClaimablePredicate(data);
    } else if(kind === 'HOME_BASE') {
        return new HomeBasePredicate(data);
    } else if(kind === 'HAS_ATTACKED') {
        return new HasAttackedPredicate(data);
    } else if(kind === 'HAS_DEPLOYED') {
        return new HasDeployedPredicate(data);
    } else if(kind === 'PRE_DEPLOY_UNITS') {
        return new PreDeployUnitsPredicate(data);
    } else if(kind === 'HOSTILE_UNIT_NEAR') {
        return new HostileUnitNearPredicate(data);
    } else if(kind === 'DIALOG_OPEN') {
        return new DialogOpenPredicate(data);
    } else if(kind === 'PLAYER_PREFERENCE') {
        return new PlayerPreferencePredicate(data);
    } else if(kind === 'FOREMAN_IS_BUSY') {
        return new ForemanIsBusyPredicate(data);
    } else if(kind === 'INVENTORY') {
        return new InventoryPredicate(data);
    } else if(kind === 'HAS_ITEM') {
        return new HasItemPredicate(data);
    } else if(kind === 'HAS_ITEM_SET') {
        return new HasItemSetPredicate(data);
    } else if(kind === 'LADDER_PLAYER') {
        return new LadderPlayerPredicate(data);
    } else if(kind === 'IS_IN_ALLIANCE') {
        return new IsInAlliancePredicate(data);
    } else if(kind === 'HAS_ALIAS') {
        return new HasAliasPredicate(data);
    } else if(kind === 'HAS_TITLE') {
        return new HasTitlePredicate(data);
    } else if(kind === 'USING_TITLE') {
        return new UsingTitlePredicate(data);
    } else if(kind === 'PLAYER_LEVEL') {
        return new PlayerLevelPredicate(data);
    } else if(kind === 'BASE_SIZE') {
        return new BaseSizePredicate(data);
    } else if(kind === 'HOME_REGION') {
        return new HomeRegionPredicate(data);
    } else if(kind === 'REGION_PROPERTY') {
        return new RegionPropertyPredicate(data);
    } else if(kind === 'MAIL_ATTACHMENTS_WAITING') {
        return new MailAttachmentsPredicate(data);
    } else if(kind === 'ARMY_SIZE') {
        return new ArmySizePredicate(data);
    } else if(kind === 'VIEWING_BASE_DAMAGE') {
        return new ViewingBaseDamagePredicate(data);
    } else if(kind === 'VIEWING_BASE_OBJECT_DESTROYED') {
        return new ViewingBaseObjectDestroyedPredicate(data);
    } else {
        throw Error('unknown predicate '+JSON.stringify(data));
    }
}

// evaluate a "cond" expression in the form of [[pred1,val1], [pred2,val2], ...]
/** @param {Array} chain
    @param {Object} player
    @param {Object=} qdata */
function eval_cond(chain, player, qdata) {
    for(var i = 0; i < chain.length; i++) {
        var pred = chain[i][0], val = chain[i][1];
        if(read_predicate(pred).is_satisfied(player, qdata)) {
            return val;
        }
    }
    return null;
}

// evaluate a "cond" expression that might also be a literal value
/** @param {?} qty
    @param {Object} player
    @param {Object=} qdata */
function eval_cond_or_literal(qty, player, qdata) {
    if((typeof qty) == 'undefined') {
        throw Error('eval_cond_or_literal of undefined');
    }

    // if it's a list, treat it as a cond chain, otherwise assume it's a literal
    if(qty && (typeof qty === 'object') && (qty instanceof Array)) {

        // exception: if it's a list and the first element is not itself a list, treat it as a literal
        // (this happens with e.g. ai_ambush_progression_showcase with "progression_reward_items"
        if(qty.length > 0 && !(qty[0] instanceof Array)) {
            return qty;
        }
        return eval_cond(qty, player, qdata);
    }
    return qty;
}
