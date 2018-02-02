#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# utilities for ETL (Extract/Transform/Load) scripts, usually going from MongoDB->SQL

import SpinNoSQL
import SpinNoSQLId
import SpinJSON
import SpinS3
import SpinConfig
import time
import tempfile
import subprocess
import hashlib

MAX_SESSION_LENGTH = 43200 # maximum conceivable session length, used to limit queries that are updated on logout

# return pairs of uniform (t0,t0+dt) intervals within the UNIX time range start->end, inclusive
def uniform_iterator(start, end, dt):
    return ((x,x+dt) for x in xrange(dt*(start//dt), dt*(end//dt + 1), dt))

# return pairs of (t0,t1) intervals for entire calendar months in the UNIX time range start->end, inclusive
def month_iterator(start, end, unused_dt):
    sy,sm,sd = SpinConfig.unix_to_cal(start) # starting year,month,day
    ey,em,ed = SpinConfig.unix_to_cal(end) # ending year,month,day
    while sy <= ey and ((sy < ey) or (sm <= em)):
        lasty = sy
        lastm = sm
        # compute next month
        sm += 1
        if sm > 12:
            sm = 1
            sy += 1

        yield (SpinConfig.cal_to_unix((lasty,lastm,1)), SpinConfig.cal_to_unix((sy,sm,1)))

# iterator for a MongoDB log_* table
def iterate_from_mongodb(game_id, table_name, start_time, end_time, query = None):
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))
    qs = {'time': {'$gt': start_time, '$lt': end_time}}
    if query:
        qs.update(query)

    for row in nosql_client.log_buffer_table(table_name).find(qs):
        row['_id'] = nosql_client.decode_object_id(row['_id'])
        yield row

# iterator for logs that are archived in Amazon S3
def iterate_from_s3(game_id, bucket, logname, start_time, end_time, verbose = True):
    assert start_time > 0

    # to protect against same-time collisions, create a unique fake "PID" for MongoDB row _ids
    sha = hashlib.sha1()
    sha.update(game_id)
    dig = sha.digest()
    fake_pid = (ord(dig[1]) << 8) | ord(dig[0])

    s3 = SpinS3.S3(SpinConfig.aws_key_file())
    last_id_time = -1
    id_serial = 0

    for t in xrange(86400*(start_time//86400), 86400*(end_time//86400), 86400): # for each day
        y, m, d = SpinConfig.unix_to_cal(t)
        prefix = '%04d%02d/%s-%04d%02d%02d-%s' % (y, m, SpinConfig.game_id_long(override_game_id=game_id), y,m,d, logname)

        for entry in s3.list_bucket(bucket, prefix=prefix):
            filename = entry['name'].split('/')[-1]
            if verbose: print 'reading', filename

            if entry['name'].endswith('.zip'):
                tf = tempfile.NamedTemporaryFile(prefix=logname+'-'+filename, suffix='.zip')
                s3.get_file(bucket, entry['name'], tf.name)
                unzipper = subprocess.Popen(['unzip', '-q', '-p', tf.name],
                                            stdout = subprocess.PIPE)
            elif entry['name'].endswith('.gz'):
                tf = tempfile.NamedTemporaryFile(prefix=logname+'-'+filename, suffix='.gz')
                s3.get_file(bucket, entry['name'], tf.name)
                unzipper = subprocess.Popen(['gunzip', '-c', tf.name],
                                            stdout = subprocess.PIPE)
            else:
                raise Exception('unhandled file extension: '+entry['name'])

            for line in unzipper.stdout.xreadlines():
                try:
                    row = SpinJSON.loads(line)
                except ValueError:
                    raise Exception('bad JSON: %r' % line)
                if row['time'] <= start_time: continue # skip ahead (note: do not include start_time - same as iterate_from_mongodb)
                elif row['time'] >= end_time: break

                if '_id' not in row:
                    # synthesize a fake MongoDB row ID
                    if row['time'] != last_id_time:
                        last_id_time = row['time']
                        id_serial = 0
                    row['_id'] = SpinNoSQLId.creation_time_id(row['time'], pid = fake_pid, serial = id_serial)
                    assert SpinNoSQLId.is_valid(row['_id'])
                    id_serial += 1

                # note: there's a small chance this could end up duplicating an event at the boundary of an S3 import and MongoDB import
                if verbose: print row
                yield row

# extract standard summary dimensions from raw playerdb/userdb JSON
def get_denormalized_summary_props(gamedata, player, user, format):
    assert format == 'brief'
    ret = {'plat': user.get('frame_platform','fb'),
           'cc': player['history'].get(gamedata['townhall']+'_level', 1),
           'rcpt': player['history'].get('money_spent', 0),
           'country': user.get('country','unknown'),
           'tier': SpinConfig.country_tier_map.get(user.get('country','unknown'), 4)}
    if user.get('developer', False): ret['developer'] = 1
    return ret

# update an interval-based summary table
# sql_util: pass in the instance of SpinSQLUtil.SQLUtil you're using
# con: the database connection
# cur: the database cursor
# table: the unquoted name of the summary table to update
# affected: a set of the start times of intervals that have changed since the last update
# source_range: the time range covered by the complete set of input data events
# interval: a string name for the interval column ("day", "hour", etc)
# dt: the time offset between successive intervals, in seconds. Use 0 when using month_iterator
# origin: "zero point" of time intervals (should be 0 except for weekly summaries that use gamedata['matchmaking']['week_origin'])
# execute_func: called to actually fill in the summary data
# iterator: time iteration function. Can be uniform_iterator or month_iterator.
# resummarize_tail: Unconditionally resummarize final entries within this many seconds of the "tail" of the existing summary,
#                   even if it they are not mentioned in the "affected" set.
#  * note: by default this function assumes that any existing summary data is fully valid
#  if there is a chance for new data available this run to need to change existing summary
#  entries (like the very last day of the summary, which might reflect less than a day's worth of events),
#  then "resummarize_tail" must be set appropriately

def update_summary(sql_util, con, cur, table, affected, source_range, interval, dt,
                   origin = 0, verbose = True, dry_run = False, execute_func = None, iterator = uniform_iterator,
                   resummarize_tail = 0):

    # check how much summary data we already have
    cur.execute("SELECT MIN("+sql_util.sym(interval)+") AS begin, MAX("+sql_util.sym(interval)+") AS end FROM "+sql_util.sym(table))
    rows = cur.fetchall()
    if rows and rows[0] and rows[0]['begin'] and rows[0]['end']:
        # we already have summary data - update it incrementally

        # convert "affected" from a list of start times to a list of start,end times for each interval
        affected = set(map(lambda xy: (xy[0]+origin,xy[1]+origin), (next(iterator(x, x+dt, dt)) for x in affected)))

        if source_range: # fill in any missing trailing summary data
            # skip dt past final row, unless we want to resummarize the last interval(s)
            source_days = sorted(affected.union(map(lambda xy: (xy[0]+origin, xy[1]+origin), iterator(rows[0]['end'] - origin + dt - resummarize_tail, source_range[1] - origin, dt))))
        else:
            source_days = sorted(list(affected))
    else:
        # recreate entire summary
        if source_range:
            source_days = map(lambda xy: (xy[0]+origin, xy[1]+origin), iterator(source_range[0]-origin, source_range[1]-origin, dt))
        else:
            source_days = None

    if source_days:
        for day_start, day_end in source_days:
            dt = day_end - day_start
            if verbose:
                time_fmt = '%Y%m%d %H:%M:%S'
                print 'updating', table, 'at', day_start, time.strftime(time_fmt, time.gmtime(day_start)), '-', time.strftime(time_fmt, time.gmtime(day_end)), 'dt', dt
            if (not dry_run):
                # delete entries for the date range we're about to update
                cur.execute("DELETE FROM "+sql_util.sym(table)+" WHERE "+sql_util.sym(interval)+" >= %s AND "+sql_util.sym(interval)+" < %s+%s", [day_start,day_start,dt])
                execute_func(cur, table, interval, day_start, dt)
                con.commit() # one commit per day
    else:
        if verbose: print 'no change to', table
