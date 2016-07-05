#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Server-side handlers for CONTROLAPI calls originated by tools like cgipcheck (PCHECK).

# These have both "online" and "offline" execution modes. The "online" mode operates
# on LivePlayer objects with active sessions, and the "offline" modes manipulate raw
# JSON structures. This allows all methods to work regardless of whether the affected
# player is currently logged in or not.

import SpinJSON
import SpinConfig
import random
#import copy
from Region import Region
import SpinNoSQLLockManager
from Raid import recall_squad, RecallSquadException, \
     army_unit_is_mobile, army_unit_spec, army_unit_is_alive, army_unit_hp, \
     calc_max_cargo, resolve_raid, make_battle_summary, get_denormalized_summary_props_from_pcache
import ResLoot
from Predicates import read_predicate

# encapsulate the return value from CONTROLAPI support calls, to be interpreted by cgipcheck.html JavaScript
# basically, we return a JSON dictionary that either has a "result" (for successful calls) or an "error" (for failures).
# there is also a "kill_session" option that tells the server to (asynchronously) log the player out after we return.
# and an "async" Deferred to hold the CONTROLAPI request until an async operation finishes
class ReturnValue(object):
    def __init__(self, result = None, error = None, http_status = None, retry_after = None, kill_session = False, async = None):
        assert (result is not None) or (error is not None) or (async is not None)
        self.result = result
        self.error = error
        self.http_status = http_status
        self.retry_after = retry_after
        self.kill_session = kill_session
        self.async = async
    def as_body(self):
        assert not self.async
        if self.error:
            ret = {'error':self.error}
            # optional additional properties for an error
            if self.retry_after:
                ret['retry_after'] = self.retry_after
        else:
            ret = {'result':self.result}
        return SpinJSON.dumps(ret, newline = True)

class Handler(object):
    # flags that userdb/playerdb entries need to be provided
    # can be turned off to optimize methods that don't need access to one of them
    need_user = True
    need_player = True
    read_only = False
    want_raw = False # prefer the raw strings instead of parsed JSON for offline execution

    def __init__(self, time_now, user_id, gamedata, gamesite, args):
        self.time_now = time_now
        self.user_id = user_id
        self.gamedata = gamedata
        self.gamesite = gamesite
        self.args = args

    def get_log_entry(self):
        # reverse lookup to find out what our method name is
        call_name = filter(lambda x: x[1] == self.__class__, methods.iteritems())[0][0]
        # clean out the "args" for logging
        log_args = self.args.copy()
        if 'ui_reason' in log_args:
            ui_reason = log_args['ui_reason']
            del log_args['ui_reason']
        else:
            ui_reason = None
        if 'spin_user' in log_args:
            spin_user = log_args['spin_user']
            del log_args['spin_user']
        else:
            spin_user = 'unknown'
        if 'user_id' in log_args: del log_args['user_id']
        entry = {'time': self.time_now,
                 'spin_user': spin_user,
                 'method': call_name}
        if ui_reason: entry['ui_reason'] = ui_reason
        if log_args: entry['args'] = log_args
        return entry

    # wrap "execute" functions to perform logging
    def exec_online(self, session, retmsg):
        ret = self.do_exec_online(session, retmsg)
        log_entry = self.get_log_entry()
        if log_entry:
            if 'customer_support' not in session.player.history:
                session.player.history['customer_support'] = []
            session.player.history['customer_support'].append(log_entry)
        return ret
    def exec_offline(self, user, player):
        ret = self.do_exec_offline(user, player)
        log_entry = self.get_log_entry()
        if log_entry:
            if 'customer_support' not in player['history']:
                player['history']['customer_support'] = []
            player['history']['customer_support'].append(log_entry)
        return ret

    # optional execution method that can be called if want_raw is true
    def exec_offline_raw(self, user_raw, player_raw): raise Exception('not implemented')

    # exec_offline() can call this to re-use exec_online() for an offline player by parsing the JSON into live objects
    # assumes the existence of a method with the signature "exec_all(self, session, retmsg, user, player)"
    # where session and retmsg will be None in the offline case
    def _exec_offline_as_online(self, json_user, json_player):
        # parse the JSON into actual User/Player instances
        player = self.gamesite.player_table.unjsonize(json_player, None, self.user_id, False)
        user = self.gamesite.user_table.unjsonize(json_user, self.user_id)

        ret = self.exec_all(None, None, user, player)

        # now mutate the JSON versions
        new_json_user = self.gamesite.user_table.jsonize(user)
        new_json_player = self.gamesite.player_table.jsonize(player)

        # make the update as atomic as possible
        json_user.clear(); json_user.update(new_json_user)
        json_player.clear(); json_player.update(new_json_player)

        return ret

class HandleGetRaw(Handler):
    read_only = True
    def __init__(self, *args, **kwargs):
        Handler.__init__(self, *args, **kwargs)
        self.stringify = bool(int(self.args.get('stringify',False)))
        # if caller wants stringified result, we can operate faster by skipping the parsing step
        self.want_raw = self.stringify

    def format_from_json(self, result):
        if self.stringify:
            result = SpinJSON.dumps(result, pretty = True, newline = True, size_hint = 1024*1024, double_precision = 5)
        return result
    def format_from_raw(self, result):
        if not self.stringify:
            result = SpinJSON.loads(result)
        return result

class HandleGetRawPlayer(HandleGetRaw):
    need_user = False
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        player_json = self.gamesite.player_table.jsonize(session.player)
        return ReturnValue(result = self.format_from_json(player_json))
    def exec_offline(self, user, player):
        return ReturnValue(result = self.format_from_json(player))
    def exec_offline_raw(self, user_raw, player_raw):
        assert self.stringify
        return ReturnValue(result = player_raw)
class HandleGetRawUser(HandleGetRaw):
    need_player = False
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        user_json = self.gamesite.user_table.jsonize(session.user)
        return ReturnValue(result = self.format_from_json(user_json))
    def exec_offline(self, user, player):
        return ReturnValue(result = self.format_from_json(user))
    def exec_offline_raw(self, user_raw, player_raw):
        assert self.stringify
        return ReturnValue(result = user_raw)

class HandleBan(Handler):
    need_user = False
    def do_exec_online(self, session, retmsg):
        session.player.banned_until = self.time_now + int(self.args.get('ban_time',self.gamedata['server']['default_ban_time']))
        return ReturnValue(result = 'ok', kill_session = True)
    def do_exec_offline(self, user, player):
        player['banned_until'] = self.time_now + int(self.args.get('ban_time',self.gamedata['server']['default_ban_time']))
        return ReturnValue(result = 'ok')
class HandleUnban(Handler):
    need_user = False
    def do_exec_online(self, session, retmsg):
        session.player.banned_until = -1
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        player['banned_until'] = -1
        return ReturnValue(result = 'ok')

class HandleApplyLockout(Handler):
    def __init__(self, *args, **kwargs):
        Handler.__init__(self, *args, **kwargs)
        self.lockout_time = int(self.args['lockout_time'])
        self.lockout_message = self.args.get('lockout_message', 'Account Under Maintenance')
    def do_exec_online(self, session, retmsg):
        session.player.lockout_until = self.time_now + self.lockout_time
        session.player.lockout_message = self.lockout_message
        return ReturnValue(result = 'ok', kill_session = True)
    def do_exec_offline(self, user, player):
        player['lockout_until'] = self.time_now + self.lockout_time
        player['lockout_message'] = self.lockout_message
        return ReturnValue(result = 'ok')
class HandleClearLockout(Handler):
    def do_exec_online(self, session, retmsg):
        session.player.lockout_until = -1
        session.player.last_lockout_end = self.time_now # clears history
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        player['lockout_until'] = -1
        player['last_lockout_end'] = self.time_now
        return ReturnValue(result = 'ok')

class HandleClearAlias(Handler):
    def update_player_cache_ui_name(self, new_ui_name):
        self.gamesite.pcache_client.player_cache_update(self.user_id, {'ui_name': new_ui_name,
                                                                       'ui_name_searchable': new_ui_name.lower()})

    # Note: this does NOT release it in the unique aliases database!
    def do_exec_online(self, session, retmsg):
        session.player.alias = None
        new_ui_name = session.user.get_real_name()
        self.update_player_cache_ui_name(new_ui_name)
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        if 'alias' in player: del player['alias']
        # needs to match User.get_real_name()
        if user.get('kg_username'):
            new_ui_name = user['kg_username']
        elif user.get('ag_username'):
            new_ui_name = user['ag_username']
        elif user.get('bh_username'):
            new_ui_name = user['bh_username']
        elif user.get('facebook_first_name'):
            new_ui_name = user['facebook_first_name']
        elif user.get('facebook_name'):
            new_ui_name = user['facebook_name'].split(' ')[0]
        else:
            new_ui_name = 'Unknown(user)'
        self.update_player_cache_ui_name(new_ui_name)
        return ReturnValue(result = 'ok')

class HandleMarkUninstalled(Handler):
    def do_exec_online(self, session, retmsg):
        session.user.uninstalled = 1
        self.gamesite.pcache_client.player_cache_update(self.user_id, {'uninstalled': 1})
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        user['uninstalled'] = 1
        self.gamesite.pcache_client.player_cache_update(self.user_id, {'uninstalled': 1})
        return ReturnValue(result = 'ok')

class HandleCheckIdle(Handler):
    # trigger idle check at next chance
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        session.player.idle_check.last_end_playtime = -1
        return ReturnValue(result = 'ok')
    def exec_offline(self, user, player):
        if 'idle_check' not in player: player['idle_check'] = {}
        player['idle_check']['last_end_playtime'] = -1
        return ReturnValue(result = 'ok')

