goog.provide('Predicates');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');

// depends on Player stuff from clientcode.js
// note: this is functionally identical to the server's Predicates.py,
// except for a handful of client-only predicates that are for GUI stuff.

/** @constructor @struct */
function Predicate(data) {
    this.data = data;
    this.kind = data['predicate'];
}

/** Encapsulates the info extracted for ui_describe() and variants
    @constructor @struct
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

/** @param {?} player
    @param {Object|null=} qdata
    @return {boolean} */
Predicate.prototype.is_satisfied = goog.abstractMethod;

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

/** for GUI purposes, return the UNIX timestamp at which this predicate will turn false
    (only applies to predicates that have some sort of time dependency)
    @final
    @return {number} */
Predicate.prototype.ui_expire_time = function(player) { return this.ui_time_range(player)[1]; };

/** for GUI purposes, return the [start,end] UNIX timestamps at which this predicate will be true
    (only applies to predicates that have some sort of time dependency)
    @return {!Array<number>} */
Predicate.prototype.ui_time_range = function(player) { throw Error('ui_time_range not implemented for this predicate: '+this.kind); }

// return a user-readable string explaining progress towards goal (e.g. "4/5 Bear Asses Collected")
// null if description is unavailable (not all predicates have these)
Predicate.prototype.ui_progress = function(player, qdata) { return null; }

/** Return a measure of the "difficulty" of satisfying a predicate, so
    that we can compare predicates and show the player the "easiest" one.
    @return {number} */
Predicate.prototype.ui_difficulty = function() { return 0; }

/** @constructor @struct
  * @extends Predicate */
function AlwaysTruePredicate(data) { goog.base(this, data); }
goog.inherits(AlwaysTruePredicate, Predicate);
AlwaysTruePredicate.prototype.is_satisfied = function(player, qdata) { return true; };
/** @override */
AlwaysTruePredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
  * @extends Predicate */
function AlwaysFalsePredicate(data) { goog.base(this, data); }
goog.inherits(AlwaysFalsePredicate, Predicate);
AlwaysFalsePredicate.prototype.is_satisfied = function(player, qdata) { return false; };
AlwaysFalsePredicate.prototype.do_ui_describe = function(player) { return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name']); };

/** @constructor @struct
  * @extends Predicate */
function RandomPredicate(data) { goog.base(this, data); this.chance = data['chance']; }
goog.inherits(RandomPredicate, Predicate);
RandomPredicate.prototype.is_satisfied = function(player, qdata) { return Math.random() < this.chance; };

/** @constructor @struct
  * @extends Predicate */
function ComboPredicate(data) {
    goog.base(this, data);
    this.subpredicates = [];
    for(var i = 0; i < data['subpredicates'].length; i++) {
        this.subpredicates.push(read_predicate(data['subpredicates'][i]));
    }
}
goog.inherits(ComboPredicate, Predicate);

/** @constructor @struct
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
/** @override */
AndPredicate.prototype.ui_time_range = function(player) {
    var range = [-1, -1];
    for(var i = 0; i < this.subpredicates.length; i++) {
        // return the most restrictive time range out of all subpredicates
        var r = this.subpredicates[i].ui_time_range(player);
        if(r[0] > 0) { range[0] = (range[0] > 0 ? Math.max(range[0], r[0]) : r[0]); }
        if(r[1] > 0) { range[1] = (range[1] > 0 ? Math.min(range[1], r[1]) : r[1]); }
    }
    return range;
};

/** @override */
AndPredicate.prototype.ui_difficulty = function() {
    var difficulty = 0;
    for(var i = 0; i < this.subpredicates.length; i++) {
        difficulty = Math.max(difficulty, this.subpredicates[i].ui_difficulty());
    }
    return difficulty;
};

/** @constructor @struct
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
    // if any subpredicate is true, return null
    if(goog.array.find(this.subpredicates, function(pred) {
        return pred.is_satisfied(player);
    }, this)) {
        return null;
    }

    // otherwise return first available subpredicate's ui_help
    for(var i = 0; i < this.subpredicates.length; i++) {
        var h = this.subpredicates[i].ui_help(player);
        if(h) { return h; }
    }
    return null;
};
/** @override */
OrPredicate.prototype.ui_time_range = function(player) {
    var range = [-1,-1];
    for(var i = 0; i < this.subpredicates.length; i++) {
        // return the most liberal expire time out of all TRUE subpredicates
        if(this.subpredicates[i].is_satisfied(player, null)) {
            var r = this.subpredicates[i].ui_time_range(player);
            if(r[0] > 0) { range[0] = (range[0] > 0 ? Math.min(range[0], r[0]) : r[0]); }
            if(r[1] > 0) { range[1] = (range[1] > 0 ? Math.max(range[1], r[1]) : r[1]); }
        }
    }
    return range;
};

/** @override */
OrPredicate.prototype.ui_difficulty = function() {
    var difficulty = Infinity;
    for(var i = 0; i < this.subpredicates.length; i++) {
        difficulty = Math.min(difficulty, this.subpredicates[i].ui_difficulty());
    }
    return difficulty;
};

/** @constructor @struct
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
/** @override */
NotPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; }; // not sure on this one

/** @constructor @struct
  * @extends Predicate */
function TutorialCompletePredicate(data) { goog.base(this, data); }
goog.inherits(TutorialCompletePredicate, Predicate);
TutorialCompletePredicate.prototype.is_satisfied = function(player, qdata) { return (player.tutorial_state === "COMPLETE"); };

/** @constructor @struct
  * @extends Predicate */
function AllBuildingsUndamagedPredicate(data) { goog.base(this, data); }
goog.inherits(AllBuildingsUndamagedPredicate, Predicate);
AllBuildingsUndamagedPredicate.prototype.is_satisfied = function(player, qdata) {
    var injured = session.for_each_real_object(function(obj) {
        if(obj.is_building() && obj.is_damaged() && obj.team === 'player') {
            return true;
        }
    }, this);

    return !injured;
};
AllBuildingsUndamagedPredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name']);
};

/** @constructor @struct
  * @extends Predicate */
function ObjectUndamagedPredicate(data) {
    goog.base(this, data);
    this.spec_name = data['spec'] || null;
}
goog.inherits(ObjectUndamagedPredicate, Predicate);
ObjectUndamagedPredicate.prototype.is_satisfied = function(player, qdata) {
    // special case for use in combat
    if(!this.spec_name) {
        if(!qdata || !('source_obj' in qdata)) { throw Error('no source_obj provided'); }
        var obj = qdata['source_obj'];
        return !obj.is_damaged();
    } else {
        // normal case, just check player's base
        return session.for_each_real_object(function(obj) {
            if(obj.spec['name'] == this.spec_name && !obj.is_damaged() && obj.team === 'player') {
                return true;
            }
        }, this);
    }
};
ObjectUndamagedPredicate.prototype.do_ui_describe = function(player) {
    var spec = gamedata['units'][this.spec_name] || gamedata['buildings'][this.spec_name];
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%s', spec['ui_name']));
};
ObjectUndamagedPredicate.prototype.do_ui_help = function(player) {
    var obj = session.for_each_real_object(function(o) {
        if(o.spec['name'] === this.spec_name && o.team === 'player' && o.is_damaged()) {
            return o;
        }
    }, this);
    if(obj) {
        return {'noun': 'building', 'verb': 'repair', 'target': obj,
                'ui_arg_s': gamedata['buildings'][this.spec_name]['ui_name'] };
    }
    return null;
};

