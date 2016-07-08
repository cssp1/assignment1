#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Adaptor that sits on top of the SpinNoSQLClient database connection
# and an AsyncHTTPRequester to manage the game server's storage of player portraits.

from twisted.internet import defer
from twisted.python import failure
import functools
import urllib
import SpinConfig
import SpinFacebook
import SpinHTTP

unknown_person_portrait_50x50_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x002\x00\x00\x002\x08\x00\x00\x00\x00;T\xd7m\x00\x00\x03OIDATx\x01b\xf8O2\xa0\x96\x96\xef_H\xd3\xf2\xef\xe7\xa6\xc2\xbc\xf6%\x0b\xbb\x8e\x029\x1f\tk\xf9\xb2\xbe\xb9\xbe\x10@H9\xb6\xcb\x12\xc3\x00\xf8\xef\x1d\xd5\xcd\\\xdb\xb6m\xdb\xb6m\xdb\xb6m\xdb\xbe\xcd\xa4\x8b\x0f\xedl\x0e7O\xde\xc6QRq.\xaa\x92\x89\x0f\xaew|]\n\xd9\xdaJp\xa1!A\x01\xcb\x9a\xb6\xab\x18JL\x18\xf9\xfb\xf6\xc9x.-\xda\xd3\x0f$Z\x81j\xb8\xeao\x14Y\xda\xa8\xb6\x00\x00\xb4\x07\xc0_$\x92\xcd\x8b!/\xea\t\x9b\xb3$\x1f\x1e\xb7\xf6P\x04\x99\xcfS\x1bo\x97#QD\xa7\xdfA\xe4I]\x839\x93e\xdeU\xca\x9bz\x8f\x82\xc8\x04N\x0e\xf2\xa6\x88y\x97\xe2P\x08yY\xcfP\xf0\x14\x1b\x919a\xf3B\xc8\xd3\xda\x16\xe3\xf1?F8\xe1\xd2\xfa\x1a\xa8N\x7f\x02\xc8\xab\xc6\x06\x1f&\'\xbcV\x8fI\xb3f\x8fh\xa7$\x15\xc2V\xbb\x18@\xde5S>\x0f\xb0z\xec\xadT\xf7\xfbHG\x0e\xa9[\xb64\x80|i\xa3(\x81\xc4\x9a\xcd\xa8 \xed(\x81\x0c\xb0\x89\xa1\x8a\xcd\xe0\t5D\xccJ\xa7\xe7\xc6m\xfc\xf3\xa3\x8b\xc2\xd0\xf8\xe2\x10\xf2\xac\xbeNKd\x9a\xbcw\x9f\xaet\xaaY\xa3\xdfS\xf7\xcf\x11\x85\xba\xfaO\x82\xdd_\xc0S\x84\x8f\xc3-i\xc2\x8c\xae\x18\xf0\xdb\x8dQC\xed\x9c\xcc\x0f\x0f\xcc\x9b\x86\x06\x191\xec\xda\x8b\xefk\x05\xfe\xd7\xfa\x9b\xebW\x13\r\xd6\x9e\x8dLr\x1fE\x1d\xafQ\xa7\xa1k\x12\x18\xb6\xc6)\x1f\xd61.\xae\x07\x11d\xaa\xa0!\xb3V\x1bH\x14\xacF\xe5r\x17\xaeh\x13\xdb\x97-\xcc\xcf\x18\xd6Z68\x81\xba\xb35\xac+{\xbdY?\x83\xc8\xef\x83\xb2\xb0\x90\xa6\xd6%\xd4]m$\x91W\xf5>\x07\x91\xfd5\xd1\xda\x0f\xbeX\x8b\xaa\x93\r\x15\xea@\x8c\x08\x07v\xd8\xd8\xfc\xa2Ps\xb6\x19E\xdde\xf3\xc2\xc8\xa3:tY\xf0\x97\xe8\xe7Zr\xab\x86\xa2\x17\x80\xcf\t#\xbfZJ\xca\x1e#\xe9\x87\x07\xaa\x12\x12z\x84EZ\xf9o \xa6O\xab\xa8[\xaf[\xbf\xbe/\xdd\x1b\x0clE\x18\xa1{A~l\x83\xd1\xe3\xc6\x0f\xabi\xfd>Wn\x8e \xebY~ye\x7f\xf7\xf9{\x13M]2\xe2X\x04\xd9Y\xa1\tp\xb9\xf4q\xe9\xbfk\xac\x00EW\xb6\xfc\x18A\xde\x0fiT\xcf\xd0\x81I\xd3\xff\xdaDc`f\xd0\xaa[\xd13\xfe\xe7U7I\x19\xab\xb6\xfb\x0f\x1c\xd8\\\xd7"\xafvd]\xfe\xb7\xb5\x8c\xbfy\xa6\xaa\xaa\x8a\xf9\xbd\xde\x95\x85|h\xa1\x8b\x0e,M\x9b\x85\xa3\x11\x84d\tO}\x14_YS\xe3R&\xf2\xa4\x8e\xa2\xfe\'yg\xb6\xce\xc3\x18B\xb2\xaf\x96\x05\x7f\xf5=c\xea\x7f\x88"$s\x04\xda\xe5!HT\xf3_%\x90\x91\xc2\x07\x86\xe6(\xbaU\t\xe4Y#EN\xc8\x17\xb2f\xf2\xb7,\xe4m\x07Q\x94\x06aVt;\xfd=\x8e\x0ce>y\x8f\x10/M\x87\x05\xf7"\xc8r\xe9S \n\x85J!E\x8d\xa1G\xbe\x07\x90\xe5\xda\x12\x92\xa7<\x8f?\x1c\xdaL:@\x14!\x7f>\xbf\xbd1\xa4\xbc\x92\x85\xe4\xbf|\xa0\x94\xa7\x9bg\xca\xa2{p-\x7f\xbe\xbe\xbb\t \x08\x0e\x08\x00\x00 \x00\x00\xfd\xff\x04\x00X\xa5to\xa7\xbb\xaa"2\xc3\xdd\xcc]MD\x88\x19\x7f@\xb0g\xf7\xd6\x8d\xa7\x7f\x90\xd5\x1e\x03\x00\x1ex\x08\xd6\xd8\xed"\x13\x00\x00\x00\x00IEND\xaeB`\x82'

