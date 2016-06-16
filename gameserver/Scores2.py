#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# next-generation player leaderboard score system
# playerdb state (S3 and live in server memory) contains latest counter values,
# for checking for mutations (minimizing DB writes) and as a safety backup.
#
# live game database (mongodb) contains latest and next-latest counter values
#
# "data warehouse" (postgres?) contains next-latest and all previous values

# {'stat': 'damage_done', 'axes': {'time': ['season',3], 'space': ['region','kasei101']}, 'val': 12345}
# {'stat': 'best_time', 'axes': {'time': ['season',3], 'space': ['region','kasei101'], 'challenge': ['ai', '321']}, 'val': 12345}

# terminology: "axis" means a [scope,value] pair like ['season',3] or ['region','kasei101']

import math

KINDS = ('player', 'alliance')
ID_FIELD = {'player': 'user_id', 'alliance': 'alliance_id'} # primary key field

FORMAT_VERSION = 1 # version number for playerdb serialization format

FREQ_ALL = 'ALL'
FREQ_SEASON = 'season'
FREQ_WEEK = 'week'
FREQ_DAY = 'day'
FREQ_VALUES = (FREQ_ALL, FREQ_SEASON, FREQ_WEEK, FREQ_DAY)

SPACE_ALL = 'ALL'
SPACE_CONTINENT = 'continent'
SPACE_REGION = 'region'
SPACE_VALUES = (SPACE_ALL, SPACE_CONTINENT, SPACE_REGION)
SPACE_ALL_LOC = '0' # default "location" for SPACE_ALL scope (string because space_locs are always strings)

# PUBLIC API

# return all time-axis coordinates for current moment in time
def make_time_coords(ts, cur_season, cur_week, cur_day, use_day = False):
    ret = {FREQ_ALL: 0,
           FREQ_SEASON: int(cur_season),
           FREQ_WEEK: int(cur_week)}
    if use_day:
        ret[FREQ_DAY] = int(cur_day)
    return ret

# return all space-axis coordinates for current location
def make_space_coords(continent, region):
    ret = {SPACE_ALL: SPACE_ALL_LOC}
    if continent is not None:
        assert type(continent) in (str, unicode)
        ret[SPACE_CONTINENT] = continent
    if region is not None:
        assert type(region) in (str, unicode)
        ret[SPACE_REGION] = region
    return ret

def make_point(time_scope, time_loc, space_scope, space_loc, extra_axes = None):
    # sanity checks
    assert type(space_loc) in (str, unicode)
    if space_scope == SPACE_ALL: assert space_loc == SPACE_ALL_LOC

    ret = {'time': [time_scope, time_loc],
           'space': [space_scope, space_loc]}
    if extra_axes:
        for name, scope_loc in extra_axes.iteritems():
            ret[name] = [scope_loc[0], scope_loc[1]]
    return ret