/** @constructor @struct
  * @extends Predicate */
function ObjectUnbusyPredicate(data) {
    goog.base(this, data);
    this.spec_name = data['spec'];
}
goog.inherits(ObjectUnbusyPredicate, Predicate);
ObjectUnbusyPredicate.prototype.is_satisfied = function(player, qdata) {
    return !session.for_each_real_object(function(obj) {
        if(obj.spec['name'] == this.spec_name && !obj.is_damaged() && !obj.is_busy() && obj.team === 'player') {
            return true;
        }
    }, this);
};
ObjectUnbusyPredicate.prototype.do_ui_describe = function(player) {
    var spec = gamedata['buildings'][this.spec_name];
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%s', spec['ui_name']));
};
ObjectUnbusyPredicate.prototype.do_ui_help = function(player) {
    var obj = session.for_each_real_object(function(o) {
        if(o.spec['name'] === this.spec_name && o.team === 'player' && (o.is_damaged() || (o.time_until_finish() > 0))) {
            return o;
        }
    }, this);
    if(obj) {
        return {'noun': 'building', 'verb': ((obj.is_damaged() && !obj.is_repairing()) ? 'repair' : 'speedup'), 'target': obj,
                'ui_arg_s': gamedata['buildings'][this.spec_name]['ui_name'] };
    }
    return null;
};

/** @constructor @struct
  * @extends Predicate */
function BuildingDestroyedPredicate(data) {
    goog.base(this, data);
    this.spec_name = data['spec'];
}
goog.inherits(BuildingDestroyedPredicate, Predicate);
BuildingDestroyedPredicate.prototype.is_satisfied = function(player, qdata) {
    return session.for_each_real_object(function(obj) {
        if(obj.spec['name'] == this.spec_name && obj.is_destroyed()) {
            return true;
        }
    }, this);
};


/** @constructor @struct
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
    session.for_each_real_object(function(obj) {
        if(obj.spec['name'] === this.building_type && (this.under_construction_ok || !obj.is_under_construction()) && obj.team === 'player') {
            howmany += 1;
        }
    }, this);
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
    session.for_each_real_object(function(obj) {
        if(obj.spec['name'] === this.building_type && (this.under_construction_ok || !obj.is_under_construction()) && obj.team === 'player') {
            howmany += 1;
        }
    }, this);
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
    session.for_each_real_object(function(obj) {
        if(obj.spec['name'] === this.building_type && obj.team === 'player') {
            if(this.under_construction_ok || !obj.is_under_construction()) {
                count += 1;
            } else if(obj.is_under_construction()) {
                under_construction_obj = obj;
            }
        }
    }, this);
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


/** @constructor @struct
  * @extends Predicate */
function BaseRichnessPredicate(data) {
    goog.base(this, data);
    this.min_richness = data['min_richness'];
}
goog.inherits(BaseRichnessPredicate, Predicate);
BaseRichnessPredicate.prototype.is_satisfied = function(player, qdata) {
    return session.viewing_base && (session.viewing_base.base_richness >= this.min_richness);
};
BaseRichnessPredicate.prototype.do_ui_describe = function(player) {
    var ret = gamedata['strings']['predicates'][this.kind]['ui_name'];
    var pair = goog.array.find(gamedata['strings']['regional_map']['richness'], function(entry) {
        return entry[0] >= this.min_richness;
    }, this);
    if(!pair) { pair = gamedata['strings']['regional_map']['richness'][gamedata['strings']['regional_map']['richness'].length-1]; }
    ret = ret.replace('%s', pair[1]);
    return new PredicateUIDescription(ret);
};
/** @override */
BaseRichnessPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
  * @extends Predicate */
function BaseTypePredicate(data) {
    goog.base(this, data);
    this.types = data['types'];
}
goog.inherits(BaseTypePredicate, Predicate);
BaseTypePredicate.prototype.is_satisfied = function(player, qdata) {
    return session.viewing_base && goog.array.contains(this.types, session.viewing_base.base_type);
};
BaseTypePredicate.prototype.do_ui_describe = function(player) { return null; }; // don't show in GUI
/** @override */
BaseTypePredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };


/** @constructor @struct
  * @extends Predicate */
