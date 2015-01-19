# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

from twisted.internet import ssl

# This piece of code allows the Twisted SSL web server to use the
# "chained" SSL certificate supplied by GoDaddy. The "certificate
# chain file" is a CONCATENATION of the server's single .crt file and
# the gd_bundle.crt provided by GoDaddy.

class ChainingOpenSSLContextFactory(ssl.DefaultOpenSSLContextFactory):
    def __init__(self, *args, **kwargs):
      self.chain = None
      if kwargs.has_key("certificateChainFile"):
        self.chain = kwargs["certificateChainFile"]
        del kwargs["certificateChainFile"]

      ssl.DefaultOpenSSLContextFactory.__init__(self, *args, **kwargs)

    def cacheContext(self):
      ssl.DefaultOpenSSLContextFactory.cacheContext(self)
      if self.chain:
          self._context.use_certificate_chain_file(self.chain)
          self._context.use_privatekey_file(self.privateKeyFileName)
