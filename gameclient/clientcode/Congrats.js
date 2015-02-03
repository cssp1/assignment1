goog.provide('Congrats');
goog.require('Predicates');
goog.require('SPText');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// generates nicely-formatted SPText for upgrade congraulations M&Ms
// uses pretty_print_number from main.js

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
    var spec = cc.spec;

    var sep = new SPText.ABlock('\n', Congrats.props.normal);

    if('provides_space' in spec) {
        ret.push([[new SPText.ABlock(gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_name'].toUpperCase(), Congrats.props.bold)]]);
        ret.push([Congrats.item(gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_name'],
                                gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_before'],
                                gamedata['strings']['cc_upgrade_congrats']['unit_space']['ui_after'],
                                spec['provides_space'][level-2], spec['provides_space'][level-1])]);
    }

    ret.push([[sep]]);
    ret.push([[new SPText.ABlock(gamedata['strings']['cc_upgrade_congrats']['max_number']['ui_name'].toUpperCase(), Congrats.props.bold)]]);
    for(var name in gamedata['buildings']) {
        var spec = gamedata['buildings'][name];

        // ignore developer_only / hidden specs
        if(spin_secure_mode || !player.is_developer) {
            if(spec['developer_only'] ||
               (spec['show_if'] && !read_predicate(spec['show_if']).is_satisfied(player, null))) {
                continue;
            }
        }

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

    ret.push([[sep]]);
    ret.push([[new SPText.ABlock(gamedata['strings']['cc_upgrade_congrats']['max_level']['ui_name'].toUpperCase(), Congrats.props.bold)]]);
    for(var name in gamedata['buildings']) {
        var os = gamedata['buildings'][name];
        // ignore developer_only if in production
        if(os['developer_only'] && (spin_secure_mode || !player.is_developer)) {
            continue;
        }
        var start = 0, end = 0;
        if('requires' in os) {
            // horrible hack... need to evaluate predicates at old and new CC levels
            var save_level = cc.level;
            cc.level = level - 1;
            var max_os_level = os['build_time'].length;
            for(var i = 1; i <= max_os_level; i++) {
                if(read_predicate(get_leveled_quantity(os['requires'], i)).is_satisfied(player, null)) {
                    start = i;
                } else {
                    break;
                }
            }

            cc.level = level;
            for(var i = 1; i <= max_os_level; i++) {
                if(read_predicate(get_leveled_quantity(os['requires'], i)).is_satisfied(player, null)) {
                    end = i;
                } else {
                    break;
                }
            }
            if(start != end) {
                ret.push([Congrats.item(os['ui_name'],
                                        gamedata['strings']['cc_upgrade_congrats']['max_level']['ui_before'],
                                        gamedata['strings']['cc_upgrade_congrats']['max_level']['ui_after'],
                                        start, end)]);
            }
            cc.level = save_level;
        }
    }

    //console.log(ret);
    return ret;
};