function BuildingLevelPredicate(data) {
    goog.base(this, data);
    this.building_spec = gamedata['buildings'][data['building_type']];
    this.trigger_level = data['trigger_level'];
    this.trigger_qty = data['trigger_qty'] || 1;
    this.upgrading_ok = data['upgrading_ok'] || false;
    this.obj_id = data['obj_id'] || null;
}
goog.inherits(BuildingLevelPredicate, Predicate);
BuildingLevelPredicate.prototype.is_satisfied = function(player, qdata) {
    // special case for quarries etc
    if(!this.obj_id && !session.home_base) {

        /** @type {string|null} for debugging */
        var err = null;
        if(!this.building_spec['track_level_in_player_history']) {
            err = 'cannot evaluate outside home base without track_level_in_player_history';
        }
        if(this.trigger_qty !== 1 || this.upgrading_ok) {
            err = 'cannot evaluate outside home base with trigger_qty != 1 or upgrading_ok';
        }
        if(err) { // don't crash, but assume it's false
            log_exception(null, err+': '+JSON.stringify(this.data));
            return false;
        }

        var history_key = this.building_spec['name']+'_level';
        var cur_level = (history_key in player.history ? player.history[history_key] : 0);
        return cur_level >= this.trigger_level;
    }

    var count = 0;
    if(session.for_each_real_object(function(obj) {
        if((!this.obj_id || this.obj_id === obj.id) &&
           obj.spec === this.building_spec &&
           obj.team === 'player' &&
           !obj.is_under_construction()) {
            if(obj.level >= this.trigger_level) {
                count += 1;
            } else if(this.upgrading_ok && obj.is_upgrading() && (obj.level + 1) >= this.trigger_level) {
                count += 1;
            } else if(this.trigger_qty < 0) {
                return true; // fail immediately - require ALL buildings to be at this level
            }
        }
    }, this)) { return false; }
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

    if(!this.obj_id && !session.home_base) { return null; } // punt to avoid a special case for quarries

    var raw_count = 0;
    var level_count = 0;
    var min_level = 999, need_to_upgrade_obj = null, need_to_speedup_obj = null;
    session.for_each_real_object(function(obj) {
        if((!this.obj_id || this.obj_id === obj.id) &&
           obj.spec === this.building_spec &&
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
    }, this);
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
/** @override */
BuildingLevelPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
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
        session.for_each_real_object(function(obj) {
            if(obj.is_building() && obj.is_manufacturer()) {
                var manuf_queue = obj.get_client_prediction('manuf_queue', obj.manuf_queue);
                for(var j = 0; j < manuf_queue.length; j++) {
                    if(manuf_queue[j]['spec_name'] === this.unit_spec['name']) {
                        howmany += 1;
                    }
                }
            }
        }, this);
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

/** @constructor @struct
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
            if(session.for_each_real_object(function(obj) {
                if(obj.team === 'player' && obj.is_building() && obj.research_item == this.tech) {
                    return true;
                }
            }, this)) { return true; }
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
TechLevelPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

// Certain operations will involve evaluating tons of predicates during a time when game state is guaranteed not to change.
// (e.g., refreshing completion status of all quests, or updating the Store dialog)
// For performance, optionally enable caches that work as long as game state does not change.

/** @type {boolean} */
var predicate_cache_enabled = false;

/** @type {(Object.<string,boolean>|null)} special cache just for QuestCompletedPredicate to avoid O(N^2) behavior */
var quest_completed_predicate_cache = null;

/** @type {(Object<string,Object>|null)}
    Special cache for HasItemPredicate
    null if not in use or no data, otherwise dictionary mapping item_name -> status (see HasItemPredicate for details) */
var has_item_cache = null;

function predicate_cache_on() {
    predicate_cache_enabled = true;
    quest_completed_predicate_cache = {};
    has_item_cache = null; // will be filled with a dictionary on first need
}
function predicate_cache_off() {
    predicate_cache_enabled = false;
    quest_completed_predicate_cache = null;
    has_item_cache = null;
}

/** @constructor @struct
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
/** @override */
QuestCompletedPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
  * @extends Predicate */
function QuestActivePredicate(data) {
    goog.base(this, data);
    this.quest = gamedata['quests'][data['quest_name']];
}
goog.inherits(QuestActivePredicate, Predicate);
QuestActivePredicate.prototype.do_ui_describe = function(player) { return null; } // internal use only
QuestActivePredicate.prototype.is_satisfied = function(player, qdata) {
    if(this.quest['name'] in player.completed_quests) { return false; }
    if(('activation' in this.quest) && !read_predicate(this.quest['activation']).is_satisfied(player, null)) {
        return false;
    }
    if(read_predicate(this.quest['goal']).is_satisfied(player, null)) {
        return false;
    }
    return true;
};

/** @constructor @struct
  * @extends Predicate */
function AuraActivePredicate(data) {
    goog.base(this, data);
    this.aura_name = data['aura_name'];
    this.min_stack = data['min_stack'] || 1;
    this.min_level = data['min_level'] || -1;
    this.match_data = data['match_data'] || null;
}
goog.inherits(AuraActivePredicate, Predicate);
/** @private
    @return {Object|null} */
AuraActivePredicate.prototype.find_aura = function(player, qdata) {
    for(var i = 0; i < player.player_auras.length; i++) {
        var aura = player.player_auras[i];
        if(aura['spec'] == this.aura_name && ((aura['stack']||1) >= this.min_stack) && ((aura['level']||1) >= this.min_level)) {
            if(('start_time' in aura) && (aura['start_time'] > server_time)) { continue; }
            if(('end_time' in aura) && (aura['end_time'] > 0) && (aura['end_time'] < server_time)) { continue; }
            if(this.match_data !== null) {
                var theirs = aura['data'] || null;
                var is_matched = true;
                for(var k in this.match_data) {
                    if(!theirs || theirs[k] !== this.match_data[k]) {
                        is_matched = false;
                        break;
                    }
                }
                if(!is_matched) { continue; }
            }
            return aura;
        }
    }
    return null;
};

AuraActivePredicate.prototype.is_satisfied = function(player, qdata) { return this.find_aura(player, qdata) !== null; };
AuraActivePredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%s', gamedata['auras'][this.aura_name]['ui_name']));
};
/** @override */
AuraActivePredicate.prototype.ui_time_range = function(player) {
    var aura = this.find_aura(player, null);
    if(aura) {
        return [('start_time' in aura) && (aura['start_time'] > 0) ? aura['start_time'] : -1,
                ('end_time' in aura) && (aura['end_time'] > 0) ? aura['end_time'] : -1];
    }
    return [-1,-1];
};

/** @constructor @struct
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
            if(('start_time' in aura) && (aura['start_time'] > server_time)) { continue; }
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
AuraInactivePredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
  * @extends Predicate */
function CooldownActivePredicate(data) {
    goog.base(this, data);
    this.name = data['name'];
    this.match_data = data['match_data'] || null;
    this.min_togo = ('min_togo' in data ? data['min_togo'] : 0);
}
goog.inherits(CooldownActivePredicate, Predicate);
CooldownActivePredicate.prototype.is_satisfied = function(player, qdata) {
    return player.cooldown_togo(this.name, this.match_data) >= this.min_togo;
};
CooldownActivePredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name'].replace('%s', this.name));
};
CooldownActivePredicate.prototype.ui_time_range = function(player) {
    var cd = player.cooldown_find(this.name, this.match_data);
    if(cd) {
        // XXX when used to determine AI base "freshness", don't base this on cooldown start time?
        // return [-1, cd['end']];
        return [cd['start'], cd['end']];
    }
    return [-1,-1];
}

/** @constructor @struct
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
/** @override */
CooldownInactivePredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };


/** @constructor @struct
  * @extends Predicate */
function GamedataVarPredicate(data, name, value, method) {
    goog.base(this, data);
    this.name = name;
    this.value = value;
    this.method = method || '==';
}
goog.inherits(GamedataVarPredicate, Predicate);
/** Perform lookup of a gamedata variable. May return a cond chain.
    @private */
GamedataVarPredicate.prototype.get_value = function(player, varname) {
    var path = varname.split('.');
    var v = gamedata;
    for(var i = 0; i < path.length; i++) {
        if(!(path[i] in v)) { throw Error('lookup of undefined var "'+varname+'"'); }
        v = v[path[i]];
    }
    return v;
};
GamedataVarPredicate.prototype.is_satisfied = function(player, qdata) {
    var v = this.get_value(player, this.name);
    var test_value = eval_cond_or_literal(v, player, null);
    if(this.method == '==') {
        return test_value == this.value;
    } else if(this.method == 'in') {
        return goog.array.contains(this.value, test_value);
    } else {
        throw Error('unknown method '+this.method);
    }
};
/** @override */
GamedataVarPredicate.prototype.ui_time_range = function(player) {
    var range = [-1,-1];
    var v = this.get_value(player, this.name);
    if(is_cond_chain(v)) {
        var chain = v;
        // return expire time of the first true predicate
        for(var i = 0; i < chain.length; i++) {
            var pred = read_predicate(chain[i][0]);
            if(pred.is_satisfied(player, null)) {
                return pred.ui_time_range(player);
            }
        }
    }
    return range;
};

/** @constructor @struct
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
/** @override */
PlayerHistoryPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @override */
PlayerHistoryPredicate.prototype.ui_difficulty = function() {
    return this.minvalue;
};

