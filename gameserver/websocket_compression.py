# References:
# https://github.com/crossbario/autobahn-python/blob/master/autobahn/websocket/compress_deflate.py
# SP3RDPARTY : Crossbar.io : MIT License
#
# https://github.com/faye/permessage-deflate-node/tree/master/lib
# SP3RDPARTY : github.com/faye : MIT License

from websocket_exceptions import WSException
import zlib

import SpinConfig # for tunables
import random # temporary, for A/B test rollout

class NoCompressor(object):
    # pass-through no-op "compressor"
    min_length = 0
    def response_headers(self): return {}
    def is_per_message(self): return False
    def start_decompress_message(self): pass
    def decompress_message_data(self, data): return data
    def end_decompress_message(self): pass
    def start_compress_message(self): pass
    def compress_message_data(self, data): return data
    def end_compress_message(self): return b''

class PerMessageDeflateCompressor(object):
    # DEFLATE (i.e. zlib) compressor

    # Permissible value for window size parameter.
    # Higher values use more memory, but produce smaller output.
    VALID_WINDOW_BITS = (8, 9, 10, 11, 12, 13, 14, 15)
    DEFAULT_WINDOW_BITS = 11 # zlib.MAX_WBITS

    # Permissible value for memory level parameter.
    # Higher values use more memory, but are faster and produce smaller output.
    VALID_MEM_LEVELS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
    DEFAULT_MEM_LEVEL = 4 # 8

    # for optimization notes, see
    # https://www.ietf.org/mail-archive/web/hybi/current/msg10222.html

    # Do not bother compressing frames shorter than this
    DEFAULT_MIN_LENGTH = 0

    def __init__(self, extension_list):
        ws_config = SpinConfig.config.get('websocket', {}).get('deflate', {})

        # parameters we control fully
        self.min_length = ws_config.get('min_message_length', self.DEFAULT_MIN_LENGTH)
        self.mem_level = ws_config.get('zlib_mem_level', self.DEFAULT_MEM_LEVEL)
        self.level = ws_config.get('zlib_compression_level', zlib.Z_DEFAULT_COMPRESSION)

        # negotiable parameters
        self.client_window_bits = ws_config.get('zlib_window_bits', self.DEFAULT_WINDOW_BITS)
        self.server_window_bits = ws_config.get('zlib_window_bits', self.DEFAULT_WINDOW_BITS)

        self.client_context_takeover = True
        self.server_context_takeover = ws_config.get('server_context_takeover', True)

        # record which negotiation requests we saw, so we can respond with the minimal set
        self.saw_server_max_window_bits = False
        self.saw_server_no_context_takeover = False

        for ext in extension_list:
            if '=' in ext:
                ext_k, ext_v = ext.split('=')
                if ext_k == b'server_max_window_bits':
                    # client wants us to limit our window size
                    requested_bits = int(ext_v)
                    if requested_bits not in self.VALID_WINDOW_BITS:
                        raise Exception('client requested invalid server_max_window_bits')
                    # accept the limit
                    self.saw_server_max_window_bits = True
                    self.server_window_bits = min(self.server_window_bits, requested_bits)

            elif ext == b'server_no_context_takeover':
                # client wants us to disable context takeover
                self.saw_server_no_context_takeover = True
                self.server_context_takeover = False
            elif ext == b'client_no_context_takeover':
                # client willing to disable context takeover, if we ask for it
                pass
            elif ext == b'client_max_window_bits':
                # client is willing to limit its own window size, if we ask for it
                pass

        self.zcomp = None
        self.zdecomp = None

    def response_headers(self):
        response_list = [b'permessage-deflate']
        if self.saw_server_max_window_bits:
            response_list.append(b'server_max_window_bits=%d' % self.server_window_bits)
        if self.saw_server_no_context_takeover:
            response_list.append(b'server_no_context_takeover')
        return {b'Sec-WebSocket-Extensions': b'; '.join(response_list)}

    def is_per_message(self):
        return True

    def start_compress_message(self):
        if self.zcomp is None or not self.server_context_takeover:
            self.zcomp = zlib.compressobj(self.level, zlib.DEFLATED, -self.server_window_bits, self.mem_level)
    def compress_message_data(self, data):
        # return stream as we go along
        return self.zcomp.compress(data)
    def end_compress_message(self):
        # return tail end
        data = self.zcomp.flush(zlib.Z_SYNC_FLUSH)
        return data[:-4]

    def start_decompress_message(self):
        if self.zdecomp is None or not self.client_context_takeover:
            self.zdecomp = zlib.decompressobj(-self.client_window_bits)
    def decompress_message_data(self, data):
        try:
            return self.zdecomp.decompress(data)
        except zlib.error as e:
            # repackage zlib error as a WSException
            raise WSException(str(e))

    def end_decompress_message(self):
        # Eat stripped LEN and NLEN field of a non-compressed block added
        # for Z_SYNC_FLUSH.
        try:
            self.zdecomp.decompress(b'\x00\x00\xff\xff')
        except zlib.error as e:
            # repackage zlib error as a WSException
            raise WSException(str(e))

# instantiate a compressor given a list of the ;-separated elements of the incoming Sec-WebSocket-Extensions header

randgen = random.Random()

def init_from_extension_list(extension_list):
    ws_config = SpinConfig.config.get('websocket', {}).get('deflate', {})

    if 'permessage-deflate' in extension_list:
        # for A/B test rollout, use a random chance % to activate compression
        enable_chance = ws_config.get('enabled', 0.0) # 0.0-1.0
        if enable_chance > 0 and (enable_chance >= 1 or (enable_chance > randgen.random())):
            return PerMessageDeflateCompressor(extension_list)

    return NoCompressor()
