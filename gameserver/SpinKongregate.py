#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# see http://developers.kongregate.com/docs/all/signed-requests

# this code is identical to Facebook's, so just reuse that
from SpinFacebook import parse_signed_request

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3:
        print 'usage: %s APP_SECRET SIGNED_REQUEST' % sys.argv[0]
        sys.exit(1)

    print parse_signed_request(sys.argv[2], sys.argv[1])
