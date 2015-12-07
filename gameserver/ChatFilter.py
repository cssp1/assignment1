#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# crude bad-language filter.
# Identical to ChatFilter.js on the client (see that file for more detailed comments).

import re
import collections

class ChatFilter(object):
    def __init__(self, config):
        self.spam_min_length = config['spam']['min_length']
        self.spam_rep_limit = config['spam']['rep_limit']
        self.spam_max_depth = config['spam']['max_depth']

        pat_ls = []

        self.space_marker = config.get('space_marker',None)
        self.space_marker_pattern = config.get('space_marker_pattern',None)

        # substitute for spacing between letters
        leet_speak_space = config['leet_speak'].get('letter_space',None)

        # ensure it includes the whitespace_marker_pattern, if one exists
        if self.space_marker_pattern:
            if not leet_speak_space:
                leet_speak_space = self.space_marker_pattern
            elif self.space_marker_pattern not in leet_speak_space:
                leet_speak_space += self.space_marker_pattern

        if leet_speak_space:
            word_space = '[' + leet_speak_space + ']*'
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

        if self.space_marker_pattern:
            space_pattern = self.space_marker_pattern+'('+'|'.join(pat_ls)+')'+self.space_marker_pattern
            self.space_bad_regex = re.compile(space_pattern, flags)
            self.whitespace_regex = re.compile('['+self.space_marker_pattern+'\\s'+']+')
        else:
            self.space_bad_regex = None
            self.whitespace_regex = None

    def compress_string(self, s):
        r = ''
        index_map = []

        # begin with a space marker
        r += self.space_marker
        index_map.append(-1)

        run = False
        for i in xrange(len(s)):
            c = s[i]
            if self.whitespace_regex.match(c):
                if not run:
                    run = True
                    r += self.space_marker
                    index_map.append(-1)
            else:
                run = False
                r += c
                index_map.append(i)

        # end with a space marker
        r += self.space_marker
        index_map.append(-1)

        return r, index_map

    def is_bad(self, input):
        if self.bad_regex.search(input): return True
        if self.space_bad_regex:
            compressed, index_map = self.compress_string(input)
            if self.space_bad_regex.search(compressed): return True
        return False

    def censor(self, original_s):
        s = self.bad_regex.sub(lambda match: '*'*len(match.group()), original_s)

        if self.space_bad_regex:
            compressed, index_map = self.compress_string(original_s)
            # back-patch the string with * wherever bad words were detected in the compressed version
            for match in self.space_bad_regex.finditer(compressed):
                index = match.start(0); length = match.end(0) - index
                begin = -1; end = -1
                for i in xrange(index, index+length):
                    s_index = index_map[i]
                    if s_index >= 0: # accumulate bounds
                        begin = min(begin, s_index) if begin >= 0 else s_index
                        end = max(end, s_index) if end >= 0 else s_index

                # replace the entire begin-end range (inclusive)
                if begin >= 0 and end >= begin:
                    s = s[:begin] + '*'*(end-begin+1) + s[end+1:]
        return s

    # check for abusive chat messages that repeat single letters or digraphs too much
    def is_spammy(self, input, min_length = None):
        if min_length is None:
            min_length = self.spam_min_length
        if len(input) < min_length: return False

        DEPTH = self.spam_max_depth
        graphs = [dict() for length in xrange(1, DEPTH+1)] # mapping of letter combination to frequency
        buffers = [collections.deque([], length) for length in xrange(1, DEPTH+1)] # circular buffers for collecting characters
        non_whitespace_len = 0 # count of non-whitespace characters in input

        for c in input:
            if c.isspace(): continue
            non_whitespace_len += 1
            for dep in xrange(1, DEPTH+1):
                buf = buffers[dep-1]
                buf.append(c)
                if len(buf) >= dep and \
                   (dep < 2 or (not all(x == buf[0] for x in buf))): # don't count N-graphs that are a repeated single character
                    key = tuple(buf)
                    graphs[dep-1][key] = graphs[dep-1].get(key,0) + 1

        for dep in xrange(1, DEPTH+1):
            gr = graphs[dep-1]
            if not gr: continue
            max_reps = max(gr.itervalues())
            # don't allow the N-graph to take up more than spam_rep_limit as a fraction of total non-whitespace length
            limit = max(2, int(non_whitespace_len * self.spam_rep_limit / float(dep)))
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
        'dwarf shortage': 'dwarf shortage',
        'do not rush it': 'do not rush it',
        'u r a sh it': 'u r a *****',
        'f u c k off': '******* off',
        'azzhole': '*******',
        'a z z hole': '***** hole',
        'a z z h ole': '***** h ole',
        }
    for input, expect in TESTS.iteritems():
        censor_result = cf.censor(input)
        if censor_result != expect:
            raise Exception('wrong censor result: "%s"->"%s" (expected "%s")' % \
                            (input, censor_result, expect))
        assert cf.is_bad(input) == (input != expect)

        if cf.is_spammy(input, min_length = 0):
            raise Exception('incorrectly is_spammy: %r' % input)

    assert cf.is_spammy('mmmmmmmmmmmmm')
    assert cf.is_spammy('mmm m ab n mm mmmm mmm')
    assert cf.is_spammy('mmm m ab mmmm m mmmmm')
    assert cf.is_spammy('mmm m ab mmmm mmmm    mmmmm')
    assert cf.is_spammy('jajajajajajajajaj ajaja')
    assert not cf.is_spammy('slowpokejoe is always looking for idiots to boss around')
    assert not cf.is_spammy('james ya lookin for a clan???')
    assert not cf.is_spammy('nao coloca defesas lado a lado, se nao os caras destroem duas com uma bomba')
    assert cf.is_spammy('thethethethethethe')
    assert not cf.is_spammy('<======== IWC')
    assert cf.is_spammy('656456456564')
    assert not cf.is_spammy('65645645')
    print 'OK'