# this is part of the live playerdb (S3/gameserver) state
class CurScores(object):
    def __init__(self, data = None):
        self._load(data)
        self.dirty_clear()

    # don't use itervalues() - bool(iter) should be false if empty
    def all_iter(self): return self.scores.values()
    def dirty_iter(self):
        return self.dirty.values()
    def dirty_alliance_iter(self):
        return self.dirty_alliance.values()

    def dirty_clear(self):
        self.dirty = {}
        self.dirty_alliance = {}

    def _key(self, stat, axes):
        ret = stat
        for name, scope_loc in sorted(axes.items()):
            ret += '_%s-%s' % (scope_loc[0], str(scope_loc[1]))
        return ret

    def clear(self): self._load(None)
    def _load(self, data):
        self.scores = {}
        if data:
            assert data['version'] == FORMAT_VERSION
            for item in data['items']:
                k = self._key(item['stat'], item['axes'])
                self.scores[k] = item

    def serialize(self): return {'version': FORMAT_VERSION, 'items': self.scores.values()}
    def unserialize(self, data): self._load(data)

    def prune(self, time_coords):
        for k, item in self.scores.items():
            time_scope, time_loc = item['axes']['time']
            if time_scope in time_coords and time_loc < time_coords[time_scope] - 1:
                del self.scores[k]

    # PUBLIC API

    def get(self, stat, axes):
        k = self._key(stat, axes)
        if k in self.scores:
            return self.scores[k]['val']
        return None

    def set(self, stat, val, time_coords, space_coords, extra_axes = None, **kwargs):
        any_changed = False
        for time_scope, time_loc in time_coords.iteritems():
            assert time_scope in FREQ_VALUES and time_loc >= 0
            for space_scope, space_loc in space_coords.iteritems():
                assert space_scope in SPACE_VALUES
                axes = make_point(time_scope, time_loc, space_scope, space_loc, extra_axes)
                if self.set_point(stat, val, axes, **kwargs) is not None:
                    any_changed = True
        return any_changed

    def set_point(self, stat, val, axes, method = '+=', floor = None, decay_kt = 0, affects_alliance = False):
        k = self._key(stat, axes)

        if k in self.scores:
            # update previously recorded score
            item = self.scores[k]
            if method == '+=':
                newval = item['val'] + val
            elif method == '=':
                newval = val
            elif method == 'max':
                newval = max(item['val'], val)
            elif method == 'min':
                newval = min(item['val'], val)
            elif method == 'decay':
                newval = int((floor or 0) + (item['val'] - (floor or 0)) * math.exp(decay_kt) + 0.5)
            else:
                raise Exception('unknown method "%s"' % method)

            if floor is not None:
                newval = max(newval, floor)

            if item['val'] != newval: # only update if different
                item['val'] = newval
                self.dirty[k] = item # mark dirty (only if different)
                if affects_alliance: self.dirty_alliance[k] = item
            return newval

        else:
            # not previously recorded
            if floor is not None:
                val = max(val, floor)

            if val != 0 or method == '=': # only update if nonzero or manually set
                item = self.scores[k] = {'stat':stat, 'axes':axes, 'val': val}
                self.dirty[k] = item # mark dirty (always)
                if affects_alliance: self.dirty_alliance[k] = item
                return val

            return None # special return value meaning "no change was recorded"

# MongoDB interface, built on top of SpinNoSQL.NoSQLClient

import pymongo # 3.0+ OK
import re

