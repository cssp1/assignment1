#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# ActivityClassifier is a little library that the game server uses to attribute
# time-in-game to specific player activities. There are a few mutually-exclusive
# "primary" activities (harvesting, chatting, PvE, etc) and then some extra
# attributes that go into more detail about what the player was doing.

# The idea is that you instantiate this once per N minutes, call its
# methods when the player does something, then finalize() to get the
# best classification of what the player was doing during that window
# of time.

class ActivityClassifier(object):
    PRIORITY = {
        'pvquarry': 100,
        'pvp_map': 100,
        'pvp_list': 100,
        'pve_map': 100,
        'pve_list': 100,
        'pve_defense': 100,
        'invest': 50,
        'consume': 40,
        'chat': 20,
        'harvest': 10,
        'idle': -1
        }

    def __init__(self, gamedata):
        self.gamedata = gamedata
        self.state = 'idle'
        self.props = None
        self.gamebucks_spent = 0
        self.money_spent = 0
        self.purchases = []

    def did_action(self, name, props = None):
        cur_prio = self.PRIORITY[self.state]
        prio = self.PRIORITY[name]
        if prio >= cur_prio:
            self.state = name
            self.props = props

    def finalize(self):
        ret = {'state':self.state}
        if self.props:
            for k,v in self.props.iteritems():
                ret[k] = v
        if self.gamebucks_spent > 0: ret['gamebucks_spent'] = self.gamebucks_spent
        if self.money_spent > 0: ret['money_spent'] = self.money_spent
        if self.purchases and 0: ret['purchases'] = self.purchases # off for now to reduce bloat
        return ret

    def spent_money(self, amount, descr):
        self.money_spent += amount
        self.purchases.append({'money':amount, 'descr':descr})
    def spent_gamebucks(self, amount, descr):
        self.gamebucks_spent += amount
        self.purchases.append({'gamebucks':amount, 'descr':descr})

    def harvested(self):
        self.did_action('harvest')

    def built_or_upgraded_building(self):
        self.did_action('invest', {'kind':'building'})
    def researched_tech(self):
        self.did_action('invest', {'kind':'tech'})

    def manufactured_unit(self):
        self.did_action('consume', {'kind':'unit'})

    def sent_chat_message(self, channel):
        self.did_action('chat', {'channel':channel})

    def get_ai_props(self, hive_template, ai_id):
        if hive_template:
            hive = self.gamedata['hives']['templates'][hive_template]
            if 'analytics_tag' in hive:
                return {'tag': hive['analytics_tag']}
            else:
                ai_id = hive['owner_id'] # fall through

        base = self.gamedata['ai_bases']['bases'][str(ai_id)]
        if 'analytics_tag' in base:
            return {'tag': base['analytics_tag']}
        else:
            return {'ui_name': base['ui_name']}

    def suffered_ai_attack(self, attacker_id):
        if str(attacker_id) not in self.gamedata['ai_bases']['bases']: return # probably a tutorial or older attack
        props = {'attacker_id': attacker_id}
        props.update(self.get_ai_props(None, attacker_id))
        self.did_action('pve_defense', props)

    def attacked_base(self, viewing_player, viewing_base, using_squads = False):
        if viewing_base.base_type == 'quarry':
            self.did_action('pvquarry', {'template':viewing_base.base_template} if viewing_base.base_template else None)
        elif viewing_base.base_type == 'hive':
            props = {'template':viewing_base.base_template}
            props.update(self.get_ai_props(viewing_base.base_template, viewing_player.user_id))
            self.did_action('pve_map', props)
        elif viewing_player.is_ai():
            props = {'defender_id': viewing_player.user_id}
            props.update(self.get_ai_props(None, viewing_player.user_id))
            self.did_action('pve_list', props)

        elif viewing_player.is_human():
            if using_squads:
                self.did_action('pvp_map', {'base_type': viewing_base.base_type, 'defender_id': viewing_player.user_id})
            else:
                self.did_action('pvp_list', {'defender_id': viewing_player.user_id})
