#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this mirrors the JavaScript implementation in clientcode/Iuppiter.js

def string_to_bytes(input): return bytearray(input.encode('utf-8'))
def bytes_to_string(input): return input.decode('utf-8')

NBBY = 8;
MATCH_BITS = 6;
MATCH_MIN = 3;
MATCH_MAX = ((1 << MATCH_BITS) + (MATCH_MIN - 1))
OFFSET_MAK = ((1 << (16 - MATCH_BITS)) - 1)
LEMPEL_SIZE = 256

def compress(sstart):
    lempel = [3435973836]*LEMPEL_SIZE
    slen = len(sstart)
    if slen > 0xffffffff: raise Exception('input too long')

    dstart = bytearray()
    # prepend uncompressed length
    dstart.append(slen&0xff)
    dstart.append((slen>>8)&0xff)
    dstart.append((slen>>16)&0xff)
    dstart.append((slen>>24)&0xff)

    copymask = 1 << (NBBY-1)
    src = 0
    while src < slen:
        copymask <<= 1
        if (copymask == (1 << NBBY)):
            if len(dstart) >= (slen - 1 - 2*NBBY):
                dstart = dstart[0:4] + sstart
                return dstart
            copymask = 1
            copymap = len(dstart)
            dstart.append(0)
        if src > slen - MATCH_MAX:
            dstart.append(sstart[src]); src += 1
            continue
        hp = ((sstart[src] + 13) ^ (sstart[src + 1] - 13) ^ sstart[src + 2]) & (LEMPEL_SIZE - 1)
        offset = (src - lempel[hp]) & OFFSET_MAK
        lempel[hp] = src
        cpy = src - offset
        if (cpy >= 0 and cpy != src and \
            sstart[src] == sstart[cpy] and \
            sstart[src+1] == sstart[cpy+1] and \
            sstart[src+2] == sstart[cpy+2]):
            dstart[copymap] |= copymask
            for mlen in xrange(MATCH_MIN, MATCH_MAX):
                if sstart[src+mlen] != sstart[cpy+mlen]:
                    break
            dstart.append(((mlen - MATCH_MIN) << (NBBY - MATCH_BITS)) | (offset >> NBBY))
            dstart.append(offset&0xff)
            src += mlen
        else:
            dstart.append(sstart[src]); src += 1
    return dstart

def decompress(sstart):
    original_length = (sstart[0] | (sstart[1]<<8) | (sstart[2]<<16) | (sstart[3]<<24))
    if len(sstart) >= original_length:
        return sstart[4:]

    dstart = bytearray()
    src = 4
    slen = len(sstart)
    copymask = 1 << (NBBY-1)
    while src < slen:
        copymask <<= 1
        if (copymask == (1 << NBBY)):
            copymask = 1
            copymap = sstart[src]; src += 1
        if copymap & copymask:
            mlen = (sstart[src] >> (NBBY - MATCH_BITS)) + MATCH_MIN
            offset = ((sstart[src] << NBBY) | sstart[src + 1]) & OFFSET_MAK
            src += 2
            cpy = len(dstart) - offset
            if (cpy >= 0):
                mlen -= 1
                while mlen >= 0:
                    dstart.append(dstart[cpy]); cpy += 1; mlen -= 1
            else:
                raise Exception('Decompression error')
        else:
            dstart.append(sstart[src]); src += 1
    return dstart


# test code

if __name__ == '__main__':
    import random, base64
    #print repr(compress(string_to_bytes('')))
    #print repr(compress(string_to_bytes('a')))
    #print repr(compress(string_to_bytes('aasdfasdfasdfasdfasdfaaaaaaaaaaaaaaaaaaaaaa---------------------------------asdfasf')))
    #s = 'asssssssssssssssffffffffffffffffff-------------------------------------------------------------asdfasdsdf-------------------'
    #print bytes_to_string(decompress(compress(string_to_bytes(s))))
    s = 'HELLO WORLD-------------------------------------------------------------HIHIHIASDFASDF--'
    print len(s), len(compress(string_to_bytes(s)))
    print ['%d'%x for x in compress(string_to_bytes(s))]
    enc = compress(string_to_bytes(s))
    #enc = base64.b64encode(bytes(enc))
    print enc
    #enc = bytearray(base64.b64decode(enc))
    print bytes_to_string(decompress(enc))
    #assert bytes_to_string(string_to_bytes(s)) == s
    #assert bytes_to_string(decompress(compress(string_to_bytes(s)))) == s
    for i in xrange(10000):
        s = ''
        mylen = random.randint(0, 40)
        for c in xrange(mylen):
            mychar = chr(random.randint(30,126))
            if random.random() > 0.75:
                for j in xrange(random.randint(1,64)):
                    s += mychar
            else:
                s += mychar
        #print s
        assert bytes_to_string(string_to_bytes(s)) == s
        if bytes_to_string(decompress(compress(string_to_bytes(s)))) != s:
            print 'FAIL', repr(s), '->', ['%d'%x for x in compress(string_to_bytes(s))]
        assert bytes_to_string(decompress(bytearray(base64.b64decode(base64.b64encode(bytes(compress(string_to_bytes(s)))))))) == s
    print 'OK'