/** @constructor @struct
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

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function ResourceStorageCapacityPredicate(data) {
    goog.base(this, data);
}
goog.inherits(ResourceStorageCapacityPredicate, Predicate);
ResourceStorageCapacityPredicate.prototype.is_satisfied = function(player, qdata) {
    return player.resource_state[this.data['res']][0] >= this.data['min'];
};
ResourceStorageCapacityPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
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

/** @constructor @struct
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
/** @override */
AnyABTestPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
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
/** @override */
LibraryPredicate.prototype.ui_time_range = function(player) {
    return this.pred.ui_time_range(player);
};

/** @constructor @struct
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

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function UserIDPredicate(data) {
    goog.base(this, data);
    this.allow = data['allow'];
    this.mod = ('mod' in data ? data['mod'] : 0);
}
goog.inherits(UserIDPredicate, Predicate);
UserIDPredicate.prototype.is_satisfied = function(player, qdata) {
    var test_id = session.user_id;
    if(this.mod > 0) {
        test_id = test_id % this.mod;
    }
    return goog.array.contains(this.allow, test_id);
};
/** @override */
UserIDPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
  * @extends Predicate */
function PriceRegionPredicate(data) {
    goog.base(this, data);
    this.regions = data['regions'];
}
goog.inherits(PriceRegionPredicate, Predicate);
PriceRegionPredicate.prototype.is_satisfied = function(player, qdata) {
    return goog.array.contains(this.regions, player.price_region);
};

/** @constructor @struct
  * @extends Predicate */
function CountryTierPredicate(data) {
    goog.base(this, data);
    this.tiers = data['tiers'];
}
goog.inherits(CountryTierPredicate, Predicate);
CountryTierPredicate.prototype.is_satisfied = function(player, qdata) {
    return goog.array.contains(this.tiers, player.country_tier);
};

/** @constructor @struct
  * @extends Predicate */
function CountryPredicate(data) {
    goog.base(this, data);
    this.countries = data['countries'];
}
goog.inherits(CountryPredicate, Predicate);
CountryPredicate.prototype.is_satisfied = function(player, qdata) {
    return goog.array.contains(this.countries, player.country);
};
/** @override */
CountryPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
  * @extends Predicate */
function LocalePredicate(data) {
    goog.base(this, data);
    this.locales = data['locales'];
}
goog.inherits(LocalePredicate, Predicate);
LocalePredicate.prototype.is_satisfied = function(player, qdata) {
    return goog.array.contains(this.locales, spin_demographics['locale'] || 'unknown');
};
/** @override */
LocalePredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };


/** @constructor @struct
  * @extends Predicate */
function PurchasedRecentlyPredicate(data) {
    goog.base(this, data);
    this.seconds_ago = data['seconds_ago'];
}
goog.inherits(PurchasedRecentlyPredicate, Predicate);
PurchasedRecentlyPredicate.prototype.is_satisfied = function(player, qdata) {
    var now = player.get_absolute_time();
    return ('last_purchase_time' in player.history) && (player.history['last_purchase_time'] >= (now - this.seconds_ago));
};
/** @override */
PurchasedRecentlyPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
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
/** @override */
EventTimePredicate.prototype.ui_time_range = function(player) {
    var neg_time_left = player.get_event_time(this.kind, this.name, 'end', this.ignore_activation, this.t_offset);
    if(neg_time_left === null) {
        throw Error('event '+this.name+' is not active');
    }
    var time_since_start = player.get_event_time(this.kind, this.name, 'start', this.ignore_activation, this.t_offset);
    var ref_time = player.get_absolute_time() + this.t_offset;
    var start_time = ref_time - time_since_start;
    var end_time = ref_time - neg_time_left;
    return [start_time, end_time];
};

/** @constructor @struct
  * @extends Predicate */
function AbsoluteTimePredicate(data) {
    goog.base(this, data);
    this.range = data['range'];
    this.mod = ('mod' in data ? data['mod'] : -1);
    this.shift = data['shift'] || 0;
    this.repeat_interval = data['repeat_interval'] || null;
}
goog.inherits(AbsoluteTimePredicate, Predicate);
AbsoluteTimePredicate.prototype.is_satisfied = function(player, qdata) {
    var et = player.get_absolute_time();
    if(!et) { return false; }
    et += this.shift;
    if(this.mod > 0) {
        et = et % this.mod;
    }
    // before range start?
    if(this.range[0] >= 0 && et < this.range[0]) { return false; }
    // after range end?
    if(this.range[1] >= 0) {
        if(this.repeat_interval) {
            var delta = (et - this.range[0]) % this.repeat_interval;
            if(delta >= (this.range[1] - this.range[0])) { return false; }
        } else {
            if(et >= this.range[1]) { return false; }
        }
    }
    return true;
};
AbsoluteTimePredicate.prototype.do_ui_describe = function(player) {
    var s = gamedata['strings']['predicates'][this.kind]['ui_name'];
    return new PredicateUIDescription(s.replace('%d1', this.range[0].toString()).replace('%d2',this.range[1].toString()));
};
/** @override */
AbsoluteTimePredicate.prototype.ui_time_range = function(player) {
    if(this.repeat_interval) {
        var et = player.get_absolute_time();
        et += this.shift;
        if(this.mod > 0) {
            et = et % this.mod;
        }
        var delta = (et - this.range[0]) % this.repeat_interval;
        var start_time = et - delta;
        var end_time = et + (this.range[1] - this.range[0]) - delta;
        return [start_time, end_time];
    } else {
        return [this.range[0], this.range[1]];
    }
};


/** @constructor @struct
  * @extends Predicate */
function AccountCreationTimePredicate(data) {
    goog.base(this, data);
    this.range = data['range'] || null;
    this.age_range = data['age_range'] || null;
}
goog.inherits(AccountCreationTimePredicate, Predicate);
AccountCreationTimePredicate.prototype.is_satisfied = function(player, qdata) {
    var creat = player.creation_time;
    if(this.range) {
        if(this.range[0] >= 0 && creat < this.range[0]) { return false; }
        if(this.range[1] >= 0 && creat >= this.range[1]) { return false; }
    }
    if(this.age_range) {
        var age = player.get_absolute_time() - creat;
        if(this.age_range[0] >= 0 && age < this.age_range[0]) { return false; }
        if(this.age_range[1] >= 0 && age > this.age_range[1]) { return false; }
    }
    return true;
};
AccountCreationTimePredicate.prototype.do_ui_describe = function(player) {
    var s = gamedata['strings']['predicates'][this.kind]['ui_name'];
    return new PredicateUIDescription(s.replace('%d1', this.range[0].toString()).replace('%d2',this.range[1].toString()));
};
/** @override */
AccountCreationTimePredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
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

/** @constructor @struct
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

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function BrowserHardwarePredicate(data) {
    goog.base(this, data);
    this.hardware = data['hardware'];
}
goog.inherits(BrowserHardwarePredicate, Predicate);
BrowserHardwarePredicate.prototype.is_satisfied = function(player, qdata) {
    return goog.array.contains(this.hardware, spin_demographics['browser_hardware']);
};

/** @constructor @struct
  * @extends Predicate */
