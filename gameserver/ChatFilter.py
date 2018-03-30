#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# crude bad-language filter.
# Identical to ChatFilter.js on the client (see that file for more detailed comments).

import re
import collections
import unicodedata
import codepoints

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
        self.leet_speak = config['leet_speak']

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
                if c in self.leet_speak:
                    pat += '['+c+self.leet_speak[c]+']'
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

    # Check if a string contains offensive language
    # This checks the *meaning* of the words, not any technical aspects like graphical symbols
    def is_bad(self, input):
        if self.bad_regex.search(input): return True
        if self.space_bad_regex:
            compressed, index_map = self.compress_string(input)
            if self.space_bad_regex.search(compressed): return True
        return False

    # Replace offensive words in a string with asterisks
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

    # Check for abusive chat messages that repeat single letters or digraphs too much
    # e.g.: "hahahahahahahahhahahfofofofofofofofo"
    # There is nothing really wrong with technical content or meaning, but other players usually
    # complain when they see messages like this, so we want to block them.
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

    # Check for non-letter "graphics" like smiley faces
    # These are usually allowed in routine chat messages, but
    # should not be allowed for important titles like player names.

    def is_graphical(self, input, allow_chars = []):

        # caller can provide exceptions
        allowed_codepoints = map(ord, allow_chars)

        # block standard graphical symbols
        # keep in sync: ChatFilter.py, main.js: alias_disallowed_chars, errors.json: ALIAS_BAD
        disallowed_codepoints = map(ord, ['\n', '\t', '\r', '\\', '/', ' ', '.', ':', ';', '+', '*', '(', ')', '<', '>', '[', ']', '{', '}', ',', '|', '"', "'", '_', '&', '^', '%', '$', '#', '@', '!', '~', '?', '`', '\0', '-', '='])

        for codepoint in codepoints.from_unicode(input):
            if codepoint in allowed_codepoints:
                continue

            if codepoint in disallowed_codepoints:
                return True

            # for reference, see https://en.wikipedia.org/wiki/Unicode_block

            if codepoint >= 0x80 and codepoint <= 0x9f: # Latin-1 Supplement: C1 Controls
                return True
            if codepoint >= 0xa0 and codepoint <= 0xbf: # Latin-1 Supplement: Punctuation and Symbols
                return True

            if codepoint < 0x10000:
                if unicodedata.category(unichr(codepoint)) == 'Po': # punctuation, other
                    return True

            if codepoint in (0x5e, # CIRCUMFLEX ACCENT
                             0x60, # GRAVE ACCENT
                             0xd7, # MULTIPLICATION SIGN
                             0xf7, # DIVISION SIGN
                             0x37e, # GREEK QUESTION MARK
                             0x387, # GREEK ANO TELEIA
                             0x589, # ARMENIAN FULL STOP
                             0x5c0, 0x5c3, 0x5c6, 0x5f3, 0x5f4, # Hebrew punctuation
                             0x640, # Arabic Tatweel (this is debatable)
                             ):
                return True

            if codepoint >= 0x2b0 and codepoint <= 0x2ff: # SPACING_MODIFIER_LETTERS
                return True

            # The whole range 0x300-0x36f "Combining Diacritical Marks" is gray area.
            # It includes some umlauts etc that might be needed for European languages.
            # Just block the most annoying-looking overlay marks.
            if codepoint >= 0x334 and codepoint <= 0x338: # overlay marks
                return True

            if codepoint >= 0x55a and codepoint <= 0x55f: # ARMENIAN punctuation
                return True
            if codepoint >= 0x1ab0 and codepoint <= 0x1abe: # Combining Diacritical Marks Extended
                return True
            if codepoint >= 0x1dc0 and codepoint <= 0x1dff: # Combining Diacritical Marks Supplement
                return True
            if codepoint >= 0x20d0 and codepoint <= 0x20ff: # Combining Diacritical Marks For Symbols
                return True
            if codepoint >= 0x2100 and codepoint <= 0x2bff: # Letterlike Symbols .. Misc Symbols
                return True
            if codepoint >= 0xfe20 and codepoint <= 0xfe2f: # Combining Half Marks
                return True
            if codepoint >= 0x16fe0 and codepoint <= 0x16fff:
                return True
            if codepoint >= 0x1d000 and codepoint <= 0x1f2ff:
                return True
            if codepoint >= 0x1f300 and codepoint <= 0x1f9ff:
                return True

        return False

    # Check for abuse of Unicode special characters to create text that renders improperly
    # This should always be blocked, even in routine chat messages, because it leads to corrupt text display.
    def is_ugly(self, input):
        nonspacing_run = 0 # don't allow very long runs of nonspacing characters

        input = tuple(codepoints.from_unicode(input))

        for i in xrange(len(input)):
            codepoint = input[i]
            next_codepoint = input[i+1] if i < len(input)-1 else None

            # disallow nonsense duplications of nonspacing marks (e.g. Arabic diacritics)
            if self.is_diacritic(codepoint):
                # disallow repetition of any single nonspacing mark
                if next_codepoint and codepoint == next_codepoint and \
                   codepoint not in (0x0e35,0x0e48,0x0e49): # special exception: Thai diacritics and vowel marks
                    #print "DUPE", hex(codepoint)
                    return True
                # disallow continuous sequences of 5 or more nonspacing marks
                nonspacing_run += 1
                if nonspacing_run >= 5:
                    return True
            else:
                nonspacing_run = 0

        return False

    def is_diacritic(self, codepoint):
        # see http://www.unicode.org/reports/tr44/tr44-4.html#General_Category_Values
        if codepoint < 0x80: return False # ASCII stuff is OK
        if codepoint in (0xbf, 0xa1, 0x61f, 0x60c): return False # Spanish/Arabic question/exclamation/comma marks are OK
        if codepoint >= 0x10000: return False # narrow python build: assume not diacritic
        return unicodedata.category(unichr(codepoint)) in ('Mn','Po')

        # see https://en.wikipedia.org/wiki/Arabic_(Unicode_block)
        #return (codepoint >= 0x610 and codepoint <= 0x61f) or \
        #       (codepoint >= 0x650 and codepoint <= 0x65f)

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
        'a z z hole': '**********',
        'a z z h ole': '***********',
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

    assert not cf.is_ugly(u'aaabcd')
    assert not cf.is_graphical(u'aaabcd')
    assert cf.is_graphical(u'aa\u21f0aa')
    assert cf.is_ugly(u'abc\u0627\u0651\u0651\u0651\u0651\u0651\u0651')
    assert cf.is_ugly(u'abc\u0627\u0651\u0652\u0651\u0652\u0651\u0652\u0651')
    assert not cf.is_ugly(u'abc\u0627\u0651\u0652\u0653\u0654abcd')
    assert not cf.is_ugly(u'abc\u0627\u0651\u0627\u0651')
    assert not cf.is_ugly(u'asdf    fd     dfsdf  _____|||  b asdfasdf!!')
    assert not cf.is_ugly(u'\u0647\u064a \u0627\u0644\u062e\u0631\u064a\u0637\u0629 \u062f\u064a \u0645\u0641\u064a\u0647\u0627\u0634 \u062d\u062f \u0646\u0647\u062c\u0645 \u0639\u0644\u064a\u0647 \u0646\u062c\u064a\u0628 \u0645\u0646\u0647 \u0645\u0648\u0627\u0631\u062f \u064a\u0627 \u062c\u0645\u0627\u0639\u0629 \u0643\u0644\u0647\u0645 \u0623\u0635\u062f\u0642\u0627\u0621 \u064a\u0639\u0646\u064a\u061f\u061f\u061f\u061f\u061f')
    assert not cf.is_ugly('u\xbf\xbf\xbf\xbf\xbf')
    assert not cf.is_ugly(u'hola a todos espero ser de utilidad entro paar aportar lo mio\xa1\xa1\xa1')
    assert not cf.is_ugly(u'\u0e2d\u0e30\u0e21\u0e32\u0e01 \u0e04\u0e23\u0e31\u0e1a \u0e17\u0e35\u0e48\u0e48')

    assert not cf.is_ugly(u'\u0627\u0644\u0633\u0644\u0627\u0645 \u0639\u0644\u064a\u0643\u0645 \u0634\u0628\u0627\u0628\u060c\u060c \u0627\u0634\u0648 \u0645\u0627\u0643\u0648 \u0644\u0627 \u062a\u0631\u0642\u064a\u0647 \u0644\u0627 \u0634\u064a \u0628\u0647\u0630\u0627 \u0627\u0644\u0643\u0644\u064a\u0646 \u0628\u0633 \u0627\u062f\u0627\u0641\u0639 \u0648 \u0627\u0633\u0647\u0631 \u0648 \u0643\u0644\u0634\u064a \u0645\u0627\u0643\u0648')
    assert not cf.is_ugly(u'\u0e1a\u0e2d\u0e01\u0e1e\u0e35\u0e35\u0e48\u0e21\u0e32\u0e0b\u0e34')

    assert cf.is_graphical(u'🖕🖕🖕')
    assert cf.is_graphical(u"\u2508\u256d\u256e\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508\u2508 \u2508\u2503\u2503\u2508\u256d\u256e\u2508\u250f\u256e\u256d\u256e\u256d\u256e\u2503\u256d \u2508\u2503\u2503\u2508\u2503\u2503\u2508\u2523\u252b\u2503\u2503\u2503\u2508\u2523\u252b \u2508\u2503\u2523\u2533\u252b\u2503\u2508\u2503\u2570\u2570\u256f\u2570\u256f\u2503\u2570 \u256d\u253b\u253b\u253b\u252b\u2503\u2508\u2508\u256d\u256e\u2503\u2503\u2501\u2533\u2501 \u2503\u2571\u256d\u2501\u256f\u2503\u2508\u2508\u2503\u2503\u2503\u2503\u2508\u2503\u2508 \u2570\u256e\u2571\u2571\u2571\u2503\u2508\u2508\u2570\u256f\u2570\u256f\u2508\u2503\u2508")
    assert cf.is_graphical(u"\ud83d\udd95\ud83c\udffb\ud83d\udd95\ud83c\udffb\ud83d\udd95\ud83c\udffb")
    assert cf.is_graphical(u'--==Death==--')
    assert cf.is_graphical(u'asdf$@#Death??@$#$')
    assert not cf.is_graphical(u'--==Death==--', allow_chars = ['-','='])
    assert cf.is_graphical(u'\u00d7\u0640')
    assert cf.is_graphical(u'S\u0337L\u0337A\u0337Y\u0337E\u0337R\u0337')
    assert cf.is_graphical(u'🔰👊💥😎THE SPECTRE😎💥👊🔰 ')

    print 'OK'
