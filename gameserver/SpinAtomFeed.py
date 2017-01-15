#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import time

# XML parsing
import xml.etree.ElementTree as ET

# entry filtering
import re

# HTML unescaping
from HTMLParser import HTMLParser
parser = HTMLParser()
html_unescape = parser.unescape

def parse_time(t):
    return int(time.mktime(time.strptime(t, '%Y-%m-%dT%H:%M:%SZ')))

class AtomEntryFilter(object):
    def __init__(self, include_expr = None, exclude_expr = None):
        self.include_expr = re.compile(include_expr, re.IGNORECASE) if include_expr else None
        self.exclude_expr = re.compile(exclude_expr, re.IGNORECASE) if exclude_expr else None
    def allow(self, entry):
        if self.exclude_expr and self.exclude_expr.search(entry.body): return False
        if self.include_expr:
            if self.include_expr.search(entry.body):
                return True
            else:
                return False
        return True

class AtomEntry(object):
    def __init__(self, published_time, title, body, link_url):
        self.published_time = published_time
        self.title = title
        self.body = body
        self.link_url = link_url
    def __unicode__(self):
        return u'%s %s (%s)\n%s...' % \
               (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.published_time)),
                self.title,
                self.link_url,
                self.body[:100])

class AtomFeed(object):
    def __init__(self, raw_bytes, entry_filter = None):
        self.entries = []
        root = ET.fromstring(raw_bytes)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        for entry in root.findall('atom:entry', ns):
            published_time = parse_time(entry.find('atom:published', ns).text)
            title = html_unescape(entry.find('atom:title', ns).text)
            body = html_unescape(entry.find('atom:content', ns).text)
            link_url = html_unescape(entry.find('atom:link', ns).get('href'))
            entry_obj = AtomEntry(published_time, title, body, link_url)
            if entry_filter and (not entry_filter.allow(entry_obj)):
                continue
            self.entries.append(entry_obj)

    def __repr__(self):
        return u'\n'.join(map(unicode, self.entries)).encode('utf-8')

# gameserver interface

def get_feed(game_id, game_name, raw_bytes):
    include_expr = game_name
    exclude_expr = ('Firestrike' if game_id in ('tr','dv') else None)
    entry_filter = AtomEntryFilter(include_expr = include_expr, exclude_expr = exclude_expr)
    feed = AtomFeed(raw_bytes, entry_filter = entry_filter)
    return feed

if __name__ == '__main__':
    import SpinConfig
    import getopt, sys, requests

    game_id = SpinConfig.game()
    time_now = int(time.time())

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g', [])

    for key, val in opts:
        if key == '-g': game_id = val

    gamedata = {'strings':SpinConfig.load(SpinConfig.gamedata_component_filename("strings.json"))}
    game_name = gamedata['strings']['game_name']
    raw_bytes = requests.get('https://www.battlehouse.com/feed/atom/').content
    feed = get_feed(game_id, game_name, raw_bytes)
    print feed