function BrowserStandaloneModePredicate(data) {
    goog.base(this, data);
}
goog.inherits(BrowserStandaloneModePredicate, Predicate);
BrowserStandaloneModePredicate.prototype.is_satisfied = function(player, qdata) {
    return is_browser_standalone_mode(); // from main.js
};


/** @constructor @struct
  * @extends Predicate */
function FramePlatformPredicate(data) {
    goog.base(this, data);
    this.platform = data['platform'];
}
goog.inherits(FramePlatformPredicate, Predicate);
FramePlatformPredicate.prototype.is_satisfied = function(player, qdata) {
    return spin_frame_platform == this.platform;
};
/** @override */
FramePlatformPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };
/** @override
    Never relevant mentioning this to the player. */
FramePlatformPredicate.prototype.do_ui_describe = function(player) { return null; };

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function ClientFacebookLikesPredicate(data) {
    goog.base(this, data);
    this.id = data['id'];
    // return value to assume if the data seems unreliable
    this.assume_default = (!!data['default']) || false;
}
goog.inherits(ClientFacebookLikesPredicate, Predicate);
ClientFacebookLikesPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!spin_facebook_enabled || spin_frame_platform != 'fb') { return false; }
    var result = SPFB.likes(this.id);
    if(result.reliable) {
        return result.likes_it;
    } else {
        // note: likes_it will always be false here
        return this.assume_default;
    }
};

/** @constructor @struct
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
            if(this.state == 'crafting' &&  (!selection.unit.is_building() || !selection.unit.is_crafting())) {
                return false;
            }
            return true;
        }
        return false;
    }
};

/** @constructor @struct
  * @extends Predicate */
function RegionMapSelectedPredicate(data) {
    goog.base(this, data);
    this.base_type = data['base_type'] || null;
    this.base_template = data['base_template'] || null;
}
goog.inherits(RegionMapSelectedPredicate, Predicate);
RegionMapSelectedPredicate.prototype.is_satisfied = function(player, qdata) {
    var mapwidget = null;
    if(selection.ui && selection.ui.user_data && selection.ui.user_data['dialog'] == 'region_map_dialog') {
        mapwidget = selection.ui.widgets['map'];
    } else {
        return false; // map dialog not up
    }

    if(!mapwidget.selection_feature) {
        return false; // nothing selected
    }
    var feature = mapwidget.selection_feature;

    if(!mapwidget.popup || !mapwidget.popup.user_data['menu']) {
        return false; // usually we want to require the popup menu to be visible
    }

    if(this.base_type) {
        if(feature['base_type'] !== this.base_type) { return false; }
    }
    if(this.base_template) {
        if(feature['base_template'] !== this.base_template) { return false; }
    }
    return true;
};

/** @constructor @struct
  * @extends Predicate */
function SquadIsMovingPredicate(data) {
    goog.base(this, data);
    this.squad_id = data['squad_id'] || 0;
}
goog.inherits(SquadIsMovingPredicate, Predicate);
SquadIsMovingPredicate.prototype.is_satisfied = function(player, qdata) {
    return player.squad_is_moving(this.squad_id);
};

/** @constructor @struct
  * @extends Predicate */
function SquadIsDeployedPredicate(data) {
    goog.base(this, data);
    this.squad_id = data['squad_id'] || 0;
}
goog.inherits(SquadIsDeployedPredicate, Predicate);
SquadIsDeployedPredicate.prototype.is_satisfied = function(player, qdata) {
    return player.squad_is_deployed(this.squad_id);
};

/** @constructor @struct
  * @extends Predicate */
function SquadLocationPredicate(data) {
    goog.base(this, data);
    this.squad_id = data['squad_id'] || 0;
    this.adjacent_to = data['adjacent_to'] || null;
}
goog.inherits(SquadLocationPredicate, Predicate);
SquadLocationPredicate.prototype.is_satisfied = function(player, qdata) {
    var squad_data = player.squads[this.squad_id.toString()];
    if(!squad_data) { return false; }
    if(!player.squad_is_deployed(this.squad_id)) { return false; }
    if(player.squad_is_moving(this.squad_id)) { return false; }

    var squad_loc = squad_data['map_loc'];

    if(this.adjacent_to) {
        var criteria = this.adjacent_to;
        var neighbor_coords = session.region.get_neighbors(squad_loc);

        // list of all neighboring features around the squad
        var neighbor_features = goog.array.concatMap(neighbor_coords, function(coord) {
            return session.region.find_features_at_coords(coord);
        }, this);

        var home_feature = session.region.find_home_feature();

        if('my_home' in criteria) {
            if(!goog.array.find(neighbor_features, function(f) { return f['base_id'] === home_feature['base_id']; }, this)) {
                return false;
            }
        }
        if('base_type' in criteria) {
            if(!goog.array.find(neighbor_features, function(f) { return f['base_type'] === criteria['base_type']; }, this)) {
                return false;
            }
        }
        if('base_template' in criteria) {
            var template_regex = new RegExp(criteria['base_template']);
            if(!goog.array.find(neighbor_features, function(f) { return template_regex.exec(f['base_template']) !== null; }, this)) {
                return false;
            }

        }
    }
    return true;
};


/** @constructor @struct
  * @extends Predicate */
function UIClearPredicate(data) {
    goog.base(this, data);
}
goog.inherits(UIClearPredicate, Predicate);
UIClearPredicate.prototype.is_satisfied = function(player, qdata) {
    return (selection.ui==null) && (client_time - selection.ui_change_time >= gamedata['client']['ui_quiet_time']);
};

/** @constructor @struct
  * @extends Predicate */
function QuestClaimablePredicate(data) {
    goog.base(this, data);
}
goog.inherits(QuestClaimablePredicate, Predicate);
QuestClaimablePredicate.prototype.is_satisfied = function(player, qdata) {
    return player.claimable_quests > 0;
};

/** @constructor @struct
  * @extends Predicate */
function HomeBasePredicate(data) {
    goog.base(this, data);
}
goog.inherits(HomeBasePredicate, Predicate);
HomeBasePredicate.prototype.is_satisfied = function(player, qdata) {
    return session.home_base;
};

/** @constructor @struct
  * @extends Predicate */
function TrustLevelPredicate(data) {
    goog.base(this, data);
    // sync with loginserver.py
    this.min_level = {'TRUST_ANONYMOUS_GUEST': 0,
                      'TRUST_UNVERIFIED': 5,
                      'TRUST_VERIFIED': 10}[data['min_level']];
}
goog.inherits(TrustLevelPredicate, Predicate);
TrustLevelPredicate.prototype.is_satisfied = function(player, qdata) {
    return player.trust_level >= this.min_level;
};
TrustLevelPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };
TrustLevelPredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name']
                                      .replace('%s', gamedata['strings']['predicates'][this.kind]['ui_min_level'][this.data['min_level']]));
};
TrustLevelPredicate.prototype.do_ui_help = function(player) {
    if(player.trust_level >= this.min_level) { return null; }
    if(player.trust_level >= 5) { // UNVERIFIED -> VERIFIED
        return {'noun': 'trust_level', 'verb': 'verify' };
    } else { // ANONYMOUS_GUEST -> UNVERIFIED -> VERIFIED
        return {'noun': 'trust_level', 'verb': 'associate' };
    }
    //return null;
};