class PlayerPortraits(object):
    def __init__(self, db_client, async_http_map):
        self.db_client = db_client
        self.async_http_map = async_http_map

    def _get_url(self, pcache_info, frame_platform, social_id, access_token):
        if frame_platform == 'fb':
            if not social_id.startswith('fb'): return None
            fb_id = social_id[2:]
            tok = access_token or SpinConfig.config.get('facebook_app_access_token','')
            return SpinFacebook.versioned_graph_endpoint('user/picture', '%s/picture' % fb_id) + '?' + urllib.urlencode({'access_token': tok})
        elif frame_platform == 'kg':
            if 'kg_avatar_url' not in pcache_info: return None
            return pcache_info['kg_avatar_url']
        elif frame_platform == 'ag':
            if 'ag_avatar_url' not in pcache_info: return None
            return pcache_info['ag_avatar_url']
        elif frame_platform == 'bh':
            if not social_id.startswith('bh'): return None
            bh_id = social_id[2:]
            return SpinConfig['battlehouse_api_path'] + '/api/v3/users/'+bh_id+'/image'
        else:
            return None

    # Retrieve latest portrait. Requires pcache_info with enough data to fetch portrait.
    # On failure, throws immediately or returns None (if allow_fail == True)
    # Otherwise returns a Deferred that fires when the fetch is complete.
    def update(self, time_now, user_id, pcache_info, frame_platform, social_id, access_token, allow_fail = False):
        url = self._get_url(pcache_info, frame_platform, social_id, access_token)
        if not url:
            if allow_fail: return None
            raise Exception('insufficient info to determine portrait URL: user_id %r pcache_info %r frame_platform %r' % \
                            (user_id, pcache_info, frame_platform))

        d = defer.Deferred()
        headers = {}
        requester = self.async_http_map.get(frame_platform)
        if not requester:
            if allow_fail: return None
            raise Exception('no async_http requester for frame_platform %r' % frame_platform)
        requester.queue_request(time_now, url, functools.partial(self.update_complete, d, url, time_now, user_id),
                                error_callback = functools.partial(self.update_complete, d, url, time_now, user_id),
                                headers = headers, callback_type = requester.CALLBACK_FULL, max_tries = 1)
        return d

    def update_complete(self, d, url, time_now, user_id, body = '', headers = {}, status = '500', ui_reason = None):
        #print status, headers
        try:
            if int(status) != 200:
                raise Exception('got non-OK status %r for player portrait URL %r: %r' % (status, url, body))
            content_type = headers['content-type'][-1] if 'content-type' in headers else None
            expires = SpinHTTP.parse_http_time(headers['expires'][-1]) if 'expires' in headers else None
            last_modified = SpinHTTP.parse_http_time(headers['last-modified'][-1]) if 'last-modified' in headers else None
            self.db_client.player_portrait_add(user_id, bytes(body), time_now, content_type, expires, last_modified)
        except Exception as e:
            d.errback(failure.Failure(e))
            return
        d.callback(None)

    def get(self, time_now, user_id,
            # all these other parameters are optional, and only used if the local storage is missing the portrait
            pcache_info = None,
            # platform and token for the QUERYING player, not the target of the query
            frame_platform = None, access_token = None):
        # first check for hit
        row = self.db_client.player_portrait_get(user_id)
        if row and ((not row.get('expires')) or row['expires'] >= time_now):
            # hit
            return defer.succeed((row['content_type'], row['data']))

        # miss - can we retrieve the portrait, as a third party?
        if pcache_info is not None:
            target_platform = pcache_info['social_id'][0:2] if 'social_id' in pcache_info else None
            if target_platform:
                ret = self.update(time_now, user_id, pcache_info, target_platform, pcache_info['social_id'],
                                  access_token if frame_platform == target_platform else None, allow_fail = True)
                if ret:
                    return ret

                # else - cannot retrieve, fall back

        # miss - fall back to unknown portrait
        return defer.succeed(('image/png', unknown_person_portrait_50x50_png))