class MongoScores2(object):
    def __init__(self, nosql_client):
        self.nosql_client = nosql_client
        self.seen_tables = set()

    # score storage in MongoDB:
    # time coordinates are stored in separate collections (for easy dropping of old data)
    # stat name, space, and extra coordinates are "baked" into a "key" string
    def _scores2_table(self, kind, stat, axes):
        assert kind in KINDS
        freq, period = axes['time']
        assert freq in FREQ_VALUES
        name = '%s_scores2_%s_%s' % (kind, freq, str(period))
        tbl = self.nosql_client._table(name)
        if name not in self.seen_tables:
            # necessary for correctness (unique scores per user/board), and per-user lookups
            tbl.create_index([(ID_FIELD[kind],1),('key',1)], unique=True)
            # used for the "Top 10" query
            tbl.create_index([('key',1),('val',-1)])
            self.seen_tables.add(name)
        return tbl.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0))

    def _scores2_key(self, stat, axes):
        ret = stat
        for name, scope_loc in sorted(axes.items()):
            if name == 'time': continue
            if name == 'space': assert scope_loc[0] in SPACE_VALUES
            ret += '_%s-%s' % (scope_loc[0], str(scope_loc[1]))
        return ret

    # API FOR SQL DUMPING

    # for a given time axis scope, return the min and max time axis locations stored
    def _scores2_get_time_range(self, kind, freq):
        assert kind in KINDS
        assert freq in FREQ_VALUES
        ret = [-1,-1]
        slave = self.nosql_client.slave_for_table(kind+'_scores2_%s_0' % freq)
        table_re = re.compile('^'+kind+'_scores2_%s_([0-9]+)$' % freq)
        for name in list(slave.table_names()):
            match = table_re.match(name)
            if match:
                loc = int(match.groups()[0])
                if ret[0] < 0 or loc < ret[0]: ret[0] = loc
                if ret[1] < 0 or loc > ret[1]: ret[1] = loc
        return ret
    def _scores2_get_stats_for_time(self, kind, freq, period, mtime_gte = -1):
        assert kind in KINDS
        assert freq in FREQ_VALUES
        tbl = self._scores2_table(kind, '', {'time':[freq, period]})
        return tbl.find({'mtime':{'$gte':mtime_gte}}, {'_id':0, ID_FIELD[kind]:1, 'stat':1, 'axes':1, 'val':1, 'mtime':1})

    def _scores2_drop_stats_for_time(self, kind, freq, period):
        assert kind in KINDS
        assert freq in FREQ_VALUES
        self._scores2_table(kind, '', {'time':[freq, period]}).drop()

    # PUBLIC API

    # record scores
    # where item_iter is in the same format as CurScores.scores above
    def player_scores2_write(self, user_id, item_iter, reason=''): return self.nosql_client.instrument('player_scores2_write(%s)'%reason, self._scores2_write, ('player', user_id, item_iter, '='))
    def alliance_scores2_write(self, alliance_id, item_iter, method, reason=''): return self.nosql_client.instrument('alliance_scores2_write(%s)'%reason, self._scores2_write, ('alliance', alliance_id, item_iter, method))
    def _scores2_write(self, kind, id, item_iter, method): # where item_iter is in the same format as CurScores.scores above
        for item in item_iter:
            key = self._scores2_key(item['stat'], item['axes'])
            qs = {'_id': '%s_' % str(id) + key, 'key': key, 'stat':item['stat'],
                  ID_FIELD[kind]: id, 'axes': item['axes']}
            tbl = self._scores2_table(kind, item['stat'], item['axes'])
            if method == '=': # overwrite
                qs['val'] = item['val']
                qs['mtime'] = self.nosql_client.time
                tbl.replace_one({'_id':qs['_id']}, qs, upsert=True)
            elif method == '+=': # incr
                tbl.update_one(qs, {'$set': {'mtime': self.nosql_client.time}, '$inc': {'val': item['val']}}, upsert=True)
            else:
                raise Exception('unknown method '+method)

    def alliance_scores2_update_weighted(self, alliance_id, item_iter, weights, offset, reason = ''):
        return self.nosql_client.instrument('alliance_score2_update_weighted(%s)'%reason, self._alliance_scores2_update_weighted, (alliance_id, item_iter, weights, offset))
    def _alliance_scores2_update_weighted(self, alliance_id, item_iter, weights, offset):
        member_ids = self.nosql_client.get_alliance_member_ids(alliance_id)
        if len(member_ids) <= 0: return True
        for item in item_iter:
            key = self._scores2_key(item['stat'], item['axes'])
            player_scores = list(self._scores2_table('player', item['stat'], item['axes']).find({'key':key, ID_FIELD['player']: {'$in': member_ids}}, {'_id':0, ID_FIELD['player']:1, 'val':1}))

            score_map = {}
            for row in player_scores:
                score_map[row[ID_FIELD['player']]] = row['val']
            member_ids.sort(key = lambda id: -score_map.get(id,0))

            total = 0.0
            for i in xrange(min(len(member_ids), len(weights))):
                sc = score_map.get(member_ids[i],0)
                total += weights[i] * (sc + offset.get(item['stat'],0))
            total = int(total)

            tbl = self._scores2_table('alliance', item['stat'], item['axes'])
            if total == 0:
                # if new score is zero, update any existing score but do not insert a zero score if none is already recorded
                # we use _id, key, stat, and ID_FIELD to find the existing row uniquely
                tbl.update_one({'_id': '%s_%s' % (str(alliance_id), key), 'key':key, 'stat':item['stat'], ID_FIELD['alliance']: alliance_id,
                                # note: don't bother matching on "axes" because that is already uniquely determined by the (tbl,key) combination (and would complicate the query syntax)
                                }, {'$set': {'val': total, 'mtime': self.nosql_client.time}}, upsert=False)
            else:
                # unconditionally write nonzero scores
                tbl.replace_one({'_id': '%s_%s' % (str(alliance_id), key)},
                                {'_id': '%s_%s' % (str(alliance_id), key), 'key':key, 'stat':item['stat'],
                                 ID_FIELD['alliance']: alliance_id, 'axes': item['axes'], 'val': total, 'mtime': self.nosql_client.time}, upsert=True)
        return True

    # get "Top N" scorers for a batch of (stat,axes) combinations
    def player_scores2_get_leaders(self, stat_axes_list, num, start=0, reason=''): return self.nosql_client.instrument('player_scores2_get_leaders(%s)'%reason, self._scores2_get_leaders, ('player',stat_axes_list, num, start))
    def alliance_scores2_get_leaders(self, stat_axes_list, num, start=0, reason=''): return self.nosql_client.instrument('alliance_scores2_get_leaders(%s)'%reason, self._scores2_get_leaders, ('alliance',stat_axes_list, num, start))
    def _scores2_get_leaders(self, kind, stat_axes_list, num, start):
        ret = []
        for stat, axes in stat_axes_list:
            key = self._scores2_key(stat, axes)
            tbl = self._scores2_table(kind, stat, axes)
            rows = list(tbl.find({'key':key}, {'_id':0, ID_FIELD[kind]:1, 'val':1}).sort([('val',-1)]).skip(start).limit(num))
            ret.append([{ID_FIELD[kind]: rows[i][ID_FIELD[kind]], 'absolute': rows[i]['val'], 'rank':start+i} for i in xrange(len(rows))])
        return ret

    # get current scores and optionally ranks for a batch of (stat,axes) combinations
    def player_scores2_get(self, player_ids, stat_axes_list, rank=False, reason=''): return self.nosql_client.instrument('player_scores2_get' + '+RANK' if rank else '' + '(%s)'%reason, self._scores2_get, ('player', player_ids, stat_axes_list, rank))
    def alliance_scores2_get(self, alliance_ids, stat_axes_list, rank=False, reason=''): return self.nosql_client.instrument('alliance_scores2_get' + '+RANK' if rank else '' + '(%s)'%reason, self._scores2_get, ('alliance', alliance_ids, stat_axes_list, rank))
    def _scores2_get(self, kind, id_list, stat_axes_list, rank):
        ret = [[None,]*len(stat_axes_list) for u in xrange(len(id_list))]
        need_totals = {}