class HandleRecordAltLogin(Handler):
    def __init__(self, *args, **kwargs):
        Handler.__init__(self, *args, **kwargs)
        self.other_id = int(self.args['other_id'])
        if 'ip' in self.args:
            self.ip = str(self.args['ip'])
        else:
            self.ip = None
        assert self.other_id != self.user_id
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        session.player.possible_alt_record_login(self.other_id, ip = self.ip)
        return ReturnValue(result = 'ok')

    def exec_offline(self, user, player):
        # reimplements Player.possible_alt_record_login()
        key = str(self.other_id)
        if ('known_alt_accounts' not in player) or type(player['known_alt_accounts']) is not dict:
            player['known_alt_accounts'] = {}

        alt_data = player['known_alt_accounts'].get(key, None)

        if alt_data is None:
            # move the ID from possible_alt_accounts to known_alt_accounts once detect_threshold logins have happened
            detect_threshold = self.gamedata['server']['alt_detect_logins']
            if detect_threshold >= 0:
                if 'possible_alt_accounts' not in player: player['possible_alt_accounts'] = {}
                player['possible_alt_accounts'][key] = player['possible_alt_accounts'].get(key, 0) + 1

                if player['possible_alt_accounts'][key] >= detect_threshold:
                    alt_data = player['known_alt_accounts'][key] = {}
                    del player['possible_alt_accounts'][key]

        if alt_data is not None:
            alt_data['logins'] = alt_data.get('logins',0) + 1
            alt_data['last_login'] = self.time_now # record time of last simultaneous login
            if self.ip:
                alt_data['last_ip'] = self.ip
        return ReturnValue(result = 'ok')

class HandleIgnoreAlt(Handler):
    def do_exec_online(self, session, retmsg):
        other_id = int(self.args['other_id'])
        if str(other_id) not in session.player.known_alt_accounts:
            session.player.known_alt_accounts[str(other_id)] = {'logins':0}
        session.player.known_alt_accounts[str(other_id)]['ignore'] = 1
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        other_id = int(self.args['other_id'])
        if ('known_alt_accounts' not in player) or type(player['known_alt_accounts']) is not dict:
            player['known_alt_accounts'] = {}
        if str(other_id) not in player['known_alt_accounts']:
            player['known_alt_accounts'][str(other_id)] = {'logins':0}
        player['known_alt_accounts'][str(other_id)]['ignore'] = 1
        return ReturnValue(result = 'ok')

class HandleUnignoreAlt(Handler):
    def do_exec_online(self, session, retmsg):
        other_id = int(self.args['other_id'])
        if str(other_id) in session.player.known_alt_accounts and \
           'ignore' in session.player.known_alt_accounts[str(other_id)]:
            del session.player.known_alt_accounts[str(other_id)]['ignore']
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        other_id = int(self.args['other_id'])
        if ('known_alt_accounts' in player) and type(player['known_alt_accounts']) is dict and \
           str(other_id) in player['known_alt_accounts'] and \
           'ignore' in player['known_alt_accounts'][str(other_id)]:
            del player['known_alt_accounts'][str(other_id)]['ignore']
        return ReturnValue(result = 'ok')

class HandleMakeDeveloper(Handler):
    def do_exec_online(self, session, retmsg):
        session.user.developer = session.player.developer = 1 # note: update Player as well as User
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        user['developer'] = 1
        return ReturnValue(result = 'ok')
class HandleUnmakeDeveloper(Handler):
    def do_exec_online(self, session, retmsg):
        session.user.developer = session.player.developer = None # note: update Player as well as User
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        if 'developer' in user: del user['developer']
        return ReturnValue(result = 'ok')

class HandleChatOfficial(Handler):
    def do_exec_online(self, session, retmsg):
        session.player.chat_official = 1
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        player['chat_official'] = 1
        return ReturnValue(result = 'ok')
class HandleChatUnofficial(Handler):
    def do_exec_online(self, session, retmsg):
        session.player.chat_official = None
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        if 'chat_official' in player: del player['chat_official']
        return ReturnValue(result = 'ok')

class HandleChatBlockOrUnblock(Handler):
    PREF_KEY = 'force_blocked_users' # key in player preferences for blocked user list
    def do_exec_online(self, session, retmsg):
        other_id = int(self.args['other_id'])
        assert other_id != session.player.user_id
        if session.player.player_preferences is None:
            session.player.player_preferences = {}
        self._do(session.player.player_preferences, other_id)
        retmsg.append(["PUSH_PREFERENCES", session.player.player_preferences])
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        other_id = int(self.args['other_id'])
        assert other_id != user['user_id']
        if ('player_preferences' not in player) or (player['player_preferences'] is None):
            player['player_preferences'] = {}
        self._do(player['player_preferences'], other_id)
        return ReturnValue(result = 'ok')

class HandleChatBlock(HandleChatBlockOrUnblock):
    def _do(self, prefs, other_id):
        if self.PREF_KEY not in prefs:
            prefs[self.PREF_KEY] = []
        if other_id not in prefs[self.PREF_KEY]:
            prefs[self.PREF_KEY].append(other_id)
class HandleChatUnblock(HandleChatBlockOrUnblock):
    def _do(self, prefs, other_id):
        if self.PREF_KEY in prefs:
            if other_id in prefs[self.PREF_KEY]:
                prefs[self.PREF_KEY].remove(other_id)

class HandleClearCooldown(Handler):
    def do_exec_online(self, session, retmsg):
        if self.args['name'] == 'ALL':
            session.player.cooldowns = {}
        else:
            if self.args['name'] in session.player.cooldowns:
                del session.player.cooldowns[self.args['name']]
        retmsg.append(["COOLDOWNS_UPDATE", session.player.cooldowns])
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        if self.args['name'] == 'ALL':
            player['cooldowns'] = {}
        else:
            if self.args['name'] in player['cooldowns']:
                del player['cooldowns'][self.args['name']]
        return ReturnValue(result = 'ok')

class HandleCooldownTogo(Handler):
    read_only = True
    need_user = False
    # note: returns duration remaining
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        return ReturnValue(result = session.player.cooldown_togo(self.args['name']))
    def exec_offline(self, user, player):
        togo = -1
        if self.args['name'] in player['cooldowns']:
            togo = max(-1, player['cooldowns'][self.args['name']]['end'] - self.time_now)
        return ReturnValue(result = togo)

class HandleCooldownActive(Handler):
    read_only = True
    need_user = False
    # note: returns number of active stacks
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        return ReturnValue(result = session.player.cooldown_active(self.args['name']))
    def exec_offline(self, user, player):
        stacks = 0
        if self.args['name'] in player['cooldowns']:
            cd = player['cooldowns'][self.args['name']]
            if cd['end'] > self.time_now:
                stacks = cd.get('stack', 1)
        return ReturnValue(result = stacks)

class HandleTriggerCooldown(Handler):
    need_user = False
    def __init__(self, *args, **kwargs):
        Handler.__init__(self, *args, **kwargs)
        self.cd_name = self.args['name']
        self.duration = int(self.args['duration'])
        self.add_stack = int(self.args['add_stack']) if 'add_stack' in self.args else -1
        self.cd_data = SpinJSON.loads(self.args['data']) if 'data' in self.args else None
    def do_exec_online(self, session, retmsg):
        session.player.cooldown_trigger(self.cd_name, self.duration, add_stack = self.add_stack, data = self.cd_data)
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        if self.duration > 0:
            stack = 1
            if self.add_stack > 0 and self.cd_name in player['cooldowns'] and player['cooldowns'][self.cd_name]['end'] > self.time_now:
                stack += player['cooldowns'][self.cd_name].get('stack',1)

            cd = {'start': self.time_now, 'end': self.time_now + self.duration}
            if stack > 1:
                cd['stack'] = stack
            if self.cd_data:
                cd['data'] = self.cd_data
            player['cooldowns'][self.cd_name] = cd

        return ReturnValue(result = 'ok')

class HandleApplyOrRemoveAura(Handler):
    def __init__(self, *args, **kwargs):
        Handler.__init__(self, *args, **kwargs)
        if 'data' in self.args:
            self.aura_data = SpinJSON.loads(self.args['data'])
            assert isinstance(self.aura_data, dict)
        else:
            self.aura_data = None

class HandleRemoveAura(HandleApplyOrRemoveAura):
    def do_exec_online(self, session, retmsg):
        session.player.remove_aura(session, retmsg, self.args['aura_name'], force = True, data = self.aura_data)
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        to_remove = []
        for aura in player.get('player_auras',[]):
            if aura['spec'] == self.args['aura_name'] and \
               (self.aura_data is None or \
                all(aura.get('data',{}).get(k,None) == v for k,v in self.aura_data.iteritems())):
                to_remove.append(aura)
        for aura in to_remove:
            player['player_auras'].remove(aura)
        return ReturnValue(result = 'ok')

class HandleApplyAura(HandleApplyOrRemoveAura):
    def do_exec_online(self, session, retmsg):
        session.player.apply_aura(self.args['aura_name'], duration = int(self.args.get('duration','-1')), ignore_limit = True, data = self.aura_data)
        session.player.stattab.send_update(session, retmsg) # also sends PLAYER_AURAS_UPDATE
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        assert self.args['aura_name'] in self.gamedata['auras']
        found = False
        if 'player_auras' not in player: player['player_auras'] = []
        for aura in player.get('player_auras',[]):
            if aura['spec'] == self.args['aura_name'] and \
               (self.aura_data is None or \
                all(aura.get('data',{}).get(k,None) == v for k,v in self.aura_data.iteritems())):
                found = True
                if 'duration' in self.args:
                    duration = int(self.args['duration'])
                    assert duration > 0 # can't handle infinite durations
                    aura['end_time'] = max(aura.get('end_time',-1), self.time_now + duration)
                # overwrite data
                if self.aura_data is None and 'data' in aura: del aura['data']
                if self.aura_data is not None: aura['data'] = self.aura_data
                break
        if not found:
            aura = {'spec': self.args['aura_name'], 'start_time': self.time_now}
            if 'duration' in self.args:
                duration = int(self.args['duration'])
                assert duration > 0 # can't handle infinite durations
                aura['end_time'] = self.time_now + duration
            if self.aura_data is not None:
                aura['data'] = self.aura_data
            player['player_auras'].append(aura)
        return ReturnValue(result = 'ok')

