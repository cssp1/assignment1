# DJM - this is hacked together from the patches at http://twistedmatrix.com/trac/ticket/4173

# Copyright (c) 2011-2012 Oregon State University Open Source Lab
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#    The above copyright notice and this permission notice shall be included
#    in all copies or substantial portions of the Software.
#
#    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
#    OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
#    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
#    NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
#    DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
#    OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
#    USE OR OTHER DEALINGS IN THE SOFTWARE.

# SP3RDPARTY : Twisted : MIT License

"""
The WebSockets protocol (RFC 6455), provided as a resource which wraps a
factory.
"""

from base64 import b64encode, b64decode
from hashlib import sha1
from struct import pack, unpack

from twisted.protocols.policies import ProtocolWrapper, WrappingFactory
from twisted.python import log
from twisted.web.resource import IResource
import twisted.web.http
from twisted.web.server import NOT_DONE_YET
from twisted.internet.address import IPv4Address
from zope.interface import implements

import BrowserDetect
import SpinHTTP
import binascii

import twisted.web.error, twisted.web.resource # DJM
# handle different Twisted versions that moved NoResource around
if hasattr(twisted.web.resource, 'NoResource'):
    TwistedNoResource = twisted.web.resource.NoResource
else:
    TwistedNoResource = twisted.web.error.NoResource

class WSException(Exception):
    """
    Something stupid happened here.

    If this class escapes txWS, then something stupid happened in multiple
    places.
    """
    def __init__(self, reason, raw_data = None):
        Exception.__init__(self, reason)
        self.raw_data = raw_data
    def __str__(self):
        ret = Exception.__str__(self)
        if self.raw_data:
            ret += (' Hex data (len %d):\n' % len(self.raw_data)) + binascii.hexlify(self.raw_data[:100]) + '...'
        return ret

# Control frame specifiers. Some versions of WS have control signals sent
# in-band. Adorable, right?

NORMAL, CLOSE, PING, PONG = range(4)

opcode_types = {
    0x0: NORMAL,
    0x1: NORMAL,
    0x2: NORMAL,
    0x8: CLOSE,
    0x9: PING,
    0xa: PONG,
}

opcode_for_type = {
    NORMAL: 0x1,
    CLOSE: 0x8,
    PING: 0x9,
    PONG: 0xa,
}

encoders = {
    "base64": b64encode,
}

decoders = {
    "base64": b64decode,
}

# Authentication for WS.

def make_accept(key):
    """
    Create an "accept" response for a given key.

    This dance is expected to somehow magically make WebSockets secure.
    """

    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    return sha1("%s%s" % (key, guid)).digest().encode("base64").strip()

# Frame helpers.
# Separated out to make unit testing a lot easier.
# Frames are bonghits in newer WS versions, so helpers are appreciated.

def mask(buf, key):
    """
    Mask or unmask a buffer of bytes with a masking key.

    The key must be exactly four bytes long.
    """

#    key = [ord(i) for i in key]
#    buf = list(buf)
#    for i, char in enumerate(buf):
#        buf[i] = chr(ord(char) ^ key[i % 4])
#    return "".join(buf)

    # DJM from fast_xor.diff
    ## Please don't bring back the xor vs encryption masking debate... :0
    k = unpack('!Q', key * 2)[0]
    ## Some long data to process, use long xor
    div, mod = divmod(len(buf), 8)
    if mod:
        ## The buffer legth is not a 8 bytes multiple, need to adjust with rest
        if div:
            ## More than 8 bytes: unmask all long words except last
            longs = [pack('!Q', k ^ unpack('!Q', buf[i:i+8])[0]) for i in range(0, div*8, 8)]
            ## Append the rest (last 0..7 bytes)
            longs.append(pack('!Q', k ^ unpack('!Q', buf[div*8:] + " "*(8-mod))[0])[:mod])
            return "".join(longs)
        else:
            ## Short: all bytes at once
            return pack('!Q', k ^ unpack('!Q', buf[div*8:] + " "*(8-mod))[0])[:mod]
    else:
        ## The buffer legth is a 8 bytes multiple
        return "".join(pack('!Q', k ^ unpack('!Q', buf[i:i+8])[0]) for i in xrange(0, div*8, 8))

def make_hybi07_frame(buf, opcode=NORMAL):
    """
    Make a HyBi-07 frame.

    This function always creates unmasked frames, and attempts to use the
    smallest possible lengths.
    """

    if len(buf) > 0xffff:
        length = "\x7f%s" % pack(">Q", len(buf))
    elif len(buf) > 0x7d:
        length = "\x7e%s" % pack(">H", len(buf))
    else:
        length = chr(len(buf))

    # Always make a normal packet.
    header = chr(0x80 | opcode_for_type[opcode])
    frame = "%s%s%s" % (header, length, buf)
    return frame

