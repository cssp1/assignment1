#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

from txpostgres import txpostgres, reconnection
from twisted.internet import reactor
import psycopg2.extras
import sys

class LoggingDetector(reconnection.DeadConnectionDetector):
    def __init__(self, parent):
        reconnection.DeadConnectionDetector.__init__(self)
        self.parent = parent
    def startReconnecting(self, f):
        self.parent.log_exception_func('AsyncPostgresDetector: database connection is down (error: %r)' % f.value)
        self.parent.okay = False
        return reconnection.DeadConnectionDetector.startReconnecting(self, f)
    def reconnect(self):
        self.parent.log_exception_func('AsyncPostgresDetector: reconnecting...')
        return reconnection.DeadConnectionDetector.reconnect(self)
    def connectionRecovered(self):
        self.parent.log_exception_func('AsyncPostgresDetector: reconnected.')
        self.parent.okay = True
        return reconnection.DeadConnectionDetector.connectionRecovered(self)
    def deathChecker(self, f):
        return reconnection.defaultDeathChecker(f)

def dict_connect(*args, **kwargs):
    kwargs['connection_factory'] = psycopg2.extras.DictConnection
    return psycopg2.connect(*args, **kwargs)

class DictConnection(txpostgres.Connection):
    connectionFactory = staticmethod(dict_connect)

class AsyncPostgres(object):
    def __init__(self, dbconfig, log_exception_func = None, verbosity = 0):
        self.dbconfig = dbconfig
        self.verbosity = verbosity
        if log_exception_func is None:
            log_exception_func = lambda x: sys.stderr.write(x+'\n')
        self.log_exception_func = log_exception_func
        self.okay = False
        self.con = DictConnection(detector = LoggingDetector(self))
        d = self.con.connect(*self.dbconfig['connect_args'], **self.dbconfig['connect_kwargs'])
        d.addErrback(self.con.detector.checkForDeadConnection)
        d.addErrback(self.connectionError)
        d.addCallback(self.connected)
    def connected(self, con):
        if self.verbosity >= 1:
            self.log_exception_func('AsyncPostgres: connected')
        self.okay = True
    def connectionError(self, f):
        if self.verbosity >= 0:
            self.log_exception_func('AsyncPostgres: connection error %r' % f.value)
        self.okay = False
    def runQuery(self, *args, **kwargs):
        if not self.okay:
            if self.verbosity >= 1:
                self.log_exception_func('AsyncPostgres: aborting query because connection is not okay')
            return None
        return self.con.runQuery(*args, **kwargs)

    # same API as the synchronous SQL/NoSQL drivers
    def _table(self, name):
        return self.dbconfig['table_prefix']+name
    def instrument(self, reason, func, args):
        return apply(func, args)

# TEST CODE

if __name__ == '__main__':
    import SpinConfig
    from twisted.python import log
    from twisted.internet import task

    cfg = SpinConfig.get_pgsql_config(SpinConfig.config['game_id']+'_scores2')

    log.startLogging(sys.stdout)
    req = AsyncPostgres(cfg, log_exception_func = lambda x: log.msg(x), verbosity = 2)

    def my_query(req):
        d = req.runQuery('select 1 as first, 2 as second;')
        if not d:
            print 'CLIENT abort'
            return

        def my_result(res):
            print 'CLIENT result', [row.items() for row in res] # res
        def my_error(f):
            print 'CLIENT error', f.value

        d.addCallbacks(my_result, my_error)

    task.LoopingCall(my_query, req).start(1)
    reactor.run()

