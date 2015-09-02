#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# crude bad-language filter. Same as ChatFilter.js on the client.

import re
import collections

class ChatFilter(object):
    def __init__(self, config):
        self.spam_min_length = config['spam']['min_length']
        self.spam_rep_limit = config['spam']['rep_limit']
        self.spam_max_depth = config['spam']['max_depth']

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

    # check for abusive chat messages that repeat single letters or digraphs too much
    def is_spammy(self, input, min_length = None):
        if min_length is None:
            min_length = self.spam_min_length
        if len(input) < min_length: return False

        DEPTH = self.spam_max_depth
        graphs = [dict() for length in xrange(1, DEPTH+1)] # mapping of letter combination to frequency
        buffers = [collections.deque([], length) for length in xrange(1, DEPTH+1)] # circular buffers for collecting characters
        for c in input:
            if c.isspace(): continue
            for dep in xrange(1, DEPTH+1):
                buf = buffers[dep-1]
                buf.append(c)
                if len(buf) >= dep:
                    key = tuple(buf)
                    graphs[dep-1][key] = graphs[dep-1].get(key,0) + 1

        for dep in xrange(1, DEPTH+1):
            gr = graphs[dep-1]
            max_reps = max(gr.itervalues())
            limit = max(2, int(len(input) * self.spam_rep_limit / float(dep)))
            if max_reps >= limit:
                #print "len", len(input), "limit", limit, "depth", dep, "graphs", gr
                return True

        return False

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
        if cf.is_spammy(input, min_length = 0):
            raise Exception('incorrectly is_spammy: %r' % input)

    assert cf.is_spammy('mmmmmmmmmmmmm')
    assert cf.is_spammy('mmm m ab n mm mmmm mmm')
    assert cf.is_spammy('jajajajajajajajaj ajaja')
    assert not cf.is_spammy('slowpokejoe is always looking for idiots to boss around')
    assert not cf.is_spammy('james ya lookin for a clan???')
    assert not cf.is_spammy('nao coloca defesas lado a lado, se nao os caras destroem duas com uma bomba')
    assert cf.is_spammy('thethethethethethe')
    print 'OK'
