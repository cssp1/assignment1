#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# simple HTTP server that reads/writes files
# used to work around lack of asynchronous file I/O in Twisted
# very insecure, do not expose outside of localhost!

import os, sys, time, signal, errno, functools, traceback

from twisted.internet import reactor, defer
from twisted.web import server, resource, http
import subprocess
import AtomicFileWrite

class IOAPI(resource.Resource):
    isLeaf = True
    def __init__(self, secret):
        resource.Resource.__init__(self)
        self.secret = secret
        self.delay_faults = 0
        self.serious_faults = 0

    def inject_fault(self, serious):
        sys.stderr.write('simulating fault!\n')
        if serious:
            self.serious_faults += 1
        else:
            self.delay_faults += 5

    def simulate_fault(self):
        if self.serious_faults > 0:
            self.serious_faults -= 1
            sys.stderr.write('simulating HTTP failure\n')
            return True

        if self.delay_faults > 0:
            self.delay_faults -= 1
            sys.stderr.write('simulating HTTP delay\n')
            time.sleep(4.0)
        return False

    def render_GET(self, request):
        assert request.args['secret'][0] == self.secret
        if self.simulate_fault():
            request.setResponseCode(http.BAD_REQUEST)
            return ''

        filename = request.args['filename'][0]
        try:
            f = open(filename)
        except:
            request.setResponseCode(http.NOT_FOUND)
            return 'NOTFOUND'
        try:
            buf = f.read()
            return buf
        except Exception as e:
            sys.stderr.write('ioslave exception: %s\n%s' % (repr(e), traceback.format_stack()))
            request.setResponseCode(http.INTERNAL_SERVER_ERROR)
            return 'error'

    def render_POST(self, request):
        assert request.args['secret'][0] == self.secret

        if ('shutdown' in request.args):
            reactor.callLater(0.1, reactor.stop)
            return 'ok'

        if self.simulate_fault():
            request.setResponseCode(http.BAD_REQUEST)
            return ''

        if 'delete' in request.args:
            filename = request.args['delete'][0]
            try:
                os.unlink(filename)
            except:
                pass
            return 'ok'

        try:
            filename = request.args['filename'][0]
            do_sync = ('fsync' in request.args and bool(request.args['fsync'][0]))
            buf = request.content.read()
            atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
            atom.fd.write(buf)
            atom.complete(fsync = do_sync)
            return 'ok'
        except Exception as e:
            sys.stderr.write('ioslave exception: %s\n%s' % (repr(e), traceback.format_stack()))
            request.setResponseCode(http.INTERNAL_SERVER_ERROR)
            return 'error'

class IoSite(server.Site):
    displayTracebacks = False
    def __init__(self, api):
        server.Site.__init__(self, api)

def do_slave(port, secret):
    api = IOAPI(secret)
    site = IoSite(api)

    # ignore SIGINT
    signal.signal(signal.SIGINT, lambda signum, frm: None)
    signal.signal(signal.SIGUSR1, lambda signum, frm: api.inject_fault(False))
    signal.signal(signal.SIGUSR2, lambda signum, frm: api.inject_fault(True))

    reactor.listenTCP(port, site, interface='localhost', backlog=500)
    # signal parent that we are alive
    print 'ready'
    sys.stdout.flush()
    reactor.run()

# CLIENT API
import AsyncHTTP

