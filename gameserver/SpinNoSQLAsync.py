#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# MongoDB adaptor API, asynchronous version using txmongo
# INCOMPLETE, TEST CODE

import SpinConfig
from twisted.internet import reactor, defer
import txmongo
import pymongo.errors
import time

# adjust some connection parameters by monkey-patching
txmongo.connection._Connection.initialDelay = 2 # Delay for the first reconnection attempt
txmongo.connection._Connection.maxDelay = 2 # Maximum number of seconds between connection attempts

class NoSQLAsyncClient (object):
    def __init__(self, dbconfig, identity = 'unknown', log_exception_func = None, max_retries = 10):
        self.dbconfig = dbconfig
        self.log_exception_func = log_exception_func
        self.in_log_exception_func = False # flag to protect against infinite recursion
        self.ident = identity
        self.max_retries = max_retries
        self.service = None
        self.db = None

    def log_exception(self, msg):
        try:
            # protect against infinite recursion - since exception logs now also go through MongoDB!
            self.in_log_exception_func = True
            self.log_exception_func('SpinNoSQLAsync(%s): %s' % (self.ident, msg))
        finally:
            self.in_log_exception_func = False

    @defer.inlineCallbacks
    def connect(self):
        self.service = txmongo.MongoConnectionPool(host=self.dbconfig['host'], port=self.dbconfig['port'], pool_size=4)
        # XXXXXX use delegate system

        self.db = self.service[self.dbconfig['dbname']]
        # this is the first thing that actually blocks
        auth_result = yield self.db.authenticate(self.dbconfig['username'], self.dbconfig['password'])
        assert self.dbconfig['dbname'] in self.service.cred_cache # make sure it worked
        defer.returnValue(auth_result)

    def shutdown(self): # returns a deferred that fires when shutdown is complete
        return self.service.disconnect()

    def table(self, name):
        return self.db[self.dbconfig['table_prefix']+name]

    def instrument(self, name, func, args, kwargs = {}):
        attempt = 0
        last_exc = None

        while True:
            try:
                ret = func(*args, **kwargs)
                if attempt > 0 and (not self.in_log_exception_func): self.log_exception('recovered from exception.')
                break
            except pymongo.errors.AutoReconnect as e: # on line 95
                # attempt to reconnect and try a second time
                if self.in_log_exception_func: return None # fail silently
                self.log_exception('AutoReconnect exception, retrying...')
                last_exc = e
                time.sleep(1)
            except pymongo.errors.ConnectionFailure as e:
                if self.in_log_exception_func: return None # fail silently
                self.log_exception('ConnectionFailure exception, retrying...')
                last_exc = e
                time.sleep(10)
            except:
                raise

            attempt += 1
            if self.max_retries >= 0 and attempt >= self.max_retries:
                raise Exception('too many MongoDB connection errors, last one was: %s' % repr(last_exc)) # give up

        return ret

    def query(self, table_name):
        tab = self.table(table_name)
        return tab.find_one({})

if __name__ == '__main__':
    import getopt, sys

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['game-id='])
    game_instance = SpinConfig.config['game_id']

    for key, val in opts:
        if key == '-g' or key == '--game-id':
            game_instance = val

    game_id = game_instance[:-4] if game_instance.endswith('test') else game_instance

    client = NoSQLAsyncClient(SpinConfig.get_mongodb_config(game_instance))
    d = client.connect()
    d.addCallback(lambda _: client.query('player_cache'))
    d.addCallback(lambda res: sys.stdout.write('result %r\n' % res))
    d.addCallback(lambda _: client.shutdown())
    d.addCallback(lambda _: reactor.stop())

    reactor.run()
    print 'OK!'