/** @constructor @struct
  * @extends Predicate */
function PrivacyConsentPredicate(data) {
    goog.base(this, data);
    this.state = data['state'];
}
goog.inherits(PrivacyConsentPredicate, Predicate);
PrivacyConsentPredicate.prototype.is_satisfied = function(player, qdata) {
    return player.privacy_consent === this.state;
};
PrivacyConsentPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
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

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function PreDeployUnitsPredicate(data) {
    goog.base(this, data);
    this.spec_name = data['spec'] || null;
    this.qty = data['qty'];
}
goog.inherits(PreDeployUnitsPredicate, Predicate);
PreDeployUnitsPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!this.spec_name) { // not looking for a specific spec
        return session.count_pre_deploy_units() >= this.qty;
    }

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

/** @constructor @struct
  * @extends Predicate */
function HostileUnitExistsPredicate(data) {
    goog.base(this, data);
}
goog.inherits(HostileUnitExistsPredicate, Predicate);
HostileUnitExistsPredicate.prototype.is_satisfied = function(player, qdata) {
    return session.for_each_real_object(function(obj) {
        if(obj.is_mobile() && !obj.is_destroyed() && obj.team === 'enemy') {
            return true;
        }
    }, this) || false;
};

/** @constructor @struct
  * @extends Predicate */
function HostileUnitNearPredicate(data) {
    goog.base(this, data);
}
goog.inherits(HostileUnitNearPredicate, Predicate);
HostileUnitNearPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!qdata || !('source_obj' in qdata)) { throw Error('no source_obj provided'); }
    var obj = qdata['source_obj'];
    var distance = ('distance' in qdata ? qdata['distance'] : this.data['distance']);

    if(obj.ai_target) {
        if(vec_distance(obj.raw_pos(), obj.ai_target.raw_pos()) < distance) {
            // mutate qdata with the hostile object found
            qdata['hostile_obj'] = obj.ai_target;
            return true;
        } else {
            return false;
        }
    }
    var obj_list = session.get_real_world().query_objects_within_distance(obj.raw_pos(), distance,
                                                 { ignore_object: obj,
                                                   exclude_invul: true,
                                                   only_team: (obj.team == 'enemy' ? 'player' : 'enemy'),
                                                   exclude_barriers: false,
                                                   mobile_only: false,
                                                   exclude_flying: !!this.data['exclude_flying'],
                                                   flying_only: false,
                                                   exclude_invisible_to: obj.team,
                                                   tag: 'HOSTILE_UNIT_NEAR'
                                                 });
    if(obj_list.length > 0) {
        // mutate qdata with the hostile object found
        qdata['hostile_obj'] = obj_list[0].obj;
        return true;
    }
    return false;
};

/** @constructor @struct
  * @extends Predicate */
function ObjectOwnershipPredicate(data) {
    goog.base(this, data);
}
goog.inherits(ObjectOwnershipPredicate, Predicate);
ObjectOwnershipPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!qdata || !('source_obj' in qdata)) { throw Error('no source_obj provided'); }
    var obj = qdata['source_obj'];
    return obj.team === this.data['team'];
};

/** @constructor @struct
  * @extends Predicate */
function ForemanIsBusyPredicate(data) {
    goog.base(this, data);
}
goog.inherits(ForemanIsBusyPredicate, Predicate);
ForemanIsBusyPredicate.prototype.is_satisfied = function(player, qdata) {
    return !!player.foreman_is_busy();
};

/** @constructor @struct
  * @extends Predicate */
function DialogOpenPredicate(data) {
    goog.base(this, data);
    this.dialog_name = data['dialog_name'];
    this.page_name = data['dialog_page'] || null;
    this.chapter_name = data['dialog_chapter'] || null;
    this.category_name = data['dialog_category'] || null;
    this.match_user_data = data['match_user_data'] || null;
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
                if(this.match_user_data) {
                    for(var k in this.match_user_data) {
                        if(d.user_data[k] !== this.match_user_data[k]) {
                            return false;
                        }
                    }
                }
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

/** @constructor @struct
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
/** @override */
BaseSizePredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };
/** @override */
BaseSizePredicate.prototype.do_ui_describe = function(player) {
    // special case when player has already exceeded the required size
    if((this.method == '==' || this.method == '<') &&
       session.viewing_base.base_size > this.value) {
        // tell the player they've already done this upgrade
        return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name_already_upgraded']);
    }
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name_'+this.method].replace('%d', this.value.toString()));
};

/** @constructor @struct
  * @extends Predicate */
function HomeRegionPredicate(data) {
    goog.base(this, data);
    this.regions = /** @type {Array<string>} */ (data['regions']) || null;
    this.require_nosql = data['is_nosql'] || false;
}
goog.inherits(HomeRegionPredicate, Predicate);
HomeRegionPredicate.prototype.is_satisfied = function(player, qdata) {
    if(!session.region.data) { return false; }

    if(this.regions !== null) {
        return (goog.array.contains(this.regions, 'ANY') ||
                goog.array.contains(this.regions, session.region.data['id']));
    }

    if(this.require_nosql) {
        return (session.region.data['storage'] == 'nosql');
    }
    return false;
};

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function InventoryPredicate(data) {
    goog.base(this, data);
    this.num = data['num'];
}
goog.inherits(InventoryPredicate, Predicate);
InventoryPredicate.prototype.is_satisfied = function(player, qdata) {
    return (player.inventory.length >= this.num);
};

/** @constructor @struct
  * @extends Predicate */
function GamebucksBalancePredicate(data) {
    goog.base(this, data);
    this.value = data['value'];
    this.method = data['method'] || '>=';
}
goog.inherits(GamebucksBalancePredicate, Predicate);
GamebucksBalancePredicate.prototype.is_satisfied = function(player, qdata) {
    if(this.method != '>=') { throw Error('unhandled method: '+this.method); }
    return player.resource_state['gamebucks'] >= this.value;
};
/** @override */
GamebucksBalancePredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
  * @extends Predicate */
