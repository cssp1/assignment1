# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

"""
Example usage:

km = KM('my-api-key')
km.identify('simon')
km.record('an event', {'attr': '1'})
"""

import urllib
import socket
from datetime import datetime

# DJM - Async HTTP request for SpinPunch server efficiency
# pass an AsyncHTTPRequester as the 'async' parameter to KM.__init__

class KM(object):
    def __init__(self, key, host='trk.kissmetrics.com:80', logging=True, async=None):
        self._key    = key
        self._host = host
        self._logging = logging
        self._async = async

    def identify(self, id):
        self._id = id

    def record(self, action, props={}):
        self.check_id_key()
        if isinstance(action, dict):
            self.set(action)

        props.update({'_n': action})
        self.request('e', props)

    def set(self, data):
        self.check_id_key()
        self.request('s',data)

    def alias(self, name, alias_to):
        self.check_init()
        self.request('a', {'_n': alias_to, '_p': name}, False)

    def log_file(self):
        return '/tmp/kissmetrics_error.log'

    def reset(self):
        self._id = None
        self._key = None

    def check_identify(self):
        if self._id == None:
            raise Exception, "Need to identify first (KM.identify <user>)"

    def check_init(self):
        if self._key == None:
            raise Exception, "Need to initialize first (KM.init <your_key>)"

    def now(self):
        return datetime.utcnow()

    def check_id_key(self):
        self.check_init()
        self.check_identify()

    def logm(self, msg):
        if not self._logging:
            return
        msg = self.now().strftime('<%c> ') + msg
        try:
            fh = open(self.log_file(), 'a')
            fh.write(msg)
            fh.close()
        except IOError:
            pass #just discard at this point

    def request(self, req_type, data, update=True):
        query = []

        # if user has defined their own _t, then include necessary _d
        if '_t' in data:
            data['_d'] = 1
        else:
            data['_t'] = self.now().strftime('%s')

        # add customer key to data sent
        data['_k'] = self._key

        if update:
            data['_p'] = self._id

        for key, val in data.items():
            if type(key) == unicode:
                safe_key = key.encode('utf-8')
            else:
                safe_key = str(key)
            if type(val) == unicode:
                safe_val = val.encode('utf-8')
            else:
                safe_val = str(val)
            query.append(urllib.quote(safe_key) + '=' + urllib.quote(safe_val))

        try:
            if self._async:
                url = 'http://' + self._host + '/' + req_type + '?' + '&'.join(query)
                self._async.queue_request(url, lambda x: None)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                host, port = self._host.split(':')
                sock.connect((host, int(port)))
                sock.setblocking(0) # 0 is non-blocking

                get = 'GET /' + req_type + '?' + '&'.join(query) + " HTTP/1.1\r\n"
                out = get
                out += "Host: " + socket.gethostname() + "\r\n"
                out += "Connection: Close\r\n\r\n";
                sock.send(out)
                sock.close()
        except:
            self.logm("Could not transmit to " + self._host)
