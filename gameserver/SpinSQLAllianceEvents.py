#!/usr/bin/env python

# Async PostgreSQL alliance event query interface
# makes use of tables loaded by alliance_events_to_psql.py

# note: Postgres sometimes pessimizes the "get_async" query
# by doing a full index scan on "time" instead of using the player_id/time indexes.
# To fix this, "SET random_page_cost TO 1;"
# or to make default for entire database, as root:
# "ALTER DATABASE ... SET random_page_cost TO 1;"

# (this lowers random_page_cost to the same value as seq_page_cost, telling Postgres
# that it's probably OK to use the sparser player_id/time index).

import SpinSQLUtil

class SQLAllianceEventsClient(object):
    def __init__(self, sql_client):
        self.sql_client = sql_client # AsyncPostgres instance
        self.util = SpinSQLUtil.PostgreSQLUtil()

    def player_alliance_membership_history_get_async(self, player_id, time_range = None, limit = -1, reason=''):
        return self.sql_client.instrument('player_alliance_membership_history_get_async(%s)'%reason, self._player_alliance_membership_history_get_async, (player_id, time_range, limit))

    def _player_alliance_membership_history_get_async(self, player_id, time_range, limit):
        tbl = self.sql_client._table('log_alliance_members')
        where_conditions = []
        where_conditions.append("((event_name IN ('4610_alliance_member_joined','4620_alliance_member_left') AND user_id = %d) OR (event_name IN ('4625_alliance_member_kicked','4626_alliance_member_promoted','4650_alliance_member_join_request_accepted') AND target_id = %d))" % (player_id,player_id))

        if time_range:
            where_conditions.append('(time >= %d AND time < %d)' % tuple(time_range))

        query = self.sql_client.runQuery('SELECT _id, time, event_name, user_id, target_id, alliance_id, role, alliance_ui_name, alliance_chat_tag from '+self.util.sym(tbl)+' WHERE '+(' AND '.join(where_conditions))+\
                                         ' ORDER BY time DESC'+\
                                         ((' LIMIT %d' % limit) if limit > 0 else ''))

        # extract raw list of summary columns
        query.addCallback(lambda result, self=self: [self.decode_event(row) for row in result])
        return query

    def decode_event(self, row):
        return dict(row)

# TEST CODE

if __name__ == '__main__':
    import sys
    from twisted.python import log
    from twisted.internet import task, reactor
    import SpinConfig
    import AsyncPostgres
    log.startLogging(sys.stdout)
    req = AsyncPostgres.AsyncPostgres(SpinConfig.get_pgsql_config(SpinConfig.config['game_id']+'_battles'),
                                      log_exception_func = lambda x: log.msg(x), verbosity = 2)
    client = SQLAllianceEventsClient(req)

    def my_query(client):
        d = client.player_alliance_membership_history_get_async(1112)
        if d is None:
            print 'CLIENT abort'
            return
        def my_success(result):
            for row in result:
                print 'ROW', row
        def my_error(f):
            print 'CLIENT error', f.value
        d.addCallbacks(my_success, my_error)

    task.LoopingCall(my_query, client).start(2)
    reactor.run()