function HasItemPredicate(data) {
    goog.base(this, data);
    this.item_name = data['item_name'];
    this.min_count = data['min_count'] || 1;
    this.level = data['level'] || null;
    this.min_level = data['min_level'] || null;
    this.check_mail = data['check_mail'] || false;
    this.check_crafting = data['check_crafting'] || false;
}
goog.inherits(HasItemPredicate, Predicate);
HasItemPredicate.prototype.is_satisfied = function(player, qdata) {
    // use cache?
    if(predicate_cache_enabled &&
       // Cache does not support leveled items. If this is required, punt to uncached path.
       this.level === null && this.min_level === null) {

        if(has_item_cache === null) {

            // Initialize the cache
            // We assume that the common case is going to be multiple checks of HasItemPredicate with different items.
            // To optimize this case, scan the player once, keeping track of what items we see.
            // Afterward, HasItemPredicate can be resolved in O(1) just by checking this cache.

            has_item_cache = {};
            var func = function(where, x) {
                var name = x['spec'];
                if(!(name in has_item_cache)) {
                    has_item_cache[name] = {'stored':0, 'equipped':0, 'mail':0, 'crafting':0};
                }
                has_item_cache[name][where] += ('stack' in x ? x['stack'] : 1);
            }
            player.stored_item_iter(goog.partial(func, 'stored'));
            player.equipped_item_iter(goog.partial(func, 'equipped'));
            player.mail_attachments_iter(goog.partial(func, 'mail'));
            player.crafting_queue_ingredients_and_products_iter(goog.partial(func, 'crafting'));
        }

        if(this.item_name in has_item_cache) {
            // present in cache. Count number of applicable items seem.
            var state = has_item_cache[this.item_name];
            var count = state['stored'] + state['equipped'];
            if(this.check_mail) { count += state['mail']; }
            if(this.check_crafting) { count += state['crafting']; }
            return count >= this.min_count;
        } else {
            return false; // definitely not present
        }
    }

    // normal, uncached path
    return player.has_item(this.item_name, this.min_count, this.check_mail, this.check_crafting, this.level, this.min_level);
};

HasItemPredicate.prototype.ui_progress = function(player, qdata) {
    var ret = gamedata['strings']['predicates'][this.kind]['ui_progress'];
    ret = ret.replace('%d1', player.count_item(this.item_name, this.check_mail, this.check_crafting, this.level).toString());
    ret = ret.replace('%d2', this.min_count.toString());
    return ret;
};
/** @override */
HasItemPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; }; // not sure on this one

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function HasAchievementPredicate(data) {
    goog.base(this, data);
    this.achievement = data['achievement'];
}
goog.inherits(HasAchievementPredicate, Predicate);
HasAchievementPredicate.prototype.is_satisfied = function(player, qdata) {
    return (this.achievement in player.achievements);
};

/** @constructor @struct
  * @extends Predicate */
function IsInAlliancePredicate(data) {
    goog.base(this, data);
}
goog.inherits(IsInAlliancePredicate, Predicate);
IsInAlliancePredicate.prototype.is_satisfied = function(player, qdata) {
    return session.is_in_alliance();
};

/** @constructor @struct
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
HasAliasPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function UsingTitlePredicate(data) {
    goog.base(this, data);
    this.name = data['name'] || null;
}
goog.inherits(UsingTitlePredicate, Predicate);
UsingTitlePredicate.prototype.is_satisfied = function(player, qdata) {
    if(this.name === null) { // true if player is using any valid title
        return (!!player.title) && (player.title in gamedata['titles']);
    } else {
        return player.title === this.name;
    }
};

/** @constructor @struct
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
/** @override */
PlayerLevelPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
  * @extends Predicate */
function PlayerVPNPredicate(data) {
    goog.base(this, data);
}
goog.inherits(PlayerVPNPredicate, Predicate);
PlayerVPNPredicate.prototype.is_satisfied = function(player, qdata) {
    return !!player.vpn_status && !('vpn_excused' in player.history && player.history['vpn_excused']);
};
PlayerVPNPredicate.prototype.do_ui_describe = function(player) {
    return new PredicateUIDescription(gamedata['strings']['predicates'][this.kind]['ui_name']);
};
/** @override */
PlayerVPNPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };

/** @constructor @struct
  * @extends Predicate */
