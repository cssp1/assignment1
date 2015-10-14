#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this is a nasty hack that reaches into the guts of Twisted's "reactor"
# implementation to install a latency monitor to track all "non-waiting"
# CPU time taken by a server process

import sys, time

g_latency_func = None

def setup(reactor, latency_func):
    global g_latency_func
    g_latency_func = latency_func

    if sys.platform != 'linux2': return # not supported

    from twisted.internet import epollreactor
    from twisted.python import log
    import errno

    assert isinstance(reactor, epollreactor.EPollReactor)
    if 1:
        print 'installing EPollReactor latency measurement wrapper'

        def mypoll(self, timeout):
            if timeout is None:
                timeout = -1  # Wait indefinitely.
            try:
                if hasattr(self._poller, 'poll'):
                    # NEW python API
                    l = self._poller.poll(timeout, len(self._selectables))
                else:
                    # OLD twisted implementation
                    l = self._poller.wait(len(self._selectables), int(1000*timeout))
            except IOError, err:
                if err.errno == errno.EINTR:
                    return
                raise
            _drdw = self._doReadOrWrite
            start_time = time.time()
            for fd, event in l:
                try:
                    selectable = self._selectables[fd]
                except KeyError:
                    pass
                else:
                    log.callWithLogger(selectable, _drdw, selectable, fd, event)
            end_time = time.time()
            g_latency_func('ALL', end_time - start_time)

        epollreactor.EPollReactor.doIteration = mypoll

        old_runUntilCurrent = epollreactor.EPollReactor.runUntilCurrent
        def myRunUntilCurrent(self):
            start_time = time.time()
            ret = old_runUntilCurrent(self)
            end_time = time.time()
            g_latency_func('ALL', end_time - start_time)
            return ret

        epollreactor.EPollReactor.runUntilCurrent = myRunUntilCurrent


# subclass of Deferred that reports callback latency

from twisted.internet import defer
class InstrumentedDeferred(defer.Deferred):
    def __init__(self, latency_tag):
        defer.Deferred.__init__(self)
        self.latency_tag = latency_tag
    def _runCallbacks(self):
        start_time = time.time()
        ret = defer.Deferred._runCallbacks(self)
        end_time = time.time()
        if g_latency_func:
            g_latency_func('(d)'+self.latency_tag, end_time - start_time)
        return ret
    def __repr__(self):
        r = defer.Deferred.__repr__(self)
        # depends on the guts of Deferred.__repr__() :(
        fields = r.split(' ')
        fields[0] += '("'+self.latency_tag+'")'
        return ' '.join(fields)
