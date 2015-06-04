#!/usr/bin/env python

# Based on http://www.quirksmode.org/js/detect.html
# Copyright (c) 2014 Niels Leenheer
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# SP3RDPARTY : BrowserDetect.py : MIT License

# Browser User-Agent parsing (server-side)
# please keep this in sync with gameclient/BrowserDetect.js!

import re

# regular expression for detectig NN.MM version strings
version_search_re = re.compile('([0-9]+\.[0-9]+)')

# parse version number out of user-agent string "ag" (agent) where
# "key" is text (plus one more character) that immediately precedes
# the version string.
def get_version(ag, key):
    i = ag.find(key)
    if i >= 0:
        field = ag[i+len(key):].strip()
        match = version_search_re.search(field)
        if match:
            try:
                ret = float(match.groups()[0])
                # get rid of small decimals e.g. 38.0
                if ret - int(ret) < 0.0001:
                    ret = int(ret)
                return ret
            except:
                return -1
    return -1

# given a user-agent string "ag", return a dictionary of properties about the browser.
def get_browser(ag):
    name = 'unknown'
    # note: OS detection may not exactly match BrowserDetect.js because we do not have access to navigator.platform
    os = None
    hardware = 'unknown'
    ver = -1

    if ('MSIE' in ag):
        name = 'Explorer'
        os = 'Windows'
        ver = get_version(ag, 'MSIE')
    elif ('Trident/' in ag):
        name = 'Explorer'
        os = 'Windows'
        if 'Windows Phone' in ag:
            hardware = 'Windows Phone'
        ver = get_version(ag, 'rv')
    elif ('Firefox' in ag):
        name = 'Firefox'
        ver = get_version(ag, 'Firefox')
    elif ('Chrome' in ag):
        name = 'Chrome'
        ver = get_version(ag, 'Chrome/')
    elif ('Apple' in ag):
        name = 'Safari'
        if ('iPhone' in ag) or ('iPad' in ag) or ('iPod' in ag):
            os = 'iOS'
            if ('iPhone' in ag):
                hardware = 'iPhone'
            elif ('iPad' in ag):
                hardware = 'iPad'
            elif ('iPod' in ag):
                hardware = 'iPod'
        else:
            os = 'Mac'
        ver = get_version(ag, 'Version')
    elif ('Opera' in ag):
        name = 'Opera'
        ver = get_version(ag, 'Version')

    if os is None:
        if 'Linux' in ag:
            os = 'Linux'
        elif 'Win' in ag:
            os = 'Windows'
        elif 'Mac' in ag:
            os = 'Mac'
        else:
            os = 'unknown'

    return {'name': name, 'version': ver, 'OS': os, 'hardware': hardware}

# given browser info (parsed above), return true if the browser can
# support loading data and code by doing eval() on the result of an
# XHR AJAX request (which means we can show download progress).
def browser_supports_xhr_eval(brow):
    # this is pretty conservative, see http://en.wikipedia.org/wiki/Cross-origin_resource_sharing#Browser_support
    if brow['name'] == 'Firefox' and brow['version'] >= 4: return True
    elif brow['name'] == 'Chrome' and brow['version'] >= 4: return True
    elif brow['name'] == 'Explorer' and brow['version'] >= 10: return True
    elif brow['name'] == 'Safari' and brow['version'] >= 4: return True
    return False

if __name__ == '__main__':
    brow = get_browser("Mozilla/5.0 (Windows NT 6.1. WOW64. Trident/7.0. rv:9.0) like Gecko")
    print brow
    print browser_supports_xhr_eval(brow)
