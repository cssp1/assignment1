# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Consequents are like Predicates, but represent actions that happen
# when a player accomplishes something instead of tests against player state.

import Predicates
import time, random, bisect, copy

# also depends on Player and GameObjects from server.py

class Consequent(object):
    # 'data' is the JSON dictionary { "predicate": "FOO", etc }
    def __init__(self, data):
        self.data = data
        self.kind = data['consequent']

class NullConsequent(Consequent):
    def execute(self, session, player, retmsg, context=None): return

class AndConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.subconsequents = []
        for sub in data['subconsequents']:
            self.subconsequents.append(read_consequent(sub))
    def execute(self, session, player, retmsg, context=None):
        for sub in self.subconsequents:
            sub.execute(session, player, retmsg, context)

class RandomConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.subconsequents = []
        self.breakpoints = []
        bp = 0.0
        for sub in data['subconsequents']:
            self.subconsequents.append(read_consequent(sub))
            bp += sub.get('random_weight',1.0)
            self.breakpoints.append(bp)
    def execute(self, session, player, retmsg, context=None):
        if not self.subconsequents: return
        choice = min(bisect.bisect(self.breakpoints, random.random()*self.breakpoints[-1]), len(self.breakpoints)-1)
        self.subconsequents[choice].execute(session, player, retmsg, context)

class PlayerHistoryConsequent(Consequent):
    def __init__(self, data, key, value, method):
        Consequent.__init__(self, data)
        self.key = key

        # if "value" starts with "$" then it's a reference to a context variable
        if type(value) in (str,unicode) and len(value) >= 1 and value[0] == '$':
            self.value = None
            self.value_from_context = value[1:]
        else: # otherwise it's a literal value
            self.value = value
            self.value_from_context = None

        self.method = method
    def execute(self, session, player, retmsg, context=None):
        if self.value_from_context:
            if context and (self.value_from_context in context):
                new_value = context[self.value_from_context]
            else:
                return # no effect
        else:
            new_value = self.value

        if self.method == 'max':
            session.deferred_history_update |= session.setmax_player_metric(self.key, new_value)
        elif self.method == 'set':
            session.deferred_history_update |= session.setvalue_player_metric(self.key, new_value)
        elif self.method == 'increment':
            session.deferred_history_update |= session.increment_player_metric(self.key, new_value)
        else:
            raise Exception('unknown method '+self.method)

class SessionLootConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.key = data['key']
        self.value = data['value']
    def execute(self, session, player, retmsg, context=None):
        session.loot[self.key] = session.loot.get(self.key,0) + self.value

class MetricEventConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.event_name = data['event_name']
        self.props = data.get('props', {})
        self.frequency = data.get('frequency', None)
        self.tag = data.get('tag', self.event_name)
    def execute(self, session, player, retmsg, context=None):
        if self.frequency == 'session':
            if session.sent_metrics.get(self.tag, False):
                return # already sent
            session.sent_metrics[self.tag] = True
        props = copy.deepcopy(self.props)
        session.metric_event_coded(player, self.event_name, props)

class SpawnSecurityTeamConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.units = data['units']
        self.spread = data.get('spread',-1)
    def execute(self, session, player, retmsg, context=None):
        session.spawn_security_team(player, retmsg, context['source_obj'], context['xy'], self.units, self.spread)

class DisplayMessageConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
    def execute(self, session, player, retmsg, context=None):
        assert self.data['consequent'] in ('DISPLAY_MESSAGE', 'MESSAGE_BOX')
        retmsg.append([self.data['consequent'], self.data])

class ClientConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
    def execute(self, session, player, retmsg, context=None):
        retmsg.append(["CLIENT_CONSEQUENT", self.data])

class FlashOfferConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.offer_name = data['offer']
    def execute(self, session, player, retmsg, context=None):
        offer = player.get_abtest_offer(self.offer_name)
        player.flash_offer = offer['spell']
        retmsg.append(["FLASH_OFFER", offer])

class GiveUnitsConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.units = data['units']
        self.limit_break = data.get('limit_break', True)
        self.limit_reduce_qty = data.get('limit_reduce_qty', False)
    def execute(self, session, player, retmsg, context=None):
        session.spawn_new_units_for_player(player, retmsg, self.units,
                                           limit_break = self.limit_break,
                                           limit_reduce_qty = self.limit_reduce_qty)

class TakeUnitsConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.units = data['units']
    def execute(self, session, player, retmsg, context=None):
        session.take_units_from_player(player, retmsg, self.units)

class TakeItemsConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.item_name = data['item_name']
        self.stack = data.get('stack',1)
    def execute(self, session, player, retmsg, context=None):
        to_take = self.stack

        to_take_from_inventory = min(to_take, session.player.inventory_item_quantity(self.item_name))
        if to_take_from_inventory > 0:
            # remove from regular inventory
            to_take -= session.player.inventory_remove_by_type(self.item_name, to_take_from_inventory, '5130_item_activated', reason='quest')
            session.player.send_inventory_update(retmsg)

        to_take_from_loot_buffer = min(to_take, session.player.loot_buffer_item_quantity(self.item_name))
        if to_take_from_loot_buffer > 0:
            # must be in the loot buffer then
            to_take -= session.player.loot_buffer_remove_by_type(self.item_name, to_take_from_loot_buffer, '5130_item_activated', reason='quest')
            retmsg.append(["LOOT_BUFFER_UPDATE", session.player.loot_buffer, False])

        if to_take > 0:
            raise Exception('did not take all the items requested (%d left)' % to_take)

class GiveTechConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.tech_name = data['tech_name']
        self.level = data.get('tech_level', 1)
    def execute(self, session, player, retmsg, context=None):
        session.give_tech(player, retmsg, self.tech_name, self.level, None, 'give_tech')

class GiveLootConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.loot = data['loot']
        self.reason = data.get('reason', None)
        self.reason_id = data.get('reason_id', None)
        self.mail_template = data.get('mail_template', None)
        self.item_duration = data.get('item_duration', -1)
        self.item_expire_at = data.get('item_expire_at', -1)
        self.force_send_by_mail = data.get('force_send_by_mail', False)
    def execute(self, session, player, retmsg, context=None):
        reason = context.get('loot_reason', self.reason) if context else self.reason
        assert reason
        reason_id = context.get('loot_reason_id', self.reason_id) if context else self.reason_id
        mail_template = context.get('loot_mail_template', self.mail_template) if context else self.mail_template
        session.give_loot(player, retmsg, self.loot, reason,
                          reason_id = reason_id,
                          mail_template = mail_template,
                          item_duration = self.item_duration, item_expire_at = self.item_expire_at,
                          force_send_by_mail = self.force_send_by_mail)

class GiveTrophiesConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.kind = data['trophy_kind']
        self.amount = data.get('amount', 0)
        self.amount_from_aura = data.get('amount_from_aura', None)
        self.method = data.get('method', '+')
        self.scale_by = data.get('scale_by', None)

    def execute(self, session, player, retmsg, context=None):
        amount = self.amount
        if self.amount_from_aura:
            for aura in player.player_auras:
                if aura['spec'] == self.amount_from_aura:
                    given = aura.get('stack', 1)
                    aura['stack'] = 0 # mark it as already given
                    amount += given

        if self.scale_by == 'base_damage':
            base_damage = session.viewing_base.calc_base_damage()
            amount = int(amount * base_damage + 0.5)
        elif self.scale_by == 'deployed_unit_space':
            deployment_limit = session.player.stattab.get_player_stat('deployable_unit_space')
            if deployment_limit > 0:
                amount = int(amount * (float(session.deployed_unit_space) / float(deployment_limit)) + 0.5)

        if amount != 0:
            sign = -1 if (self.method == '-') else 1
            session.give_trophies(player, self.kind, sign * amount)

class ApplyAuraConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.name = data['aura_name']
        self.duration = data.get('aura_duration',-1)
        self.strength = data.get('aura_strength',1)
        self.stack = data.get('stack',-1)
        self.stack_decay = data.get('stack_decay', None)
        if self.stack_decay:
            self.stack_decay_min = data.get('stack_decay_min',1)
            if self.stack_decay == 'periodic':
                self.stack_decay_origin = data['stack_decay_origin']
                self.stack_decay_period = data['stack_decay_period']
            elif self.stack_decay == 'event':
                self.stack_decay_event_kind = data['stack_decay_event_kind']
                self.stack_decay_event_name = data['stack_decay_event_name']
            else:
                raise Exception('unknown stack_decay type '+self.stack_decay)
        self.stack_from_context = data.get('stack_from_context', None)

    def execute(self, session, player, retmsg, context=None):
        stack = -1
        duration = self.duration

        if self.stack > 0:
            stack = self.stack
            if self.stack_decay:
                if self.stack_decay == 'periodic':
                    et = player.get_absolute_time()
                    et = max(et, self.stack_decay_origin)
                    progress = ((et - self.stack_decay_origin) % self.stack_decay_period) / float(self.stack_decay_period)
                    duration = self.stack_decay_period - ((et - self.stack_decay_origin) % self.stack_decay_period)
                elif self.stack_decay == 'event':
                    progress = player.get_event_time(self.stack_decay_event_kind, self.stack_decay_event_name, 'progress')
                    if not progress: return
                    duration = -player.get_event_time(self.stack_decay_event_kind, self.stack_decay_event_name, 'end')
                stack = max(int(stack + (self.stack_decay_min-stack)*progress + 0.5), 1)
            if self.stack_from_context and context:
                # override with the context value
                stack = context.get(self.stack_from_context, stack)

        if session.player.apply_aura(self.name, self.strength, duration, stack = stack, ignore_limit = True):
            session.player.stattab.send_update(session, retmsg)
            spec = session.player.get_abtest_aura(self.name)
            if ('on_apply' in spec):
                read_consequent(spec['on_apply']).execute(session, player, retmsg, context)

class RemoveAuraConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.name = data['aura_name']
        self.remove_stack = data.get('remove_stack',-1)
    def execute(self, session, player, retmsg, context=None):
        session.player.remove_aura(session, retmsg, self.name, remove_stack = self.remove_stack, force = True)

class CooldownTriggerConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.name = data['name']
        self.data = data.get('data', None)
        self.method = data.get('method', 'constant')
        if self.method == 'constant':
            self.duration_from_cooldown = data.get('duration_from_cooldown', None)
            self.duration = data.get('duration', None)
            assert (self.duration_from_cooldown is not None) or (self.duration is not None)
        elif self.method == 'periodic':
            self.period = data['period']
            self.origin = data['origin']
        else:
            raise Exception('unhandled cooldown method '+self.method)

    def execute(self, session, player, retmsg, context=None):
        if self.method == 'constant':
            if self.duration_from_cooldown:
                duration = player.cooldown_togo(self.duration_from_cooldown)
            else:
                duration = self.duration
        elif self.method == 'periodic':
            et = player.get_absolute_time()
            duration = self.period - ((et - self.origin) % self.period)
        session.player.cooldown_trigger(self.name, duration, data = self.data)
        retmsg.append(["COOLDOWNS_UPDATE", session.player.cooldowns])

class CooldownResetConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.name = data['name']
    def execute(self, session, player, retmsg, context=None):
        session.player.cooldown_reset(self.name)
        retmsg.append(["COOLDOWNS_UPDATE", session.player.cooldowns])

class FindAndReplaceItemsConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.item_map = data.get('item_map', None)
        self.recipe_map = data.get('recipe_map', None)
        self.config_map = data.get('config_map', None)
        self.affect_equipment = data.get('affect_equipment', True)
        self.affect_config = data.get('affect_config', True)
        self.affect_crafting = data.get('affect_crafting', True)
        self.affect_inventory = data.get('affect_inventory', True)

    def execute(self, session, player, retmsg, context=None):
        obj_updates = set()
        for obj in player.home_base_iter():
            if obj.is_building():
                if self.recipe_map and self.affect_crafting and obj.is_crafting():
                    for entry in obj.crafting.queue:
                        if entry.craft_state['recipe'] in self.recipe_map:
                            entry.craft_state['recipe'] = self.recipe_map[entry.craft_state['recipe']]
                            obj_updates.add(obj)
                if self.item_map and self.affect_equipment and obj.equipment:
                    for slot_type in obj.equipment:
                        for i in xrange(len(obj.equipment[slot_type])):
                            if obj.equipment[slot_type][i] in self.item_map:
                                obj.equipment[slot_type][i] = self.item_map[obj.equipment[slot_type][i]]
                                obj_updates.add(obj)
                if self.config_map and self.affect_config and obj.config:
                    for key in obj.config:
                        if key in self.config_map:
                            if obj.config[key] in self.config_map[key]:
                                obj.config[key] = self.config_map[key][obj.config[key]]
                                obj_updates.add(obj)

        if self.item_map and self.affect_equipment and player.unit_equipment:
            for equipment in player.unit_equipment.itervalues():
                for slot_type in equipment:
                    for i in xrange(len(equipment[slot_type])):
                        equipment[slot_type][i] = self.item_map.get(equipment[slot_type][i], equipment[slot_type][i])

        if self.item_map and self.affect_inventory:
            for entry in player.inventory:
                entry['spec'] = self.item_map.get(entry['spec'], entry['spec'])

        for obj in obj_updates:
            retmsg.append(["OBJECT_STATE_UPDATE2", obj.serialize_state()])
        if self.affect_equipment:
            retmsg.append(["PLAYER_UNIT_EQUIP_UPDATE", session.player.unit_equipment])
            session.player.recalc_stattab(session.player)
            session.player.stattab.send_update(session, retmsg)
        if self.affect_inventory:
            session.player.send_inventory_update(retmsg)

class FindAndReplaceObjectsConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.replacements = data['replacements']

    def execute(self, session, player, retmsg, context=None):
        for obj in player.home_base_iter():
            if obj.is_building(): # right now this only handles buildings
                for select, replace in self.replacements:
                    if obj.spec.name == select['spec'] and (('level' not in select) or (obj.level+1 if obj.is_upgrading() else obj.level) == select['level']):
                        # we found it!

                        # perform an automatic speedup to avoid corner cases
                        obj.heal_to_full(); obj.repair_finish_time = -1
                        if obj.is_under_construction():
                            obj.build_total_time = obj.build_start_time = obj.build_done_time = -1
                        if obj.is_upgrading():
                            obj.upgrade_total_time = obj.upgrade_start_time = obj.upgrade_done_time = -1
                            obj.change_level(obj.level + 1)

                        # now perform replacements
                        if 'spec' in replace:
                            obj.change_spec(player.get_abtest_object_spec(replace['spec']))
                        if 'level' in replace:
                            obj.change_level(replace['level'])
                        if 'equipment' in replace:
                            for slot_type, name_list in replace['equipment'].iteritems():
                                # XXXXXX separate Equipment.py from server.py and use it here
                                if obj.equipment is None: obj.equipment = {}
                                if slot_type not in obj.equipment: obj.equipment[slot_type] = []
                                for name in name_list:
                                    if name not in obj.equipment[slot_type]:
                                        obj.equipment[slot_type].append(name)

                        session.deferred_object_state_updates.add(obj)
                        session.deferred_stattab_update = True
                        session.deferred_power_change = True

                        # run history metrics
                        # XXXXXX unify with server.py do_ping_object
                        num_built = sum([1 for p in obj.owner.home_base_iter() if p.spec.name == obj.spec.name])
                        session.deferred_history_update |= session.setmax_player_metric('building:'+obj.spec.name+':num_built', num_built, bucket = bool(obj.spec.worth_less_xp))
                        max_level = max([p.level for p in obj.owner.home_base_iter() if p.spec.name == obj.spec.name])
                        session.deferred_history_update |= session.setmax_player_metric('building:'+obj.spec.name+':max_level', max_level, bucket = bool(obj.spec.worth_less_xp))
                        if obj.spec.history_category:
                            max_level = max([p.level for p in obj.owner.home_base_iter() if p.spec.history_category == obj.spec.history_category])
                            session.deferred_history_update |= session.setmax_player_metric(obj.spec.history_category+'_max_level', max_level, bucket = bool(obj.spec.worth_less_xp))
                        if obj.spec.track_level_in_player_history:
                            session.deferred_history_update |= session.setmax_player_metric(obj.spec.name+'_level', obj.level, bucket = bool(obj.spec.worth_less_xp))

class ChatSendConsequent(Consequent):
   def __init__(self, data):
       Consequent.__init__(self, data)
       self.channels = data.get('channels', ['GLOBAL'])
       self.text = data.get('text','')
       self.type = data.get('type','default')
   def execute(self, session, player, retmsg, context=None):
       props = None
       if self.type != 'default':
           props = {'type': self.type}
       for chan in self.channels:
           # XXX unify this code into something like session.map_chat_channel()
           if chan == 'GLOBAL': chan = session.global_chat_channel
           elif chan == 'REGION': chan = session.region_chat_channel
           elif chan == 'ALLIANCE': chan = session.alliance_chat_channel
           if chan:
               session.do_chat_send(chan, self.text, bypass_gag = True, props = props)

class MarkBirthdayConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.tag = data['tag']
    def execute(self, session, player, retmsg, context=None):
        player.history['birthday_' + self.tag] = max(player.history.get('birthday_' + self.tag, 0), time.gmtime(player.get_absolute_time()).tm_year)
        session.player.cooldown_trigger('birthday_' + self.tag, 31536000) # 365 days

class IfConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.predicate = Predicates.read_predicate(data['if'])
        self.then_consequent = read_consequent(data['then'])
        if 'else' in data:
            self.else_consequent = read_consequent(data['else'])
        else:
            self.else_consequent = None
    def execute(self, session, player, retmsg, context=None):
        if self.predicate.is_satisfied2(session, player, None):
            return self.then_consequent.execute(session, player, retmsg, context)
        elif self.else_consequent:
            return self.else_consequent.execute(session, player, retmsg, context)

class CondConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.cond = []
        for entry in data['cond']:
            self.cond.append((Predicates.read_predicate(entry[0]), read_consequent(entry[1])))
    def execute(self, session, player, retmsg, context=None):
        for pred, cons in self.cond:
            if pred.is_satisfied2(session, player, None):
                return cons.execute(session, player, retmsg, context)

class DisplayDailyTipConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.name = data['name']
    def execute(self, session, player, retmsg, context=None):
        assert self.data['consequent'] == 'DISPLAY_DAILY_TIP'
        retmsg.append([self.data['consequent'], self.name])

class HealAllUnitsConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
    def execute(self, session, player, retmsg, context=None):
        session.heal_all_units(retmsg)

class HealAllBuildingsConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
    def execute(self, session, player, retmsg, context=None):
        session.heal_all_buildings(retmsg)

class LibraryConsequent(Consequent):
    def __init__(self, data):
        Consequent.__init__(self, data)
        self.name = data['name']
    def execute(self, session, player, retmsg, context=None):
        return read_consequent(player.get_abtest_consequent(self.name)).execute(session, player, retmsg, context)

# instantiate a Consequent object from JSON
def read_consequent(data):
    kind = data['consequent']
    if kind == 'NULL': return NullConsequent(data)
    elif kind == 'AND': return AndConsequent(data)
    elif kind == 'RANDOM': return RandomConsequent(data)
    elif kind == 'IF': return IfConsequent(data)
    elif kind == 'COND': return CondConsequent(data)
    elif kind == 'PLAYER_HISTORY': return PlayerHistoryConsequent(data, data['key'], data['value'], data['method'])
    elif kind == 'SESSION_LOOT': return SessionLootConsequent(data)
    elif kind == 'METRIC_EVENT': return MetricEventConsequent(data)
    elif kind == 'SPAWN_SECURITY_TEAM': return SpawnSecurityTeamConsequent(data)
    elif kind == 'DISPLAY_MESSAGE' or kind == 'MESSAGE_BOX': return DisplayMessageConsequent(data)
    elif kind == 'FLASH_OFFER': return FlashOfferConsequent(data)
    elif kind == 'GIVE_UNITS': return GiveUnitsConsequent(data)
    elif kind == 'TAKE_UNITS': return TakeUnitsConsequent(data)
    elif kind == 'TAKE_ITEMS': return TakeItemsConsequent(data)
    elif kind == 'GIVE_TECH': return GiveTechConsequent(data)
    elif kind == 'GIVE_LOOT': return GiveLootConsequent(data)
    elif kind == 'GIVE_TROPHIES': return GiveTrophiesConsequent(data)
    elif kind == 'APPLY_AURA': return ApplyAuraConsequent(data)
    elif kind == 'REMOVE_AURA': return RemoveAuraConsequent(data)
    elif kind == 'COOLDOWN_TRIGGER': return CooldownTriggerConsequent(data)
    elif kind == 'COOLDOWN_RESET': return CooldownResetConsequent(data)
    elif kind == 'FIND_AND_REPLACE_ITEMS': return FindAndReplaceItemsConsequent(data)
    elif kind == 'FIND_AND_REPLACE_OBJECTS': return FindAndReplaceObjectsConsequent(data)
    elif kind == 'CHAT_SEND': return ChatSendConsequent(data)
    elif kind == 'MARK_BIRTHDAY': return MarkBirthdayConsequent(data)
    elif kind == 'DISPLAY_DAILY_TIP': return DisplayDailyTipConsequent(data)
    elif kind == 'HEAL_ALL_UNITS': return HealAllUnitsConsequent(data)
    elif kind == 'HEAL_ALL_BUILDINGS': return HealAllBuildingsConsequent(data)
    elif kind == 'LIBRARY': return LibraryConsequent(data)
    elif kind in ('INVOKE_UPGRADE_DIALOG','INVOKE_BLUEPRINT_CONGRATS','START_AI_ATTACK','PRELOAD_ART_ASSET'): return ClientConsequent(data)
    else:
        raise Exception('unknown consequent '+kind)