def parse_hybi07_frames(buf):
    """
    Parse HyBi-07 frames in a highly compliant manner.
    """

    start = 0
    frames = []

    while True:
        # If there's not at least two bytes in the buffer, bail.
        if len(buf) - start < 2:
            break

        # Grab the header. This single byte holds some flags nobody cares
        # about, and an opcode which nobody cares about.
        header = ord(buf[start])

        # Get the FIN bit that we now care about.
        fin = bool(header & 0x80)

        # Check if any of the reserved flags are set.
        if header & 0x70:
            # At least one of the reserved flags is set. Pork chop sandwiches!
            raise WSException("Reserved flag in HyBi-07 frame (%d)" % header, raw_data = buf[start:])
            frames.append(("", CLOSE, fin))
            return frames, buf

        # Get the opcode, and translate it to a local enum which we actually
        # care about.
        opcode = header & 0xf
        try:
            opcode = opcode_types[opcode]
        except KeyError:
            raise WSException("Unknown opcode %d in HyBi-07 frame" % opcode, raw_data = buf[start:])

        # Get the payload length and determine whether we need to look for an
        # extra length.
        length = ord(buf[start + 1])
        masked = length & 0x80
        length &= 0x7f

        # The offset we're gonna be using to walk through the frame. We use
        # this because the offset is variable depending on the length and
        # mask.
        offset = 2

        # Extra length fields.
        if length == 0x7e:
            if len(buf) - start < 4:
                break

            length = buf[start + 2:start + 4]
            length = unpack(">H", length)[0]
            offset += 2
        elif length == 0x7f:
            if len(buf) - start < 10:
                break

            # Protocol bug: The top bit of this long long *must* be cleared;
            # that is, it is expected to be interpreted as signed. That's
            # fucking stupid, if you don't mind me saying so, and so we're
            # interpreting it as unsigned anyway. If you wanna send exabytes
            # of data down the wire, then go ahead!
            length = buf[start + 2:start + 10]
            length = unpack(">Q", length)[0]
            offset += 8

        if masked:
            if len(buf) - (start + offset) < 4:
                break

            key = buf[start + offset:start + offset + 4]
            offset += 4

        if len(buf) - (start + offset) < length:
            break

        data = buf[start + offset:start + offset + length]

        if masked:
            data = mask(data, key)

        if opcode == CLOSE:
            if len(data) >= 2:
                # Gotta unpack the opcode and return usable data here.
                data = unpack(">H", data[:2])[0], data[2:]
            else:
                # No reason given; use generic data.
                data = 1000, "No reason given"

        frames.append((opcode, data, fin))
        start += offset + length

    return frames, buf[start:]

