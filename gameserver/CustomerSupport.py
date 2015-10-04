#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Server-side handlers for CONTROLAPI calls originated by tools like cgipcheck (PCHECK).

# These have both "online" and "offline" execution modes. The "online" mode operates
# on LivePlayer objects with active sessions, and the "offline" modes manipulate raw
# JSON structures. This allows all methods to work regardless of whether the affected
# player is currently logged in or not.

import SpinJSON
import random
import functools
from twisted.internet import defer
from Region import Region

# encapsulate the return value from CONTROLAPI support calls, to be interpreted by cgipcheck.html JavaScript
# basically, we return a JSON dictionary that either has a "result" (for successful calls) or an "error" (for failures).
# there is also a "kill_session" option that tells the server to (asynchronously) log the player out after we return.
# and an "async" Deferred to hold the CONTROLAPI request until an async operation finishes
class ReturnValue(object):
    def __init__(self, result = None, error = None, kill_session = False, async = None, read_only = False):
        assert (result is not None) or (error is not None) or (async is not None)
        self.result = result
        self.error = error
        self.kill_session = kill_session
        self.async = async
        self.read_only = read_only
    def as_body(self):
        assert not self.async
        if self.error:
            ret = {'error':self.error}
        else:
            ret = {'result':self.result}
        return SpinJSON.dumps(ret, newline = True)

class Handler(object):
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
            ui_reason = 'Not specified'
        if 'spin_user' in log_args:
            spin_user = log_args['spin_user']
            del log_args['spin_user']
        else:
            spin_user = 'unknown'
        if 'user_id' in log_args: del log_args['user_id']
        entry = {'time': self.time_now,
                 'spin_user': spin_user,
                 'method': call_name,
                 'ui_reason': ui_reason}
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

class HandleGetRaw(Handler):
    def format(self, result):
        if bool(int(self.args.get('stringify',False))):
            result = SpinJSON.dumps(result, pretty = True, newline = True, size_hint = 1024*1024, double_precision = 5)
        return result
class HandleGetRawPlayer(HandleGetRaw):
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        player_json = SpinJSON.loads(self.gamesite.player_table.unparse(session.player))
        return ReturnValue(result = self.format(player_json), read_only = True)
    def exec_offline(self, user, player):
        return ReturnValue(result = self.format(player), read_only = True)
class HandleGetRawUser(HandleGetRaw):
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        user_json = SpinJSON.loads(self.gamesite.user_table.unparse(session.user))
        return ReturnValue(result = self.format(user_json), read_only = True)
    def exec_offline(self, user, player):
        return ReturnValue(result = self.format(user), read_only = True)

class HandleBan(Handler):
    def do_exec_online(self, session, retmsg):
        session.player.banned_until = self.time_now + int(self.args.get('ban_time',self.gamedata['server']['default_ban_time']))
        return ReturnValue(result = 'ok', kill_session = True)
    def do_exec_offline(self, user, player):
        player['banned_until'] = self.time_now + int(self.args.get('ban_time',self.gamedata['server']['default_ban_time']))
        return ReturnValue(result = 'ok')
class HandleUnban(Handler):
    def do_exec_online(self, session, retmsg):
        session.player.banned_until = -1
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        player['banned_until'] = -1
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
        assert self.other_id != self.user_id
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        session.player.possible_alt_record_login(self.other_id)
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
    # note: returns duration remaining
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        return ReturnValue(result = session.player.cooldown_togo(self.args['name']), read_only = True)
    def exec_offline(self, user, player):
        togo = -1
        if self.args['name'] in player['cooldowns']:
            togo = max(-1, player['cooldowns'][self.args['name']]['end'] - self.time_now)
        return ReturnValue(result = togo, read_only = True)

class HandleCooldownActive(Handler):
    # note: returns number of active stacks
    # note: no logging, directly override exec()
    def exec_online(self, session, retmsg):
        return ReturnValue(result = session.player.cooldown_active(self.args['name']), read_only = True)
    def exec_offline(self, user, player):
        stacks = 0
        if self.args['name'] in player['cooldowns']:
            cd = player['cooldowns'][self.args['name']]
            if cd['end'] > self.time_now:
                stacks = cd.get('stack', 1)
        return ReturnValue(result = stacks, read_only = True)

class HandleTriggerCooldown(Handler):
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

class HandleChatGag(Handler):
    def do_exec_online(self, session, retmsg):
        if 'duration' in self.args:
            # new-style gag
            if session.player.apply_aura('chat_gagged', duration = int(self.args['duration']), ignore_limit = True):
                session.player.stattab.send_update(session, session.outgoing_messages)
        else:
            # old-style gag
            session.user.chat_gagged = True
            self.gamesite.pcache_client.player_cache_update(self.user_id, {'chat_gagged': session.user.chat_gagged})
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        if 'duration' in self.args:
            duration = int(self.args['duration'])
            # new-style gag
            player['player_auras'] = filter(lambda x: x['spec'] != 'chat_gagged', player.get('player_auras',[]))
            new_aura = {'spec':'chat_gagged', 'start_time': self.time_now}
            if duration > 0:
                new_aura['end_time'] = self.time_now + duration
            player['player_auras'].append(new_aura)
        else:
            # old-style gag
            user['chat_gagged'] = True
            self.gamesite.pcache_client.player_cache_update(self.user_id, {'chat_gagged': user['chat_gagged']})
        return ReturnValue(result = 'ok')
