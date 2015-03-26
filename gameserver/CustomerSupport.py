#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Server-side handlers for CONTROLAPI calls originated by tools like cgipcheck (PCHECK).

# These have both "online" and "offline" execution modes. The "online" mode operates
# on LivePlayer objects with active sessions, and the "offline" modes manipulate raw
# JSON structures. This allows all methods to work regardless of whether the affected
# player is currently logged in or not.

import SpinJSON
import random

# encapsulate the return value from CONTROLAPI support calls, to be interpreted by cgipcheck.html JavaScript
# basically, we return a JSON dictionary that either has a "result" (for successful calls) or an "error" (for failures).
# there is also a "kill_session" option that tells the server to (asynchronously) log the player out after we return.
class ReturnValue(object):
    def __init__(self, result = None, error = None, kill_session = False):
        assert result or error
        self.result = result
        self.error = error
        self.kill_session = kill_session
    def as_body(self):
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
        if 'customer_support' not in session.player.history:
            session.player.history['customer_support'] = []
        session.player.history['customer_support'].append(self.get_log_entry())
        return ret
    def exec_offline(self, user, player):
        ret = self.do_exec_offline(user, player)
        if 'customer_support' not in player['history']:
            player['history']['customer_support'] = []
        player['history']['customer_support'].append(self.get_log_entry())
        return ret

class HandleGetRaw(Handler):
    def format(self, result):
        if bool(int(self.args.get('stringify',False))):
            result = SpinJSON.dumps(result, pretty = True, newline = True, size_hint = 1024*1024, double_precision = 5)
        return result
class HandleGetRawPlayer(HandleGetRaw):
    # note: no logging
    def exec_online(self, session, retmsg):
        player_json = SpinJSON.loads(self.gamesite.player_table.unparse(session.player))
        return ReturnValue(result = self.format(player_json))
    def exec_offline(self, user, player):
        return ReturnValue(result = self.format(player))
class HandleGetRawUser(HandleGetRaw):
    # note: no logging
    def exec_online(self, session, retmsg):
        user_json = SpinJSON.loads(self.gamesite.user_table.unparse(session.user))
        return ReturnValue(result = self.format(user_json))
    def exec_offline(self, user, player):
        return ReturnValue(result = self.format(user))

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
    # Note: this does NOT release it in the unique aliases database!
    def do_exec_online(self, session, retmsg):
        session.player.alias = None
        return ReturnValue(result = 'ok')
    def do_exec_offline(self, user, player):
        if 'alias' in player: del player['alias']
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
        if 'blocked_users' not in prefs:
            prefs['blocked_users'] = []
        if other_id not in prefs['blocked_users']:
            prefs['blocked_users'].append(other_id)
class HandleChatUnblock(HandleChatBlockOrUnblock):
    def _do(self, prefs, other_id):
        if 'blocked_users' in prefs:
            if other_id in prefs['blocked_users']:
                prefs['blocked_users'].remove(other_id)

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

class HandleChatGag(Handler):
    def do_exec_online(self, session, retmsg):
        if 'duration' in self.args:
            # new-style gag
            if session.player.apply_aura('chat_gagged', 1, int(self.args['duration']), ignore_limit = True):
                session.player.stattab.send_update(session, session.deferred_messages)
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
            session.player.remove_aura(session, session.deferred_messages, aura_name, force = True)
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
        item = {'spec':self.args['spec']}
        stack = int(self.args.get('stack','1'))
        if stack > 1: item['stack'] = stack
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

methods = {
    'get_raw_player': HandleGetRawPlayer,
    'get_raw_user': HandleGetRawUser,
    'ban': HandleBan,
    'unban': HandleUnban,
    'make_developer': HandleMakeDeveloper,
    'unmake_developer': HandleUnmakeDeveloper,
    'clear_alias': HandleClearAlias,
    'chat_block': HandleChatBlock,
    'chat_unblock': HandleChatUnblock,
    'chat_official': HandleChatOfficial,
    'chat_unofficial': HandleChatUnofficial,
    'clear_lockout': HandleClearLockout,
    'clear_cooldown': HandleClearCooldown,
    'chat_gag': HandleChatGag,
    'chat_ungag': HandleChatUngag,
    'give_item': HandleGiveItem,
    'send_message': HandleSendMessage
}