class WebSocketsProtocol(ProtocolWrapper):
    """
    Protocol which wraps another protocol to provide a WebSockets transport
    layer.
    """

    buf = ""
    complete_data = ""
    codec = None
    dumb_pong = False # temporary hack to work around Chrome v39+ Websockets code that doesn't like to receive data with a PONG

    # DJM - for returning something in the Close frame
    close_code = None
    close_reason = ""

    # capture the peer address here since parsing it from a proxied HTTP request is complex
    # (see calls to SpinHTTP.* below) and we don't want to repeat that work.
    def __init__(self, factory, wrappedProtocol, spin_peer_addr = None):
        ProtocolWrapper.__init__(self, factory, wrappedProtocol)
        self.pending_frames = []
        self.spin_peer_addr = spin_peer_addr

    def connectionMade(self):
        ProtocolWrapper.connectionMade(self)
        log.msg("Opening connection with %s" % self.transport.getPeer())

    def parseFrames(self):
        """
        Find frames in incoming data and pass them to the underlying protocol.
        """

        try:
            frames, self.buf = parse_hybi07_frames(self.buf)
        except WSException as e:
            # Couldn't parse all the frames, something went wrong, let's bail.
            # DJM - for debugging, include the peer address we were talking to
            log.err(e, _why = 'WSException while communicating with '+str(self.spin_peer_addr))
            self.loseConnection()
            return

        for frame in frames:
            opcode, data, fin = frame
            if opcode == NORMAL:
                # Business as usual. Decode the frame, if we have a decoder.
                if self.codec:
                    self.complete_data += decoders[self.codec](data)
                # If no decoder, just tack it on as is to any previous frame data.
                else:
                    self.complete_data += data

                # If FIN bit is set this is the last data frame in this context.
                if fin:
                    # Pass the data compiled from the frames to the underlying protocol.
                    ProtocolWrapper.dataReceived(self, self.complete_data)
                    self.complete_data = ""
            elif opcode == CLOSE:
                # The other side wants us to close. I wonder why?
                reason, text = data
                log.msg("Closing connection: %r (%d)" % (text, reason))

                # Close the connection.
                self.loseConnection()
                return
            elif opcode == PING:
                # 5.5.2 PINGs must be responded to with PONGs.
                # 5.5.3 PONGs must contain the data that was sent with the
                # provoking PING.
                pong_data = data

                # DJM/JW - Chrome v39+ Websockets code breaks when you follow 5.5.3!
                if self.dumb_pong:
                    pong_data = ""

                self.transport.write(make_hybi07_frame(pong_data, opcode=PONG)) # DJM - this used to say make_hybi07_packet() but there is no definition for that!
            elif opcode == PONG:
                pass # log.err("PONG! %r" % (self.spin_peer_addr,))

    def sendFrames(self):
        # DJM - this shouldn't happen
        # if self.disconnecting:
        #     import sys, traceback
        #     sys.stderr.write('send while disconnecting!\n%r\n%s\n' % (self.pending_frames, ''.join(traceback.format_stack())))

        """
        Send all pending frames.
        """

        for frame in self.pending_frames:
            # Encode the frame before sending it.
            if self.codec:
                frame = encoders[self.codec](frame)
            packet = make_hybi07_frame(frame)
            self.transport.write(packet)
        self.pending_frames = []

    def sendPing(self):
        # log.err("PING! %r" % (self.spin_peer_addr,))
        self.transport.write(make_hybi07_frame("", opcode=PING))

    def dataReceived(self, data):
        self.buf += data

        self.parseFrames()

        # Kick any pending frames. This is needed because frames might have
        # started piling up early; we can get write()s from our protocol above
        # when they makeConnection() immediately, before our browser client
        # actually sends any data. In those cases, we need to manually kick
        # pending frames.
        if self.pending_frames:
            self.sendFrames()

    def write(self, data):
        """
        Write to the transport.

        This method will only be called by the underlying protocol.
        """

        self.pending_frames.append(data)
        self.sendFrames()

    def writeSequence(self, data):
        """
        Write a sequence of data to the transport.

        This method will only be called by the underlying protocol.
        """

        self.pending_frames.extend(data)
        self.sendFrames()

    def loseConnection(self):
        """
        Close the connection.

        This includes telling the other side we're closing the connection.

        If the other side didn't signal that the connection is being closed,
        then we might not see their last message, but since their last message
        should, according to the spec, be a simple acknowledgement, it
        shouldn't be a problem.
        """

        # Send a closing frame. It's only polite. (And might keep the browser
        # from hanging.)
        if not self.disconnecting:
            if self.close_code:
                body = "%s%s" % (pack(">H", self.close_code), self.close_reason)
            else:
                body = ""
            frame = make_hybi07_frame(body, opcode=CLOSE)
            self.transport.write(frame)

            ProtocolWrapper.loseConnection(self)

    # DJM from request_handler.patch
    def onRequest(self, request):
        request_hanler = getattr(self.wrappedProtocol,
                                 'onRequest',
                                 None)
        if request_hanler:
            request_hanler(request)

class WebSocketsFactory(WrappingFactory):
    """
    Factory which wraps another factory to provide WebSockets frames for all
    of its protocols.

    This factory does not provide the HTTP headers required to perform a
    WebSockets handshake; see C{WebSocketsResource}.
    """

    protocol = WebSocketsProtocol

    # pass extra addr parameter to WebsocketsProtocol to remember the peer address
    def buildProtocol(self, addr):
        return self.protocol(self, self.wrappedFactory.buildProtocol(addr), spin_peer_addr = addr)

