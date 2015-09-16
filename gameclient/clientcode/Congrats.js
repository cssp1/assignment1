goog.provide('Congrats');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Generates nicely-formatted SPText for townhall upgrade congratulations dialog.
    */

goog.require('Predicates');
goog.require('SPText');

var Congrats = {
    color_neutral: 'rgba(200,200,200,1)',
    color_hi: 'rgba(255,255,255,1)'
};

Congrats.props = { normal: {color:Congrats.color_neutral},
                   bold:   {color:Congrats.color_hi, style:'bold'},
                   hi:     {color:Congrats.color_hi} };

// return an ARRAY OF PARAGRAPHS
// each PARAGRAPH is an array of LINES
// each LINE is an array of ABlocks

/** @param {string} ui_name
    @param {string} text_before
    @param {string} text_after
    @param {number} start
    @param {number} end
    @return {!Array.<!SPText.ABlock>} */
Congrats.item = function(ui_name, text_before, text_after, start, end) {
    var delta = end-start;
    var line = [];
    line.push(new SPText.ABlock('+'+pretty_print_number(delta)+' '+text_before+' ', Congrats.props.normal));
    line.push(new SPText.ABlock(ui_name, Congrats.props.hi));
    line.push(new SPText.ABlock(' ('+pretty_print_number(end)+' '+text_after+')', Congrats.props.normal));
    return line;
};

// EXPERIMENTAL

/** @dict
    @typedef {!{subpredicates: (Array.<!PredicateSpec>|undefined)}} */
var PredicateSpec;

/** @dict
    @typedef {!{developer_only: (boolean|undefined),
                limit: (Array.<number>|number|undefined),
                ui_name: string,
                ui_name_plural: (string|undefined),
                requires: (Array.<PredicateSpec>|PredicateSpec|undefined),
                show_if: (Array.<PredicateSpec>|PredicateSpec|undefined)
                }} */
var GameObjectSpec;

/** @param {Building} cc the townhall object
    @param {number} level
    @return {!Array.<!Array.<!Array.<!SPText.ABlock>>>} */