class IOClient (object):
    def __init__(self, port, secret, log_exception_func = None):
        self.port = port
        self.secret = secret
        self.proc = subprocess.Popen(['./ioslave.py', str(port), secret], stdout=subprocess.PIPE)
        input = self.proc.stdout.readline().strip()
        assert input == 'ready'

        # NOTE: we don't use the normal AsyncHTTP throttling mechanism, which drops requests that exceed the queue limit
        # instead, we NEVER drop a request, but do throttle other things (e.g. user login) if the wire gets full
        if not log_exception_func: log_exception_func = sys.stderr.write
        self.req = AsyncHTTP.AsyncHTTPRequester(-1, -1, 30, 0,
                                                log_exception_func,
                                                error_on_404 = False)

        # this trigger postpones reactor shutdown until all in-progress I/Os complete
        reactor.addSystemEventTrigger('before', 'shutdown', self.defer_until_all_complete)
        self.shutdown_semaphore = None

    def __repr__(self):
        return '(IOClient port %d pid %d)' % (self.port, self.proc.pid)

    def num_in_flight(self): return self.req.num_on_wire()

    def async_read(self, filename, time_now, success_cb, error_cb):
        self.req.queue_request(time_now, 'http://localhost:'+str(self.port)+'/?filename='+filename+'&secret='+self.secret,
                               success_cb, error_callback = error_cb, method='GET')

    # need a little adaptor function to throw away the unnecessary "response" from write requests
    def async_write_success(self, filename, cb, response):
        cb()

    def async_write(self, filename, data, time_now, success_cb, error_cb, fsync = True):
        self.req.queue_request(time_now, 'http://localhost:'+str(self.port)+'/?filename='+filename+('&fsync=1' if fsync else '')+'&secret='+self.secret,
                               functools.partial(self.async_write_success, filename, success_cb),
                               error_callback = error_cb, method='POST',
                               postdata=data)

    def async_delete(self, filename, time_now, success_cb, error_cb):
        self.req.queue_request(time_now, 'http://localhost:'+str(self.port)+'/?delete='+filename+'&secret='+self.secret,
                               functools.partial(self.async_write_success, filename, success_cb),
                               error_callback = error_cb, method='POST')

    # shutdown mechanics are complicated:
    # 1) reactor.stop() begins the shutdown process
    # 2) defer_until_all_complete(), which we insert into the shutdown path with addSystemEventTrigger(),
    #    creates a Deferred object and returns it to Twisted,
    #    preventing the reactor shutdown from finishing until we are fully cleaned up.
    # 3) we ask AsyncHTTP to finish any outstanding read/write requests and then call our post_all_complete()
    # --- HTTP traffic continues until the wire goes quiet ---
    # 4) post_all_complete() sends the "shutdown" message to the ioslave process
    # --- HTTP traffic continues until the wire goes quiet ---
    # 5) after the "shutdown" message response comes back, we finally
    #    call release_shutdown() which waits on the subprocess to exit, then fires the semaphore and lets
    #    Twisted continue the shutdown process.

    def defer_until_all_complete(self):
        print self, 'postponing reactor shutdown until all async I/Os complete...'
        assert not self.shutdown_semaphore
        self.shutdown_semaphore = defer.Deferred()
        self.req.call_when_idle(self.post_all_complete)
        return self.shutdown_semaphore
    def post_all_complete(self):
        print self, 'all async I/Os completed, shutting down ioslave...'
        self.req.queue_request(0, 'http://localhost:'+str(self.port)+'/?shutdown=1&secret='+self.secret,
                               self.release_shutdown, error_callback = self.release_shutdown, method='POST')
    def release_shutdown(self, unused):
        while True:
            try:
                os.waitpid(self.proc.pid, 0)
                break
            except OSError as e:
                if e.errno != errno.EINTR:
                    break
            except:
                break
        print self, 'ioslave stopped cleanly, continuing reactor shutdown...'
        self.shutdown_semaphore.callback(1)


# for testing

TEST_SECRET = 'asbasdf'

class TestClient (object):
    def __init__(self):
        self.master = IOClient(12222, TEST_SECRET)
        self.success_count = 0

    def success_cb(self, result):
        print 'SUCCESS', len(result)
        self.success_count += 1
        if self.success_count == 4:
            print 'stopping reactor...'
            reactor.stop()

    def error_cb(self, reason):
        print 'ERROR', reason

    def go(self):
        self.master.async_read('ioslave.py', time.time(), self.success_cb, self.error_cb)
        self.master.async_read('missing.py', time.time(), self.success_cb, self.error_cb)
        self.master.async_write('/tmp/zzz', 'ZZZZZZZZZZZZZZZZZZZZZ\\u1234\\u4321ZZZZZ\n',
                                time.time(), lambda: self.success_cb('xxx'), self.error_cb, fsync = True)
        self.master.async_delete('/tmp/zzz', time.time(), lambda: self.success_cb('xxx'), self.error_cb)



def test_client():
    client = TestClient()
    client.go()
    reactor.run()


if __name__ == '__main__':
    if 'client' in sys.argv:
        test_client()
    else:
        do_slave(int(sys.argv[1]), sys.argv[2])