function LadderPlayerPredicate(data) {
    goog.base(this, data);
}
goog.inherits(LadderPlayerPredicate, Predicate);
LadderPlayerPredicate.prototype.is_satisfied = function(player, qdata) {
    return player.is_ladder_player();
};

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function ArmySizePredicate(data) {
    goog.base(this, data);
    this.trigger_qty = data['trigger_qty'];
    this.method = data['method'] || ">=";
    this.include_queued = 'include_queued' in data ? data['include_queued'] : true;
    this.squad_id = 'squad_id' in data ? data['squad_id'] : 'ALL';
}
goog.inherits(ArmySizePredicate, Predicate);
ArmySizePredicate.prototype.is_satisfied = function(player, qdata) {
    var army_size = player.get_army_space_usage_by_squad()[this.squad_id.toString()];

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

/** @constructor @struct
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

/** @constructor @struct
  * @extends Predicate */
function ViewingBaseTypePredicate(data) {
    goog.base(this, data);
    this.base_type = data['base_type'];
}
goog.inherits(ViewingBaseTypePredicate, Predicate);
ViewingBaseTypePredicate.prototype.is_satisfied = function(player, qdata) {
    var world = session.get_real_world();
    return world.base.base_type === this.base_type;
};

/** @constructor @struct
  * @extends Predicate */
function ViewingBaseObjectDestroyedPredicate(data) {
    goog.base(this, data);
    this.spec = data['spec'];
}
goog.inherits(ViewingBaseObjectDestroyedPredicate, Predicate);
ViewingBaseObjectDestroyedPredicate.prototype.is_satisfied = function(player, qdata) {
    return session.for_each_real_object(function(obj) {
        if(obj.is_destroyed() && obj.spec['name'] === this.spec) {
            return true;
        }
    }, this);
};

/** @constructor @struct
  * @extends Predicate */
function QueryStringPredicate(data) {
    goog.base(this, data);
    this.key = data['key'];
    this.value = data['value'];
}
goog.inherits(QueryStringPredicate, Predicate);
QueryStringPredicate.prototype.is_satisfied = function(player, qdata) {
    return get_query_string(this.key) === this.value;
};

/** @constructor @struct
  * @extends Predicate */
function ClientPlatformPredicate(data) {
    goog.base(this, data);
    this.platforms = data['platforms'];
    this.any_electron = data['any_electron'];
}
goog.inherits(ClientPlatformPredicate, Predicate);
ClientPlatformPredicate.prototype.is_satisfied = function(player, qdata) {
    var ret = false;
    if(this.any_electron) {
        return spin_client_platform.indexOf('electron') == 0;
    }
    goog.array.forEach(this.platforms, function(platform) {
        if(platform === spin_client_platform) {
            ret = true;
        }
    });
    return ret;
};
/** @override */
ClientPlatformPredicate.prototype.ui_time_range = function(player) { return [-1,-1]; };
/** @override
    Never relevant mentioning this to the player. */
ClientPlatformPredicate.prototype.do_ui_describe = function(player) { return null; };

/** @constructor @struct
  * @extends Predicate */
function ClientVendorPredicate(data) {
    goog.base(this, data);
    this.vendors = data['vendors'];
}
goog.inherits(ClientVendorPredicate, Predicate);
ClientVendorPredicate.prototype.is_satisfied = function(player, qdata) {
    var ret = false;
    goog.array.forEach(this.vendors, function(vendor) {
        if(vendor === spin_client_vendor) {
            ret = true;
        }
    });
    return ret;
};

/** @constructor @struct
  * @extends Predicate */
function ClientVersionPredicate(data) {
    goog.base(this, data);
    this.method = data['method'];
    this.version = data['version'];
}
goog.inherits(ClientVersionPredicate, Predicate);
ClientVersionPredicate.prototype.is_satisfied = function(player, qdata) {
    if(this.method === '>=') {
        return spin_client_version >= this.version;
    } else if(this.method === '==') {
        return spin_client_version === this.version;
    } else if(this.method === '<') {
        return spin_client_version < this.version;
    }
    return false;
};

/** @param {!Object} data
    @return {!Predicate} */
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
    else if(kind === 'BASE_TYPE') { return new BaseTypePredicate(data); }
    else if(kind === 'BASE_RICHNESS') { return new BaseRichnessPredicate(data); }
    else if(kind === 'BUILDING_DESTROYED') { return new BuildingDestroyedPredicate(data); }
    else if(kind === 'BUILDING_QUANTITY') { return new BuildingQuantityPredicate(data); }
    else if(kind === 'BUILDING_LEVEL') { return new BuildingLevelPredicate(data); }
    else if(kind === 'UNIT_QUANTITY') { return new UnitQuantityPredicate(data); }
    else if(kind === 'TECH_LEVEL') { return new TechLevelPredicate(data); }
    else if(kind === 'QUEST_COMPLETED') { return new QuestCompletedPredicate(data); }
    else if(kind === 'QUEST_ACTIVE') { return new QuestActivePredicate(data); }
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
    else if(kind === 'GAMEDATA_VAR') { return new GamedataVarPredicate(data, data['name'], data['value'], ('method' in data ? data['method'] : null)); }
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
    } else if(kind === 'RESOURCE_STORAGE_CAPACITY') {
        return new ResourceStorageCapacityPredicate(data);
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
    } else if(kind == 'LOCALE') {
        return new LocalePredicate(data);
    } else if(kind === 'PURCHASED_RECENTLY') {
        return new PurchasedRecentlyPredicate(data);
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
    } else if(kind === 'BROWSER_STANDALONE_MODE') {
        return new BrowserStandaloneModePredicate(data);
    } else if(kind === 'SELECTED') {
        return new SelectedPredicate(data);
    } else if(kind === 'REGION_MAP_SELECTED') {
        return new RegionMapSelectedPredicate(data);
    } else if(kind === 'SQUAD_IS_MOVING') {
        return new SquadIsMovingPredicate(data);
    } else if(kind === 'SQUAD_IS_DEPLOYED') {
        return new SquadIsDeployedPredicate(data);
    } else if(kind === 'SQUAD_LOCATION') {
        return new SquadLocationPredicate(data);
    } else if(kind === 'UI_CLEAR') {
        return new UIClearPredicate(data);
    } else if(kind === 'QUEST_CLAIMABLE') {
        return new QuestClaimablePredicate(data);
    } else if(kind === 'HOME_BASE') {
        return new HomeBasePredicate(data);
    } else if(kind === 'TRUST_LEVEL') {
        return new TrustLevelPredicate(data);
    } else if(kind === 'PRIVACY_CONSENT') {
        return new PrivacyConsentPredicate(data);
    } else if(kind === 'HAS_ATTACKED') {
        return new HasAttackedPredicate(data);
    } else if(kind === 'HAS_DEPLOYED') {
        return new HasDeployedPredicate(data);
    } else if(kind === 'PRE_DEPLOY_UNITS') {
        return new PreDeployUnitsPredicate(data);
    } else if(kind === 'HOSTILE_UNIT_EXISTS') {
        return new HostileUnitExistsPredicate(data);
    } else if(kind === 'HOSTILE_UNIT_NEAR') {
        return new HostileUnitNearPredicate(data);
    } else if(kind === 'OBJECT_OWNERSHIP') {
        return new ObjectOwnershipPredicate(data);
    } else if(kind === 'DIALOG_OPEN') {
        return new DialogOpenPredicate(data);
    } else if(kind === 'PLAYER_PREFERENCE') {
        return new PlayerPreferencePredicate(data);
    } else if(kind === 'FOREMAN_IS_BUSY') {
        return new ForemanIsBusyPredicate(data);
    } else if(kind === 'INVENTORY') {
        return new InventoryPredicate(data);
    } else if(kind === 'GAMEBUCKS_BALANCE') {
        return new GamebucksBalancePredicate(data);
    } else if(kind === 'HAS_ITEM') {
        return new HasItemPredicate(data);
    } else if(kind === 'HAS_ITEM_SET') {
        return new HasItemSetPredicate(data);
    } else if(kind === 'HAS_ACHIEVEMENT') {
        return new HasAchievementPredicate(data);
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
    } else if(kind === 'PLAYER_VPN') {
        return new PlayerVPNPredicate(data);
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
    } else if(kind === 'VIEWING_BASE_TYPE') {
        return new ViewingBaseTypePredicate(data);
    } else if(kind === 'VIEWING_BASE_OBJECT_DESTROYED') {
        return new ViewingBaseObjectDestroyedPredicate(data);
    } else if(kind === 'QUERY_STRING') {
        return new QueryStringPredicate(data);
    } else if (kind === 'CLIENT_PLATFORM') {
        return new ClientPlatformPredicate(data);
    } else if (kind === 'CLIENT_VENDOR') {
        return new ClientVendorPredicate(data);
    } else if (kind === 'CLIENT_VERSION') {
        return new ClientVersionPredicate(data);
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

/** @param {?} qty
    @return {boolean} */
function is_cond_chain(qty) {
    if((typeof qty) == 'undefined') {
        throw Error('is_cond_chain of undefined');
    }
    // if it's a list, treat it as a cond chain, otherwise assume it's a literal
    return (qty && (typeof qty === 'object') && (qty instanceof Array) &&
        // exception: if it's a list and the first element is not itself a list, treat it as a literal
        // (this happens with e.g. ai_ambush_progression_showcase with "progression_reward_items"
            !(qty.length > 0 && !(qty[0] instanceof Array)));
}

/** Evaluate a "cond" expression that might also be a literal value
    @param {?} qty
    @param {Object} player
    @param {Object=} qdata */
function eval_cond_or_literal(qty, player, qdata) {
    if((typeof qty) == 'undefined') {
        throw Error('eval_cond_or_literal of undefined');
    }

    if(is_cond_chain(qty)) {
        return eval_cond(qty, player, qdata);
    } else {
        return qty;
    }
}

/** Evaluate a "cond" expression that might also be a literal value
    @param {?} qty
    @param {Object} player
    @param {Object=} qdata */
function eval_pred_or_literal(qty, player, qdata) {
    if((typeof qty) == 'undefined') {
        throw Error('eval_pred_or_literal of undefined');
    }
    if(qty && (typeof qty === 'object') && ('predicate' in qty)) {
        return read_predicate(qty).is_satisfied(player, qdata);
    } else {
        return qty;
    }
}