if __name__ == '__main__':
    import SpinNoSQL, AsyncHTTP
    from twisted.internet import reactor
    import sys, time

    async_http = AsyncHTTP.AsyncHTTPRequester(-1, -1, 30, # request timeout
                                              -1,
                                              lambda x: sys.stderr.write(x+'\n'))
    db_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']),
                                      identity = 'PlayerPortraits.py', log_exception_func = lambda x: sys.stderr.write(x+'\n'),
                                      max_retries = -1) # never give up

    def run_test():
        port = PlayerPortraits(db_client, {'fb':async_http, 'kg':async_http, 'ag':async_http, 'bh':async_http})
        now = int(time.time())
        pcache_info_fb = {'social_id':'fb427233'}
        pcache_info_kg = {'social_id':'kgexample', 'kg_avatar_url':'http://cdn4.kongcdn.com/assets/resize-image/50x50/assets/avatars/defaults/frog.png'}
        dlist = defer.DeferredList([port.update(now, 1112, pcache_info_fb, 'fb', 'fb427233', None),
                                    port.update(now, 1113, pcache_info_kg, 'kg', 'kgexample', None),
                                    port.get(now, 9999),
                                    port.get(now, 1112),
                                    port.get(now, 1113),
                                    port.get(now, 1113, pcache_info_kg, 'fb', None),
                                    port.get(now, 1112, pcache_info_fb, 'fb', None),
                                    ])
        dlist.addBoth(lambda _: reactor.stop())

    reactor.callLater(0, run_test)
    reactor.run()
