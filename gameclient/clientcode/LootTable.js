goog.provide('LootTable');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// Client-side implementation of LootTable.py

goog.require('goog.array');
goog.require('goog.object');

/** @typedef {!Object} */
LootTable.ItemDict;

/** @typedef {!Array<!LootTable.ItemDict>} */
LootTable.ItemList;

/** @typedef {!Object|!Array} */
LootTable.LootEntry;

/** @typedef {!Array<!LootTable.LootEntry>} */
LootTable.LootList;

/** @typedef {!Object} */
LootTable.PredDict;

/** @typedef {{0: !LootTable.PredDict, 1: !LootTable.LootList}} */
LootTable.CondEntry;

/** @typedef {!Array<!LootTable.CondEntry>} */
LootTable.CondChain;

/** Final result of loot table query. Includes the item list as well as the most restrictive predicate
    that was referenced in creating it.
    @typedef {{item_list: !LootTable.ItemList, predicate: (LootTable.PredDict|null)}} */
LootTable.Result;

/** @param {!Object} tables - gamedata['loot_tables'], in case there is an external reference
    @param {!LootTable.LootList} tab - the table you want the result from
    @param {function(!LootTable.PredDict):boolean} cond_resolver - resolves predicates
    @return {!LootTable.Result} */
LootTable.get_loot = function(tables, tab, cond_resolver) {
    if(!(tab instanceof Array)) { throw Error('non-list loot table '+JSON.stringify(tab)); }

    /** @type {!LootTable.Result} */
    var ret = { item_list: [], predicate: null };

    if(tab.length <= 0) { return ret; }

    var groupnum;
    if(tab.length === 1) {
        groupnum = 0;
    } else {
        /** @type {!Array<number>} */
        var breakpoints = [];
        /** @type {number} */
        var bp = 0.0;
        goog.array.forEach(tab, function(item) {
            var weight = (('weight' in item) ? /** @type {number} */ (item['weight']) : 1.0);
            bp += weight;
            breakpoints.push(bp);
        });

        var r = Math.random();
        r *= breakpoints[breakpoints.length-1];
        groupnum = Math.min(goog.array.binarySearch(breakpoints, r), breakpoints.length-1);
    }

    var data = tab[groupnum];

    if('table' in data) {
        ret = LootTable.combine_result(ret, LootTable.get_loot(tables, tables[data['table']]['loot'], cond_resolver));
    } else if('cond' in data) {
        var cond = /** @type {LootTable.CondChain} */ (data['cond']);
        for(var i = 0; i < cond.length; i++) {
            var pred_result = cond[i];
            var pred = /** @type {!LootTable.PredDict} */ (pred_result[0]);
            var result = /** @type {!LootTable.LootList} */ (pred_result[1]);
            if(cond_resolver(pred)) {
                ret.predicate = pred;
                ret = LootTable.combine_result(ret, LootTable.get_loot(tables, (result instanceof Array) ? result : [result], cond_resolver));
                break;
            }
        }
    } else if('spec' in data) {
        // make a copy of the entry, just in case the caller is naughty and mutates it
        var ret_item = goog.object.clone(data);
        if('weight' in ret_item) {
            delete ret_item['weight'];
        }
        if('random_stack' in ret_item) {
            var random_stack = /** @type {!Array<number>} */ (ret_item['random_stack']);
            delete ret_item['random_stack'];
            // pick a random stack amount between the min and max, inclusive
            ret_item['stack'] = Math.floor(random_stack[0] + Math.random()*(random_stack[1]+1-random_stack[0]));
        }
        ret.item_list = [ret_item];
    } else if('multi' in data) {
        // combine multiple loot drops into a flat list
        var multi = /** @type {!LootTable.LootList} */ (data['multi']);
        ret = goog.array.reduce(multi, /** !LootTable.ItemList */ function(/** !LootTable.Result */ accum, /** !LootTable.LootEntry */ x) {
            var next = LootTable.get_loot(tables, (x instanceof Array) ? x : [x], cond_resolver);
            return LootTable.combine_result(accum, next);
        }, ret);

        if('multi_stack' in data) {
            goog.array.forEach(ret.item_list, function(/** !LootTable.ItemDict */ item) {
                item['stack'] = ('stack' in item ? (/** @type {number} */ (item['stack'])) : 1) * /** @type {number} */ (data['multi_stack']);
            });
        }
    } else if(data['nothing']) {
        // nothing
    } else {
        throw Error('invalid loot table entry ' + JSON.stringify(data));
    }

    return ret;
};

/** @param {!LootTable.Result} a
    @param {!LootTable.Result} b
    @return {!LootTable.Result} */
LootTable.combine_result = function(a, b) {
    /** @type {!LootTable.Result} */
    var ret = {item_list: a.item_list.concat(b.item_list),
               predicate: null};
    if(a.predicate && b.predicate) {
        ret.predicate = {'predicate': 'AND', 'subpredicates': [a.predicate, b.predicate]};
    } else {
        ret.predicate = a.predicate || b.predicate || null;
    }
    return ret;
};