#        start_time = time.time()

        for i in xrange(len(stat_axes_list)):
            stat, axes = stat_axes_list[i]
            key = self._scores2_key(stat, axes)
            scores = list(self._scores2_table(kind, stat, axes).find({'key':key, ID_FIELD[kind]: {'$in': id_list}},
                                                                     {'_id':0, ID_FIELD[kind]:1, 'val':1}))
            for score in scores:
                u = id_list.index(score[ID_FIELD[kind]])
                ret[u][i] = {'absolute': score['val']}
                if rank and score['val'] > 0:
                    need_totals[key] = True

#        end_time = time.time(); print "A %.2fms" % (1000.0*(end_time-start_time)); start_time = end_time

        if rank: # find number of players above you, and percentile
            n_totals = {}

            for stat, axes in stat_axes_list:
                key = self._scores2_key(stat, axes)
                if need_totals.get(key, False):
                    # this is actually the slowest part of the query - getting the total number of scores for this stat,axes
                    n_totals[key] = self._scores2_table(kind, stat, axes).find({'key':key},{'_id':0}).count()

#            end_time = time.time(); print "B %d of %d %.2fms" % (len(n_totals), len(addrs), 1000.0*(end_time-start_time)); start_time = end_time

            for u in xrange(len(id_list)):
                for i in xrange(len(stat_axes_list)):
                    if ret[u][i]:
                        stat, axes = stat_axes_list[i]
                        if ret[u][i]['absolute'] <= 0:
                            # if absolute score is zero, don't bother querying
                            total = 1000000 # use a fictional total so that the rank is like #999,999
                            ret[u][i]['rank'] = max(total-1, 0)
                            ret[u][i]['rank_total'] = total
                            ret[u][i]['percentile'] = 1.0
                        else:
                            key = self._scores2_key(stat, axes)
                            total = n_totals[key]
                            if total > 0:
                                qs = {'key': key, 'val': {'$gt': ret[u][i]['absolute']}}
                                n_above_me = self._scores2_table(kind, stat, axes).find(qs,{'_id':0}).count()
                                ret[u][i]['rank'] = n_above_me
                                ret[u][i]['rank_total'] = total
                                ret[u][i]['percentile'] = n_above_me/float(total)

