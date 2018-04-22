#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# load some standard Python libraries
import sys, urllib, urllib2, getopt, socket
import SpinConfig
import SpinFacebook

# just load achievements.json, not all of gamedata, so we can populate before running make-gamedata.sh
gamedata = {'achievements': SpinConfig.load(SpinConfig.gamedata_component_filename('achievements.json'))}

def get_endpoint_url(params):
    port = SpinConfig.config['proxyserver']['external_http_port']
    port_str = (':%d' % port) if port != 80 else ''
    # note: use stable ordering of key/value pairs for the query string, so that the canonical URL is deterministic
    qs = urllib.urlencode(sorted(params.items(), key = lambda k_v: k_v[0]))
    return ("http://%s%s/OGPAPI?" % (SpinConfig.config['proxyserver'].get('external_listen_host', socket.gethostname()),
                                     port_str)) + qs

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['dry-run'])
    dry_run = False
    verbose = True

    for key, val in opts:
        if key == '--dry-run':
            dry_run = True
        elif key == '--quiet':
            verbose = False

    for name, data in gamedata['achievements'].iteritems():
        if 'fb_open_graph' not in data: continue
        if not data['fb_open_graph'].get('populate', True): continue

        endpoint = get_endpoint_url({'type': SpinConfig.game()+'_achievement', 'name': name})
        params = {'access_token': SpinConfig.config['facebook_app_access_token'],
                  'achievement': endpoint}
        if 'display_order' in data:
            params['display_order'] = str(data['display_order'])

        postdata = urllib.urlencode(params)
        url = SpinFacebook.versioned_graph_endpoint('achievement', SpinConfig.config['facebook_app_id']+'/achievements')
        request = urllib2.Request(url, data = postdata)
        request.get_method = lambda: 'POST'
        print 'url:', url
        print 'request:', postdata
        if not dry_run:
            ret = urllib2.urlopen(request).read()
            print 'achievement creation request sent for', name
            print 'response: ', str(ret)

