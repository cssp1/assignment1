#!/usr/bin/env python

# Async PostgreSQL battle history query interface
# makes use of tables loaded by battles_to_psql.py

import SpinSQLUtil

class SQLBattlesClient(object):
    def __init__(self, sql_client):
        self.sql_client = sql_client # AsyncPostgres instance
        self.util = SpinSQLUtil.PostgreSQLUtil()

    # async API
    BATTLES_ALL = 0
    BATTLES_AI_ONLY = 1
    BATTLES_HUMAN_ONLY = 2

    # XXXXXX time_range-based paging with limit means that some battles could be dropped (if several occur in the same second
    # and the limit gets hit part-way through). Might need GUID-based paging.
    def battles_get_async(self, player_id_A, player_id_B, time_range = None, ai_or_human = BATTLES_ALL, limit = -1, reason=''):
        return self.sql_client.instrument('battles_get_async(%s)'%reason, self._battles_get_async, (player_id_A, player_id_B, time_range, ai_or_human, limit))

    def _battles_get_async(self, player_id_A, player_id_B, time_range, ai_or_human, limit):
        tbl = self.sql_client._table('battles')
        where_conditions = []
        if player_id_A > 0:
            where_conditions.append('(involved_player0 = %d OR involved_player1 = %d)' % (player_id_A,player_id_A))
        if player_id_B > 0:
            where_conditions.append('(involved_player0 = %d OR involved_player1 = %d)' % (player_id_B,player_id_B))
        if ai_or_human == self.BATTLES_AI_ONLY:
            where_conditions.append('is_ai = TRUE')
        elif ai_or_human == self.BATTLES_HUMAN_ONLY:
            where_conditions.append('is_ai = FALSE')
        if time_range:
            where_conditions.append('time >= %d AND time < %d' % tuple(time_range))
        query = self.sql_client.runQuery('SELECT summary from '+self.util.sym(tbl)+' WHERE '+(' AND '.join(where_conditions))+\
                                         ' ORDER BY time DESC'+\
                                         ((' LIMIT %d' % limit) if limit > 0 else ''))
        if query:
            # extract raw list of summary columns
            query.addCallback(lambda result: [row['summary'] for row in result])
        return query

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
    client = SQLBattlesClient(req)

    def my_query(client):
        d = client.battles_get_async(1112, -1, limit = 1)
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
