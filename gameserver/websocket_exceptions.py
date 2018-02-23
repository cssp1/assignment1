# common exception class shared by websockets modules

import binascii

class WSException(Exception):
    def __init__(self, reason, raw_data = None):
        Exception.__init__(self, reason)
        self.raw_data = raw_data
    def __str__(self):
        ret = Exception.__str__(self)
        if 0: # self.raw_data:
            ret += (' Hex data (len %d):\n' % len(self.raw_data)) + binascii.hexlify(self.raw_data[:100]) + '...'
        return ret
