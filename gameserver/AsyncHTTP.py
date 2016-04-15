#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import twisted.python.failure
import twisted.internet.defer
import twisted.internet.protocol
import twisted.internet.reactor
import twisted.web.client
import twisted.web.error
import traceback
import time
from collections import deque

class AsyncHTTPRequester(object):
    # there are two "modes" for the callbacks on a request:

    # callback receives one argument that is the response body (success)
    # or a stringified error message (failure)
    CALLBACK_BODY_ONLY = 'body_only'

    # callback receives keyword arguments {body:"asdf", headers:{"Content-Type":["image/jpeg"]}, status:200}
    # and failure also gets ui_reason: "Some Exception Happened"
    CALLBACK_FULL = 'full'

    class Request:
        def __init__(self, qtime, method, url, headers, callback, error_callback, preflight_callback, postdata, max_tries, callback_type):
            self.method = method
            self.url = url
            self.headers = headers
            self.callback = callback
            self.error_callback = error_callback
            self.preflight_callback = preflight_callback
            self.postdata = postdata
            self.fire_time = qtime
            self.max_tries = max_tries
            self.callback_type = callback_type
            self.tries = 1
        def __hash__(self): return hash((self.url, self.method, self.fire_time, self.callback))
        def __repr__(self): return self.method + ' ' + self.url
        def get_stats(self):
            return {'method':self.method, 'url':self.url, 'time':self.fire_time, 'tries': self.tries}

    def __init__(self, concurrent_request_limit, total_request_limit, request_timeout, verbosity, log_exception_func,
                 max_tries = 1, retry_delay = 0, error_on_404 = True):
        # reference to the server's global event Reactor
        self.reactor = twisted.internet.reactor

        # this semaphore limits the number of connections allowed concurrently
        # additional connection attempts are queued until previous ones finish
        if concurrent_request_limit > 0:
            self.semaphore = twisted.internet.defer.DeferredSemaphore(concurrent_request_limit)
        else:
            self.semaphore = None

        # requests that are not on the wire yet
        self.queue = deque()

        # requests on the wire that we are waiting to hear back on
        self.on_wire = set()

        # requests that are awaitng a requeue after failing
        self.waiting_for_retry = set()

        self.total_request_limit = total_request_limit
        self.request_timeout = request_timeout

        # disable overly verbose log messages
        self.verbosity = verbosity
        twisted.web.client.HTTPClientFactory.noisy = False

        self.log_exception_func = log_exception_func
        self.default_max_tries = max_tries
        self.retry_delay = retry_delay
        self.error_on_404 = error_on_404

        # function to call when all outstanding requests have either succeeded or failed
        self.idle_cb = None

        self.n_dropped = 0
        self.n_accepted = 0
        self.n_fired = 0
        self.n_ok = 0
        self.n_errors = 0
        self.n_retries = 0

    def num_on_wire(self): return len(self.on_wire)

    def call_when_idle(self, cb):
        assert not self.idle_cb
        self.idle_cb = cb
        # defer so that if we are in the shutdown path, we don't
        # prematurely shut down before other shutdown callbacks start their own I/O requests
        self.reactor.callLater(0, self.idlecheck)


    def idlecheck(self):
        if self.idle_cb and len(self.queue) == 0 and len(self.on_wire) == 0 and len(self.waiting_for_retry) == 0:
            cb = self.idle_cb
            self.idle_cb = None
            cb()

    def queue_request(self, qtime, url, user_callback, method='GET', headers=None, postdata=None, error_callback=None, preflight_callback=None, max_tries=None, callback_type = CALLBACK_BODY_ONLY):
        if self.total_request_limit > 0 and len(self.queue) >= self.total_request_limit:
            self.log_exception_func('AsyncHTTPRequester queue is full, dropping request %s %s!' % (method,url))
            self.n_dropped += 1
            return

        self.n_accepted += 1

        if max_tries is None:
            max_tries = self.default_max_tries
        else:
            max_tries = max(max_tries, self.default_max_tries)

        if headers: assert isinstance(headers, dict)
        request = AsyncHTTPRequester.Request(qtime, method, url, headers, user_callback, error_callback, preflight_callback, postdata, max_tries, callback_type)

        self.queue.append(request)
        if self.verbosity >= 1:
            print 'AsyncHTTPRequester queueing request %s, %d now in queue' % (repr(request), len(self.queue))
        if self.semaphore:
            self.semaphore.run(self._send_request)
        else:
            self._send_request()

    def _send_request(self):
        request = self.queue.popleft()
        if request.preflight_callback: # allow caller to adjust headers/url/etc at the last minute before transmission
            request.preflight_callback(request)
        self.n_fired += 1
        self.on_wire.add(request)
        if self.verbosity >= 1:
            print 'AsyncHTTPRequester opening connection %s, %d now in queue, %d now on wire' % (repr(request), len(self.queue), len(self.on_wire))

        getter = self.make_web_getter(bytes(request.url), twisted.web.client.HTTPClientFactory,
                                      method=request.method,
                                      headers=request.headers,
                                      agent='spinpunch game server',
                                      timeout=self.request_timeout,
                                      postdata=request.postdata)
        d = getter.deferred
        d.addCallback(self.on_response, getter, request)
        d.addErrback(self.on_error, getter, request)
        return d

    # Wrap Twisted's HTTP Client with a strict watchdog timer
    # Twisted's own "timeout" parameter doesn't always fire reliably, meaning it does not guarantee
    # that a request's deferred fires with either callback or errback within the timeout interval.
    # We see this problem with ~0.01% of Amazon S3 requests - it might be due to a hangup in the
    # SSL negotiation.

    def make_web_getter(self, *args, **kwargs):
        # this is like calling twisted.web.client.getPage, but we want the full HTTPClientFactory
        # and not just its .deferred member, since we want to access the response headers as well as the body.
        getter = twisted.web.client._makeGetterFactory(*args, **kwargs)

        if kwargs and 'timeout' in kwargs:
            # set up our own watchdog timer

            # add slop time to allow Twisted's own timeout to fire first if it wants
            delay = kwargs['timeout'] + 5 # seconds

            def watchdog_func(self, getter):
                if getter.deferred.called: return # somehow it succeeded

                # swap a fresh Deferred into getter so that Twisted won't call the original one again
                d, getter.deferred = getter.deferred, twisted.internet.defer.Deferred()

                self.log_exception_func('AsyncHTTP getter watchdog timeout at %r' % time.time())

                d.errback(twisted.python.failure.Failure(Exception('AsyncHTTP getter watchdog timeout')))

            watchdog = twisted.internet.reactor.callLater(delay, watchdog_func, self, getter)

            # cancel the watchdog as soon as getter.deferred fires, regardless of whether it's a callback or errback
            def cancel_watchdog_and_continue(_, watchdog):
                if watchdog.active(): # we might be called downstream from the watchdog firing itself
                    watchdog.cancel()
                return _

            getter.deferred.addBoth(cancel_watchdog_and_continue, watchdog)

        return getter

    def on_response(self, response, getter, request):
        self.n_ok += 1
        self.on_wire.remove(request)
        if self.verbosity >= 1:
            print 'AsyncHTTPRequester got response for', request
            if self.verbosity >= 3:
                print 'AsyncHTTPRequester response was:', 'status', getter.status, 'headers', getter.response_headers, 'body', response
        try:
            if request.callback_type == self.CALLBACK_FULL:
                request.callback(body = response, headers = getter.response_headers, status = getter.status)
            else:
                request.callback(response)
        except:
            self.log_exception_func('AsyncHTTP Exception: ' + traceback.format_exc())
        self.idlecheck()

    def retry(self, request):
        self.waiting_for_retry.remove(request)
        request.tries += 1
        self.n_retries += 1
        self.queue.append(request)
        if self.verbosity >= 1:
            print 'AsyncHTTPRequester retrying failed request %s, %d now in queue' % (repr(request), len(self.queue))
        if self.semaphore:
            self.semaphore.run(self._send_request)
        else:
            self._send_request()

    def on_error(self, reason, getter, request):
        # note: "reason" here is a twisted.python.failure.Failure object that wraps the exception that was thrown

        # for HTTP errors, extract the HTTP status code
        if (reason.type is twisted.web.error.Error):
            http_code = int(reason.value.status) # note! "status" is returned as a string, not an integer!
            if http_code == 404 and (not self.error_on_404):
                # received a 404, but the client wants to treat it as success with buf = 'NOTFOUND'
                return self.on_response('NOTFOUND', getter, request)
            elif http_code == 204:
                # 204 is not actually an error, just an empty body
                return self.on_response('', getter, request)

        self.on_wire.remove(request)
        if request.tries < request.max_tries:
            # retry the request by putting it back on the queue
            self.waiting_for_retry.add(request)
            if self.retry_delay <= 0:
                self.retry(request)
            else:
                self.reactor.callLater(self.retry_delay, self.retry, request)
            return

        self.n_errors += 1

        if self.verbosity >= 0: # XXX maybe disable this if there's a reliable error_callback?
            self.log_exception_func('AsyncHTTPRequester error: ' + reason.getTraceback() + ' for %s (after %d tries)' % (repr(request), request.tries))

        if request.error_callback:
            try:
                # transform the Failure object to a human-readable string
                if (reason.type is twisted.web.error.Error):
                    # for HTTP errors, we want the status AND any explanatory response that came with it
                    # (since APIs like Facebook and S3 usually have useful info in the response body when returning errors)
                    ui_reason = 'twisted.web.error.Error(HTTP %s (%s): "%s")' % (reason.value.status, reason.value.message, reason.value.response)
                    body = reason.value.response
                else:
                    ui_reason = repr(reason.value)
                    body = None # things like TimeoutError have no .response attribute

                if request.callback_type == self.CALLBACK_FULL:
                    request.error_callback(ui_reason = ui_reason, body = body, headers = getter.response_headers,
                                           status = getattr(getter, 'status', '999')) # status may not be present on a failed request
                else:
                    request.error_callback(ui_reason)
            except:
                self.log_exception_func('AsyncHTTP Exception (error_callback): '+traceback.format_exc())

        self.idlecheck()

    # return JSON dictionary of usage statistics
    def get_stats(self, expose_info = True):
        queue = [x.get_stats() for x in self.queue] if expose_info else []
        on_wire = [x.get_stats() for x in self.on_wire] if expose_info else []
        waiting_for_retry = [x.get_stats() for x in self.waiting_for_retry] if expose_info else []
        return {'accepted':self.n_accepted,
                'dropped':self.n_dropped,

                'fired':self.n_fired,
                'retries':self.n_retries,

                'done_ok':self.n_ok,
                'done_error':self.n_errors,
                # all accepted requests should either be in flight, or end with OK/Error. Otherwise we're "leaking" requests.
                'missing': self.n_accepted - (self.n_ok + self.n_errors + len(self.queue) + len(self.on_wire)),

                'queue':queue, 'num_in_queue': len(self.queue),
                'on_wire':on_wire, 'num_on_wire': len(self.on_wire),
                'waiting_for_retry':waiting_for_retry, 'num_waiting_for_retry' : len(self.waiting_for_retry),
                }

    # merge together statistics from multiple AsyncHTTP instances (reduce)
    @staticmethod
    def merge_stats(statlist):
        ret = {}
        for stats in statlist:
            for key, val in stats.iteritems():
                if key in ('queue', 'on_wire', 'waiting_for_retry'):
                    ret[key] = ret.get(key,[]) + val
                else:
                    ret[key] = ret.get(key,0) + val
        return ret

    # convert JSON stats to HTML
    @staticmethod
    def stats_to_html(stats, cur_time, expose_info = True):
        ret = '<table border="1" cellspacing="0">'
        for key in ('accepted', 'dropped', 'fired', 'retries', 'done_ok', 'done_error', 'missing', 'num_on_wire','num_in_queue','num_waiting_for_retry'):
            val = str(stats[key])
            if key == 'missing' and stats[key] > 0:
                val = '<font color="#ff0000">'+val+'</font>'
            ret += '<tr><td>%s</td><td>%s</td></tr>' % (key, val)
        ret += '</table><p>'

        if expose_info:
            for key in ('queue', 'on_wire', 'waiting_for_retry'):
                ret += key+'<br>'
                ret += '<table border="1" cellspacing="1">'
                ret += '<tr><td>URL</td><td>AGE</td></tr>'
                for val in stats[key]:
                    url = val['method'] + ' ' + val['url']
                    age = '%.2f' % (cur_time - val['time'])
                    ret += '<tr><td>%s</td><td>%s</td></tr>' % (url, age)
                ret += '</table><p>'

        return ret

    def get_stats_html(self, cur_time, expose_info = True):
        return self.stats_to_html(self.get_stats(expose_info = expose_info), cur_time, expose_info = expose_info)


# TEST CODE

if __name__ == '__main__':
    import sys
    from twisted.python import log
    from twisted.internet import reactor

    log.startLogging(sys.stdout)
    req = AsyncHTTPRequester(2, 10, 10,1, lambda x: log.msg(x), max_tries = 3, retry_delay = 1.0)
    server_time = int(time.time())
    req.queue_request(server_time, 'http://localhost:8000/clientcode/Predicates.js', lambda x: log.msg('RESPONSE A'))
    req.queue_request(server_time, 'http://localhost:8000/clientcode/SPay.js', lambda x: log.msg('RESPONSE B'))
    req.queue_request(server_time, 'http://localhost:8005/', lambda x: log.msg('RESPONSE C'))
    req.queue_request(server_time, 'http://localhost:8000/', lambda x: log.msg('RESPONSE D'))
    print req.get_stats_html(time.time())
    reactor.run()

    print req.get_stats()
