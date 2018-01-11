goog.provide('ChatFilter');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Crude bad-language filter. Same as ChatFilter.py on the server.
*/

/** @type {RegExp|null} main bad-word filter */
ChatFilter.bad_regex = null;

// to catch bad words that have interspersed whitespace, e.g. "you d o r k",
// we also operate on a "compressed" version of the string that replaces all
// whitespace runs with a single "marker" character (which is treated as optional
// during the main regex match, if the match candidate begins with a marker).
// Note: it doesn't work to always treat all whitespace as optional, since that
// would falsely flag "rush it" (whereas "r u a sh it" should be flagged).

/** @type {string|null} space replacement character */
ChatFilter.space_marker = null;
/** @type {string|null} regex-quoted version of space_marker */
ChatFilter.space_marker_pattern = null;

/** @type {RegExp|null} sensitive to all whitespace (but must also include space_marker) */
ChatFilter.whitespace_regex = null;

/** @type {RegExp|null} space-insensitive bad-word filter */
ChatFilter.space_bad_regex = null;

/** @param {!Object} config */
ChatFilter.init = function(config) {
    var pat_ls = [];
    var word_space;

    ChatFilter.space_marker = /** @type {string|null} */ (config['space_marker']);
    ChatFilter.space_marker_pattern = /** @type {string|null} */ (config['space_marker_pattern']);

    // substitute for spacing between letters
    var leet_speak_space = /** @type {string|null} */ (config['leet_speak']['letter_space']);

    // ensure it includes the whitespace_marker_pattern, if one exists
    if(ChatFilter.space_marker_pattern) {
        if(!leet_speak_space) {
            leet_speak_space = ChatFilter.space_marker_pattern;
        } else if(leet_speak_space.indexOf(ChatFilter.space_marker_pattern) === -1) {
            leet_speak_space += ChatFilter.space_marker_pattern;
        }
    }

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

    // construct main filter regex, which looks for bad words with ordinary word boundaries
    var pattern = '\\b('+pat_ls.join('|')+')\\b';
    ChatFilter.bad_regex = new RegExp(pattern, /** @type {string} */ (config['options']));

    if(ChatFilter.space_marker_pattern) {
        // construct space-insensitive regex, which looks for bad words with interspersed space_markers *that begin and end with a space_marker*
        var space_pattern = ChatFilter.space_marker_pattern+'('+pat_ls.join('|')+')'+ChatFilter.space_marker_pattern;
        ChatFilter.space_bad_regex = new RegExp(space_pattern, /** @type {string} */ (config['options']));
        ChatFilter.whitespace_regex = new RegExp('['+ChatFilter.space_marker_pattern+'\\s'+']+', 'g');
    }
};

/** Create a "compressed" version of a string by replacing all whitespace with the whitespace_marker
    e.g. "Hey you are a j e r k" -> ".Hey.you.are.a.j.e.r.k."
    We will then search for bad words that begin after a marker.
    Also returns an array with the index of each character in the original string, for backwards mapping.
    @param {string} s
    @return {{compressed: string,
              index_map: !Array<number>}} */
ChatFilter.compress_string = function(s) {
    /** @type {string} */
    var r = '';
    /** @type {!Array<number>} */
    var index_map = [];

    // begin with a space marker
    r += ChatFilter.space_marker;
    index_map.push(-1);

    for(var i = 0, run = false; i < s.length; i++) {
        var c = s.charAt(i);
        if(c.match(ChatFilter.whitespace_regex)) {
            if(!run) {
                run = true;
                r += ChatFilter.space_marker;
                index_map.push(-1);
            } else {
                // absorb the run
            }
        } else {
            run = false;
            r += c;
            index_map.push(i);
        }
    }

    // end with a space marker
    r += ChatFilter.space_marker;
    index_map.push(-1);

    return { compressed: r, index_map: index_map };
};

/** Check a string for offensive language
    @param {string} s
    @return {boolean} */
ChatFilter.is_bad = function(s) {
    if(s.search(ChatFilter.bad_regex) != -1) { return true; }
    if(ChatFilter.space_bad_regex) {
        var compressed = ChatFilter.compress_string(s).compressed;
        ChatFilter.space_bad_regex.lastIndex = 0; // reset the regex
        if(compressed.search(ChatFilter.space_bad_regex) != -1) { return true; }
    }
    return false;
};

/** Replace an offensive word with asterisks of the same string length
    @param {string} rep
    @return {string} */
ChatFilter.censor_replacer = function(rep) {
    var asterisks = "";
    for(var i = 0; i < rep.length; i++) {
        asterisks += "*";
    }
    return asterisks;
};

/** Replace offensive words in a string with asterisks
    @param {string} original_s
    @return {string} */
ChatFilter.censor = function(original_s) {
    var s = original_s.replace(ChatFilter.bad_regex, ChatFilter.censor_replacer);

    if(ChatFilter.space_bad_regex) {
        var comp = ChatFilter.compress_string(original_s);

        // back-patch the string with * wherever bad words were detected in the compressed version
        ChatFilter.space_bad_regex.lastIndex = 0; // reset the regex
        var match;
        while ((match = ChatFilter.space_bad_regex.exec(comp.compressed)) !== null) {
            var index = match.index, length = match[0].length;

            // replace the entire run in the source string with asterixes
            var begin = -1, end = -1;
            for(var i = index; i < index+length; i++) {
                var s_index = comp.index_map[i];
                if(s_index >= 0) { // accumulate bounds
                    begin = (begin >= 0 ? Math.min(begin, s_index) : s_index);
                    end = (end >= 0 ? Math.max(end, s_index) : s_index);
                }
            }

            // replace the entire begin-end range (inclusive)
            if(begin >= 0 && end >= begin) {
                var new_s = s.substr(0,begin);
                for(var i = 0; i < end-begin+1; i++) {
                    new_s += "*";
                }
                new_s += s.substr(end+1);
                s = new_s;
            }
        }
    }
    return s;
};
