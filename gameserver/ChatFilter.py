#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# crude bad-language filter. Same as ChatFilter.js on the client.

import re

class ChatFilter(object):
    def __init__(self, config):
        pat_ls = []

        # substitute for spacing between letters
        if config['leet_speak'].get('word_space',None):
            word_space = '['+config['leet_speak']['word_space']+']*'
        else:
            word_space = ''

        for word in config['bad_words']:
            pat = word_space
            for c in word:
                if c in config['leet_speak']:
                    pat += '['+c+config['leet_speak'][c]+']'
                else:
                    pat += c
                pat += word_space
            pat_ls.append(pat)

        pattern = '\\b('+'|'.join(pat_ls)+')\\b'
        flags = 0
        if 'i' in config['options']: flags |= re.I
        # no 'g' option, re is greedy by default
        self.bad_regex = re.compile(pattern, flags)
    def is_bad(self, input):
        return bool(self.bad_regex.search(input))
    def censor(self, input):
        return self.bad_regex.sub(lambda match: '*'*len(match.group()), input)

if __name__ == '__main__':
    import SpinConfig
    config = SpinConfig.load(SpinConfig.gamedata_component_filename('chat_filter.json'))
    cf = ChatFilter(config)
    TESTS = {
        'asdf': 'asdf',
        'sh!t': '****',
        'fu!ckers': '********',
        'dwarf shortage': 'dwarf shortage'
        }
    for input, expect in TESTS.iteritems():
        assert cf.censor(input) == expect
    print 'OK'