class WebSocketsResource(object):
    """
    A resource for serving a protocol through WebSockets.

    This class wraps a factory and connects it to WebSockets clients. Each
    connecting client will be connected to a new protocol of the factory.

    Due to unresolved questions of logistics, this resource cannot have
    children.
    """

    implements(IResource)

    isLeaf = True

    def __init__(self, factory):
        self._factory = WebSocketsFactory(factory)

    def getChildWithDefault(self, name, request):
        return TwistedNoResource("No such child resource.") # DJM

    def putChild(self, path, child):
        pass

    def render(self, request):
        """
        Render a request.

        We're not actually rendering a request. We are secretly going to
        handle a WebSockets connection instead.
        """

        # If we fail at all, we're gonna fail with 400 and no response.
        # You might want to pop open the RFC and read along.
        failed = False

        if request.method != "GET":
            # 4.2.1.1 GET is required.
            failed = True

        upgrade = request.getHeader("Upgrade")
        if upgrade is None or "websocket" not in upgrade.lower():
            # 4.2.1.3 Upgrade: WebSocket is required.
            failed = True

        connection = request.getHeader("Connection")
        if connection is None or "upgrade" not in connection.lower():
            # 4.2.1.4 Connection: Upgrade is required.
            failed = True

        key = request.getHeader("Sec-WebSocket-Key")
        if key is None:
            # 4.2.1.5 The challenge key is required.
            failed = True

        version = request.getHeader("Sec-WebSocket-Version")
        if version != "13":
            # 4.2.1.6 Only version 13 works.
            failed = True
            # 4.4 Forward-compatible version checking.
            request.setHeader("Sec-WebSocket-Version", "13")

        dumb_pong = False

        user_agent = request.getHeader("User-Agent")
        if user_agent:
            browser = BrowserDetect.get_browser(user_agent)
            if browser['name'] == 'Chrome' and browser['version'] >= 39:
                #log.msg('Forcing blank PONGs')
                dumb_pong = True

        # Check whether a codec is needed. WS calls this a "protocol" for
        # reasons I cannot fathom. The specification permits multiple,
        # comma-separated codecs to be listed, but this functionality isn't
        # used in the wild. (If that ever changes, we'll have already added
        # the requisite codecs here anyway.) The main reason why we check for
        # codecs at all is that older draft versions of WebSockets used base64
        # encoding to work around the inability to send \x00 bytes, and those
        # runtimes would request base64 encoding during the handshake. We
        # stand prepared to engage that behavior should any of those runtimes
        # start supporting RFC WebSockets.
        #
        # We probably should remove this altogether, but I'd rather leave it
        # because it will prove to be a useful reference if/when extensions
        # are added, and it *does* work as advertised.
        codec = request.getHeader("Sec-WebSocket-Protocol")

        if codec:
            if codec not in encoders or codec not in decoders:
                log.msg("Codec %s is not implemented" % codec)
                failed = True

        if failed:
            request.setResponseCode(400)
            return ""

        # We are going to finish this handshake. We will return a valid status
        # code.
        # 4.2.2.5.1 101 Switching Protocols
        request.setResponseCode(101)
        # 4.2.2.5.2 Upgrade: websocket
        request.setHeader("Upgrade", "WebSocket")
        # 4.2.2.5.3 Connection: Upgrade
        request.setHeader("Connection", "Upgrade")
        # 4.2.2.5.4 Response to the key challenge
        request.setHeader("Sec-WebSocket-Accept", make_accept(key))
        # 4.2.2.5.5 Optional codec declaration
        if codec:
            request.setHeader("Sec-WebSocket-Protocol", codec)

        # DJM - get the true original peer, possibly forwarded
        peer_ip = SpinHTTP.get_twisted_client_ip(request)
        forw_port = SpinHTTP.get_twisted_header(request, 'X-Forwarded-Port')
        if forw_port:
            peer_port = int(forw_port)
        else:
            peer_port = request.transport.getPeer().port
        peer = IPv4Address('TCP', peer_ip, peer_port)

        # Create the protocol. This could fail, in which case we deliver an
        # error status. Status 502 was decreed by glyph; blame him.
        protocol = self._factory.buildProtocol(peer)
        if not protocol:
            request.setResponseCode(502)
            return ""
        if codec:
            protocol.codec = codec

        protocol.dumb_pong = dumb_pong

        # prevent Twisted from going into chunked mode and adding "Content-Encoding: chunked" header,
        # which doesn't seem to be correct for WebSockets
        # (and breaks CloudFlare)
        twisted.web.http.NO_BODY_CODES = (204, 304, 101)

        # prevent Twisted from returning a "Content-Type" header, which breaks CloudFlare WebSockets
        request.defaultContentType = None

        # Provoke request into flushing headers and finishing the handshake.
        request.write("")

        # And now take matters into our own hands. We shall manage the
        # transport's lifecycle.
        transport, request.channel.transport = request.channel.transport, None

        # Connect the transport to our factory, and make things go. We need to
        # do some stupid stuff here; see #3204, which could fix it.

        # DJM - Autobahn uses this variant, not sure which is correct (in wrapped case,
        # websockets-tls.diff sets transport.protocol.wrappedProtocol = protocol)
        if isinstance(transport, ProtocolWrapper):
        # i.e. TLS is a wrapping protocol
            transport.wrappedProtocol = protocol
        else:
            transport.protocol = protocol

        protocol.makeConnection(transport)

        # On Twisted 16.3.0+, the transport is paused whilst the existing
        # request is served; there won't be any requests after us so we can
        # just resume this ourselves.
        if hasattr(transport, "resumeProducing"):
            transport.resumeProducing()

        return NOT_DONE_YET

__all__ = ("WebSocketsResource",)
