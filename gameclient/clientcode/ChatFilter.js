goog.provide('ChatFilter');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// crude bad-language filter. Same as ChatFilter.py on the server.

ChatFilter = {
    bad_regex: null,
    init: function(config) {
        var pat_ls = [];
        var word_space;

        // substitute for spacing between letters
        if(config['leet_speak']['word_space']) {
            word_space = '['+config['leet_speak']['word_space']+']*';
        } else {
            word_space = '';
        }

        for(var i = 0; i < config['bad_words'].length; i++) {
            var word = config['bad_words'][i];
            var pat = word_space;
            for(var j = 0; j < word.length; j++) {
                var c = word.charAt(j);
                if(c in config['leet_speak']) {
                    pat += '['+c+config['leet_speak'][c]+']';
                } else {
                    pat += c;
                }
                pat += word_space;
            }
            pat_ls.push(pat);
        }


        var pattern = '\\b('+pat_ls.join('|')+')\\b';
        ChatFilter.bad_regex = new RegExp(pattern,config['options']);
    },

    censor: function(s) {
        return s.replace(ChatFilter.bad_regex, function(rep) {
            var asterisks = "";
            for(var i = 0; i < rep.length; i++) {
                asterisks += "*";
            }
            return asterisks;
        });
    }
};
