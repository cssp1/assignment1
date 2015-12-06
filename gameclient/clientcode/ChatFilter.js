goog.provide('ChatFilter');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Crude bad-language filter. Same as ChatFilter.py on the server.
*/

/** @type {RegExp|null} */
ChatFilter.bad_regex = null;

/** @param {!Object} config */
ChatFilter.init = function(config) {
    var pat_ls = [];
    var word_space;

    // substitute for spacing between letters
    var leet_speak_space = /** @type {string|null} */ (config['leet_speak']['word_space']);
    if(leet_speak_space) {
        word_space = '[' + leet_speak_space + ']*';
    } else {
        word_space = '';
    }
    var leet_speak_dict = /** @type {!Object.<string,string>} */ (config['leet_speak']);

    var bad_words = /** @type {!Array.<string>} */ (config['bad_words']);

    for(var i = 0; i < bad_words.length; i++) {
        var word = bad_words[i];
        var pat = word_space;
        for(var j = 0; j < word.length; j++) {
            var c = word.charAt(j);
            if(c in leet_speak_dict) {
                pat += '['+c+leet_speak_dict[c]+']';
            } else {
                pat += c;
            }
            pat += word_space;
        }
        pat_ls.push(pat);
    }


    var pattern = '\\b('+pat_ls.join('|')+')\\b';
    ChatFilter.bad_regex = new RegExp(pattern, /** @type {string} */ (config['options']));
};

/** Check a string for bad words
    @param {string} s
    @return {boolean} */
ChatFilter.is_bad = function(s) {
    return s.search(ChatFilter.bad_regex) != -1;
};

/** Replace a bad word with asterisks of the same string length
    @param {string} rep
    @return {string} */
ChatFilter.censor_replacer = function(rep) {
    var asterisks = "";
    for(var i = 0; i < rep.length; i++) {
        asterisks += "*";
    }
    return asterisks;
};

/** Replace bad words in a string with asterisks
    @param {string} s
    @return {string} */
ChatFilter.censor = function(s) {
    return s.replace(ChatFilter.bad_regex, ChatFilter.censor_replacer);
};