Congrats.cc_upgrade = function(cc, level) {
    var ret = [];
    var line = [];

    var sep = new SPText.ABlock('\n', Congrats.props.normal);

    if('provides_space' in cc.spec && (cc.spec['provides_space'][level-2] != cc.spec['provides_space'][level-1])) {
        ret.push([[new SPText.ABlock(/** @type {string} */ (gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_name']).toUpperCase(), Congrats.props.bold)]]);
        ret.push([Congrats.item(gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_name'],
                                gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_before'],
                                gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_after'],
                                cc.spec['provides_space'][level-2], cc.spec['provides_space'][level-1])]);
    }

    ret.push([[sep]]);
    ret.push([[new SPText.ABlock(/** @type {string} */ (gamedata['strings']['cc_upgrade_congrats']['max_number']['ui_name']).toUpperCase(), Congrats.props.bold)]]);
    for(var name in gamedata['buildings']) {
        var spec = /** @type {GameObjectSpec} */ (gamedata['buildings'][name]);

        // ignore developer_only / hidden specs
        if(('developer_only' in spec) && (!!spec['developer_only']) && (spin_secure_mode || !player.is_developer())) { continue; }
        if(('show_if' in spec) && !read_predicate(spec['show_if']).is_satisfied(player, null)) { continue; }

        if('limit' in spec && (typeof spec['limit']) !== 'number') {
            var /** number */ start = spec['limit'][level-2];
            var /** number */ end = spec['limit'][level-1];
            if(start != end) {
                var ui_name;
                if (end - start != 1) {
                    ui_name = ('ui_name_plural' in spec ? /** @type {string} */ (spec['ui_name_plural']) : (/** @type {string} */ (spec['ui_name'])+'s'));
                } else {
                    ui_name = /** @type {string} */ (spec['ui_name']);
                }

                ret.push([Congrats.item(ui_name,
                                        gamedata['strings']['cc_upgrade_congrats']['max_number']['ui_before'],
                                        gamedata['strings']['cc_upgrade_congrats']['max_number']['ui_after'],
                                        start, end)]);
            }
        }
    }

    if('provides_limited_equipped' in cc.spec) {
        for(var key in cc.spec['provides_limited_equipped']) {
            var arr = /** @type {!Array.<number>} */ (cc.spec['provides_limited_equipped'][key]);
            var start = arr[level-2], end = arr[level-1];
            if(start != end) {
                var ui_name = /** @type {string} */ (gamedata['strings']['modstats']['stats']['provides_limited_equipped:'+key]['ui_name']);

                ret.push([Congrats.item(ui_name,
                                        gamedata['strings']['cc_upgrade_congrats']['max_number']['ui_before'],
                                        gamedata['strings']['cc_upgrade_congrats']['max_number']['ui_after'],
                                        start, end)]);
            }
        }
    }

    ret.push([[sep]]);
    ret.push([[new SPText.ABlock(/** @type {string} */ (gamedata['strings']['cc_upgrade_congrats']['max_level']['ui_name']).toUpperCase(), Congrats.props.bold)]]);
    for(var name in gamedata['buildings']) {
        var item = Congrats.building_level_gain(/** @type {GameObjectSpec} */ (cc.spec), level, gamedata['buildings'][name]);
        if(item) {
            ret.push([item]);
        }
    }

    //console.log(ret);
    return ret;
};

/** Given a gamedata['buildings'] spec, see if upgrading source_building to source_level unlocks a higher level for it
    if so, return a Congrats.item.

    Originally, this mutated the source_building and checked predicates using is_satisfied(), but this misses upgrades
    that have additional unsatisfied requirements. So for now, reach manually into the predicates and parse out BUILDING_LEVEL.
    @param {GameObjectSpec} source_spec
    @param {number} source_level
    @param {GameObjectSpec} spec
    @return {Array.<!SPText.ABlock>|null} */
Congrats.building_level_gain = function(source_spec, source_level, spec) {

    // ignore developer_only if in production
    if(('developer_only' in spec) && (!!spec['developer_only']) && (spin_secure_mode || !player.is_developer())) { return null; }
    if(('show_if' in spec) && !read_predicate(spec['show_if']).is_satisfied(player, null)) { return null; }
    if(!spec['requires'] || !(spec['requires'] instanceof Array)) { return null; } // missing or non-array-valued "requires"

    var requires = /** @type {!Array.<PredicateSpec>} */ (spec['requires']);

    var start = 0, end = 0;
    for(var i = 0; i < requires.length; i++) {
        if(Congrats.building_level_predicate_is_satisfied(requires[i], source_spec['name'], source_level-1)) {
            start = i+1;
        }
        if(Congrats.building_level_predicate_is_satisfied(requires[i], source_spec['name'], source_level)) {
            end = i+1;
        }
    }

    if(start != end) {
        return Congrats.item(spec['ui_name'],
                             gamedata['strings']['cc_upgrade_congrats']['max_level']['ui_before'],
                             gamedata['strings']['cc_upgrade_congrats']['max_level']['ui_after'],
                             start, end);
    }
    return null;
};

/** @param {!Object} pred
    @param {string} specname
    @param {number} level
    @return {boolean} */
Congrats.building_level_predicate_is_satisfied = function(pred, specname, level) {
    if(pred['predicate'] === 'AND') {
        var subpredicates = /** @type {!Array.<PredicateSpec>} */ (pred['subpredicates']);
        for(var i = 0; i < subpredicates.length; i++) {
            if(!Congrats.building_level_predicate_is_satisfied(subpredicates[i], specname, level)) {
                return false;
            }
        }
        return true;
    } else if(pred['predicate'] === 'BUILDING_LEVEL') {
        if(pred['building_type'] === specname) {
            return level >= pred['trigger_level'];
        }
    }
    // ignore all other predicates
    return true;
};
