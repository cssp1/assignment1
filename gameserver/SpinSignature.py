#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import base64, hmac, hashlib

# create HMAC signature of proxyserver-generated session parameters so
# that gameserver can verify that the params are valid when they come
# back from the client.
def sign_session(user_id, country, session_id, session_time, server_name, auth_user, auth_token, extra_data, secret):
    SALT = '3RqMRLWY9ypDrZt6gNJtukmgWuaqeuzR'
    tosign = str(user_id) + ':' + str(country) + ':' + str(session_id) + ':' + str(session_time) + ':' + str(server_name) + ':' + auth_user + ':' + auth_token + ':' + extra_data + ':' + SALT
    return base64.urlsafe_b64encode(hmac.new(str(secret), msg=tosign, digestmod=hashlib.sha256).digest())

class AnonID (object):
    # Mostly-secure tokens for carrying over login information (URL
    # parameters etc) between separate index hits in proxyserver.

    # To be truly secure, this needs to incorporate some element of the
    # frame platform's login token into the "tosign" bit.

    @classmethod
    def create(cls, expire_time, ip_addr, frame_platform, secret, salt):
        tosign = ':'.join(['%d' % expire_time, ip_addr, frame_platform, salt])
        return base64.urlsafe_b64encode(hmac.new(str(secret), msg=tosign, digestmod=hashlib.sha256).digest()) + '|' + tosign
    @classmethod
    def verify(cls, input, time_now, ip_addr, frame_platform, secret):
        if (not input) or ('|' not in input) or len(input) < 10: return False
        sig, tosign = input.split('|')
        s_expire_time, s_ip_addr, s_frame_platform, s_salt = tosign.split(':')
        if int(s_expire_time) > time_now and s_ip_addr == ip_addr and s_frame_platform == frame_platform:
            if sig == base64.urlsafe_b64encode(hmac.new(str(secret), msg=tosign, digestmod=hashlib.sha256).digest()):
                return True
        return False

if __name__ == '__main__':
    TEST_SECRET = 'asdffdsasdf'
    print sign_session(1112, 'us', '12345abcd', 123456, 'asdffdsa', '123423234', 'ZZZZZYYYY', '123,321,23', '111222')
    assert AnonID.verify(AnonID.create(1234, '1.2.3.4', 'fb', TEST_SECRET, 'salt'), 1233, '1.2.3.4', 'fb', TEST_SECRET)
    assert not AnonID.verify(AnonID.create(1234, '1.2.3.4', 'fb', TEST_SECRET, 'salt'), 1237, '1.2.3.4', 'fb', TEST_SECRET)
    assert not AnonID.verify(AnonID.create(1234, '1.2.3.4', 'fb', TEST_SECRET, 'salt'), 1233, '4.2.3.4', 'fb', TEST_SECRET)
    assert not AnonID.verify(AnonID.create(1234, '1.2.3.4', 'fb', TEST_SECRET, 'salt'), 1233, '1.2.3.4', 'fasdf', TEST_SECRET)