class HandleChatUngag(Handler):
    AURAS = ('chat_gagged', 'chat_warned')
    def do_exec_online(self, session, retmsg):
        for aura_name in self.AURAS:
            session.player.remove_aura(session, session.outgoing_messages, aura_name, force = True)
        session.user.chat_gagged = False
        self.gamesite.pcache_client.player_cache_update(self.user_id, {'chat_gagged': session.user.chat_gagged})
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        user['chat_gagged'] = False
        player['player_auras'] = filter(lambda x: x['spec'] not in self.AURAS, player.get('player_auras',[]))
        self.gamesite.pcache_client.player_cache_update(self.user_id, {'chat_gagged': user['chat_gagged']})
        return ReturnValue(result = 'ok')

class MessageSender(Handler):
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
        assert self.args['spec'] in self.gamedata['items']
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
                'from_name': self.args.get('message_sender', 'SpinPunch'),
                'to': [self.user_id],
                'subject':self.args.get('message_subject', 'Special Item'),
                'attachments': [item],
                'body': self.args.get('message_body', 'The SpinPunch customer support team sent us a special item.\n\nClick the item to collect it.') + \
                ('\n\nIMPORTANT: Activate this item quickly! Its time is limited.' if expire_time > 0 else '')}
class HandleSendMessage(MessageSender):
    def make_message(self):
        expire_time = (int(self.args['expire_time']) if 'expire_time' in self.args else self.time_now + 30*24*60*60)
        return {'type':'mail',
                'expire_time': expire_time,
                'msg_id': self.get_msg_id(),
                'from_name': self.args.get('message_sender', 'SpinPunch'),
                'to': [self.user_id],
                'subject':self.args.get('message_subject', 'Customer Support'),
                'body': self.args['message_body']}

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
        self.d = defer.Deferred() # for the asynchronous callback
        self.gamesite.gameapi.complete_attack(session, retmsg, functools.partial(self.do_exec_online2, session, retmsg),
                                              reason = 'CustomerSupport')
        return ReturnValue(async = self.d)

    # then after complete_attack...
    def do_exec_online2(self, session, retmsg, is_sync):
        # force a synchronous session change back to home base
        if session.viewing_base is not session.player.my_home:
            self.gamesite.gameapi.change_session_complete(None, session, retmsg, self.user_id, session.user, session.player, None, None, None, None, {}, {})
        success = session.player.change_region(self.new_region, None, session, retmsg, reason = 'CustomerSupport')
        if success:
            ret = ReturnValue(result = 'ok')
        else:
            ret = ReturnValue(error = 'change_region failed')
        self.d.callback(ret)

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
        return props

    def recall_squad(self, player, region_id, squad_id):
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
            random.seed(self.user_id + self.gamedata['territory']['map_placement_gen'] + int(100*random.random()))

            map_dims = self.gamedata['regions'][new_region]['dimensions']
            BORDER = self.gamedata['territory']['border_zone_player']

            # radius: how far from the center of the map we can place the player
            radius = [map_dims[0]//2 - BORDER, map_dims[1]//2 - BORDER]

            # rectangle within which we can place the player
            placement_range = [[map_dims[0]//2 - radius[0], map_dims[0]//2 + radius[0]],
                               [map_dims[1]//2 - radius[1], map_dims[1]//2 + radius[1]]]
            trials = map(lambda x: (min(max(placement_range[0][0] + int((placement_range[0][1]-placement_range[0][0])*random.random()), 2), map_dims[0]-2),
                                    min(max(placement_range[1][0] + int((placement_range[1][1]-placement_range[1][0])*random.random()), 2), map_dims[1]-2)), xrange(100))

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
                    self.recall_squad(player, old_region, squad_id)
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
    def do_exec_online(self, session, retmsg):
        session.player.reset_idle_check_state()
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        if 'idle_check' in player:
            del player['idle_check']
        return ReturnValue(result = 'ok')

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
    'clear_lockout': HandleClearLockout,
    'clear_cooldown': HandleClearCooldown,
    'cooldown_togo': HandleCooldownTogo,
    'cooldown_active': HandleCooldownActive,
    'trigger_cooldown': HandleTriggerCooldown,
    'apply_aura': HandleApplyAura,
    'remove_aura': HandleRemoveAura,
    'check_idle': HandleCheckIdle,
    'chat_gag': HandleChatGag,
    'chat_ungag': HandleChatUngag,
    'give_item': HandleGiveItem,
    'send_message': HandleSendMessage,
    'change_region': HandleChangeRegion,
    'demote_alliance_leader': HandleDemoteAllianceLeader,
    'kick_alliance_member': HandleKickAllianceMember,
    'reset_idle_check_state': HandleResetIdleCheckState,
}
