#!/usr/bin/env python

# library that attempts to fix malformed JSON.stringify() output that
# has missing quotes around dictionary keys and/or values.

import re

# look for a dictionary that begins with an unquoted key, e.g. "{foo:...}"
detect_malformed = re.compile(r'^{[a-z]+.*')

# detect unquoted keys/values. Note, assumes no whitespace, and will be fooled by special characters within strings.
unquoted_keys = re.compile(r'([\'"])?([a-zA-Z0-9_]+)([\'"])?:')
unquoted_values = re.compile(r':([a-zA-Z0-9_=\-\+]+)')

def fix(input):
    output = input
    if detect_malformed.match(output):
        output = unquoted_keys.sub(r'"\2":', output)
        output = unquoted_values.sub(r':"\1"', output)
    return output

# test code
if __name__ == '__main__':
    import SpinJSON

    for input, expected in \
    [(u"{replay:1468932215-2219158-vs-2458400,replay_signature:w1nrURfoj9IWM1Mn5HtoFxJbmNa1McgBk5-ueifRjo8=}",
      u'{"replay":"1468932215-2219158-vs-2458400","replay_signature":"w1nrURfoj9IWM1Mn5HtoFxJbmNa1McgBk5-ueifRjo8="}'),
     (u'{"replay":"1468932215-2219158-vs-2458400","replay_signature":"w1nrURfoj9IWM1Mn5HtoFxJbmNa1McgBk5-ueifRjo8="}',
      u'{"replay":"1468932215-2219158-vs-2458400","replay_signature":"w1nrURfoj9IWM1Mn5HtoFxJbmNa1McgBk5-ueifRjo8="}')
     ]:
        output = fix(input)
        assert output == expected
        print SpinJSON.loads(output)
