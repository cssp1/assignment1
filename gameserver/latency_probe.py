#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# "heartbeat" server latency checker

import AsyncHTTP
import AsyncPostgres
import SpinConfig
import SpinLog
import SpinNoSQL
import Daemonize
from twisted.python import log
from twisted.internet import reactor, task
import sys, os, time, traceback, signal, getopt

pidfile = 'latency_probe.pid'
daemonize = True
verbose = 0
enable_postgres = False
interval = None
bg_task = None
exception_log = None
nosql_client = None
postgres_clients = {}
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

def on_response(_, key, success):
    time_now = time.time()
    nosql_client.set_time(time_now)
    req = requests[key]
    if success:
        latency = time_now - req['start_time']
    else:
        latency = 0 # a value of exactly 0 means "error"
    if verbose:
        if success:
            print '%s latency %.2f ms' % (key, latency*1000.0)
        else:
            print '%s ERROR' % (key,)
    nosql_client.server_latency_record(key, latency)
    del requests[key]

def bgtask_func():
    time_now = time.time()
    nosql_client.set_time(int(time_now))

    servers = []
    rows = nosql_client.server_status_query({'state':{'$ne':'shutting_down'}}, fields = {'_id':1, 'type':1, 'hostname':1, 'internal_listen_host':1,
                                                                                         'game_http_port':1, 'external_http_port':1, 'server_time':1})
    for row in rows:
        key = row['server_name']
        if row['type'] == 'proxyserver':
            url = 'http://%s:%d/PING' % (row.get('internal_listen_host', row['hostname']), row['external_http_port'])
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
                                                              lambda body, key=key: on_response(body, key, True),
                                                              error_callback = lambda reason, key=key: on_response(None, key, False))}

    for key, postgres_client in postgres_clients.iteritems():
        if key in requests:
            if verbose:
                log_exception_func('skipping postgres query since previous request is still in flight: %s' % key)
            continue
        d = postgres_client.runQuery('SELECT 1; -- latency_probe.py')
        requests[key] = {'start_time': time_now,
                         'request': d}
        d.addCallbacks(callback = on_response, errback = on_response,
                       callbackArgs = [key, True], errbackArgs = [key, False])

def log_exception_func(msg):
    if daemonize:
        exception_log.event(int(time.time()), 'latency_probe.py: %s' % msg)
    else:
        sys.stderr.write(msg+'\n')

def main():
    global http_client, nosql_client, postgres_clients, bg_task, exception_log

    http_client = AsyncHTTP.AsyncHTTPRequester(-1, -1, int(0.8*interval), -1, log_exception_func, max_tries = 1)
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), max_retries = -1) # never give up

    if enable_postgres and 'pgsql_servers' in SpinConfig.config:
        for name in SpinConfig.config['pgsql_servers']:
            cfg = SpinConfig.get_pgsql_config(name)
            # de-dupe identical configs
            key = 'pgsql:%s:%d' % (cfg['host'], cfg['port'])
            if key not in postgres_clients:
                postgres_clients[key] = AsyncPostgres.AsyncPostgres(cfg, log_exception_func = log_exception_func,
                                                                    verbosity = verbose)

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

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'nv', ['enable-postgres'])
    for key, val in opts:
        if key == '-n': daemonize = False
        elif key == '-v': verbose += 1
        elif key == '--enable-postgres': enable_postgres = True

    # create PID file
    open(pidfile, 'w').write('%d\n' % os.getpid())
    try:
        main()
    finally:
        # remove PID file
        os.unlink(pidfile)