class HandleAuraActive(Handler):
    read_only = True
    need_user = False
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        return ReturnValue(result = self.aura_active(session.player.player_auras, self.args['aura_name']))
    def exec_offline(self, user, player):
        return ReturnValue(result = self.aura_active(player.get('player_auras', []), self.args['aura_name']))
    def aura_active(self, player_auras, aura_name):
        for aura in player_auras:
            if aura.get('end_time',-1) > 0 and aura['end_time'] < self.time_now: continue
            if aura['spec'] == aura_name:
                return True
        return False

class HandleChatGag(Handler):
    need_user = False
    def __init__(self, *args, **kwargs):
        Handler.__init__(self, *args, **kwargs)
        if 'duration' in self.args:
            self.duration = int(self.args['duration'])
        else:
            self.duration = -1
    def do_exec_online(self, session, retmsg):
        if session.player.apply_aura('chat_gagged', duration = self.duration, ignore_limit = True):
            session.player.stattab.send_update(session, session.outgoing_messages)
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        player['player_auras'] = filter(lambda x: x['spec'] != 'chat_gagged', player.get('player_auras',[]))
        new_aura = {'spec':'chat_gagged', 'start_time': self.time_now}
        if self.duration > 0:
            new_aura['end_time'] = self.time_now + self.duration
        player['player_auras'].append(new_aura)
        return ReturnValue(result = 'ok')

class HandleChatUngag(Handler):
    AURAS = ('chat_gagged', 'chat_warned')
    need_user = False
    def do_exec_online(self, session, retmsg):
        for aura_name in self.AURAS:
            session.player.remove_aura(session, session.outgoing_messages, aura_name, force = True)
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        player['player_auras'] = filter(lambda x: x['spec'] not in self.AURAS, player.get('player_auras',[]))
        return ReturnValue(result = 'ok')

class MessageSender(Handler):
    need_user = False
    def get_msg_id(self): return str(self.time_now)+'-'+str(int(1000*random.random()))
    def make_message(self): raise Exception('implement this')
    def do_exec_online(self, session, retmsg):
        session.player.mailbox_append(self.make_message(), safe_not_to_copy = True)
        session.player.send_mailbox_update(retmsg)
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        if 'mailbox' not in player: player['mailbox'] = []
        player['mailbox'].append(self.make_message())
        return ReturnValue(result = 'ok')

class HandleGiveItem(MessageSender):
    def make_message(self):
        if self.args['spec'] not in self.gamedata['items']:
            raise Exception('Invalid item name (item not found in gamedata.items): %r' % self.args['spec'])
        item_spec = self.gamedata['items'][self.args['spec']]
        item = {'spec':self.args['spec']}
        stack = int(self.args.get('stack','1'))
        level = int(self.args.get('level','1'))
        if stack > 1: item['stack'] = stack
        if level > 1:
            assert 'max_level' in item_spec and level <= item_spec['max_level']
            item['level'] = level
        expire_time = int(self.args.get('expire_time','-1'))
        if expire_time > 0: item['expire_time'] = expire_time
        if self.args.get('undiscardable',False): item['undiscardable'] = 1
        if self.args.get('log',False): item['log'] = self.args['log']
        return {'type':'mail',
                'expire_time': expire_time,
                'msg_id': self.get_msg_id(),
                'from_name': self.args.get('message_sender', 'Customer Support'),
                'to': [self.user_id],
                'subject':self.args.get('message_subject', 'Special Item'),
                'attachments': [item],
                'body': self.args.get('message_body', 'The Customer Support team sent us a special item.\n\nClick the item to collect it.') + \
                ('\n\nIMPORTANT: Activate this item quickly! Its time is limited.' if expire_time > 0 else '')}
class HandleSendMessage(MessageSender):
    def make_message(self):
        expire_time = (int(self.args['expire_time']) if 'expire_time' in self.args else self.time_now + 30*24*60*60)
        return {'type':'mail',
                'expire_time': expire_time,
                'msg_id': self.get_msg_id(),
                'from_name': self.args.get('message_sender', 'Customer Support'),
                'to': [self.user_id],
                'subject':self.args.get('message_subject', 'Support Issue'),
                'body': self.args['message_body']}

class HandleSquadDockUnits(Handler):
    need_user = False
    def __init__(self, *args, **kwargs):
        Handler.__init__(self, *args, **kwargs)
        self.squad_id = int(self.args['squad_id'])
        self.state_list = SpinJSON.loads(self.args['units']) if 'units' in self.args else []
        self.cargo = SpinJSON.loads(self.args['cargo']) if 'cargo' in self.args else None
        self.cargo_source = SpinJSON.loads(self.args['cargo_source']) if 'cargo_source' in self.args else None
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        session.player.squad_dock_units(self.squad_id, self.state_list, cargo = self.cargo, cargo_source = self.cargo_source, force = False) # shouldn't need to force here
        if self.cargo:
            session.deferred_player_state_update = True
        session.send([["SQUADS_UPDATE", session.player.squads]])
        # note: we don't send any army updates here, because the player "should" know about the units from a previous map ping
        return ReturnValue(result = 'ok')
    def exec_offline(self, user, player):
        # DO accept units from unknown squads, but put them into reserves
        squad = player['squads'].get(str(self.squad_id), {})
        home_objects_by_id = dict((obj['obj_id'], obj) for obj in player['my_base'])
        new_obj_list = []

        for state in self.state_list:
            if ('kind' in state and state['kind'] != 'mobile') or ('owner_id' in state and state['owner_id'] != self.user_id):
                self.gamesite.exception_log.event(self.time_now, 'player %d HandleSquadDockUnits bad state: %r' % (self.user_id, state))
                continue

            # force items with squad_ids not in player.squads into reserves, to avoid accidentally giving the player more squads than allowed
            if 'squad_id' in state:
                if state['squad_id'] != self.squad_id or str(state['squad_id']) not in player['squads']:
                    state['squad_id'] = -1

            if ('obj_id' in state):
                if state['obj_id'] in home_objects_by_id:
                    if self.gamedata['server'].get('log_nosql',0) >= 2:
                        self.gamesite.exception_log.event(self.time_now, 'player %d HandleSquadDockUnits %d already has object %s at home, skipping' % \
                                                          (self.user_id, self.squad_id, state['obj_id']))
                    continue
                home_objects_by_id[state['obj_id']] = state

            # slightly mutate object state to conform NoSQL format to playerdb format
            assert 'spec' in state
            for FIELD in ('owner_id','kind'):
                if FIELD in state: del state[FIELD]
            if 'xy' not in state: state['xy'] = [0,0] # will be fixed on next load

            new_obj_list.append(state)

        player['my_base'] += new_obj_list # append atomically

        # add resources - code path for this is complex to implement off-line, so queue as message
        # (could re-implement later as a totally off-line operation though)
        if self.cargo:
            self.gamesite.msg_client.msg_send([{'to': [self.user_id], 'type':'squad_cargo', 'expire_time': self.time_now + 7*86400,
                                                'squad_id': self.squad_id, 'cargo': self.cargo, 'cargo_source': self.cargo_source
                                                }])

        # update player.squads cache to show the squad as at home now
        for FIELD in ('map_loc', 'map_path', 'travel_speed', 'raid', 'max_cargo'):
            if FIELD in squad: del squad[FIELD]

        return ReturnValue(result = 'ok')

