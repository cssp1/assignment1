#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# "heartbeat" server latency checker

import AsyncHTTP
import SpinConfig
import SpinLog
import SpinNoSQL
import Daemonize
from twisted.python import log
from twisted.internet import reactor, task
import sys, os, time, traceback, signal, functools, getopt

pidfile = 'latency_probe.pid'
daemonize = True
interval = None
bg_task = None
exception_log = None
nosql_client = None
http_client = None


def reconfig():
    global interval
    try:
        SpinConfig.reload() # reload config.json file
        new_interval = SpinConfig.config.get('latency_probe_interval', 10)
        if new_interval != interval:
            if interval:
                bg_task.stop()
                bg_task.start(new_interval, now = False)
            interval = new_interval
    except:
        if exception_log:
            exception_log.event(int(time.time()), 'latency_probe SIGHUP Exception: ' + traceback.format_exc())
        else:
            raise

def handle_SIGHUP(signum, frm):
    reactor.callLater(0, reconfig)

reconfig() # init interval

requests = {}

def on_response(key, success, body):
    time_now = time.time()
    nosql_client.set_time(time_now)
    req = requests[key]
    if success:
        latency = time_now - req['start_time']
    else:
        latency = 0 # a value of exactly 0 means "error"
    nosql_client.server_latency_record(key, latency)
    del requests[key]

def bgtask_func():
    time_now = time.time()
    nosql_client.set_time(int(time_now))

    servers = []
    rows = nosql_client.server_status_query({}, fields = {'_id':1, 'type':1, 'hostname':1, 'game_http_port':1, 'external_http_port':1, 'server_time':1})
    for row in rows:
        key = row['server_name']
        if row['type'] == 'proxyserver':
            url = 'http://%s:%d/PING' % (row['hostname'], row['external_http_port'])
        elif row['type'] == SpinConfig.game():
            url = 'http://%s:%d/CONTROLAPI?secret=%s&method=ping' % (row['hostname'], row['game_http_port'], SpinConfig.config['proxy_api_secret'])
        else:
            continue
        servers.append((key,url))

    for key, url in servers:
        if key in requests:
            #print 'still running'
            continue

        requests[key] = {'start_time': time_now,
                         'request': http_client.queue_request(time_now, url,
                                                              functools.partial(on_response, key, True),
                                                              error_callback = functools.partial(on_response, key, False))} # standin parameter



def main():
    global http_client, nosql_client, bg_task, exception_log

    http_client = AsyncHTTP.AsyncHTTPRequester(-1, -1, int(0.8*interval), -1, lambda x: exception_log.event(int(time.time()), x) if daemonize else sys.stderr.write(x+'\n'), max_tries = 1)
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), max_retries = -1) # never give up

    #log.startLogging(sys.stdout)
    signal.signal(signal.SIGHUP, handle_SIGHUP)
    bg_task = task.LoopingCall(bgtask_func)

    if daemonize:
        Daemonize.daemonize()

        # update PID file with new PID
        open(pidfile, 'w').write('%d\n' % os.getpid())

        exception_log = SpinLog.DailyRawLog(SpinConfig.config.get('log_dir', 'logs')+'/', '-exceptions.txt')

        # turn on Twisted logging
        def log_exceptions(eventDict):
            if eventDict['isError']:
                if 'failure' in eventDict:
                    text = ((eventDict.get('why') or 'Unhandled Error')
                            + '\n' + eventDict['failure'].getTraceback().strip())
                else:
                    text = ' '.join([str(m) for m in eventDict['message']])
                exception_log.event(int(time.time()), text)
        def log_raw(eventDict): return

        log.startLoggingWithObserver(log_raw)
        log.addObserver(log_exceptions)

    bg_task.start(interval)
    reactor.run()

if __name__ == '__main__':
    if os.path.exists(pidfile):
        print 'latency_probe is already running (%s).' % pidfile
        sys.exit(1)

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'n', [])
    for key, val in opts:
        if key == '-n': daemonize = False

    # create PID file
    open(pidfile, 'w').write('%d\n' % os.getpid())
    try:
        main()
    finally:
        # remove PID file
        os.unlink(pidfile)
