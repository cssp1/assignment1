#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# query recent logs for DAU, receipts, and tutorial completion rate

import SpinConfig
import SpinNoSQL
import sys, time, getopt

time_now = int(time.time())

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:yt', ['yesterday','date=','trailing'])
    time_offset = 0
    trailing = False
    game_id = SpinConfig.config['game_id']
    for key, val in opts:
        if key == '--yesterday' or key == '-y': time_offset = -86400
        elif key == '--date':
            time_offset = SpinConfig.cal_to_unix((int(val[0:4]),int(val[4:6]),int(val[6:8]))) - time_now
        elif key == '-g': game_id = val
        elif key == '--trailing' or key == '-t': trailing = True

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    day_start = 86400*((time_now+time_offset)//86400)

    if trailing:
        dau = 0
        time_range = [time_now-86400, time_now]
    else:
        dau = nosql_client.dau_get(time_now + time_offset)
        time_range = [day_start, day_start + 86400]

    credits_tbl = nosql_client._table('log_credits')
    receipts_result = credits_tbl.aggregate([{'$match':{'code':1000,'time':{'$gte':time_range[0],'$lt':time_range[1]},
                                                        'summary.developer':{'$exists':False}
                                                        }},
                                             {'$group':{'_id':1,'total':{'$sum':'$Billing Amount'}}}])['result']
    receipts = receipts_result[0]['total'] if receipts_result else 0
    refunds_result = credits_tbl.aggregate([{'$match':{'code':1310,'time':{'$gte':time_range[0],'$lt':time_range[1]},
                                                       'summary.developer':{'$exists':False}
                                                       }},
                                            {'$group':{'_id':1,'total':{'$sum':'$Billing Amount'}}}])['result']
    refunds = refunds_result[0]['total'] if refunds_result else 0
    net_receipts = receipts - refunds

    metrics_tbl = nosql_client._table('log_metrics')
    tutorial_starts = metrics_tbl.find({'code':140,'time':{'$gte':time_range[0],'$lt':time_range[1]}}).count()
    tutorial_completes = 1.0*metrics_tbl.find({'code':399,'time':{'$gte':time_range[0],'$lt':time_range[1]}}).count()
    tutorial_completion = tutorial_completes/tutorial_starts if tutorial_starts > 0 else 0

    if trailing:
        prefix = 'TRAILING 24h '
    elif time_now - day_start < 86400:
        expand_by = 86400.0/(time_now - day_start)
        dau *= expand_by
        net_receipts *= expand_by
        prefix = 'PROJECTED 24h '
    else:
        prefix = ''

    print prefix + ('DAU %d ' % int(dau) if dau>0 else '') + 'Rct $%d Tut %d%%' % (int(net_receipts), int(100.0*tutorial_completion))