class HandleResolveHomeRaid(Handler):

    def __init__(self, *args, **kwargs):
        Handler.__init__(self, *args, **kwargs)
        self.region_id = self.args['region_id']
        self.squad_base_ids = SpinJSON.loads(self.args['squad_base_ids'])
        self.loc = SpinJSON.loads(self.args['loc'])

        # remember some data needed for the offline FB notification
        self.attacker_ui_name = 'Unknown'
        self.raid_mode = None

    def query_raid_squads(self):
        # XXXXXXRAIDGUARDS
        raid_squads = list(self.gamesite.nosql_client.get_map_features_by_loc(self.region_id, self.loc))
        raid_squads = filter(lambda feature: feature['base_type'] == 'squad' and \
                             feature.get('raid') and \
                             feature['base_landlord_id'] != self.user_id and \
                             feature['base_id'] in self.squad_base_ids, raid_squads)
        # XXX for now - we can fix this later
        assert len(raid_squads) == 1
        return raid_squads

    def get_pvp_balance_online(self, player, other_pcinfo, my_alliance, other_alliance):
        his_level = other_pcinfo.get('player_level',1)
        my_level_range = player.attackable_level_range()

        if my_alliance >= 0 and self.gamedata['prevent_same_alliance_attacks'] and other_alliance == my_alliance:
            return 'CANNOT_ATTACK_SAME_ALLIANCE'

        if (self.region_id in self.gamedata['regions']) and (not self.gamedata['regions'][self.region_id].get('enable_pvp_level_gap', True)):
            return None # region has no limits

        if (self.gamedata['matchmaking']['revenge_time'] > 0) and player.cooldown_active('revenge_defender:%d' % other_pcinfo['user_id']):
            return None # revenge - no limit

        if (my_level_range[0]>=0) and (his_level < my_level_range[0]):
            # we are much stronger
            return 'CANNOT_ATTACK_WEAKER_PLAYER'

        elif (my_level_range[1]>=0) and (his_level > my_level_range[1]):
            # we are much weaker - prevent attack
            return 'CANNOT_ATTACK_STRONGER_PLAYER'

        return None

    def recall_squads(self, raid_squads):
        # *ASSUMES SQUAD LOCKS ARE TAKEN*
        for squad in raid_squads:
            try:
                recall_squad(self.gamesite.nosql_client, self.region_id, squad, self.time_now)
            except RecallSquadException as e:
                self.gamesite.exception_log.event(self.time_now, str(e))
                continue

    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        if session.home_base and session.has_attacked:
            # currently defending against AI attack - punt
            return ReturnValue(result = 'CANNOT_ATTACK_PLAYER_WHILE_ALREADY_UNDER_ATTACK')
        return self.exec_all(session, retmsg, session.user, session.player)

    def exec_all(self, session, retmsg, defender_user, defender_player):
        # note: if defender is offline, session and retmsg can be None, and will be ignored

        assert defender_player.home_region == self.region_id and defender_player.my_home.base_map_loc == self.loc
        if defender_player.has_damage_protection():
            return ReturnValue(result = 'CANNOT_ATTACK_PLAYER_UNDER_PROTECTION')

        affected = defender_player.unit_repair_tick()
        if affected and session:
            for obj in affected: session.deferred_object_state_updates.add(obj)
            session.send([["UNIT_REPAIR_UPDATE", defender_player.unit_repair_queue]])

        for obj in defender_player.home_base_iter():
            if obj.is_building():
                # simulate passage of time for repairs, and also
                # kickstart research and upgrading if it got stopped for some reason, and the building is at full health
                obj.update_all()

        with SpinNoSQLLockManager.LockManager(self.gamesite.nosql_client) as lock_manager:

            for squad_base_id in self.squad_base_ids:
                if not lock_manager.acquire(self.region_id, squad_base_id):
                    # can't get a lock
                    return ReturnValue(result = 'HARMLESS_RACE_CONDITION')

            raid_squads = self.query_raid_squads()
            if not raid_squads: # no squads found
                return ReturnValue(result = 'HARMLESS_RACE_CONDITION')

            temp = self.gamesite.sql_client.get_users_alliance([self.user_id,] + [squad['base_landlord_id'] for squad in raid_squads], reason = 'resolve_home_raid')
            my_alliance, raid_alliances = temp[0], temp[1:]

            my_pcinfo = self.gamesite.gameapi.get_player_cache_props(defender_user, defender_player, my_alliance)
            raid_pcinfos = self.gamesite.nosql_client.player_cache_lookup_batch([squad['base_landlord_id'] for squad in raid_squads], reason = 'resolve_home_raid')

            i = 0
            for squad, raid_pcinfo, raid_alliance in zip(raid_squads[:], raid_pcinfos[:], raid_alliances[:]):
                balance_error = self.get_pvp_balance_online(defender_player, raid_pcinfo, my_alliance, raid_alliance)
                if balance_error:
                    del raid_squads[i]
                    del raid_alliances[i]
                    del raid_pcinfos[i]
                    if not raid_squads:
                        return ReturnValue(balance_error)
                    i -= 1
                i += 1

            raid_mode = 'scout' if all(squad['raid'] == 'scout' for squad in raid_squads) else 'attack'
            self.raid_mode = raid_mode # remember for offline notification

            # set up ladder state

            attacker_sticky_alliances = set(filter(lambda a: a >= 0, raid_alliances + sum((x.get('sticky_alliances',[]) for x in raid_squads), [])))
            defender_sticky_alliances = set(defender_player.get_sticky_alliances())

            if raid_mode != 'scout' and \
               all(squad.get('ladderable',True) for squad in raid_squads) and \
               all(('ladder_points' in squad) for squad in raid_squads) and \
               not bool(attacker_sticky_alliances.intersection(defender_sticky_alliances)) and \
               read_predicate(self.gamedata['regions'][self.region_id].get('ladder_on_map_if_defender',{'predicate':'ALWAYS_TRUE'})).is_satisfied(defender_player, None) and \
               defender_player.my_home.calc_base_damage() < self.gamedata['matchmaking']['ladder_win_damage']:
                # note: this is a classmethod, not associated with this particular player
                delta = defender_player.ladder_points() - raid_squads[0]['ladder_points']
                ladder_state = defender_player.create_ladder_state_points_scaled_by_trophy_delta(raid_squads[0]['base_landlord_id'], self.user_id, delta,
                                                                                                 self.gamedata['matchmaking']['ladder_point_on_map_table'])
            else:
                ladder_state = None

            raid_stattabs = [squad.get('player_stattab',{}) for squad in raid_squads]
            raid_auras = [squad.get('player_auras',[]) for squad in raid_squads]
            raid_techs = [squad.get('player_tech',{}) for squad in raid_squads]
            attacker_loot_factor_pvp = raid_stattabs[0].get('player',{}).get('loot_factor_pvp',{'val':1})['val']

            self.attacker_ui_name = raid_pcinfos[0].get('ui_name','Unknown')

            # defender side of init_attack() - attacker side is done on launch
            is_revenge_attack = raid_squads[0].get('is_revenge_attack')
            defender_player.init_attack_defender(raid_squads[0]['base_landlord_id'], True, True, ladder_state, is_revenge_attack)

            defender_player.my_home.base_last_attack_time = self.time_now
            defender_player.my_home.base_times_attacked += 1

            attacking_army = sorted(sum([filter(lambda x: army_unit_is_alive(x, self.gamedata),
                                                self.gamesite.nosql_client.get_mobile_objects_by_base(self.region_id, squad['base_id'])) for squad in raid_squads], []),
                                     key = lambda obj: obj['spec'])
            defending_army = sorted([obj.persist_state(nosql = True) for obj in defender_player.home_base_iter() if \
                                     obj.is_building() or \
                                     (obj.is_mobile() and self.gamedata.get('enable_defending_units',True) and obj.squad_id == 0) and \
                                     (not obj.is_destroyed())
                                     ],
                                     key = lambda obj: obj['spec'])

            if not attacking_army:
                return ReturnValue(result = 'HARMLESS_RACE_CONDITION') # no units to scout or attack with

            # set up damage log
            if self.gamedata['server'].get('enable_damage_log',True):
                damage_log = self.gamesite.gameapi.ArmyUnitDamageLog_factory(defender_player.my_home.base_id) # observer is actually attacker, but shouldn't matter here
                damage_log.init_multi(defending_army)
                damage_log.init_multi(attacking_army)
            else:
                damage_log = None

            # set up attack log (not enabled for now)
            if 0:
                attack_log = self.gamesite.gameapi.AttackLog_factory(self.time_now, raid_squads[0]['base_landlord_id'], self.user_id, defender_player.my_home.base_id)
            else:
                attack_log = None

            try:
                if attack_log:
                    pass
                    ## if defender_player.player_auras:
                    ##     attack_log.event({'user_id':self.user_id, 'event_name': '3901_player_auras', 'code': 3901, 'player_auras':copy.copy(defender_player.player_auras)})
                    ##     # XXX log attacker's auras here

                    ## for obj in defending_units:
                    ##     props = session._log_attack_unit_props(obj)
                    ##     props.update({'user_id': self.user_id, 'event_name': '3900_unit_exists', 'code': 3900})
                    ##     attack_log.event(props)

                    ## for obj in attacking_units:
                    ##     props = session._log_attack_unit_props(obj, props = {'method':'from_home', 'squad_id':obj.squad_id or 0})
                    ##     props.update({'user_id': obj.owner.user_id, 'event_name': '3910_unit_deployed', 'code': 3910})
                    ##     attack_log.event(props)

                base_props = defender_player.my_home.get_cache_props()
                squad_update, unused_base_update, unused_pve_loot, is_win, new_attacking_army, new_defending_army = \
                              resolve_raid(raid_squads[0], base_props, attacking_army, defending_army, self.gamedata,
                                           squad_stattab = raid_squads[0].get('player_stattab', None),
                                           raid_stattab = defender_player.stattab.serialize(), # not just for_squad, to include buildings
                                           raid_power_factor = defender_player.my_home.get_power_factor())

                is_conquest = is_win and raid_mode != 'scout' and (defender_player.resources.player_level >= raid_pcinfos[0]['player_level'])

                #self.gamesite.exception_log.event(self.time_now, 'attacking_army %r\ndefending_army %r\nnew_attacking_army %r\nnew_defending_army %r' % (attacking_army, defending_army, new_attacking_army, new_defending_army))

                # perform mutation on defender, not including looting
                recalc_resources = False

                actual_loot = {}

                if new_defending_army is not None:
                    recalc_power = False

                    for before, after in zip(defending_army, new_defending_army):
                        # note: defending_army has already been filtered down to live units only

                        if army_unit_is_mobile(after, self.gamedata) and (not army_unit_is_alive(after, self.gamedata)):
                            # totally destroyed a mobile unit (similar to Player.destroy_object())
                            obj = defender_player.my_home.find_object_by_id(after['obj_id'])
                            assert obj
                            if session and session.has_object(after['obj_id']):
                                retmsg.append(["OBJECT_REMOVED2", after['obj_id']])
                                session.rem_object(after['obj_id'])

                            defender_player.unit_repair_cancel(obj)
                            defender_player.home_base_remove(obj)
                            spec = army_unit_spec(after, self.gamedata)
                            can_resurrect = spec.get('resurrectable') or \
                                            raid_stattabs[0].get('units',{}).get(after['spec'],{}).get('resurrection',{'val':1})['val'] >= 2 # RESURRECT_AND_REPAIR_WITH_TECH
                            if can_resurrect:
                                # add back as zombie unit
                                obj.hp = 0
                                defender_player.home_base_add(obj)
                                if session and session.home_base and self.gamedata.get('enable_defending_units',True):
                                    session.add_object(obj)
                                    retmsg.append(["OBJECT_CREATED2", obj.serialize_state()])
                                    if obj.auras:
                                        retmsg.append(["OBJECT_AURAS_UPDATE", obj.serialize_auras()])
                            else:
                                if session:
                                    defender_player.send_army_update_destroyed(obj, retmsg)
                        else:
                            # partially damaged unit/building, or totally destroyed building (similar to Player.object_combat_updates())
                            if after != before: # lazy
                                old_hp = army_unit_hp(before, self.gamedata)
                                new_hp = army_unit_hp(after, self.gamedata)

                                if old_hp != new_hp:
                                    obj = defender_player.my_home.find_object_by_id(after['obj_id'])
                                    assert obj
                                    if session: session.deferred_object_state_updates.add(obj)
                                    new_hp = int(max(0, min(new_hp, obj.max_hp)))

                                    if obj.is_mobile():
                                        if defender_player.unit_repair_cancel(obj):
                                            recalc_resources = True
                                    elif obj.is_building():
                                        obj.halt_all() # returns true if havoc caused
                                        if obj.affects_power():
                                            recalc_power = True

                                        if new_hp <= 0:
                                            # give XP for destroying the building
                                            if obj.spec.worth_less_xp:
                                                actual_loot['xp'] = actual_loot.get('xp',0) + self.gamedata['player_xp']['destroy_building_min_xp']
                                            else:
                                                actual_loot['xp'] = actual_loot.get('xp',0) + int(obj.level * self.gamedata['player_xp']['destroy_building'])
                                                # keep track of total levels of destroyed buildings for awarding victory bonus XP
                                                actual_loot['destroyed_building_levels'] = actual_loot.get('destroyed_building_levels',0) + obj.level

                                            # XXX missing: on_destroy consequents

                                            for removed_item in obj.destroy_fragile_equipment_items():
                                                defender_player.inventory_log_event('5131_item_trashed', removed_item['spec'], -removed_item.get('stack',1), removed_item.get('expire_time',-1), level=removed_item.get('level',1), reason='destroyed')

                                        # END building destroyed

                                    obj.hp = new_hp # mutate!

                    # record state changes to affected players
                    if recalc_power:
                        if session:
                            # note: this sends OBJECT_STATE_UPDATE for harvesters as well as BASE_POWER_UPDATE
                            session.power_changed(session.viewing_base, None, retmsg)
                        else:
                            # offline version
                            defender_player.my_home.power_changed(None)


                # LOOTING

                if is_win and raid_mode != 'scout':
                    cur_cargo = raid_squads[0].get('cargo', {})
                    max_cargo = calc_max_cargo(new_attacking_army if (new_attacking_army is not None) else attacking_army, self.gamedata)
                    cargo_space = dict((res, max(0, max_cargo.get(res,0) - cur_cargo.get(res,0))) for res in self.gamedata['resources'])

                    if any(cargo_space[res] > 0 for res in self.gamedata['resources']):
                        if session:
                            # reset base_resource_loot state for online attack
                            defender_player.my_home.base_resource_loot = None

                        # note: OK to pass session = None
                        res_looter = ResLoot.AllOrNothingPvPResLoot(self.gamedata, session, None, defender_player, defender_player.my_home,
                                                                    attacker_loot_factor_pvp, cargo_space)

                        looted, lost = res_looter.do_loot_base(self.gamedata, session, defender_player)

                        if looted or lost:
                            for res in looted:
                                if looted[res] > 0:
                                    actual_loot[res] = actual_loot.get(res,0) + looted[res]
                                    recalc_resources = True

                            for res in lost:
                                if lost[res] > 0:
                                    actual_loot[res+'_lost'] = actual_loot.get(res+'_lost',0) + lost[res]
                                    recalc_resources = True

                            # record econ flow
                            # human attacking human - log the frictional loss only, because the rest is a transfer
                            econ_delta = dict((res,looted.get(res,0)-lost.get(res,0)) for res in self.gamedata['resources'])
                            self.gamesite.admin_stats.econ_flow_player(defender_player, 'loot', 'friction', econ_delta)

                            wasted = {}
                            for res in self.gamedata['resources']:
                                if res in cur_cargo:
                                    if cur_cargo[res] > max_cargo.get(res,0):
                                        # resources disappear if cargo-carrying units are destroyed
                                        wasted[res] = - (cur_cargo[res] - max_cargo.get(res,0)) # negative quantity
                                        cur_cargo[res] = min(cur_cargo.get(res,0), max_cargo.get(res,0))
                                if res in actual_loot:
                                    if (res in max_cargo) and cur_cargo.get(res,0) < max_cargo[res]: # is there room for any loot?
                                        amount = min(actual_loot[res], max_cargo[res] - cur_cargo.get(res,0))
                                        assert actual_loot[res] == amount # should be enured by ResLoot code
                                        cur_cargo[res] = cur_cargo.get(res,0) + amount
                                    else:
                                        del actual_loot[res]

                            if wasted:
                                self.gamesite.admin_stats.econ_flow(raid_squads[0]['base_landlord_id'],
                                                                    get_denormalized_summary_props_from_pcache(self.gamedata, raid_pcinfos[0]),
                                                                    'waste', 'raid', wasted)

                            squad_update['max_cargo'] = max_cargo
                            squad_update['cargo'] = cur_cargo
                            squad_update['cargo_source'] = 'human'

                            # XP for looting
                            if sum(lost.itervalues(),0) > 0:
                                coeff = self.gamedata['player_xp']['pvp_loot_xp']
                                if is_win: coeff *= self.gamedata['player_xp']['loot_victory_bonus']
                                actual_loot['xp'] = actual_loot.get('xp',0) + int(coeff * self.gamedata['player_xp']['loot'] * sum(lost.itervalues(),0))

                if session and recalc_resources:
                    retmsg.append(["PLAYER_STATE_UPDATE", defender_player.resources.calc_snapshot().serialize()])

                if raid_mode != 'scout' or is_win:
                    base_damage = defender_player.my_home.calc_base_damage()
                else:
                    base_damage = None

                if ladder_state:
                    is_ladder_win = is_win and defender_player.my_home.ladder_victory_satisfied(None, base_damage)
                    actual_loot['trophies_pvp'] = ladder_state['points']['victory' if is_ladder_win else 'defeat'][str(raid_squads[0]['base_landlord_id'])]
                    actual_loot['viewing_trophies_pvp'] = ladder_state['points']['defeat' if is_ladder_win else 'victory'][str(self.user_id)]

                # bonus XP for destroyed building levels
                if is_win and actual_loot.get('destroyed_building_levels',0) > 0:
                    actual_loot['xp'] = actual_loot.get('xp',0) + int(actual_loot['destroyed_building_levels'] * self.gamedata['player_xp']['destroy_building_victory_bonus'])

                summary = make_battle_summary(self.gamedata, self.gamesite.nosql_client, self.time_now, self.region_id, raid_squads[0], base_props,
                                              raid_squads[0]['base_landlord_id'], self.user_id,
                                              raid_pcinfos[0], my_pcinfo,
                                              raid_auras[0], defender_player.player_auras_censored(),
                                              raid_techs[0], defender_player.tech,
                                              'victory' if is_win else 'defeat', 'defeat' if is_win else 'victory',
                                              attacking_army, defending_army,
                                              new_attacking_army, new_defending_army,
                                              actual_loot, raid_mode = raid_mode, base_damage = base_damage,
                                              is_revenge = is_revenge_attack)

                # perform mutation on attacking army
                # note: client should ping squads to get the army update

                self.gamesite.nosql_client.update_map_feature(self.region_id, raid_squads[0]['base_id'], squad_update)
                if new_attacking_army is not None:

                    mobile_deletions = [unit for unit in new_attacking_army if army_unit_is_mobile(unit, self.gamedata) and unit.get('DELETED')]
                    mobile_updates = [unit for unit in new_attacking_army if army_unit_is_mobile(unit, self.gamedata) and not unit.get('DELETED')]

                    for unit in mobile_deletions: self.gamesite.nosql_client.drop_mobile_object_by_id(self.region_id, unit['obj_id'], reason = 'resolve_home_raid')
                    if mobile_updates: self.gamesite.nosql_client.save_mobile_objects(self.region_id, mobile_updates, reason = 'resolve_home_raid')

                # defender's battle statistics (attacker's is done via message)
                defender_player.increment_battle_statistics(raid_squads[0]['base_landlord_id'], summary)
                self.gamesite.nosql_client.battle_record(summary, reason = 'resolve_home_raid')

                # create revenge allowance
                if self.gamedata['matchmaking']['revenge_time'] > 0:
                    defender_player.cooldown_trigger('revenge_defender:%d' % raid_squads[0]['base_landlord_id'], self.gamedata['matchmaking']['revenge_time'])

                # remove battle fatigue on victim against this attacker
                fatigue_cdname = ('ladder_fatigue' if ladder_state else 'battle_fatigue')
                if (not ladder_state) or (defender_player.is_ladder_player() and (not is_revenge_attack)):
                    defender_player.cooldown_reset(fatigue_cdname+':%d' % raid_squads[0]['base_landlord_id'])

                if session: session.deferred_player_cooldowns_update = True

                # update victim's player cache entry
                cache_props = {'lootable_buildings': defender_player.get_lootable_buildings(),
                               'base_damage': base_damage,
                               'base_repair_time': -1,
                               'last_defense_time': self.time_now,
                               'last_fb_notification_time': defender_player.last_fb_notification_time
                               }
                self.gamesite.pcache_client.player_cache_update(self.user_id, cache_props, reason = 'resolve_home_raid')

                # collect stat updates
                stats = {}
                stats['xp'] = summary['loot'].get('xp', 0)
                stats['conquests'] = 1 if is_conquest else 0
                stats['resources_looted'] = sum((summary['loot'].get(res,0) for res in self.gamedata['resources']),0)
                stats['havoc_caused'] = summary['loot'].get('havoc_caused',0) if is_conquest else 0
                stats['damage_inflicted'] = summary['loot'].get('damage_inflicted',0)

                # update defender's trophy stats immediately
                if actual_loot.get('viewing_trophies_pvp',0):
                    defender_player.modify_scores({'trophies_pvp': actual_loot['viewing_trophies_pvp']}, reason = 'resolve_home_raid')
                # update attacker's trophy stats on next login (XXX should be immediate?)
                if actual_loot.get('trophies_pvp',0):
                    stats['trophies_pvp'] = actual_loot['trophies_pvp']

                # mail the attacker the battle summary and stat updates
                self.gamesite.msg_client.msg_send([{'from': self.user_id,
                                                    'to': [raid_squads[0]['base_landlord_id']],
                                                    'type': 'you_attacked_me',
                                                    'expire_time': self.time_now + self.gamedata['server']['message_expire_time']['i_attacked_you'],
                                                    'from_name': unicode(self.attacker_ui_name),
                                                    'summary': summary,
                                                    'stats': stats
                                                    }])

                # mail the victim a "you've been attacked" message and battle summary (offline case only)
                if not session:
                    self.gamesite.msg_client.msg_send([{'from': raid_squads[0]['base_landlord_id'],
                                                        'to': [self.user_id],
                                                        'type': 'i_attacked_you',
                                                        'expire_time': self.time_now + self.gamedata['server']['message_expire_time']['i_attacked_you'],
                                                        'from_name': unicode(self.attacker_ui_name),
                                                        'summary': summary}])


                # broadcast map attack for GUI and battle history jewel purposes
                # regenerate my_pcinfo since it depends on trophies etc
                my_pcinfo = self.gamesite.gameapi.get_player_cache_props(defender_user, defender_player, my_alliance)
                self.gamesite.gameapi.broadcast_map_attack(self.region_id, base_props,
                                                           raid_squads[0]['base_landlord_id'], self.user_id,
                                                           {'battle_type':'raid', 'raid_mode': raid_mode, 'defender_outcome': summary['defender_outcome']},
                                                           [my_pcinfo,] + raid_pcinfos,
                                                           msg = 'REGION_MAP_ATTACK_COMPLETE')

            finally:
                if attack_log:
                    attack_log.close()

            if damage_log:
                # XXX lift and replace Raid.make_battle_summary() version with this
                # damage_report = summary['damage'] = damage_log.finalize()
                pass

            # send the squads back home
            self.recall_squads(raid_squads)

            return ReturnValue(result = 'ok')

    def exec_offline(self, json_user, json_player):
        ret = self._exec_offline_as_online(json_user, json_player)

        if self.raid_mode and self.raid_mode != 'scout':
            # send "You got attacked" FB notification
            config = self.gamedata['fb_notifications']['notifications']['you_got_attacked']
            notif_text = config.get('ui_name_home_raid')
            if notif_text:
                notif_text = notif_text.replace('%ATTACKER', self.attacker_ui_name)

                # re-use the handler logic
                # note: this mutates the JSON again
                send_handler = HandleSendNotification(self.time_now, self.user_id, self.gamedata, self.gamesite,
                                                      {'config': 'you_got_attacked', 'text': notif_text})
                send_handler.exec_offline(json_user, json_player)

        return ret

