goog.provide('Congrats');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// generates nicely-formatted SPText for upgrade congraulations M&Ms
// uses pretty_print_number from main.js

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

Congrats.item = function(ui_name, text_before, text_after, start, end) {
    var delta = end-start;
    var line = [];
    line.push(new SPText.ABlock('+'+pretty_print_number(delta)+' '+text_before+' ', Congrats.props.normal));
    line.push(new SPText.ABlock(ui_name, Congrats.props.hi));
    line.push(new SPText.ABlock(' ('+pretty_print_number(end)+' '+text_after+')', Congrats.props.normal));
    return line;
};

// pass in the townhall object
Congrats.cc_upgrade = function(cc, level) {
    var ret = [];
    var line = [];

    var sep = new SPText.ABlock('\n', Congrats.props.normal);

    if('provides_space' in cc.spec && (cc.spec['provides_space'][level-2] != cc.spec['provides_space'][level-1])) {
        ret.push([[new SPText.ABlock(gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_name'].toUpperCase(), Congrats.props.bold)]]);
        ret.push([Congrats.item(gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_name'],
                                gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_before'],
                                gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_after'],
                                cc.spec['provides_space'][level-2], cc.spec['provides_space'][level-1])]);
    }

    ret.push([[sep]]);
    ret.push([[new SPText.ABlock(gamedata['strings']['cc_upgrade_congrats']['max_number']['ui_name'].toUpperCase(), Congrats.props.bold)]]);
    for(var name in gamedata['buildings']) {
        var spec = gamedata['buildings'][name];

        // ignore developer_only / hidden specs
        if(spec['developer_only'] && (spin_secure_mode || !player.is_developer())) { continue; }
        if(spec['show_if'] && !read_predicate(spec['show_if']).is_satisfied(player, null)) { continue; }

        if('limit' in spec && (typeof spec['limit']) !== 'number') {
            var start = spec['limit'][level-2], end = spec['limit'][level-1];
            if(start != end) {
                var ui_name;
                if (end - start != 1) {
                    ui_name = 'ui_name_plural' in spec ? spec['ui_name_plural'] : spec['ui_name']+'s';
                } else {
                    ui_name = spec['ui_name'];
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
            var arr = cc.spec['provides_limited_equipped'][key];
            var start = arr[level-2], end = arr[level-1];
            if(start != end) {
                var ui_name = gamedata['strings']['modstats']['stats']['provides_limited_equipped:'+key]['ui_name'];

                ret.push([Congrats.item(ui_name,
                                        gamedata['strings']['cc_upgrade_congrats']['max_number']['ui_before'],
                                        gamedata['strings']['cc_upgrade_congrats']['max_number']['ui_after'],
                                        start, end)]);
            }
        }
    }

    ret.push([[sep]]);
    ret.push([[new SPText.ABlock(gamedata['strings']['cc_upgrade_congrats']['max_level']['ui_name'].toUpperCase(), Congrats.props.bold)]]);
    for(var name in gamedata['buildings']) {
        var item = Congrats.building_level_gain(cc.spec, level, gamedata['buildings'][name]);
        if(item) {
            ret.push([item]);
        }
    }

    //console.log(ret);
    return ret;
};

// given a gamedata['buildings'] spec, see if upgrading source_building to source_level unlocks a higher level for it
// if so, return a Congrats.item.
// Originally, this mutated the source_building and checked predicates using is_satisfied(), but this misses upgrades
// that have additional unsatisfied requirements. So for now, reach manually into the predicates and parse out BUILDING_LEVEL.
Congrats.building_level_gain = function(source_spec, source_level, spec) {

    // ignore developer_only if in production
    if(spec['developer_only'] && (spin_secure_mode || !player.is_developer())) { return null; }
    if(spec['show_if'] && !read_predicate(spec['show_if']).is_satisfied(player, null)) { return null; }
    if(!spec['requires'] || !(0 in spec['requires'])) { return null; } // missing or non-array-valued "requires"

    var start = 0, end = 0;
    for(var i = 0; i < spec['requires'].length; i++) {
        if(Congrats.building_level_predicate_is_satisfied(spec['requires'][i], source_spec['name'], source_level-1)) {
            start = i+1;
        }
        if(Congrats.building_level_predicate_is_satisfied(spec['requires'][i], source_spec['name'], source_level)) {
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

Congrats.building_level_predicate_is_satisfied = function(pred, specname, level) {
    if(pred['predicate'] === 'AND') {
        for(var i = 0; i < pred['subpredicates'].length; i++) {
            if(!Congrats.building_level_predicate_is_satisfied(pred['subpredicates'][i], specname, level)) {
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
