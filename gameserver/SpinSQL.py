#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# OBSOLETE! This has been replaced by SpinNoSQL.py

import time, sys, string
import SpinMySQLdb, SpinMySQLdb.constants.CLIENT

def unix_to_db(ts):
    return SpinMySQLdb.Timestamp(*time.localtime(ts)[:6])
def db_to_unix(ts):
    raise 'not implemented' # use UNIX_TIMESTAMP() on SQL side instead

class SQLClient (object):
    ALLIANCE_JOIN_TYPES = {'anyone':0, 'invite_only':1}
    ALLIANCE_JOIN_TYPES_REV = dict((v,k) for k,v in ALLIANCE_JOIN_TYPES.iteritems())
    SCORE_FREQ_SEASON = 0
    SCORE_FREQ_WEEKLY = 1
    ROLE_DEFAULT = 0
    ROLE_LEADER = 4

    def __init__(self, cfg, latency_func = None):
        self.cfg = cfg
        self.latency_func = latency_func
        self.con = None
        self.connect()

    def connect(self):
        assert self.con is None
        self.con = SpinMySQLdb.connect(self.cfg['host'], self.cfg['username'], self.cfg['password'], self.cfg['database'],
                                   use_unicode = True, charset = 'utf8',

                                   # this setting is for UPDATE
                                   # queries - it makes cur.rowcount
                                   # count rows that matched the query
                                   # but already had identical values
                                   # to what we were trying to set
                                   # client_flag = SpinMySQLdb.constants.CLIENT.FOUND_ROWS
                                   )

    def shutdown(self):
        if self.con:
            self.con.close()
            self.con = None

    # reconnect to get around MySQL timing out idle connection
    def ping_connection(self):
        assert self.con
        if self.con.open: self.con.stat()
        if (not self.con.open) or (self.con.errno() != 0):
            # reconnect
            self.con = None
            self.connect()

    def instrument(self, name, func, args):
        if self.con is None:
            self.ping_connection()
        if self.con is None:
            raise Exception('MySQL connection failed')

        if self.latency_func: start_time = time.time()

        try:
            try:
                ret = func(*args)
            except SpinMySQLdb.OperationalError:
                # attempt to reconnect and try a second time
                self.ping_connection()
                ret = func(*args)
        except:
            # auto-rollback on Python exceptions
            if self.con and self.con.open: self.con.rollback()
            raise

        if self.latency_func:
            end_time = time.time()
            elapsed = end_time - start_time
            self.latency_func('SQL:'+name, elapsed)
            self.latency_func('SQL:ALL', elapsed)
        return ret

    def array_param(self, n):
        return ', '.join(['%s'] * n)

    def drop_tables(self):
        cur = self.con.cursor()
        cur.execute("DROP TABLE IF EXISTS alliances")
        cur.execute("DROP TABLE IF EXISTS alliance_members")
        cur.execute("DROP TABLE IF EXISTS alliance_invites")
        cur.execute("DROP TABLE IF EXISTS alliance_join_requests")
        cur.execute("DROP TABLE IF EXISTS alliance_scores") # obsolete
        cur.execute("DROP TABLE IF EXISTS alliance_score_cache")
        cur.execute("DROP TABLE IF EXISTS player_scores")
        cur.execute("DROP TABLE IF EXISTS recent_attacks")
        cur.execute("DROP TABLE IF EXISTS unit_donation_requests")
        self.con.commit()

    def init_tables(self):
        cur = self.con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS alliances(id INT NOT NULL AUTO_INCREMENT, creation_time TIMESTAMP NOT NULL DEFAULT 0, ui_name VARCHAR(64) NOT NULL UNIQUE, ui_description VARCHAR(256), join_type INT NOT NULL, founder_id INT NOT NULL, leader_id INT NOT NULL, logo VARCHAR(32) NOT NULL, chat_motd VARCHAR(256) NOT NULL DEFAULT 'Welcome to Alliance chat!', PRIMARY KEY(id), KEY(ui_name)) CHARACTER SET utf8")
        cur.execute("CREATE TABLE IF NOT EXISTS alliance_members(user_id INT NOT NULL UNIQUE, alliance_id INT NOT NULL, join_time TIMESTAMP NOT NULL DEFAULT 0, PRIMARY KEY(user_id), KEY(alliance_id)) CHARACTER SET utf8")
        cur.execute("CREATE TABLE IF NOT EXISTS alliance_invites(user_id INT NOT NULL, alliance_id INT NOT NULL, creation_time TIMESTAMP NOT NULL DEFAULT 0, expire_time TIMESTAMP NOT NULL DEFAULT 0, KEY(user_id)) CHARACTER SET utf8")
        cur.execute("CREATE TABLE IF NOT EXISTS alliance_join_requests(user_id INT NOT NULL UNIQUE, alliance_id INT NOT NULL, creation_time TIMESTAMP NOT NULL DEFAULT 0, expire_time TIMESTAMP NOT NULL DEFAULT 0, PRIMARY KEY(user_id), KEY(alliance_id)) CHARACTER SET utf8")

        cur.execute("CREATE TABLE IF NOT EXISTS player_scores(user_id INT NOT NULL, field_name VARCHAR(48), frequency INT NOT NULL, period INT NOT NULL, score INT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, UNIQUE unique_user_and_field (user_id, field_name, frequency, period), KEY by_user_and_field (user_id, field_name, frequency, period), KEY by_field_and_score (field_name, frequency, period, score)) CHARACTER SET utf8")
        # XXX the by_user_and_field index may be redundant with the unique constraint

        cur.execute("CREATE TABLE IF NOT EXISTS alliance_score_cache(alliance_id INT NOT NULL, field_name VARCHAR(48), frequency INT NOT NULL, period INT NOT NULL, score INT NOT NULL, UNIQUE unique_alliance_and_field (alliance_id, field_name, frequency, period), KEY by_field_and_score (field_name, frequency, period, score)) CHARACTER SET utf8")

        cur.execute("CREATE TABLE IF NOT EXISTS recent_attacks(attacker_id INT NOT NULL, defender_id INT NOT NULL, severity FLOAT NOT NULL, time TIMESTAMP NOT NULL DEFAULT 0, KEY(attacker_id), KEY(defender_id), KEY defender_attacker (defender_id, attacker_id)) CHARACTER SET utf8")

        cur.execute("CREATE TABLE IF NOT EXISTS unit_donation_requests(user_id INT NOT NULL UNIQUE, alliance_id INT NOT NULL, time TIMESTAMP NOT NULL DEFAULT 0, tag INT NOT NULL, cur_space INT NOT NULL, max_space INT NOT NULL, PRIMARY KEY(user_id)) CHARACTER SET utf8")

        self.con.commit()

    def prune_tables(self, gamedata):
        time_now = int(time.time())

        cur_week = SpinConfig.get_pvp_week(gamedata['matchmaking']['week_origin'], time_now)
        print 'Current week is', cur_week

        cur = self.con.cursor()
        print 'Checking for alliances with no members...'
        cur.execute("SELECT id, ui_name FROM alliances WHERE (select COUNT(alliance_members.user_id) FROM alliance_members WHERE alliance_members.alliance_id = alliances.id) = 0")
        for row in cur.fetchall():
            print 'Deleting memberless alliance:', row
            cur.execute("DELETE FROM alliances WHERE id = %s", (row[0],))
        self.con.commit()

        print 'Checking for dangling member relationships...'
        cur.execute("DELETE FROM alliance_members WHERE NOT EXISTS (SELECT * FROM alliances WHERE alliances.id = alliance_members.alliance_id)")
        if cur.rowcount > 0:
            print 'Deleted', cur.rowcount, 'dangling member relationships'
        self.con.commit()

        print 'Checking for old player_scores entries...'
        cur.execute("DELETE FROM player_scores WHERE frequency = %s AND period < %s", (self.SCORE_FREQ_WEEKLY, cur_week - 2))
        if cur.rowcount > 0:
            print 'Deleted', cur.rowcount, 'old player_scores entries'
        self.con.commit()

        print 'Checking for stale unit_donation_requests...'
        earliest = time_now - 24*60*60 # clear entries more than 1 day old
        cur.execute("DELETE FROM unit_donation_requests WHERE time < %s", (unix_to_db(earliest),))
        if cur.rowcount > 0:
            print 'Deleted', cur.rowcount, 'old unit_donation_requests'
        self.con.commit()

        print 'Checking for old or dangling alliance_score_cache entries...'
        cur.execute("DELETE FROM alliance_score_cache WHERE (NOT EXISTS (SELECT * FROM alliances WHERE alliances.id = alliance_score_cache.alliance_id)) OR (frequency = %s AND period < %s)", (self.SCORE_FREQ_WEEKLY, cur_week - 2))
        if cur.rowcount > 0:
            print 'Deleted', cur.rowcount, 'old or dangling alliance_score_cache entries'
        self.con.commit()

        print 'Checking for dangling or stale invites...'
        cur.execute("DELETE FROM alliance_invites WHERE (NOT EXISTS (SELECT * FROM alliances WHERE alliances.id = alliance_invites.alliance_id)) OR (alliance_invites.expire_time < %s)", (unix_to_db(time_now),))
        if cur.rowcount > 0:
            print 'Deleted', cur.rowcount, 'dangling or stale invites'
        self.con.commit()

        print 'Checking for dangling or stale join requests...'
        cur.execute("DELETE FROM alliance_join_requests WHERE (NOT EXISTS (SELECT * FROM alliances WHERE alliances.id = alliance_join_requests.alliance_id)) OR (alliance_join_requests.expire_time < %s)", (unix_to_db(time_now),))
        if cur.rowcount > 0:
            print 'Deleted', cur.rowcount, 'dangling or stale join requests'
        self.con.commit()

        print 'Clearing old attack entries...'
        earliest = time_now - 7*24*60*60 # clear entries more than 1 week old
        cur.execute("DELETE FROM recent_attacks WHERE time < %s", (unix_to_db(earliest),))
        if cur.rowcount > 0:
            print 'Deleted', cur.rowcount, 'old attack entries'
        self.con.commit()

    def add_recent_attack(self, attacker_id, defender_id, severity, creat, reason=''): return self.instrument('add_recent_attack(%s)'%reason, self._add_recent_attack, (attacker_id, defender_id, severity, creat))
    def _add_recent_attack(self, attacker_id, defender_id, severity, creat):
        cur = self.con.cursor()
        cur.execute("INSERT INTO recent_attacks (attacker_id, defender_id, severity, time) VALUES (%s, %s, %s, %s)", (attacker_id, defender_id, severity, unix_to_db(creat)))
        self.con.commit()

    def get_recent_attacks(self, attackers, defender_id, time_range, reason=''): return self.instrument('get_recent_attacks(%s)'%reason, self._get_recent_attacks, (attackers, defender_id, time_range))
    def _get_recent_attacks(self, attackers, defender_id, time_range):
        cur = self.con.cursor(SpinMySQLdb.cursors.DictCursor)
        filter_fmt = ''
        filter_args = tuple()
        if attackers:
            if len(attackers) == 1:
                filter_fmt = " AND attacker_id = %s"
                filter_args = tuple(attackers)
            else:
                filter_fmt = " AND attacker_id IN (" + ", ".join(["%s"] * len(attackers))+ ")"
                filter_args = tuple(attackers)

        cur.execute("SELECT UNIX_TIMESTAMP(time) AS time, attacker_id, severity FROM recent_attacks WHERE defender_id = %s AND time >= %s AND time < %s" + filter_fmt, (defender_id, unix_to_db(time_range[0]), unix_to_db(time_range[1]))+filter_args)
        ret = cur.fetchall()
        self.con.commit()
        return ret

    def create_alliance(self, ui_name, ui_descr, join_type, founder_id, logo, creat, chat_motd='', chat_tag='', reason=''): return self.instrument('create_alliance(%s)'%reason, self._create_alliance, (ui_name,ui_descr,join_type,founder_id,logo,creat, chat_motd))
    def _create_alliance(self, ui_name, ui_descr, join_type, founder_id, logo, creat, chat_motd):
        assert join_type in self.ALLIANCE_JOIN_TYPES
        new_id = -1
        err_reason = None
        cur = self.con.cursor()
        try:
            cur.execute("INSERT INTO alliances (ui_name, ui_description, join_type, founder_id, leader_id, logo, creation_time, chat_motd) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (ui_name, ui_descr, self.ALLIANCE_JOIN_TYPES[join_type], founder_id, founder_id, logo, unix_to_db(creat), chat_motd))
            new_id = self.con.insert_id()
            self.con.commit()
        except SpinMySQLdb.IntegrityError:
            err_reason = "CANNOT_CREATE_ALLIANCE_NAME_IN_USE"
            self.con.rollback()
            pass

        return new_id, err_reason

    def modify_alliance(self, alliance_id, modifier_id, ui_name = None, ui_description = None, join_type = None, logo = None, leader_id = None, chat_motd = None, chat_tag = None, reason = ''):
        return self.instrument('modify_alliance(%s)'%reason, self._modify_alliance, (alliance_id, modifier_id, ui_name, ui_description, join_type, logo, leader_id, chat_motd))

    # note: modifications are rejected unless modifier_id is the same as the alliance's leader_id
    def _modify_alliance(self, alliance_id, modifier_id, ui_name, ui_description, join_type, logo, leader_id, chat_motd):
        cur = self.con.cursor()
        updates = []
        args = []
        success = False
        err_reason = None

        if ui_name is not None: updates.append('ui_name = %s'); args.append(ui_name)
        if ui_description is not None: updates.append('ui_description = %s'); args.append(ui_description)
        if chat_motd is not None: updates.append('chat_motd = %s'); args.append(chat_motd)
        if logo is not None: updates.append('logo = %s'); args.append(logo)
        if leader_id is not None: updates.append('leader_id = %s'); args.append(leader_id)
        if join_type is not None:
            assert join_type in self.ALLIANCE_JOIN_TYPES
            updates.append('join_type = %s'); args.append(self.ALLIANCE_JOIN_TYPES[join_type])

        # note: add an AND so that only alliance leader can make modifications
        query_string = "UPDATE alliances SET %s WHERE id = %%s AND leader_id = %%s" % (', '.join(updates))
        try:
            cur.execute(query_string, args + [alliance_id, modifier_id])
            success = cur.rowcount > 0
            self.con.commit()
        except SpinMySQLdb.IntegrityError:
            success = False
            err_reason = "CANNOT_CREATE_ALLIANCE_NAME_IN_USE"
            self.con.rollback()

        return success, err_reason

    def delete_alliance(self, id, reason=''): return self.instrument('delete_alliance(%s)'%reason, self._delete_alliance, (id,))
    def _delete_alliance(self, id):
        cur = self.con.cursor()
        cur.execute("DELETE FROM alliances WHERE id = %s", (id,))
        cur.execute("DELETE FROM alliance_members WHERE alliance_id = %s", (id,))
        cur.execute("DELETE FROM alliance_invites WHERE alliance_id = %s", (id,))
        cur.execute("DELETE FROM alliance_score_cache WHERE alliance_id = %s", (id,))
        self.con.commit()

    def send_alliance_invite(self, sender_id, user_id, alliance_id, time_now, expire_time, reason=''): return self.instrument('send_alliance_invite(%s)'%reason, self._send_alliance_invite, (sender_id, user_id, alliance_id, time_now, expire_time))
    def _send_alliance_invite(self, sender_id, user_id, alliance_id, time_now, expire_time):
        cur = self.con.cursor()
        success = True

        # check that sender is leader. We DO allow sending invites even if the alliance is open-join.
        cur.execute("SELECT leader_id FROM alliances WHERE id = %s", (alliance_id,))
        if cur.fetchone()[0] != sender_id:
            success = False
        if success:
            # get rid of any existing invites
            cur.execute("DELETE FROM alliance_invites WHERE user_id = %s AND alliance_id = %s", (user_id, alliance_id))
            cur.execute("INSERT INTO alliance_invites (user_id, alliance_id, creation_time, expire_time) VALUES (%s, %s, %s, %s)",
                        (user_id, alliance_id, unix_to_db(time_now), unix_to_db(expire_time)))
            success = cur.rowcount > 0
        self.con.commit()
        return success

    def send_join_request(self, user_id, alliance_id, time_now, expire_time, reason=''): return self.instrument('send_join_request(%s)'%reason, self._send_join_request, (user_id, alliance_id, time_now, expire_time))
    def _send_join_request(self, user_id, alliance_id, time_now, expire_time):
        cur = self.con.cursor()
        success = True

        # check that alliance really exists
        cur.execute("SELECT id, join_type FROM alliances WHERE id = %s", (alliance_id,))
        temp = cur.fetchall()
        if not temp:
            # alliance does not exist
            success = False
        else:
            join_type = temp[0][1]
            if join_type != self.ALLIANCE_JOIN_TYPES['invite_only']:
                success = False

        if success:
            cur.execute("DELETE FROM alliance_join_requests WHERE user_id = %s", (user_id,))
            cur.execute("INSERT INTO alliance_join_requests (user_id, alliance_id, creation_time, expire_time) VALUES (%s, %s, %s, %s)",
                        (user_id, alliance_id, unix_to_db(time_now), unix_to_db(expire_time)))

        self.con.commit()
        return success

    def poll_join_requests(self, poller_id, alliance_id, time_now, reason=''): return self.instrument('poll_join_requests(%s)'%reason, self._poll_join_requests, (poller_id, alliance_id, time_now))
    def _poll_join_requests(self, poller_id, alliance_id, time_now):
        cur = self.con.cursor()
        success = True
        ret = []

        # check that poller is leader
        cur.execute("SELECT leader_id FROM alliances WHERE id = %s", (alliance_id,))
        if cur.fetchone()[0] != poller_id:
            success = False

        if success:
            cur.execute("SELECT user_id FROM alliance_join_requests WHERE alliance_id = %s AND expire_time >= %s", (alliance_id, unix_to_db(time_now)))
            rows = cur.fetchall()
            if rows:
                ret = map(lambda x: x[0], rows)

        self.con.commit()
        return ret

    def ack_join_request(self, poller_id, alliance_id, user_id, accept, time_now, max_members, reason=''): return self.instrument('ack_join_request(%s)'%reason, self._ack_join_request, (poller_id, alliance_id, user_id, accept, time_now, max_members))
    def _ack_join_request(self, poller_id, alliance_id, user_id, accept, time_now, max_members):
        success = True

        # check that poller is leader
        cur = self.con.cursor()
        cur.execute("SELECT leader_id FROM alliances WHERE id = %s", (alliance_id,))
        if cur.fetchone()[0] != poller_id:
            success = False
        self.con.commit()

        if success:
            if accept:
                success = self._join_alliance(user_id, alliance_id, time_now, max_members, force = True)
            if (not success) or (not accept):
                # _join_alliance cleans up the request in the success case
                cur = self.con.cursor()
                cur.execute("DELETE FROM alliance_join_requests WHERE user_id = %s", (user_id,))
                self.con.commit()

        return success

    def am_i_invited(self, alliance_id, user_id, time_now, reason=''): return self.instrument('am_i_invited(%s)'%reason, self._am_i_invited, (alliance_id,user_id,time_now))
    def _am_i_invited(self, alliance_id, user_id, time_now):
        cur = self.con.cursor()
        cur.execute("SELECT user_id FROM alliance_invites WHERE user_id = %s AND alliance_id = %s AND expire_time >= %s", (user_id, alliance_id, unix_to_db(time_now)))
        success = cur.rowcount > 0
        self.con.commit()
        return success

    def join_alliance(self, user_id, alliance_id, time_now, max_members, role = 0, force = False, reason=''): return self.instrument('join_alliance(%s)'%reason, self._join_alliance, (user_id,alliance_id,time_now, max_members, force))
    def _join_alliance(self, user_id, alliance_id, time_now, max_members, force = False):
        success = True

        cur = self.con.cursor()

        try:
            # necessary to ensure that member count is updated atomically
            cur.execute("LOCK TABLES alliance_members WRITE, alliances READ, alliance_invites WRITE, alliance_join_requests WRITE")

            # check if player is already in an alliance
            cur.execute("SELECT alliance_id FROM alliance_members WHERE user_id = %s", (user_id,))
            temp = cur.fetchall()
            if temp:
                # player might already have an alliance - check if it's obsolete
                old_alliance = temp[0][0]
                cur.execute("SELECT id FROM alliances WHERE id = %s", (old_alliance,))
                temp = cur.fetchall()
                if cur:
                    # player has a valid alliance
                    success = False
                else:
                    # it was a bogus entry
                    cur.execute("DELETE FROM alliance_members WHERE user_id = %s", (user_id,))
            if success:
                # check that alliance really exists
                cur.execute("SELECT id, join_type FROM alliances WHERE id = %s", (alliance_id,))
                temp = cur.fetchall()
                if not temp:
                    # alliance does not exist
                    success = False
                else:
                    join_type = temp[0][1]
                    if join_type != self.ALLIANCE_JOIN_TYPES['anyone'] and (not force):
                        cur.execute("SELECT user_id FROM alliance_invites WHERE user_id = %s AND alliance_id = %s AND expire_time >= %s",
                                    (user_id, alliance_id, unix_to_db(time_now)))
                        temp = cur.fetchall()
                        if not temp:
                            # we're not invited
                            success = False

            if success:
                # perform insertion
                cur.execute("INSERT INTO alliance_members (user_id, alliance_id, join_time) VALUES (%s, %s, %s)", (user_id, alliance_id, unix_to_db(time_now)))
                # check if the alliance got too big
                cur.execute("SELECT COUNT(*) FROM alliance_members WHERE alliance_id = %s", (alliance_id,))
                if cur.fetchone()[0] > max_members:
                    success = False # it's already full
                if success:
                    # get rid of all outstanding invites
                    cur.execute("DELETE FROM alliance_invites WHERE user_id = %s", (user_id,))
                    cur.execute("DELETE FROM alliance_join_requests WHERE user_id = %s", (user_id,))

            if success:
                self.con.commit()

        except:
            success = False
            raise

        finally:
            if not success:
                self.con.rollback()

        cur.execute("UNLOCK TABLES")
        return success

    def leave_alliance(self, user_id, reason=''): return self.instrument('leave_alliance(%s)'%reason, self._leave_alliance, (user_id,))
    def _leave_alliance(self, user_id):
        cur = self.con.cursor()
        cur.execute("DELETE FROM alliance_members WHERE user_id = %s", (user_id,))
        self.con.commit()

    def kick_from_alliance(self, kicker_id, alliance_id, user_id, reason=''): return self.instrument('kick_from_alliance(%s)'%reason, self._kick_from_alliance, (kicker_id, alliance_id, user_id))
    def _kick_from_alliance(self, kicker_id, alliance_id, user_id):
        cur = self.con.cursor()
        if kicker_id == user_id: return False # cannot kick yourself

        # verify that the kicker is the leader
        cur.execute("SELECT leader_id FROM alliances WHERE id = %s", (alliance_id,))
        if cur.fetchone()[0] != kicker_id:
            return False
        cur.execute("DELETE FROM alliance_members WHERE user_id = %s AND alliance_id = %s", (user_id, alliance_id))
        success = cur.rowcount > 0
        if success:
            # delete any pending invites too
            cur.execute("DELETE FROM alliance_invites WHERE user_id = %s AND alliance_id = %s", (user_id, alliance_id))
        self.con.commit()
        return success

    def decode_alliance_info(self, info):
        info['join_type'] = self.ALLIANCE_JOIN_TYPES_REV[info['join_type']]
        return info

    def get_alliance_list(self, limit, members_fewer_than = -1, open_join_only = False, reason=''): return self.instrument('get_alliance_list(%s)'%reason, self._get_alliance_list, (limit, members_fewer_than, open_join_only))
    def _get_alliance_list(self, limit, members_fewer_than, open_join_only):
        cur = self.con.cursor(SpinMySQLdb.cursors.DictCursor)
        predicates = []
        if open_join_only:
            predicates.append('join_type = %d' % self.ALLIANCE_JOIN_TYPES['anyone'])
        if members_fewer_than > 0:
            predicates.append('(select COUNT(alliance_members.user_id) FROM alliance_members WHERE alliance_members.alliance_id = alliances.id) < %d' % members_fewer_than)

        predicate_str = ' WHERE '+string.join(predicates, ' AND ') if predicates else ''

        if limit < 1:
            cur.execute("SELECT id, ui_name, ui_description, join_type, founder_id, leader_id, logo, (select COUNT(alliance_members.user_id) FROM alliance_members WHERE alliance_members.alliance_id = alliances.id) as num_members FROM alliances" + predicate_str, ())
        else:
            # only return first 'limit' alliances, ordered with largest number of vacancies first (or fewest, if members_fewer_than is active)
            member_sort = 'DESC' if members_fewer_than > 0 else 'ASC'
            # XXX check that this statement works - it might be applying LIMIT *before* the num_members calculation, which
            # would lead to incorrect results!
            cur.execute("SELECT id, ui_name, ui_description, join_type, founder_id, leader_id, logo, (select COUNT(alliance_members.user_id) FROM alliance_members WHERE alliance_members.alliance_id = alliances.id) as num_members FROM alliances" + predicate_str + " ORDER BY join_type ASC, num_members "+member_sort+" LIMIT %s", (limit,))

        ret = cur.fetchall()
        ret = map(self.decode_alliance_info, ret)
        self.con.commit()
        return ret

    def search_alliance(self, name, limit = -1, reason=''): return self.instrument('search_alliance(%s)'%reason, self._search_alliance, (name, limit))
    def _search_alliance(self, name, limit):
        cur = self.con.cursor(SpinMySQLdb.cursors.DictCursor)
        if limit >= 1:
            limit_clause = ' LIMIT %d' % limit
        else:
            limit_clause = ''

        # note: the "COLLATION" part asks for case-insensitive comparison
        cur.execute("SELECT id, ui_name, ui_description, join_type, founder_id, leader_id, logo, (select COUNT(alliance_members.user_id) FROM alliance_members WHERE alliance_members.alliance_id = alliances.id) as num_members FROM alliances WHERE ui_name COLLATE utf8_general_ci LIKE %s COLLATE utf8_general_ci" + limit_clause, (name+'%',))
        ret = cur.fetchall()
        ret = map(self.decode_alliance_info, ret)
        self.con.commit()
        return ret

    # get dictionary of info about one or more alliances
    # can pass an array to perform batch query
    def get_alliance_info(self, alliance_id, member_access=False, get_roles=False, reason=''): return self.instrument('get_alliance_info(%s)'%reason, self._get_alliance_info, (alliance_id,member_access))
    def _get_alliance_info(self, alliance_id, member_access):
        cur = self.con.cursor(SpinMySQLdb.cursors.DictCursor)

        fields = "id, ui_name, ui_description, join_type, founder_id, leader_id, logo, (select COUNT(alliance_members.user_id) FROM alliance_members WHERE alliance_members.alliance_id = alliances.id) as num_members"

        if member_access: # get private member-only fields
            fields += ", chat_motd"

        if type(alliance_id) is list:
            ret = [None] * len(alliance_id)
            cur.execute("SELECT %s FROM alliances WHERE id IN (%s)" % (fields,self.array_param(len(alliance_id))), alliance_id)
            for row in cur.fetchall():
                row = self.decode_alliance_info(row)
                ret[alliance_id.index(row['id'])] = row
        else:
            cur.execute("SELECT "+fields+" FROM alliances WHERE id = %s", (alliance_id,))
            result = cur.fetchone()
            if result:
                ret = self.decode_alliance_info(result)
            else:
                ret = None
        self.con.commit()
        return ret

    def get_alliance_members(self, alliance_id, reason=''): return self.instrument('get_alliance_members(%s)'%reason, self._get_alliance_members, (alliance_id,))
    def _get_alliance_members(self, alliance_id):
        cur = self.con.cursor()
        cur.execute("SELECT user_id FROM alliance_members WHERE alliance_id = %s", (alliance_id,))
        ret = map(lambda x: {'user_id':x[0]}, cur.fetchall())
        self.con.commit()
        return ret

    # get ID of alliance user belongs to
    # can pass an array of user IDs to perform a batch query
    def get_users_alliance(self, user_id, reason=''): return self.instrument('get_users_alliance(%s)'%reason, self._get_users_alliance, (user_id,))
    def _get_users_alliance(self, user_id):
        cur = self.con.cursor()
        if type(user_id) is list:
            ret = [-1] * len(user_id)
            cur.execute("SELECT user_id, alliance_id FROM alliance_members WHERE user_id IN (%s)" % self.array_param(len(user_id)), user_id)
            for row in cur.fetchall():
                ret[user_id.index(row[0])] = row[1]
        else:
            cur.execute("SELECT alliance_id FROM alliance_members WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            if result:
                ret = result[0]
            else:
                ret = -1
        self.con.commit()
        return ret

    def get_users_alliance_membership(self, user_id, reason=''):
        id = self.instrument('get_users_alliance_membership(%s)'%reason, self._get_users_alliance, (user_id,))
        if id < 0: return None
        return {'user_id':user_id, 'alliance_id':id, 'role':self.ROLE_DEFAULT}

    # the "updates" parameter here is a list of (address, score) tuples
    # where address is a tuple of (field_name, frequency, period)
    def update_player_scores(self, player_id, updates, reason=''): return self.instrument('update_player_scores(%s)'%reason, self._update_player_scores, (player_id, updates))

    def parse_player_score_addr(self, addr):
        field_name, frequency, period = addr
        assert frequency in (self.SCORE_FREQ_SEASON, self.SCORE_FREQ_WEEKLY)
        assert period >= 0
        return (field_name, frequency, period)

    def _update_player_scores(self, player_id, updates):
        cur = self.con.cursor()
        ret = 0

        for addr, score in updates:
            cur.execute("INSERT INTO player_scores (user_id, field_name, frequency, period, score) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE score = %s", tuple((player_id,) + self.parse_player_score_addr(addr) + (score,score)))
            ret += cur.rowcount

        self.con.commit()
        return ret

    def request_unit_donation(self, *args): return self.instrument('request_unit_donation', self._request_unit_donation, args)
    def _request_unit_donation(self, user_id, alliance_id, time_now, tag, cur_space, max_space):
        cur = self.con.cursor()
        ret = 0

        cur.execute("INSERT INTO unit_donation_requests (user_id, alliance_id, time, tag, cur_space, max_space) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE alliance_id = %s, time = %s, tag = %s, cur_space = %s, max_space = %s", (user_id, alliance_id, unix_to_db(time_now), tag, cur_space, max_space, alliance_id, unix_to_db(time_now), tag, cur_space, max_space))
        ret += cur.rowcount

        self.con.commit()
        return ret

    def invalidate_unit_donation_request(self, *args): return self.instrument('invalidate_unit_donation_request', self._invalidate_unit_donation_request, args)
    def _invalidate_unit_donation_request(self, user_id):
        cur = self.con.cursor()
        cur.execute("DELETE FROM unit_donation_requests WHERE user_id = %s", (user_id,))
        ret = cur.rowcount
        self.con.commit()
        return ret

    def make_unit_donation(self, *args): return self.instrument('make_unit_donation', self._make_unit_donation, args)
    def _make_unit_donation(self, recipient_id, alliance_id, tag, space_array):
        cur = self.con.cursor(SpinMySQLdb.cursors.DictCursor)
        ret = None

        # try to increment cur_space for the outstanding donation request, but do not exceed max_space
        # make successive attempts for all elements of space_array, starting largest to smallest

        for donated_space in space_array:
            cur.execute("UPDATE unit_donation_requests SET cur_space = cur_space + %s WHERE user_id = %s AND alliance_id = %s AND tag = %s AND cur_space + %s <= max_space", (donated_space, recipient_id, alliance_id, tag, donated_space))
            if cur.rowcount > 0:
                cur.execute("SELECT cur_space, max_space FROM unit_donation_requests WHERE user_id = %s AND alliance_id = %s AND tag = %s",
                            (recipient_id, alliance_id, tag))
                temp = cur.fetchall()
                ret = (temp[0]['cur_space'], temp[0]['max_space'])
                break

        self.con.commit()
        return ret

    def get_player_score_leaders(self, field, num, start = 0, reason = ''): return self.instrument('get_player_score_leaders(%s)'%reason, self._get_player_score_leaders, (field, num, start))
    def _get_player_score_leaders(self, field, num, start):
        cur = self.con.cursor(SpinMySQLdb.cursors.DictCursor)
        qs = "SELECT user_id, score AS absolute FROM player_scores WHERE (field_name, frequency, period) = (%s, %s, %s) ORDER BY score DESC LIMIT %s OFFSET %s"
        cur.execute(qs, self.parse_player_score_addr(field) + (num,start))
        ret = cur.fetchall()
        if ret:
            for i in xrange(len(ret)):
                ret[i]['rank'] = start+i
        self.con.commit()
        return ret

    def get_player_scores(self, player_ids, fields, rank = False, reason=''): return self.instrument('get_player_scores' + '+RANK' if rank else '' + '(%s)'%reason, self._get_player_scores, (player_ids, fields, rank))

    def _get_player_scores(self, player_ids, fields, rank):
        cur = self.con.cursor(SpinMySQLdb.cursors.DictCursor)
        ret = [[None,]*len(fields) for u in xrange(len(player_ids))]

        addrs = map(self.parse_player_score_addr, fields)
        rank_columns = ''

        # ranking is optional, because it's slow
        if rank:
            rank_columns = ', (SELECT COUNT(*) FROM player_scores AS other WHERE (other.field_name, other.frequency, other.period) = (self.field_name, self.frequency, self.period) AND other.score > self.score) AS rank' + \
                           ', (SELECT COUNT(*) FROM player_scores AS other WHERE (other.field_name, other.frequency, other.period) = (self.field_name, self.frequency, self.period)) AS rank_total'

        query = "SELECT self.user_id, self.field_name, self.frequency, self.period, self.score" + rank_columns + \
                " FROM player_scores AS self" + \
                " WHERE self.user_id IN ("+",".join(['%s']*len(player_ids))+")" + \
                " AND (self.field_name, self.frequency, self.period) IN ("+ ",".join(["(%s, %s, %s)"]*len(fields))+")"

        query_args = tuple(player_ids + [x for y in addrs for x in y])

        if 0:
            cur.execute("EXPLAIN "+query, query_args)
            rows = cur.fetchall()
            print "EXPLAIN", rows

        cur.execute(query, query_args)

        rows = cur.fetchall()
        for row in rows:
            u = player_ids.index(row['user_id'])
            try:
                key = (str(row['field_name']),row['frequency'],row['period'])
                i = addrs.index(key)
            except ValueError:
                continue
            ret[u][i] = {'absolute':row['score']}
            if ('rank' in row) and row.get('rank_total',0) > 0:
                ret[u][i]['rank'] = row['rank']
                ret[u][i]['percentile'] = float(row['rank_total'] - row['rank'])/float(row['rank_total'])

        self.con.commit()
        return ret

    def update_alliance_score_cache(self, alliance_id, fields, weights, offset, reason = ''):
        return self.instrument('update_alliance_score_cache(%s)'%reason, self._update_alliance_score_cache, (alliance_id, fields, weights, offset))
    def _update_alliance_score_cache(self, alliance_id, fields, weights, offset):
        cur = self.con.cursor()
        ret = 0

        cur.execute("SELECT user_id FROM alliance_members WHERE alliance_id = %s", (alliance_id,))
        member_ids = map(lambda x: x[0], cur.fetchall())
        self.con.commit()
        #print "MEMBER_IDS", member_ids

        addrs = map(self.parse_player_score_addr, fields)
        for addr in addrs:
            if len(member_ids) > 0:
                cur.execute("SELECT user_id, score FROM player_scores WHERE (field_name, frequency, period) = (%s, %s, %s) AND user_id IN (%ARR)".replace('%ARR', self.array_param(len(member_ids))), addr + tuple(member_ids))
                player_scores = cur.fetchall()
            else:
                player_scores = []

            score_map = {}
            for row in player_scores:
                score_map[row[0]] = row[1]
            member_ids.sort(key = lambda id: -score_map.get(id,0))

            #print "SCORE_MAP", score_map

            total = 0.0
            for i in xrange(min(len(member_ids), len(weights))):
                sc = score_map.get(member_ids[i],0)
                total += weights[i] * (sc + offset.get(addr[0],0))
            total = int(total)

            cur.execute("INSERT INTO alliance_score_cache (alliance_id, field_name, frequency, period, score) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE score = %s", tuple((alliance_id,) + addr + (total,total)))

            ret += cur.rowcount
            #print "HERE", alliance_id, addr, total
        self.con.commit()
        return ret

    def get_alliance_score_leaders(self, field, num, start = 0, reason = ''): return self.instrument('get_alliance_score_leaders(%s)'%reason, self._get_alliance_score_leaders, (field, num, start))
    def _get_alliance_score_leaders(self, field, num, start):
        cur = self.con.cursor(SpinMySQLdb.cursors.DictCursor)
        qs = "SELECT alliance_id, score AS absolute FROM alliance_score_cache WHERE (field_name, frequency, period) = (%s, %s, %s) ORDER BY score DESC LIMIT %s OFFSET %s"
        cur.execute(qs, self.parse_player_score_addr(field) + (num,start))
        ret = cur.fetchall()
        if ret:
            for i in xrange(len(ret)):
                ret[i]['rank'] = start+i
        self.con.commit()
        return ret

    def get_alliance_score(self, alliance_id, field, rank = False, reason=''): return self.instrument('get_alliance_score' + '+RANK' if rank else '' + '(%s)'%reason, self._get_alliance_score, (alliance_id, field, rank))

    def _get_alliance_score(self, alliance_id, field, rank):
        cur = self.con.cursor(SpinMySQLdb.cursors.DictCursor)
        ret = None

        addr = self.parse_player_score_addr(field)
        rank_column = ''

        # ranking is optional, because it's slow
        if rank:
            rank_column = ', (SELECT COUNT(*) FROM alliance_score_cache AS other WHERE (other.field_name, other.frequency, other.period) = (self.field_name, self.frequency, self.period) AND other.score > self.score) AS rank' + \
                           ', (SELECT COUNT(*) FROM alliance_score_cache AS other WHERE (other.field_name, other.frequency, other.period) = (self.field_name, self.frequency, self.period)) AS rank_total'

        query = "SELECT self.alliance_id, self.score" + rank_column + \
                " FROM alliance_score_cache AS self" + \
                " WHERE self.alliance_id = %s" + \
                " AND (self.field_name, self.frequency, self.period) = (%s, %s, %s)"

        query_args = (alliance_id,) + addr

        if 0:
            cur.execute("EXPLAIN "+query, query_args)
            rows = cur.fetchall()
            print "EXPLAIN", rows

        cur.execute(query, query_args)

        rows = cur.fetchall()
        if len(rows) > 0:
            row = rows[0]
            ret = {'absolute': row['score']}
            if ('rank' in row) and row.get('rank_total',0) > 0:
                ret['rank'] = row['rank']
                ret['percentile'] = float(row['rank'])/float(row['rank_total'])

        self.con.commit()
        return ret


if __name__ == '__main__':
    import getopt
    import SpinConfig
    import codecs
    sys.stdout = codecs.getwriter('utf8')(sys.stdout)

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['reset', 'init', 'prune', 'test', 'winners', 'trophy-type=', 'week=', 'season=', 'recache'])
    mode = None
    week = -1
    season = -1
    time_now = int(time.time())
    trophy_type = 'pve'

    for key, val in opts:
        if key == '--reset':
            mode = 'reset'
        elif key == '--init':
            mode = 'init'
        elif key == '--prune':
            mode = 'prune'
        elif key == '--test':
            mode = 'test'
        elif key == '--winners':
            mode = 'winners'
        elif key == '--recache':
            mode = 'recache'
        elif key == '--week':
            week = int(val)
        elif key == '--season':
            season = int(val)
        elif key == '--trophy-type':
            assert val in ('pve', 'pvp')
            trophy_type = val


    if mode is None:
        print 'usage: SpinSQL.py MODE'
        print 'Modes:'
        print '    --reset   Destroy and re-create alliance tables'
        print '    --init    Create alliance tables, without disturbing existing ones'
        print '    --prune   Prune stale/invalid data from alliance tables'
        print '    --recache --week N Recalculate all alliance scores for week N'
        print '    --winners --week N --season N --trophy-type TYPE Report Alliance Tournament winners for week N (or season N) and trophy type TYPE (pve or pvp)'
        print '                       ^ if season is missing or < 0, then weekly score is used for standings, otherwise season score is used'
        print '    --test    Run alliance DB test code'
        sys.exit(1)

    client = SQLClient(SpinConfig.config['sqlserver'])

    if mode == 'reset':
        client.drop_tables()
        client.init_tables()
        print 'ALLIANCE DATABASES RESET'
    elif mode == 'init':
        client.init_tables()
        print 'INIT OK'

    elif mode == 'prune':
        import SpinJSON, SpinConfig
        gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

        client.prune_tables(gamedata)

    elif mode == 'recache':
        import SpinJSON, SpinConfig
        gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
        alliance_list = client.get_alliance_list(-1)
        for alliance in alliance_list:
            print 'updating alliance', alliance['id'], 'week', week, 'scores'
            addrs = [(field, freq, period) for field in ('trophies_pvp', 'trophies_pve') for freq in (SQLClient.SCORE_FREQ_WEEKLY,) for period in (week,)]
            #print addrs
            client.update_alliance_score_cache(alliance['id'], addrs, gamedata['alliances']['trophy_weights'][0:gamedata['alliances']['max_members']], {'trophies_pvp':gamedata['trophy_display_offset']['pvp'], 'trophies_pve':gamedata['trophy_display_offset']['pve']})

    elif mode == 'winners':
        import SpinJSON, SpinConfig
        gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

        def display_trophy_count(gamedata, raw, trophy_type):
            return raw + gamedata['trophy_display_offset'][trophy_type]
        def display_alliance_trophy_count(gamedata, raw, trophy_type, nmembers):
            if 0:
                table = gamedata['alliances']['trophy_weights'][0:gamedata['alliances']['max_members']]
                offset = gamedata['trophy_display_offset'][trophy_type]
                alliance_offset = 0
                for i in xrange(nmembers):
                    alliance_offset += table[i] * offset
                return int(raw + alliance_offset)
            return raw

        freq = SQLClient.SCORE_FREQ_SEASON if season >= 0 else SQLClient.SCORE_FREQ_WEEKLY
        freq_name = 'SEASON'  if season >= 0 else 'WEEK'
        period = season if season >= 0 else week

        addr = ('trophies_'+trophy_type, freq, period)
        print '[color="#FFFF00"]TOP ALLIANCES FOR %sWEEK %d[/color]' % ('SEASON %d ' % (season+gamedata['matchmaking']['season_ui_offset']) if season >= 0 else '', week)
        top_alliances = client.get_alliance_score_leaders(addr, 5, 0)
        data = client.get_alliance_info([x['alliance_id'] for x in top_alliances])
        PRIZES = [10*x for x in gamedata['events']['challenge_pvp_ladder_with_prizes']['prizes']] # multiply by 10x to convert from FB Credits to gamebucks # [10000, 5000, 3000]
        WINNERS = 10 # number of players to split the prize within each winning alliance
        commands = []

        USE_DBSERVER = 1
        if USE_DBSERVER:
            import SpinDBClient, SpinConfig
            db_client = SpinDBClient.Client(SpinConfig.config['dbserver']['db_host'],
                                            SpinConfig.config['dbserver']['db_port'],
                                            SpinConfig.config['dbserver']['secret_full'],
                                            lambda x: sys.stdout.write(x))
        else:
            db_client = None

        for i in xrange(len(top_alliances)):
            rank = top_alliances[i]
            info = data[i]

            if not info: continue

            members = client.get_alliance_members(rank['alliance_id'])
            if not members: continue

            print ''
            print '%d) [COLOR="#FFD700"]%s[/COLOR] with %d points (id %5d)' % (rank['rank']+1, info['ui_name'], display_alliance_trophy_count(gamedata, rank['absolute'], trophy_type, len(members)), rank['alliance_id'])

            if i >= len(PRIZES): continue
            alliance_prize = PRIZES[i]

            scores = client.get_player_scores(members, [addr], rank = False)
            scored_members = [{'user_id': members[x], 'absolute': scores[x][0]['absolute'] if scores[x][0] is not None else 0} for x in xrange(len(members))]

            if db_client:
                pc = db_client.player_cache_lookup_batch([member['user_id'] for member in scored_members])
                for j in xrange(len(pc)):
                    if pc[j]:
                        for FIELD in ('facebook_name', 'facebook_first_name', 'player_level', 'home_region', 'ladder_player', 'money_spent'):
                            scored_members[j][FIELD] = pc[j].get(FIELD, 0)

            # note: use player level as tiebreaker, higher level wins
            scored_members.sort(key = lambda x: 100*x['absolute'] + x.get('player_level',1), reverse = True)

            player_prize = alliance_prize / min(len(scored_members), WINNERS)
            print '[COLOR="#FFFFFF"]Winners receive %s Alloy each:[/COLOR]' % player_prize

            for j in xrange(len(scored_members)):
                member = scored_members[j]

                is_tie = (j >= WINNERS and (member['absolute'] == scored_members[WINNERS-1]['absolute']) and (member.get('player_level',1) >= scored_members[WINNERS-1].get('player_level',1)))
                if j < WINNERS or is_tie:
                    my_prize = player_prize
                else:
                    my_prize = 0

                name = member.get('facebook_first_name','Unknown')
                if ('facebook_name' in member) and (' ' in member['facebook_name']) and len(member['facebook_name'].split(' ')[1]) > 0:
                    name += member['facebook_name'].split(' ')[1][0]
#                name = name.encode('utf-8')
                detail = '%s L%2d' % (name, member.get('player_level',1))
                ladder_player = member.get('ladder_player',0)
                if my_prize <= 0: # or (not ladder_player):
                    print "    #%2d %-24s with %5d points does not win %s (id %7d spend $%05.02f)" % (j+1, detail, display_trophy_count(gamedata, member['absolute'], trophy_type), gamedata['store']['gamebucks_ui_name'], member['user_id'], member.get('money_spent',0))
                else:

                    print "    #%2d%s %-24s with %5d points WINS %6d %s (id %7d spend $%05.02f)" % (j+1 if (not is_tie) else WINNERS, '(tie)' if is_tie else '',
                                                                                    detail, display_trophy_count(gamedata, member['absolute'], trophy_type), my_prize, gamedata['store']['gamebucks_ui_name'], member['user_id'], member.get('money_spent',0))
                    commands.append("./check_player.py %d --give-item gamebucks --melt-hours -1 --item-stack %d --give-item-subject 'Tournament Prize' --give-item-body 'Congratulations, here is your Tournament prize for %sWeek %d!'" % (member['user_id'], my_prize, ('Season %d ' % (season+gamedata['matchmaking']['season_ui_offset'])) if season >= 0 else '', week))

        print "COMMANDS"
        print '\n'.join(commands)

    elif mode == 'test':
        client.create_alliance(u'Democratic Mars Union', "We are awesome", 'anyone', 1112, 0, time_now)
        client.create_alliance(u'Mars Federation', "We are cool", 'invite_only', 1113, 0, time_now)
        client.create_alliance(u'Temp Alliance', "We are dead", 'anyone', 1120, 0, time_now)

        for num in xrange(6):
            client.create_alliance(u'Temp2 Alliance %d' % num, "We are dead", 'anyone', 1121+num, 0, time_now)

        MAX_MEMBERS = 2
        print "OK" if client.join_alliance(1112, 1, time_now, MAX_MEMBERS) else "FAIL"
        print "OK" if client.join_alliance(1112, 1, time_now, MAX_MEMBERS) else "FAIL"
        print "OK" if client.join_alliance(1115, 1, time_now, MAX_MEMBERS) else "FAIL"
        print "OK" if client.join_alliance(1114, 1, time_now, MAX_MEMBERS) else "FAIL"


        print "OK" if client.join_alliance(1113, 2, time_now, MAX_MEMBERS) else "FAIL"
        client.leave_alliance(1113)
        print "OK" if client.join_alliance(1113, 2, time_now, MAX_MEMBERS) else "FAIL"
        client.send_alliance_invite(1113, 1113, 2, time_now, time_now+300)
        print "OK" if client.join_alliance(1113, 2, time_now, MAX_MEMBERS) else "FAIL"

        print "OK" if client.join_alliance(1120, 9, time_now, MAX_MEMBERS) else "FAIL"
        print "OK" if client.join_alliance(1121, 9, time_now, MAX_MEMBERS) else "FAIL"
        print "OK" if client.join_alliance(1120, 3, time_now, MAX_MEMBERS) else "FAIL"
        client.leave_alliance(1120)
        client.kick_from_alliance(1112, 1, 1115)
        print "OK" if client.join_alliance(1115, 1, time_now, MAX_MEMBERS) else "FAIL"

        print "MOD OK" if client.modify_alliance(1, 1112, ui_name = 'New Democratic Mars Union', ui_description = "We are newer")[0] else "MOD FAIL"
        print "MOD OK" if client.modify_alliance(1, 1114, ui_name = 'New Democratic Mars Union2', ui_description = "We are newer2")[0] else "MOD FAIL"

        print "ALLIANCE LIST (unlimited)", client.get_alliance_list(-1)
        print "ALLIANCE LIST (limited)", client.get_alliance_list(1)
        print "ALLIANCE LIST (open join only)", client.get_alliance_list(1, open_join_only = True)
        print "ALLIANCE INFO (single)", client.get_alliance_info(2, reason = 'test')
        print "ALLIANCE INFO (multi)\n", '\n'.join(map(repr, client.get_alliance_info([1,2,3], reason = 'test2')))
        print "ALLIANCE MEMBERS", client.get_alliance_members(2)
        print "MY ALLIANCE (single)", client.get_users_alliance(1112, reason = 'hello')
        print "MY ALLIANCE (single)", client.get_users_alliance(1116, reason = 'hello')
        print "MY ALLIANCE (multi)", client.get_users_alliance([1112,1113,1115], reason = 'hello')
        print "SEARCH (unlimited)", client.search_alliance('mar')
        print "SEARCH (limited)", client.search_alliance('', limit = 1)

        print "TEMP"
        cur = client.con.cursor(SpinMySQLdb.cursors.DictCursor)
        cur.execute("SELECT * FROM alliance_members")
        print cur.fetchall()

        client.add_recent_attack(1112, 1115, 0.1, time_now - 50)
        client.add_recent_attack(1113, 1115, 0.2, time_now - 25)
        client.add_recent_attack(1119, 1115, 0.3, time_now - 25)
        print "ATTACKS any", client.get_recent_attacks(None, 1115, [time_now - 100, time_now])
        print "ATTACKS single", client.get_recent_attacks([1112], 1115, [time_now - 100, time_now])
        print "ATTACKS multi", client.get_recent_attacks([1112,1113,1114], 1115, [time_now - 100, time_now])

        client.update_player_scores(1112, [[('quarry_resources_valles256', SQLClient.SCORE_FREQ_WEEKLY, 11), 333],
                                           [('quarry_resources_valles256', SQLClient.SCORE_FREQ_SEASON, 2), 444],
                                           [('damage_inflicted', SQLClient.SCORE_FREQ_WEEKLY, 11), 444],
                                           [('damage_inflicted', SQLClient.SCORE_FREQ_WEEKLY, 11), 555],
                                           ])
        addr = ('damage_inflicted', SQLClient.SCORE_FREQ_WEEKLY, 11)
        client.update_player_scores(1113, [[addr, 666]])
        print "UPDATE (changed)", client.update_player_scores(1115, [[addr, 888]])
        print "UPDATE (unchanged)", client.update_player_scores(1115, [[addr, 888]])

        print "PLAYER SCORES", client.get_player_scores([1112,1115], [addr], rank = False)
        print "PLAYER RANKS", client.get_player_scores([1112,1115], [addr], rank = True)

        print "CACHE", client.update_alliance_score_cache(1, [addr], [0.5, 0.4], {})
        print "LEADERS", client.get_alliance_score_leaders(addr, 10, 0)
        print "ALLIANCE SCORE", client.get_alliance_score(1, addr, rank = True)

        print "REQUEST DONATION", client.request_unit_donation(1112, 1, time_now, 1234, 10, 100)
        print "MAKE DONATION", client.make_unit_donation(1112, 1, 1234, [10])
        print "MAKE DONATION", client.make_unit_donation(1112, 1, 1234, [100])
        print "MAKE DONATION", client.make_unit_donation(1112, 1, 1234, [100,50,10])