class HandleChangeRegion(Handler):
    def __init__(self, *pargs, **pkwargs):
        Handler.__init__(self, *pargs, **pkwargs)
        self.new_region = self.args.get('new_region', 'ANY')
        if self.new_region == 'ANY':
            self.new_region = None
        assert (self.new_region in (None,'LIMBO') or self.new_region in self.gamedata['regions'])

    # the online handler has to first end any ongoing attack, which may go asynchronous, and then
    # a synchronous return to home base, and finally the region change
    def do_exec_online(self, session, retmsg):
        self.d = self.gamesite.gameapi.change_session(session, retmsg, dest_user_id = session.user.user_id, force = True)
        self.d.addCallback(self.do_exec_online2, session, retmsg)
        return ReturnValue(async = self.d)

    # then after complete_attack...
    def do_exec_online2(self, change_session_result, session, retmsg):
        success = session.player.change_region(self.new_region, None, session, retmsg, reason = 'CustomerSupport')
        if success:
            ret = ReturnValue(result = 'ok')
        else:
            ret = ReturnValue(error = 'change_region failed')
        return ret

    # the offline implementation is complex because it needs to do
    # everything Player.change_region() does, including careful trial
    # placement in the new region, recall of old squads, etc.

    # this must match Base.get_cache_props() in server
    def get_cache_props(self, player):
        props = { 'base_id': 'h'+str(self.user_id),
                  'base_landlord_id': self.user_id,
                  'base_type': 'home',
                  'base_map_loc': player['base_map_loc']}
        for FIELD in ('base_ncells','base_creation_time','base_size',):
            if FIELD in player:
                props[FIELD] = player[FIELD]

        townhall_level = player['history'].get(self.gamedata['townhall']+'_level', 1)
        if townhall_level > 0: props[self.gamedata['townhall']+'_level'] = townhall_level
        props['protection_end_time'] = player['resources'].get('protection_end_time',-1)
        return props

    def recall_squad_instantly(self, player, region_id, squad_id):
        base_id = 's'+str(self.user_id)+'_'+str(squad_id)
        feature = self.gamesite.nosql_client.get_map_feature_by_base_id(region_id, base_id)
        if not feature: return
        if self.gamesite.nosql_client.map_feature_lock_acquire(region_id, base_id, self.user_id) != 2: # BEING_ATTACKED
            # squad is locked, do nothing
            return

        try:
            squad_units = self.gamesite.nosql_client.get_mobile_objects_by_base(region_id, base_id)
            self.refund_units(player, feature, squad_units)
            self.gamesite.nosql_client.drop_mobile_objects_by_base(region_id, base_id)
        except:
            self.gamesite.nosql_client.map_feature_lock_release(region_id, base_id, self.user_id)
            raise

        self.gamesite.nosql_client.drop_map_feature(region_id, base_id) # gets rid of the lock

    def refund_units(self, player, feature, objlist):
        to_add = []
        squad_id = int(feature['base_id'].split('_')[1])
        for obj in objlist:
            if obj['spec'] not in self.gamedata['units']: continue
            props = {'spec': obj['spec'],
                     'xy': [90,90],
                     'squad_id': squad_id}
            for FIELD in ('obj_id', 'hp_ratio', 'level', 'equipment'):
                if FIELD in obj:
                    props[FIELD] = obj[FIELD]
            to_add.append(props)

        # force items with squad_ids not in player.squads into reserves, to avoid accidentally giving the player more squads than allowed
        player_squads = player.get('squads',{})
        for item in to_add:
            if str(item['squad_id']) not in player_squads:
                item['squad_id'] = -1

        player['my_base'] += to_add

    def do_exec_offline(self, user, player):
        # can't execute predicates on offline player (to choose a region), so require a specific destination region
        assert self.new_region in self.gamedata['regions'] or self.new_region == 'LIMBO'

        # this should do the same things that Player.change_region() does

        if player.get('home_region'):
            assert player['base_region'] == player['home_region']
            old_region = player['home_region']
            old_loc = player['base_map_loc']
        else:
            old_region = old_loc = None

        new_region = self.new_region
        new_loc = None

        base_id = 'h'+str(self.user_id) # copy of server.py: home_base_id()

        if old_region:
            if self.gamesite.nosql_client.map_feature_lock_acquire(old_region, base_id, self.user_id) != 2: # BEING_ATTACKED
                # base is locked
                return ReturnValue(error = 'change_region failed: base is locked')

        if new_region and new_region != 'LIMBO':
            randgen = random.Random(self.user_id ^ self.gamedata['territory']['map_placement_gen'] ^ int(self.time_now))

            map_dims = self.gamedata['regions'][new_region]['dimensions']
            BORDER = self.gamedata['territory']['border_zone_player']

            # radius: how far from the center of the map we can place the player
            radius = [map_dims[0]//2 - BORDER, map_dims[1]//2 - BORDER]

            # rectangle within which we can place the player
            placement_range = [[map_dims[0]//2 - radius[0], map_dims[0]//2 + radius[0]],
                               [map_dims[1]//2 - radius[1], map_dims[1]//2 + radius[1]]]
            trials = map(lambda x: (min(max(placement_range[0][0] + int((placement_range[0][1]-placement_range[0][0])*randgen.random()), 2), map_dims[0]-2),
                                    min(max(placement_range[1][0] + int((placement_range[1][1]-placement_range[1][0])*randgen.random()), 2), map_dims[1]-2)), xrange(100))

            trials = filter(lambda x: not Region(self.gamedata, new_region).obstructs_bases(x), trials)

            i = 0
            for tr in trials:
                i += 1
                player['base_region'] = new_region
                player['base_map_loc'] = tr
                props = self.get_cache_props(player)

                if (new_region == old_region):
                    success = self.gamesite.nosql_client.move_map_feature(new_region, base_id, props, old_loc = old_loc,
                                                                          exclusive = self.gamedata['territory']['exclusive_zone_player'], originator=self.user_id, reason='CustomerSupport')
                else:
                    success = self.gamesite.nosql_client.create_map_feature(new_region, base_id, props,
                                                                            exclusive = self.gamedata['territory']['exclusive_zone_player'], originator=self.user_id, reason='CustomerSupport')
                if success:
                    break
                else:
                    player['base_region'] = old_region
                    player['base_map_loc'] = old_loc
                # note! temporarily leave player['home_region'] pointing to the old region, so that we can clear the squads out

            if (not player['base_region']) or ((player['base_region'] == old_region) and (player['base_map_loc'] == old_loc)):
                if not new_loc: # don't print this warning when player deliberately tries to enter a crowded neighborhood
                    self.gamesite.exception_log.event(self.time_now, 'map: failed to place player %d in region %s after %d trials' % (self.user_id, new_region, i))
                if old_region:
                    self.gamesite.nosql_client.map_feature_lock_release(old_region, base_id, self.user_id)
                return ReturnValue(error = 'change_region failed: too crowded')

        elif old_region:
            # just remove from the map, do not add to a new region
            player['base_region'] = None
            player['base_map_loc'] = None

        if player['base_region']:
            player['base_climate'] = Region(self.gamedata, player['base_region']).read_climate_name(player['base_map_loc'])
        elif 'base_climate' in player:
            del player['base_climate']

        # just get rid of all scenery
        to_remove = []
        for obj in player['my_base']:
            if obj['spec'] in self.gamedata['inert']:
                spec = self.gamedata['inert'][obj['spec']]
                if spec.get('auto_spawn', False):
                    to_remove.append(obj)
        for obj in to_remove:
            player['my_base'].remove(obj)

        if old_region:
            # recall squads
            for squad_sid, squad in player.get('squads',{}).iteritems():
                squad_id = int(squad_sid)
                if 'map_loc' in squad: # is deployed
                    self.recall_squad_instantly(player, old_region, squad_id)
                    for FIELD in ('map_loc', 'map_path'):
                        if FIELD in squad:
                            del squad[FIELD]

            # drop all remaining units
            self.gamesite.nosql_client.drop_mobile_objects_by_owner(old_region, self.user_id)

            if player['base_region'] != old_region:
                # remove home base from old region (drops old lock as well)
                self.gamesite.nosql_client.drop_map_feature(old_region, base_id, originator=self.user_id, reason='CustomerSupport')

                # skip modifying ladder scores and on_enter consequent
            else:
                # changed location within one region - no need to drop old stuff
                pass

        player['history']['map_placement_gen'] = self.gamedata['territory']['map_placement_gen'] if player['base_region'] else -1
        player['home_region'] = player['base_region']

        # update player cache
        self.gamesite.pcache_client.player_cache_update(self.user_id, {'home_region':player['home_region'], 'home_base_loc':player['base_map_loc']}, reason ='CustomerSupport')

        self.gamesite.metrics_log.event(self.time_now, {'user_id': self.user_id,
                                                        'event_name': '4701_change_region_success',
                                                        'request_region':new_region, 'request_loc':new_loc,
                                                        'new_region': player['base_region'], 'new_loc': player['base_map_loc'],
                                                        'old_region':old_region, 'old_loc':old_loc, 'reason':'CustomerSupport'})
        # drop lock from create_map_feature()
        if new_region and new_region != 'LIMBO' and (new_region != old_region):
            self.gamesite.nosql_client.map_feature_lock_release(new_region, base_id, self.user_id)

        return ReturnValue(result = 'ok')

class HandleDemoteAllianceLeader(Handler):
    def do_exec_online(self, session, retmsg): return self.do_exec_both()
    def do_exec_offline(self, user, player): return self.do_exec_both()
    def do_exec_both(self):
        alliance_membership = self.gamesite.sql_client.get_users_alliance_membership(self.user_id, reason = 'CustomerSupport')
        if not alliance_membership:
            return ReturnValue(error = 'demote_alliance_leader failed: user %d is not in an alliance' % (self.user_id,))

        alliance_id = alliance_membership['alliance_id']
        if alliance_membership['role'] != self.gamesite.nosql_client.ROLE_LEADER:
            return ReturnValue(error = 'demote_alliance_leader failed: user %d is in alliance %d, but is not the leader' % (self.user_id, alliance_id))

        new_role = alliance_membership['role'] - 1
        if not self.gamesite.nosql_client.promote_alliance_member(alliance_id, self.user_id, self.user_id,
                                                                  alliance_membership['role'],
                                                                  new_role,
                                                                  force = True, reason = 'CustomerSupport'):
            return ReturnValue(error = 'demote_alliance_leader failed: user %d might not be the leader of alliance %d' % \
                               (self.user_id, alliance_id))
        new_leader_id = self.gamesite.nosql_client.do_maint_fix_leadership_problem(alliance_id, exclude_leader_id = self.user_id, verbose = False)

        self.gamesite.metrics_log.event(self.time_now, {'user_id': self.user_id,
                                                        'event_name': '4626_alliance_member_promoted',
                                                        'alliance_id': alliance_id, 'target_id': self.user_id, 'role':new_role,
                                                        'reason':'CustomerSupport'})
        return ReturnValue(result = {'new_leader_id': new_leader_id})

class HandleKickAllianceMember(Handler):
    def do_exec_online(self, session, retmsg): return self.do_exec_both()
    def do_exec_offline(self, user, player): return self.do_exec_both()
    def do_exec_both(self):
        alliance_membership = self.gamesite.sql_client.get_users_alliance_membership(self.user_id, reason = 'CustomerSupport')
        if not alliance_membership:
            return ReturnValue(error = 'kick_alliance_member failed: user %d is not in an alliance' % (self.user_id,))

        alliance_id = alliance_membership['alliance_id']
        if not self.gamesite.nosql_client.kick_from_alliance(self.user_id, alliance_id, self.user_id, force = True, reason='CustomerSupport'):
            return ReturnValue(error = 'kick_alliance_member failed: user %d might not be a member of of alliance %d' % \
                               (self.user_id, alliance_id))

        self.gamesite.pcache_client.player_cache_update(self.user_id, {'alliance_id': -1}, reason = 'CustomerSupport')

        self.gamesite.metrics_log.event(self.time_now, {'user_id': self.user_id,
                                                        'event_name': '4625_alliance_member_kicked',
                                                        'alliance_id': alliance_id, 'target_id': self.user_id,
                                                        'reason':'CustomerSupport'})

        new_leader_id = self.gamesite.nosql_client.do_maint_fix_leadership_problem(alliance_id, verbose = False)
        if new_leader_id > 0:
            self.gamesite.metrics_log.event(self.time_now, {'user_id': new_leader_id,
                                                            'event_name': '4626_alliance_member_promoted',
                                                            'alliance_id': alliance_id, 'target_id': new_leader_id,
                                                            'role':self.gamesite.nosql_client.ROLE_LEADER,
                                                            'reason':'CustomerSupport'})
        return ReturnValue(result = 'ok')

class HandleResetIdleCheckState(Handler):
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        session.player.idle_check.reset_state()
        return ReturnValue(result = 'ok')
    def exec_offline(self, user, player):
        if 'idle_check' in player:
            if 'history' in player['idle_check']:
                for entry in player['idle_check']['history']:
                    entry['seen'] = 1
        return ReturnValue(result = 'ok')

online_only = Exception('offline execution not implemented')

class HandleAIAttack(Handler):
    def exec_offline(self, user, player): raise online_only
    def do_exec_online(self, session, retmsg):
        session.start_ai_attack(session.outgoing_messages, self.args['attack_type'], override_protection = True, verbose = True)
        return ReturnValue(result = 'ok')

class HandlePushGamedata(Handler): # no logging
    def exec_offline(self, user, player): raise online_only
    def exec_online(self, session, retmsg):
        self.gamesite.gameapi.push_gamedata(session, session.outgoing_messages)
        return ReturnValue(result = 'ok')

class HandleForceReload(Handler): # no logging
    def exec_offline(self, user, player): raise online_only
    def exec_online(self, session, retmsg):
        session.send([["FORCE_RELOAD"]], flush_now = True)
        return ReturnValue(result = 'ok')

class HandleClientEval(Handler): # no logging
    def exec_offline(self, user, player): raise online_only
    def exec_online(self, session, retmsg):
        session.send([["CLIENT_EVAL", self.args['expr']]], flush_now = True)
        return ReturnValue(result = 'ok')

class HandleOfferPayerPromo(Handler): # no logging
    def exec_offline(self, user, player): raise online_only
    def exec_online(self, session, retmsg):
        session.user.offer_payer_promo(session, session.outgoing_messages)
        return ReturnValue(result = 'ok')

class HandleInvokeFacebookAuth(Handler): # no logging
    def exec_offline(self, user, player): raise online_only
    def exec_online(self, session, retmsg):
        scope = self.args.get('scope', 'email')
        session.send([["INVOKE_FACEBOOK_AUTH", scope, "Test", "Test authorization"]], flush_now = True)
        return ReturnValue(result = 'ok')

class HandleSendNotification(Handler):
    # useful for sending one-off

    def __init__(self, *pargs, **pkwargs):
        Handler.__init__(self, *pargs, **pkwargs)

        # refers to an entry in gamedata['fb_notifications']['notifications']
        self.config_name = self.args.get('config',None)
        if self.config_name:
            self.config = self.gamedata['fb_notifications']['notifications'].get(self.config_name, None)
            if self.config is None:
                raise Exception('notification config not found in gamedata.fb_notifications')
        else:
            self.config = None # arbitrary message

        # "force" means "ignore all frequency checks, just send it!" (e.g. for payment confirmations)
        self.force = bool(int(self.args.get('force','0')))
        # enable sending notification even if one was already sent since last logout
        self.multi_per_logout = bool(int(self.args.get('multi_per_logout','0')))

        self.text = self.args['text'] # should be Unicode

        # optional override of the "ref" referer parameter. Only used if no "config" is selected.
        self.ref_override = self.args.get('ref',None)
        if not self.config and not self.ref_override:
            raise Exception('ref= parameter is required if no config= is used')

        self.simulate = bool(int(self.args.get('simulate','0'))) # for testing, act as if we actually transmitted the notification

        # if true, and player is logged in, send via an in-game text notification instead of using the social network
        self.send_ingame = bool(int(self.args.get('send_ingame','0')))

    # no logging
    def exec_online(self, session, retmsg):
        if self.send_ingame:
            session.send([["NOTIFICATION", self.text]], flush_now = True)
            return ReturnValue(result = 'ok')

        if not session.user.facebook_id:
            return ReturnValue(result = 'no social network to send notification')
        if (not session.player.get_any_abtest_value('enable_fb_notifications', self.gamedata['enable_fb_notifications'])):
            return ReturnValue(result = 'disabled by global enable_fb_notifications setting')
        if session.player.player_preferences and type(session.player.player_preferences) is dict and \
           (not session.player.player_preferences.get('enable_fb_notifications', self.gamedata['strings']['settings']['enable_fb_notifications']['default_val'])): # note: doesn't handle predicate chains
            return ReturnValue(result = 'disabled by player preference')

        is_elder = (len(session.player.history.get('sessions', [])) >= self.gamedata['fb_notifications']['elder_threshold'])

        if not self.force: # "soft" enable/disable checks

            if self.config and \
               (is_elder and (not self.config.get('enable_elder', True))) or \
               ((not is_elder) and (not self.config.get('enable_newbie', True))):
                return ReturnValue(result = 'disabled by elder/newbie status in the notification config')

            if not self.multi_per_logout:
                last_logout = session.player.last_logout_time()
                if last_logout < 0 or session.player.last_fb_notification_time > last_logout:
                    return ReturnValue(result = 'already notified since last logout')

            # do not send notification if one *WITH SAME REF* was sent since min_minterval ago
            # note: config-specific min_interval overrides the global one here, unlike in retention_newbie.py
            if self.config and \
               (self.time_now - session.player.history.get('notification:'+self.config['ref']+':last_time',-1)) < self.config.get('min_interval', self.gamedata['fb_notifications']['min_interval']):
                return ReturnValue(result = 'too frequent, same notification sent within min_interval ago')

            if self.config and self.config.get('auto_mute',0) > 0:
                mute_key = 'notification:'+self.config['ref']+':unacked'
                if session.player.history.get(mute_key,0) >= self.config['auto_mute']:
                    session.player.player_preferences[self.config['mute_preference_key']] = 0
                    return ReturnValue(result = 'too many unacknowledged %s notifications, auto-muting' % (self.config['ref']))

        # going to send!
        if self.gamedata['fb_notifications']['elder_suffix'] and self.config and self.config.get('elder_suffix',True):
            fb_ref = self.config['ref'] + ('_e' if is_elder else '_n')
        elif self.config:
            fb_ref = self.config['ref']
        else:
            assert self.ref_override
            fb_ref = self.ref_override

        if self.gamesite.gameapi.do_send_fb_notification_to(self.user_id, session.user.facebook_id, self.text, self.config_name or self.ref_override, fb_ref,
                                                            session.player.get_denormalized_summary_props('brief')) or self.simulate:
            session.player.last_fb_notification_time = self.time_now
            session.player.history['fb_notifications_sent'] = session.player.history.get('fb_notifications_sent',0)+1
            if self.config:
                key = 'fb_notification:'+self.config['ref']+':sent'
                session.player.history[key] = session.player.history.get(key,0)+1
                key = 'notification:'+self.config['ref']+':unacked'
                session.player.history[key] = session.player.history.get(key,0)+1
                key = 'notification:'+self.config['ref']+':last_time'
                session.player.history[key] = self.time_now

        return ReturnValue(result = 'ok')

    def exec_offline(self, user, player):
        if not user.get('facebook_id'):
            return ReturnValue(result = 'no social network to send notification')
        if not self.gamedata['enable_fb_notifications']:
            return ReturnValue(result = 'disabled by global enable_fb_notifications setting')
        if player.get('player_preferences') and type(player['player_preferences']) is dict and \
           (not player['player_preferences'].get('enable_fb_notifications', self.gamedata['strings']['settings']['enable_fb_notifications']['default_val'])): # note: doesn't handle predicate chains
            return ReturnValue(result = 'disabled by player preference')

        is_elder = (len(player['history'].get('sessions', [])) >= self.gamedata['fb_notifications']['elder_threshold'])

        if not self.force: # "soft" enable/disable checks

            if self.config and \
               (is_elder and (not self.config.get('enable_elder', True))) or \
               ((not is_elder) and (not self.config.get('enable_newbie', True))):
                return ReturnValue(result = 'disabled by elder/newbie status in the notification config')

            if not self.multi_per_logout:
                last_logout = -1
                if player['history'].get('sessions'):
                    last_logout = player['history']['sessions'][-1][1]
                if last_logout < 0 or player.get('last_fb_notification_time',-1) > last_logout:
                    return ReturnValue(result = 'already notified since last logout')

            # do not send notification if one *WITH SAME REF* was sent since min_minterval ago
            # note: config-specific min_interval overrides the global one here, unlike in retention_newbie.py
            if self.config and \
               (self.time_now - player['history'].get('notification:'+self.config['ref']+':last_time',-1)) < self.config.get('min_interval', self.gamedata['fb_notifications']['min_interval']):
                return ReturnValue(result = 'too frequent, same notification sent within min_interval ago')

            if self.config and self.config.get('auto_mute',0) > 0:
                mute_key = 'notification:'+self.config['ref']+':unacked'
                if player['history'].get(mute_key,0) >= self.config['auto_mute']:
                    if 'player_preferences' not in player: player['player_preferences'] = {}
                    player['player_preferences'][self.config['mute_preference_key']] = 0
                    return ReturnValue(result = 'too many unacknowledged %s notifications, auto-muting' % (self.config['ref']))

        # going to send!
        if self.gamedata['fb_notifications']['elder_suffix'] and self.config and self.config.get('elder_suffix',True):
            fb_ref = self.config['ref'] + ('_e' if is_elder else '_n')
        elif self.config:
            fb_ref = self.config['ref']
        else:
            assert self.ref_override
            fb_ref = self.ref_override

        if self.gamesite.gameapi.do_send_fb_notification_to(self.user_id, user['facebook_id'], self.text, self.config_name or self.ref_override, fb_ref,
                                                            self.get_denormalized_summary_props_offline(user, player)) or self.simulate:
            player['last_fb_notification_time'] = self.time_now
            player['history']['fb_notifications_sent'] = player['history'].get('fb_notifications_sent',0)+1
            if self.config:
                key = 'fb_notification:'+self.config['ref']+':sent'
                player['history'][key] = player['history'].get(key,0)+1
                key = 'notification:'+self.config['ref']+':unacked'
                player['history'][key] = player['history'].get(key,0)+1
                key = 'notification:'+self.config['ref']+':last_time'
                player['history'][key] = self.time_now

        return ReturnValue(result = 'ok')

    def get_denormalized_summary_props_offline(self, user, player):
        ret = {'cc': player['history'].get(self.gamedata['townhall']+'_level',1),
               'plat': user.get('frame_platform','fb'),
               'rcpt': player['history'].get('money_spent', 0),
               'ct': user.get('country','unknown'),
               'tier': SpinConfig.country_tier_map.get(user.get('country','unknown'), 4)}
        if user.get('developer'):
            ret['developer'] = 1
        return ret

class HandleApplyAllianceLeavePointLoss(Handler):
    def __init__(self, *pargs, **pkwargs):
        Handler.__init__(self, *pargs, **pkwargs)
        self.alliance_ui_name = self.args.get('alliance_ui_name','Unknown')
    # note: no logging
    def exec_offline(self, json_user, json_player):
        return self._exec_offline_as_online(json_user, json_player)
    def exec_online(self, session, retmsg):
        return self.exec_all(session, retmsg, session.user, session.player)
    def exec_all(self, session, retmsg, user, player):
        if player.apply_alliance_leave_point_loss(self.alliance_ui_name):
            # notify live session
            if session:
                session.deferred_mailbox_update = True
            if retmsg is not None:
                retmsg.append(["PLAYER_CACHE_UPDATE", [self.gamesite.gameapi.get_player_cache_props(user, player, None)]])
        return ReturnValue(result = 'ok')

class HandlePlayerBatch(Handler):
    read_only = True
    need_user = False
    need_player = False
    def __init__(self, time_now, user_id, gamedata, gamesite, args):
        Handler.__init__(self, time_now, user_id, gamedata, gamesite, args)
        batch = SpinJSON.loads(self.args['batch']) # [{'method': 'method0', 'args':{'foo':'bar'}}, ...]
        self.handlers = []
        for entry in batch:
            handler = methods[entry['method']](time_now, user_id, gamedata, gamesite, entry.get('args',{}))
            if not handler.read_only: self.read_only = False
            if handler.need_user: self.need_user = True
            if handler.need_player: self.need_player = True
            self.handlers.append(handler)
        self.handlers.reverse() # we're going to use pop() to pull off entries, so go back-to-front

    def exec_offline(self, user, player):
        self.results = []
        while self.handlers:
            h = self.handlers.pop()
            ret = h.exec_offline(user, player)
            assert not ret.async # XXX async case not handled
            self.results.append(ret)
        return self.reduce_results(self.results)
    def exec_online(self, session, retmsg):
        self.results = []
        while self.handlers:
            h = self.handlers.pop()
            ret = h.exec_online(session, retmsg)
            assert not ret.async # XXX async case not handled
            self.results.append(ret)
        return self.reduce_results(self.results)

    def reduce_results(self, retlist):
        if any(x.error for x in retlist):
            result = None
            error = [x.error for x in retlist]
        else:
            result = [x.result for x in retlist]
            error = None
        return ReturnValue(result = result, error = error,
                           kill_session = any(x.kill_session for x in retlist),
                           async = False)

methods = {
    'get_raw_player': HandleGetRawPlayer,
    'get_raw_user': HandleGetRawUser,
    'ban': HandleBan,
    'unban': HandleUnban,
    'mark_uninstalled': HandleMarkUninstalled,
    'record_alt_login': HandleRecordAltLogin,
    'make_developer': HandleMakeDeveloper,
    'unmake_developer': HandleUnmakeDeveloper,
    'ignore_alt': HandleIgnoreAlt,
    'unignore_alt': HandleUnignoreAlt,
    'clear_alias': HandleClearAlias,
    'chat_block': HandleChatBlock,
    'chat_unblock': HandleChatUnblock,
    'chat_official': HandleChatOfficial,
    'chat_unofficial': HandleChatUnofficial,
    'apply_lockout': HandleApplyLockout,
    'clear_lockout': HandleClearLockout,
    'clear_cooldown': HandleClearCooldown,
    'cooldown_togo': HandleCooldownTogo,
    'cooldown_active': HandleCooldownActive,
    'trigger_cooldown': HandleTriggerCooldown,
    'apply_aura': HandleApplyAura,
    'remove_aura': HandleRemoveAura,
    'aura_active': HandleAuraActive,
    'check_idle': HandleCheckIdle,
    'chat_gag': HandleChatGag,
    'chat_ungag': HandleChatUngag,
    'give_item': HandleGiveItem,
    'send_message': HandleSendMessage,
    'squad_dock_units': HandleSquadDockUnits,
    'resolve_home_raid': HandleResolveHomeRaid,
    'change_region': HandleChangeRegion,
    'demote_alliance_leader': HandleDemoteAllianceLeader,
    'kick_alliance_member': HandleKickAllianceMember,
    'reset_idle_check_state': HandleResetIdleCheckState,
    'ai_attack': HandleAIAttack,
    'push_gamedata': HandlePushGamedata,
    'force_reload': HandleForceReload,
    'client_eval': HandleClientEval,
    'offer_payer_promo': HandleOfferPayerPromo,
    'invoke_facebook_auth': HandleInvokeFacebookAuth,
    'send_notification': HandleSendNotification,
    'apply_alliance_leave_point_loss': HandleApplyAllianceLeavePointLoss,
    'player_batch': HandlePlayerBatch,
    # not implemented yet: join_abtest, clear_abtest
}
