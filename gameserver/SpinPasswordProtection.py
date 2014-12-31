# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import twisted.web.guard
import twisted.cred.portal
import twisted.cred.checkers
from twisted.web import resource
import zope.interface

# hack - lengthen the default auth timeout from 15 min to 4 hours
twisted.web.guard.DigestCredentialFactory.CHALLENGE_LIFETIME_SECS = 4 * 60 * 60

default_username = 'example'
default_password = 'example.com'

# wrapper to secure web interfaces with HTTP Digest auth
class SecureResource(twisted.web.guard.HTTPAuthSessionWrapper):
    class AdminRealm(object):
        zope.interface.implements(twisted.cred.portal.IRealm)
        def __init__(self, resource_factory):
            self.resource_factory = resource_factory
        def requestAvatar(self, avatarId, mind, *interfaces):
            if resource.IResource in interfaces:
                return (resource.IResource, self.resource_factory(), lambda: None)
            raise NotImplementedError()
    def __init__(self, resource_factory, username = default_username, password = default_password):
        passdb = twisted.cred.checkers.InMemoryUsernamePasswordDatabaseDontUse(**{username:password})
        portal = twisted.cred.portal.Portal(self.AdminRealm(resource_factory), [passdb])
        credfact = twisted.web.guard.DigestCredentialFactory('md5', 'SpinPunch Admin')
        twisted.web.guard.HTTPAuthSessionWrapper.__init__(self, portal, [credfact])
    def render(self, request):
        # do not return a revealing error message on exceptions
        try:
            return super(SecureResource, self).render(request)
        except:
            import traceback
            return 'exception on password-protected resource '+ traceback.format_exc()