#            end_time = time.time(); print "C %.2fms" % (1000.0*(end_time-start_time)); start_time = end_time
        return ret

# SQL score query interface, built on top of (SpinSQL2?)
# XXX break out into a separate library to avoid dependencies?
import SpinSQLUtil

# temporary stub, for testing only
class SpinSQL2(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.con = psycopg2.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    def _table(self, name):
        return self.cfg['table_prefix']+name
    def instrument(self, reason, func, args):
        return apply(func, args)

class SQLScores2(object):
    def __init__(self, sql_client):
        self.sql_client = sql_client
        self.util = SpinSQLUtil.PostgreSQLUtil()

    # parse to list of key/value pairs for the SQL columns to match
    def _scores2_parse_addr(self, stat, axes):
        ret = [('stat', stat),
               ('time_scope', axes['time'][0]), ('time_loc', axes['time'][1]),
               ('space_scope', axes['space'][0]), ('space_loc', axes['space'][1])]
        found_extra = False
        for name, scope_loc in axes.iteritems():
            if name in ('time','space'): continue
            if found_extra: raise Exception('only one extra axis allowed')
            else: found_extra = True
            ret += [('extra_scope', scope_loc[0]), ('extra_loc', scope_loc[1])]
        return ret

    # return a unique hashable key for an addr key/value pair list
    def _scores2_addr_key(self, addr):
        return ''.join(['%s-%s' % (k,str(v)) for k,v in sorted(addr)])

    # get top "num" leaders for a batch of (stat,axes) combinations
    def player_scores2_get_leaders(self, stat_axes_list, num, start = 0, reason = ''): return self.sql_client.instrument('player_scores2_get_leaders(%s)'%reason, self._scores2_get_leaders, ('player',stat_axes_list,num,start))
    def alliance_scores2_get_leaders(self, stat_axes_list, num, start = 0, reason = ''): return self.sql_client.instrument('alliance_scores2_get_leaders(%s)'%reason, self._scores2_get_leaders, ('alliance',stat_axes_list,num,start))

    def _scores2_get_leaders(self, kind, stat_axes_list, num, start):
        cur = self.sql_client.con.cursor()
        ret = []
        for stat, axes in stat_axes_list:
            addr = self._scores2_parse_addr(stat, axes)
            cur.execute("SELECT %s, val FROM " % self.util.sym(ID_FIELD[kind]) + self.sql_client._table(kind+'_scores2') + \
                        " WHERE ("+",".join([self.util.sym(k) for k,v in addr]) + ") = (" + ",".join(["%s"]*len(addr))+") ORDER BY val DESC LIMIT %s OFFSET %s",
                        [v for k,v in addr] + [num, start])
            rows = cur.fetchall()
            r = [{ID_FIELD[kind]: rows[i][0], 'absolute': rows[i][1], 'rank': start+i} for i in xrange(len(rows))]
            ret.append(r)
        self.sql_client.con.commit()
        return ret

    # get current scores and optionally ranks for a batch of (stat,axes) combinations

    # sync API
    def player_scores2_get(self, player_ids, stat_axes_list, rank = False, reason=''): return self.sql_client.instrument('player_scores2_get' + '+RANK' if rank else '' + '(%s)'%reason, self._scores2_get, ('player',player_ids, stat_axes_list, rank))
    def alliance_scores2_get(self, alliance_ids, stat_axes_list, rank = False, reason=''): return self.sql_client.instrument('alliance_scores2_get' + '+RANK' if rank else '' + '(%s)'%reason, self._scores2_get, ('alliance',alliance_ids, stat_axes_list, rank))

    def _scores2_get(self, kind, id_list, stat_axes_list, rank):
        # prepare queries
        batch = self.GetBatch(self, kind, id_list, stat_axes_list, rank)

        # launch queries
        cur = self.sql_client.con.cursor(cursor_factory=psycopg2.extras.DictCursor)
        sql_results = {}
        for tag, qs_args in batch.get_qs_dict().iteritems():
            query, query_args = qs_args
            if 0:
                cur.execute("EXPLAIN "+query, query_args)
                print "EXPLAIN", cur.fetchall()
            cur.execute(query, query_args)
            sql_results[tag] = cur.fetchall()
        self.sql_client.con.commit()

        # collect results
        return batch.receive_rows_dict(sql_results)

    # async API
    def player_scores2_get_async(self, player_ids, stat_axes_list, rank = False, reason=''): return self.sql_client.instrument('player_scores2_get_async(%s)'%reason, self._scores2_get_async, ('player',player_ids, stat_axes_list, rank))
    def player_scores2_get_async_complete(self, batch, sql_results, reason=''): return self.sql_client.instrument('player_scores2_get_async_complete(%s)'%reason, self._scores2_get_async_complete, (batch, sql_results))

    def _scores2_get_async(self, kind, id_list, stat_axes_list, rank):
        return self.GetBatch(self, kind, id_list, stat_axes_list, rank)
    def _scores2_get_async_complete(self, batch, sql_results):
        return batch.receive_rows_dict(sql_results)

    # SCORE RETRIEVAL

    # GetBatch handles queries for a list of players/alliances and a list of stat/axes combinations, optionally getting rank info too
    # Due to SQL syntax limitations, GetBatch may have to run multiple SQL queries, one per number of dimensions
    # Each SQL query's state is stored in a GetBatch.GetOne object

    class GetBatch (object):
        def __init__(self, parent, kind, id_list, stat_axes_list, rank):
            self.parent = parent
            self.kind = kind
            self.id_list = id_list
            self.stat_axes_list = stat_axes_list
            self.rank = rank

            # since we cannot use (a,b,c) IN ((d,e,f),...) to match rows
            # when NULLs are involved, we have to do separate queries when
            # the batch includes different numbers of dimensions.
            self.queries = {} # number of dimensions -> stat_axes_list
            self.query_map = {} # key -> (dims, index_within_query)

            for i in xrange(len(stat_axes_list)):
                stat, axes = stat_axes_list[i]
                dims = len(axes)
                if dims not in self.queries:
                    self.queries[dims] = []

                key = self.parent._scores2_addr_key(self.parent._scores2_parse_addr(stat, axes))
                assert key not in self.query_map
                self.query_map[key] = (dims, len(self.queries[dims]))
                self.queries[dims].append([stat, axes])

            self.getters = dict((dims, self.GetOne(self, self.kind, self.id_list, self.queries[dims], self.rank)) for dims in self.queries)

            self.ret = [] # final return value

        # return a dictionary of the SQL queries we need to run, indexed by an opaque "tag"
        # { tag0: (query0, query_args0), tag1: (query1, query_args1), ... }
        def get_qs_dict(self):
            return dict((dims, self.getters[dims].get_qs()) for dims in self.getters)

        # receive the results of these SQL queries, indexed by the "tag", and return the final result
        # { tag0: query_result0, tag1: query_result1, ... }
        def receive_rows_dict(self, d):
            ret = []
            results = dict((dims, self.getters[dims].receive_rows(d[dims])) for dims in self.queries)
            for u in xrange(len(self.id_list)):
                r = []
                for i in xrange(len(self.stat_axes_list)):
                    stat, axes = self.stat_axes_list[i]
                    key = self.parent._scores2_addr_key(self.parent._scores2_parse_addr(stat, axes))
                    dims, j = self.query_map[key]
                    r.append(results[dims][u][j])
                ret.append(r)
            return ret


        class GetOne (object): # one score-retrieval SQL query
            def __init__(self, parent, kind, id_list, stat_axes_list, rank):
                self.parent = parent
                self.kind = kind
                self.id_list = id_list
                self.stat_axes_list = stat_axes_list
                self.rank = rank


                self.addr_fields = None
                self.addr_list = []
                self.addr_map = {}

                for i in xrange(len(self.stat_axes_list)):
                    stat, axes = self.stat_axes_list[i]
                    addr = self.parent.parent._scores2_parse_addr(stat, axes)
                    fields = [k for k,v in addr]
                    if self.addr_fields is None:
                        self.addr_fields = fields
                    elif fields != self.addr_fields:
                        raise Exception('inconsistent addr fields: %s vs %s' % (fields, self.addr_fields))
                    addr_key = self.parent.parent._scores2_addr_key(addr)
                    assert addr_key not in self.addr_map
                    self.addr_map[addr_key] = i
                    self.addr_list.append(addr)

                tbl = self.parent.parent.sql_client._table(self.kind+'_scores2')
                if rank:
                    rank_columns = ', (SELECT COUNT(*) FROM '+tbl+' AS other WHERE ('+",".join(['other.'+k for k in self.addr_fields])+') = ('+",".join(['self.'+k for k in self.addr_fields])+') AND other.val > self.val) AS rank' + \
                                   ', (SELECT COUNT(*) FROM '+tbl+' AS other WHERE ('+",".join(['other.'+k for k in self.addr_fields])+') = ('+",".join(['self.'+k for k in self.addr_fields])+')) AS rank_total'
                else:
                    rank_columns = ''

                self.query = "SELECT self."+self.parent.parent.util.sym(ID_FIELD[self.kind])+", self.val, "+ ",".join(['self.'+k for k in self.addr_fields]) + rank_columns + \
                             " FROM "+tbl+" AS self" + \
                             " WHERE self."+self.parent.parent.util.sym(ID_FIELD[self.kind])+" IN ("+",".join(['%s']*len(self.id_list))+")" + \
                             " AND ("+",".join(['self.'+k for k in self.addr_fields])+") IN ("+ ",".join(["("+",".join(["%s"]*len(self.addr_fields))+")"]*len(self.stat_axes_list))+")"

                self.query_args = tuple(id_list + [v for entry in self.addr_list for k,v in entry])

            def get_qs(self):
                return self.query, self.query_args

            def receive_rows(self, rows):
                ret = [[None,]*len(self.stat_axes_list) for u in xrange(len(self.id_list))]

                for row in rows:
                    u = self.id_list.index(row[ID_FIELD[self.kind]])

                    # map coords back to addr index
                    key = self.parent.parent._scores2_addr_key([(k,str(row[k]) if k!='time_loc' else int(row[k])) for k in self.addr_fields])
                    i = self.addr_map.get(key,-1)
                    if i < 0:
                        raise Exception('did not find addr: '+repr(key)+' in '+repr(self.addr_map))
                        continue

                    ret[u][i] = {'absolute':row['val']}

                    if ('rank' in row) and row.get('rank_total',0) > 0:
                        ret[u][i]['rank'] = row['rank']
                        ret[u][i]['rank_total'] = row['rank_total']
                        ret[u][i]['percentile'] = float(row['rank'])/float(row['rank_total'])
                return ret



# TEST CODE

if __name__ == '__main__':
    import string, subprocess, sys

    s = CurScores()
    for season in (0,1,2,3):
        s.set('damage_done', 100*season, make_time_coords(86401, season, 0, 0), make_space_coords('english', 'kasei101'))
    s.set('damage_done',  50, make_time_coords(86401, 2, 0, 0), make_space_coords('english', 'kasei101'))
    s.set('xp', 12, make_time_coords(86401, 2, 0, 0), make_space_coords(None, 'kasei101'))
    s.set('best_time', 1344, make_time_coords(86401, 2, 0, 0), make_space_coords('english', 'kasei101'), extra_axes = {'challenge':('ai','321')}, method='min')
    s.set('best_time',  900, make_time_coords(86401, 2, 0, 0), make_space_coords('english', 'kasei101'), extra_axes = {'challenge':('ai','321')}, method='min')

    print string.join(map(repr, s.scores.values()), '\n')

    data = s.serialize()

    t = CurScores(data)
    assert s.scores == t.scores

    test_points = [('damage_done', make_point(FREQ_DAY, 1, SPACE_REGION, 'kasei101')),
                   ('damage_done', make_point(FREQ_DAY, 1, SPACE_CONTINENT, 'english')),
                   ('xp', make_point(FREQ_WEEK, 0, SPACE_REGION, 'kasei101')),
                   ('xp', make_point(FREQ_WEEK, 0, SPACE_ALL, SPACE_ALL_LOC)),
                   ('best_time', make_point(FREQ_DAY, 1, SPACE_CONTINENT, 'english', {'challenge':['ai','321']})),
                   ('best_time', make_point(FREQ_DAY, 1, SPACE_CONTINENT, 'english', {'challenge':['ai','322']})),
                   ]

    if 1: # test MongoDB writes
        print "MONGO"
        import SpinNoSQL, SpinConfig, time
        client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
        client.set_time(int(time.time()))
        api = MongoScores2(client)
        api.player_scores2_write(1114, s.dirty_iter())
        api.alliance_scores2_update_weighted(1, (item for item in s.dirty_iter() if item['stat'] == 'damage_done'), [1,1,1,1,1], {})
        s.dirty_clear()
        api.player_scores2_write(1115, [{'stat':'damage_done', 'axes':make_point(FREQ_DAY, 1, SPACE_CONTINENT, 'english'), 'val':200}])

        mongo_test1 = api.player_scores2_get_leaders(test_points, 10); print mongo_test1
        mongo_test2 = api.player_scores2_get([1114,1115,1119], test_points, True); print mongo_test2

    # dump to SQL
    subprocess.check_call(['./scores2_to_sql.py', '--reset', '--force', '-q'])

    if 1: # test SQL reads
        print "SQL"
        import psycopg2, psycopg2.extras
        sql_config = SpinConfig.get_pgsql_config(SpinConfig.config['game_id']+'_scores2')
        client = SQLScores2(SpinSQL2(sql_config))
        sql_test1 = client.player_scores2_get_leaders(test_points, 10); print sql_test1
        sql_test2 = client.player_scores2_get([1114,1115,1119], test_points, True); print sql_test2

        # final test - make sure they match!
        assert sql_test1 == mongo_test1
        assert sql_test2 == mongo_test2

        client = None

        if 1: # test async SQL reards
            print "SQL (async)"
            from twisted.python import log
            from twisted.internet import task, reactor
            import AsyncPostgres
            import functools
            log.startLogging(sys.stdout)
            req = AsyncPostgres.AsyncPostgres(sql_config, log_exception_func = lambda x: log.msg(x), verbosity = 2)
            client = SQLScores2(req)

            def my_query(req):
                batch = client.player_scores2_get_async([1114,1115,1119], test_points, True)
                bdict = batch.get_qs_dict()
                rdict = {}
                tag_list = sorted(bdict.keys())

                def next_query(client, req, batch, bdict, rdict, tag_list, i, last_result):
                    if i > 0:
                        rdict[tag_list[i-1]] = last_result
                    if i >= len(tag_list):
                        # done!
                        sql_test2 = client.player_scores2_get_async_complete(batch, rdict)
                        print "DONE!!"
                        assert sql_test2 == mongo_test2
                        return

                    qs, qs_args = bdict[tag_list[i]]
                    d = req.runQuery("SELECT pg_sleep(1); "+qs, qs_args) # insert artificial delay to test what happens when we kill the server manually

                    def my_error(f):
                        print 'CLIENT error', f.value
                    d.addCallbacks(functools.partial(next_query, client, req, batch, bdict, rdict, tag_list, i+1), my_error)

                next_query(client, req, batch, bdict, rdict, tag_list, -1, None)

            task.LoopingCall(my_query, req).start(3)
            reactor.run()

    print "ALL TESTS OK"
