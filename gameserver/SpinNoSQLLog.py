#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinNoSQL
import SpinLog

class NoSQLLogBase(SpinLog.Log):
    def __init__(self, nosql_client, table_name, safe = False):
        SpinLog.Log.__init__(self)
        self.nosql_client = nosql_client
        self.table_name = table_name
        self.safe = safe
    # note: we do not "own" the nosql_client connection, so do not close it
    def close(self): SpinLog.Log.close(self)

class NoSQLJSONLog(NoSQLLogBase):
    def event(self, t, props, reason = ''):
        assert type(t) in (int, float)
        self.nosql_client.log_record(self.table_name, t, props, safe = self.safe, reason = reason)

class NoSQLRawLog(NoSQLLogBase):
    def event(self, t, text, reason = ''):
        assert type(t) in (int, float)
        self.nosql_client.log_record(self.table_name, t, {'text':unicode(text)}, safe = self.safe, reason = reason)

if __name__ == '__main__':
    import SpinConfig
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), identity = 'test')
    mylog = NoSQLJSONLog(nosql_client, 'log_fb_conversion_pixels')
    mylog.event(1389328096, {"user_id":1112,"event_name":"7510_adnetwork_event_sent","code":7510,"api":"fb_conversion_pixels","context":"1234","kpi":"ftd"})
    myraw = NoSQLRawLog(nosql_client, 'log_fbrtapi')
    myraw.event(1389328096, 'hello 1 2 3')
