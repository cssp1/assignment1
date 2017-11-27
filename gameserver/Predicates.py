# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinConfig
import time, random

# depends on Player and GameObjects from server.py
# note: this is functionally identical to the client's Predicates.js

class Predicate(object):
    # 'data' is the JSON dictionary { "predicate": "FOO", etc }
    def __init__(self, data):
        self.kind = data['predicate']
    def remember_state(self, player, qdata):
        pass

    # this is a new function we want to migrate some session-dependent .is_satisfied() calls to
    # it will default to the old is_satisfied() if there is no override in the subclass
    # XXX add a context= parameter to this, like Consequent.execute()
    def is_satisfied2(self, session, player, qdata, override_time = None):
        return self.is_satisfied(player, qdata)

class AlwaysTruePredicate(Predicate):
    def is_satisfied(self, player, qdata):
        return True

class AlwaysFalsePredicate(Predicate):
    def is_satisfied(self, player, qdata):
        return False

class RandomPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.chance = data['chance']
    def is_satisfied(self, player, qdata):
        return random.random() < self.chance

class ComboPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.subpredicates = []
        for sub in data['subpredicates']:
            self.subpredicates.append(read_predicate(sub))
    def remember_state(self, player, qdata):
        for sub in self.subpredicates:
            sub.remember_state(player, qdata)

class AndPredicate(ComboPredicate):
    def is_satisfied(self, player, qdata):
        for sub in self.subpredicates:
            if not sub.is_satisfied(player, qdata):
                return False
        return True
    def is_satisfied2(self, session, player, qdata, override_time = None):
        for sub in self.subpredicates:
            if not sub.is_satisfied2(session, player, qdata, override_time = override_time):
                return False
        return True
class OrPredicate(ComboPredicate):
    def is_satisfied(self, player, qdata):
        for sub in self.subpredicates:
            if sub.is_satisfied(player, qdata):
                return True
        return False
    def is_satisfied2(self, session, player, qdata, override_time = None):
        for sub in self.subpredicates:
            if sub.is_satisfied2(session, player, qdata, override_time = override_time):
                return True
        return False
class NotPredicate(ComboPredicate):
    def is_satisfied(self, player, qdata):
        return not self.subpredicates[0].is_satisfied(player, qdata)
    def is_satisfied2(self, session, player, qdata, override_time = None):
        return not self.subpredicates[0].is_satisfied2(session, player, qdata, override_time = override_time)

class AllBuildingsUndamagedPredicate(Predicate):
    def is_shooter(self, spec):
        for spellname in spec.spells:
            if 'SHOOT' in spellname:
                return True
        return False
    def is_satisfied(self, player, qdata):
        for obj in player.home_base_iter():
            # don't count turrets, since they may be damaged/degraded by A/B tests or tutorial
            if obj.spec.kind == "building" and (not self.is_shooter(obj.spec)) and obj.is_damaged() and obj.owner is player:
                return False
        return True

class TutorialCompletePredicate(Predicate):
    def is_satisfied(self, player, qdata):
        return player.tutorial_state == "COMPLETE"

class RetainedPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.duration = data.get('duration',None)
        self.age_range = data.get('age_range',None)

    def is_satisfied(self, player, qdata):
        if player.creation_time < 0: return False
        if ('sessions' not in player.history): return False
        sessions = player.history['sessions']
        if len(sessions) < 1: return False
        if self.age_range is not None:
            for s in sessions:
                if (s[0] > 0):
                    age = s[0] - player.creation_time
                    if age < self.age_range[0]:
                        continue
                    elif age < self.age_range[1]:
                        return True
                    else:
                        break
            return False
        else:
            assert self.duration is not None
            s = sessions[-1]
            if s[0] < 1: return False
            return (s[0] - player.creation_time) >= self.duration

class LoggedInRecentlyPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.seconds_ago = data['seconds_ago']
    def is_satisfied(self, player, qdata):
        now = player.get_absolute_time()
        if player.creation_time < 0: return False
        if ('sessions' not in player.history): return False
        sessions = player.history['sessions']
        if len(sessions) < 1: return False
        s = sessions[-1]
        if (s[1] > 0) and (s[1] < (now - self.seconds_ago)): return False
        return True

class SessionLengthTrendPredicate(Predicate):
    # checks for decreasing trend in average session length, indicating that churn is likely
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.recent_window = data['recent_window']
        self.longterm_window = data['longterm_window']
        self.threshold = data['threshold']
        assert data['method'] == '<'
    def get_avg_session_length(self, sessions, lookback, skip):
        # return average length of up to "lookback" sessions, not including the most recent "skip" sessions
        recent_num = 0
        recent_time = 0
        for s in sessions[-lookback:-skip]:
            if (s[0] > 0) and (s[1] > 0) and (s[1] > s[0]):
                recent_num += 1
                recent_time += s[1]-s[0]
        if recent_num < 1: return -1
        return float(recent_time)/float(recent_num)
    def is_satisfied(self, player, qdata):
        if ('sessions' not in player.history): return False
        sessions = player.history['sessions']
        if len(sessions) < (2*self.recent_window): return False # ensure there are at least two test windows worth of sessions
        recent_avg = self.get_avg_session_length(sessions, self.recent_window, 0)
        longterm_avg = self.get_avg_session_length(sessions, self.longterm_window, self.recent_window)
        return (recent_avg > 0) and (longterm_avg > 0) and (recent_avg < self.threshold * longterm_avg)

class TimeInGamePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        if 'seconds' in data:
            self.seconds = data['seconds']
        else:
            self.seconds = 60*60*data['hours']
        if 'by_day' in data:
            self.by_age = 24*60*60*data['by_day']
        else:
            self.by_age = None
        if 'within_last' in data:
            self.within_last = data['within_last']
        else:
            self.within_last = None

    def is_satisfied2(self, session, player, qdata, override_time = None):
        if player.creation_time < 0: return False
        if ('sessions' not in player.history): return False

        cur_time = player.get_absolute_time()
        sessions = player.history['sessions']

        time_range = [player.creation_time, cur_time]
        direction = 1

        if self.by_age is not None:
            time_range[1] = player.creation_time + self.by_age
        if self.within_last is not None:
            time_range[0] = cur_time - self.within_last
            direction = -1 # iterate backwards, it's likely faster

        total_seconds = 0

        if direction > 0:
            sessions_iter = xrange(0, len(sessions), 1)
        else:
            sessions_iter = xrange(len(sessions)-1, -1, -1)

        for i in sessions_iter:
            s = sessions[i]
            if s[0] < 0 or s[1] < 0: continue
            if s[1] < time_range[0]: continue
            if s[0] >= time_range[1]: continue
            clipped_start = max(s[0], time_range[0])
            clipped_end = min(s[1], time_range[1])
            if clipped_end > clipped_start:
                total_seconds += clipped_end - clipped_start
            if total_seconds >= self.seconds: break

        # add the current session
        if session.login_time < time_range[1]:
            clipped_start = max(session.login_time, time_range[0])
            clipped_end = min(cur_time, time_range[1])
            if clipped_end > clipped_start:
                total_seconds += clipped_end - clipped_start

        return total_seconds >= self.seconds

class AccountCreationTimePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.range = data.get('range', None)
        self.age_range = data.get('age_range', None)
    def is_satisfied(self, player, qdata):
        creat = player.creation_time
        if self.range:
            if self.range[0] >= 0 and creat < self.range[0]: return False
            if self.range[1] >= 0 and creat > self.range[1]: return False
        if self.age_range:
            age = player.get_absolute_time() - creat
            if self.age_range[0] >= 0 and age < self.age_range[0]: return False
            if self.age_range[1] >= 0 and age > self.age_range[1]: return False
        return True

class ObjectUndamagedPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.spec_name = data['spec']
    def is_satisfied(self, player, qdata):
        for obj in player.home_base_iter():
            if obj.spec.name == self.spec_name and (not obj.is_damaged()) and obj.owner is player:
                return True
        return False

class ObjectUnbusyPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.spec_name = data['spec']
    def is_satisfied(self, player, qdata):
        for obj in player.home_base_iter():
            if obj.spec.name == self.spec_name and (not obj.is_damaged()) and (not obj.is_busy()) and obj.owner is player:
                return True
        return False

class ForemanIsBusyPredicate(Predicate):
    def is_satisfied(self, player, qdata):
        return player.foreman_is_busy()

class BaseRichnessPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.min_richness = data['min_richness']
    def is_satisfied2(self, session, player, qdata, override_time = None):
        return (session.viewing_base.base_type == 'quarry') and \
               session.viewing_base.base_richness >= self.min_richness

class BaseTypePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.types = data['types']
    def is_satisfied2(self, session, player, qdata, override_time = None):
        return session.viewing_base.base_type in self.types

class BuildingQuantityPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.building_type = data['building_type']
        self.trigger_qty = data['trigger_qty']
        self.under_construction_ok = data.get('under_construction_ok', False)

    def is_satisfied(self, player, qdata):
        howmany = 0
        for obj in player.home_base_iter():
            if obj.spec.kind == 'building' and obj.spec.name == self.building_type and \
               ((not obj.is_under_construction()) or self.under_construction_ok):
                howmany += 1
        return (howmany >= self.trigger_qty)

class BuildingLevelPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.building_type = data['building_type']
        self.trigger_level = data['trigger_level']
        self.trigger_qty = data.get('trigger_qty', 1)
        self.upgrading_ok = data.get('upgrading_ok', False)
    def is_satisfied(self, player, qdata):
        count = 0
        for obj in player.home_base_iter():
            if obj.spec.kind == 'building' and obj.spec.name == self.building_type and \
               (not obj.is_under_construction()):
                if (obj.level >= self.trigger_level):
                    count += 1
                elif (self.upgrading_ok and ((obj.level+1) >= self.trigger_level)):
                    count += 1
                elif self.trigger_qty < 0:
                    return False # require ALL buildings to be at this level

        return count >= self.trigger_qty

class UnitQuantityPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.unit_type = data['unit_type']
        self.trigger_qty = data['trigger_qty']
        self.method = data.get('method', '>=')
    def is_satisfied(self, player, qdata):
        howmany = 0
        for obj in player.home_base_iter():
            if obj.spec.kind == 'mobile' and obj.spec.name == self.unit_type and obj.owner is player:
                howmany += 1

        if self.method == '>=':
            return howmany >= self.trigger_qty
        elif self.method == '==':
            return howmany == self.trigger_qty
        elif self.method == '<':
            return howmany < self.trigger_qty
        else:
            raise Exception('unknown method '+self.method)

class TechLevelPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.tech = data['tech']
        self.min_level = data['min_level']
        self.max_level = data.get('max_level',-1)
    def is_satisfied(self, player, qdata):
        return (player.tech.get(self.tech,0) >= self.min_level) and \
               ((self.max_level < 0) or (player.tech.get(self.tech,0) <= self.max_level))

class QuestActivePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.quest_name = data['quest_name']
    def is_satisfied2(self, session, player, qdata, override_time = None):
        if (self.quest_name in player.completed_quests): return False
        target_quest = player.get_abtest_quest(self.quest_name)
        if target_quest.activation and (not target_quest.activation.is_satisfied2(session, player, qdata, override_time = override_time)): return False
        if target_quest.goal.is_satisfied2(session, player, qdata): return False
        return True

    def is_satisfied(self, player, qdata): # XXXXXX remove when safe
        if (self.quest_name in player.completed_quests): return False
        target_quest = player.get_abtest_quest(self.quest_name)
        if target_quest.activation and (not target_quest.activation.is_satisfied(player, qdata)): return False
        if target_quest.goal.is_satisfied(player, qdata): return False
        return True

class QuestCompletedPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.quest_name = data['quest_name']
        self.must_claim = bool(data.get('must_claim', False))
    def is_satisfied2(self, session, player, qdata, override_time = None):
        target_quest = player.get_abtest_quest(self.quest_name)
        # new skip_quest_claim behavior - don't require quest to have been claimed
        # (if this becomes a performance problem, may need to cache the player's satisfied quests)
        if (not self.must_claim) and (not target_quest.force_claim):
            if target_quest.activation and (not target_quest.activation.is_satisfied2(session, player, qdata, override_time = override_time)): return False
            return target_quest.goal.is_satisfied2(session, player, qdata)
        else:
            return (self.quest_name in player.completed_quests)

    def is_satisfied(self, player, qdata): # XXXXXX remove when safe
        target_quest = player.get_abtest_quest(self.quest_name)
        # new skip_quest_claim behavior - don't require quest to have been claimed
        # (if this becomes a performance problem, may need to cache the player's satisfied quests)
        if (not self.must_claim) and (not target_quest.force_claim):
            if target_quest.activation and (not target_quest.activation.is_satisfied(player, qdata)): return False
            return target_quest.goal.is_satisfied(player, qdata)
        else:
            return (self.quest_name in player.completed_quests)

class AuraActivePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.aura_name = data['aura_name']
        self.min_stack = data.get('min_stack',1)
        self.min_level = data.get('min_level',-1)
        self.match_data = data.get('match_data', None)
    def is_satisfied(self, player, qdata):
        return self.is_satisfied2(None, player, qdata)
    def is_satisfied2(self, session, player, qdata, override_time = None):
        player.prune_player_auras()
        aura_list = player.player_auras_iter_const()
        if override_time is not None:
            # also check against recently-expired auras (e.g. for sales)
            aura_list = list(aura_list) + player.get_player_auras_recently_expired(override_time)
        for aura in aura_list:
            if override_time is not None and aura.get('start_time',-1) > override_time: continue

            if aura['spec'] == self.aura_name and aura.get('stack',1) >= self.min_stack and aura.get('level',1) >= self.min_level:
                if self.match_data is not None:
                    is_matched = True
                    for k, v in self.match_data.iteritems():
                        if aura.get('data',{}).get(k, None) != v:
                            is_matched = False
                            break
                    if not is_matched: continue
                return True
        return False
class AuraInactivePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.act_pred = AuraActivePredicate(data)
    def is_satisfied(self, player, qdata):
        return self.is_satisfied2(None, player, qdata)
    def is_satisfied2(self, session, player, qdata, override_time = None):
        return not self.act_pred.is_satisfied2(session, player, qdata, override_time = override_time)

class CooldownActivePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.name = data['name']
        self.match_data = data.get('match_data',None)
        self.min_togo = data.get('min_togo', 0)
    def is_satisfied(self, player, qdata):
        return player.cooldown_togo(self.name, match_data = self.match_data) >= self.min_togo

class CooldownInactivePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.act_pred = CooldownActivePredicate(data)
    def is_satisfied(self, player, qdata):
        return not self.act_pred.is_satisfied(player, qdata)

class FramePlatformPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.platform = data['platform']
    def is_satisfied(self, player, qdata):
        return player.frame_platform == self.platform

class FacebookLikesPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.id = data['id']
    def is_satisfied(self, player, qdata):
        if not player.user_facebook_likes: return False
        for entry in player.user_facebook_likes:
            if entry.get('id',None) == self.id:
                return True
        return False

class BrowserNamePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.names = data['names']
    def is_satisfied(self, player, qdata):
        return player.browser_name in self.names
class BrowserOSPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.os = data['os']
    def is_satisfied(self, player, qdata):
        return player.browser_os in self.os
class BrowserVersionPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.versions = data['versions']
    def is_satisfied(self, player, qdata):
        ver = int(player.browser_version)
        if self.versions[0] >= 0 and ver < self.versions[0]: return False
        if self.versions[1] >= 0 and ver > self.versions[1]: return False
        return True
class BrowserHardwarePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.hardware = data['hardware']
    def is_satisfied(self, player, qdata):
        return player.browser_hardware in self.hardware
class BrowserCapPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.cap_name = data['cap_name']
    def is_satisfied(self, player, qdata):
        return bool(player.browser_caps.get(self.cap_name, False))

class UserIDPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.allow = data['allow']
        self.mod = data.get('mod', None)
    def is_satisfied(self, player, qdata):
        test_id = player.user_id
        if self.mod is not None:
            test_id = test_id % self.mod
        return test_id in self.allow

class FacebookIDPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.allow = data['allow']
    def is_satisfied(self, player, qdata):
        return str(player.facebook_id) in self.allow

class FacebookAppNamespacePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.namespace = data['namespace']
    def is_satisfied(self, player, qdata):
        return SpinConfig.config.get('facebook_app_namespace',None) == self.namespace

class PriceRegionPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.regions = data['regions']
    def is_satisfied(self, player, qdata):
        return player.price_region in self.regions

class CountryTierPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.tiers = data['tiers']
    def is_satisfied(self, player, qdata):
        return SpinConfig.country_tier_map.get(player.country, 4) in self.tiers

class CountryPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.countries = data['countries']
    def is_satisfied(self, player, qdata):
        return player.country in self.countries

class PvPAggressedRecentlyPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.seconds_ago = data['seconds_ago']
    def is_satisfied(self, player, qdata):
        now = player.get_absolute_time()
        return player.history.get('last_pvp_aggression_time',-1) >= (now - self.seconds_ago)

class PurchasedRecentlyPredicate(Predicate):
    # true if player made a purchase less than "seconds_ago"
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.seconds_ago = data['seconds_ago']
    def is_satisfied(self, player, qdata):
        now = player.get_absolute_time()
        return player.history.get('last_purchase_time',-1) >= (now - self.seconds_ago)

class GamedataVarPredicate(Predicate):
    def __init__(self, data, name, value, method):
        Predicate.__init__(self, data)
        self.name = name
        self.value = value
        self.method = method or '=='

    def is_satisfied2(self, session, player, qdata, override_time = None):
        test_value = eval_cond_or_literal(player.get_gamedata_var(self.name), session, player, qdata, override_time = override_time)
        if self.method == '==':
            return test_value == self.value
        elif self.method == 'in':
            assert isinstance(self.value, list)
            return test_value in self.value
        else:
            raise Exception('unknown method '+self.method)

# generic predicate that searches player history stats for a specific minimum value
class PlayerHistoryPredicate(Predicate):
    def __init__(self, data, key, value, method):
        Predicate.__init__(self, data)
        self.key = key
        self.value = value
        self.method = method
        self.relative = data.get('relative', False)
        if 'by_day' in data:
            self.by_age = 24*60*60*data['by_day']
        else:
            self.by_age = -1

    def is_satisfied(self, player, qdata):
        if self.method == 'count_samples':
            count = 0
            series = player.history.get(self.key+'_at_time', {})
            for sage, value in series.iteritems():
                age = int(sage)
                if self.by_age < 0 or age < self.by_age:
                    count += 1
            return count >= self.value

        if self.by_age > 0:
            series = player.history.get(self.key+'_at_time', {})
            test_value = 0
            for sage, value in series.iteritems():
                age = int(sage)
                if age < self.by_age:
                    test_value = max(test_value, value)
        elif qdata and self.relative:
            # "qdata" is a chunk of player.completed_quests passed in that
            # allows us to check completion of repeatable quests that
            # involve incrementing a counter in player.history
            test_value = player.history.get(self.key, 0) - qdata.get(self.key, 0)
        else:
            test_value = player.history.get(self.key, 0)

        if self.method == '>=':
            return test_value >= self.value
        elif self.method == '==':
            return test_value == self.value
        elif self.method == '<':
            return test_value < self.value
        else:
            raise Exception('unknown method '+self.method)

    def remember_state(self, player, qdata):
        if self.relative:
            qdata[self.key] = player.history.get(self.key, 0)

class AIInstanceGenerationPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.value = data['value']
        self.method = data['method']
    def is_satisfied2(self, session, player, qdata, override_time = None):
        assert session.viewing_player.is_ai()
        test_value = session.viewing_player.ai_generation
        if self.method == '>=':
            return test_value >= self.value
        elif self.method == '==':
            return test_value == self.value
        elif self.method == '<':
            return test_value < self.value
        else:
            raise Exception('unknown method '+self.method)

# this looks at the delta between current friends_in_game and the initial_friends_in_game (set once on first login)
class FriendsJoinedPredicate(PlayerHistoryPredicate):
    def is_satisfied(self, player, qdata):
        if 'initial_friends_in_game' not in player.history:
            return False
        return (player.history.get(self.key, 0) - player.history['initial_friends_in_game']) >= self.value

class ABTestPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.test = data['test']
        self.key = data['key']
        self.value = data['value']
        self.defvalue = data['default']
    def is_satisfied(self, player, qdata):
        return player.get_abtest_value(self.test, self.key, self.defvalue) == self.value

class AnyABTestPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.key = data['key']
        self.value = data['value']
        self.defvalue = data.get('default',0)
    def is_satisfied(self, player, qdata):
        return player.get_any_abtest_value(self.key, self.defvalue) == self.value

class LibraryPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.name = data['name']
    def is_satisfied2(self, session, player, qdata, override_time = None):
        return read_predicate(player.get_abtest_predicate(self.name)).is_satisfied2(session, player, qdata, override_time = override_time)
    def is_satisfied(self, player, qdata): # XXXXXX remove when safe
        return read_predicate(player.get_abtest_predicate(self.name)).is_satisfied(player, qdata)

class AIBaseActivePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.user_id = data['user_id']
    def is_satisfied(self, player, qdata):
        base = player.get_abtest_ai_base(self.user_id)
        if base:
            if 'activation' in base:
                return read_predicate(base['activation']).is_satisfied(player, qdata)
            return True
        return False
class AIBaseShownPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.user_id = data['user_id']
    def is_satisfied(self, player, qdata):
        base = player.get_abtest_ai_base(self.user_id)
        if base:
            if 'show_if' in base:
                return read_predicate(base['show_if']).is_satisfied(player, qdata)
            if 'activation' in base:
                return read_predicate(base['activation']).is_satisfied(player, qdata)
            return True
        return False

class EventTimePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.name = data.get('event_name', None)
        self.kind = data.get('event_kind', 'current_event')
        self.method = data.get('method', 'inprogress')
        self.range = data['range'] if 'range' in data else None
        self.ignore_activation = data.get('ignore_activation', False)
        self.t_offset = data.get('time_offset', 0)
    def is_satisfied(self, player, qdata):
        return self.is_satisfied2(None, player, qdata)
    def is_satisfied2(self, session, player, qdata, override_time = None):
        if override_time is not None:
            # offset that will adjust absolute time back to override_time
            ref_offset = override_time - player.get_absolute_time()
        else:
            ref_offset = 0
        et = player.get_event_time(self.kind, self.name, self.method, ignore_activation = self.ignore_activation,
                                   t_offset = self.t_offset + ref_offset)
        if et is None: return False
        if self.range:
            return (et >= self.range[0] and et < self.range[1])
        else:
            return bool(et)

class AbsoluteTimePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.range = data['range']
        self.mod = data.get('mod', -1)
        self.shift = data.get('shift', 0)
        self.repeat_interval = data.get('repeat_interval', None)
    def is_satisfied(self, player, qdata):
        return self.is_satisfied2(None, player, qdata)
    def is_satisfied2(self, session, player, qdata, override_time = None):
        if override_time is not None:
            et = override_time
        else:
            et = player.get_absolute_time()
            if et is None: return False

        et = et + self.shift
        if self.mod > 0:
            et = et % self.mod

        # before range start?
        if self.range[0] >= 0 and et < self.range[0]: return False

        # after range end?
        if self.range[1] >= 0:
            if self.repeat_interval:
                delta = (et - self.range[0]) % self.repeat_interval
                if delta >= (self.range[1] - self.range[0]): return False
            else:
                if et >= self.range[1]: return False
        return True

class TimeOfDayPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.hour_range = data['hour_range']
    def is_satisfied(self, player, qdata):
        et = player.get_absolute_time()
        if et is None: return False
        gmt = time.gmtime(et)
        if self.hour_range[0] >= 0 and gmt.tm_hour < self.hour_range[0]: return False
        if self.hour_range[1] >= 0 and gmt.tm_hour > self.hour_range[1]: return False
        return True

class HasAttackedPredicate(Predicate):
    def is_satisfied2(self, session, player, qdata, override_time = None):
        return session.has_attacked

class BaseSizePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.method = data['method']
        self.value = data['value']
    def is_satisfied(self, player, qdata):
        cur = player.my_home.base_size
        if self.method == '>=':
            return cur >= self.value
        elif self.method == '<':
            return cur < self.value
        elif self.method == '==':
            return cur == self.value
        else:
            raise Exception('unknown method '+self.method)

class HomeRegionPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.regions = data.get('regions',None)
        self.require_nosql = data.get('is_nosql',False)
    def is_satisfied(self, player, qdata):
        if self.regions is not None:
            if 'ANY' in self.regions:
                return bool(player.home_region)
            else:
                return (player.home_region in self.regions)
        if self.require_nosql:
            if not player.home_region: return False
            data = player.get_abtest_region(player.home_region)
            if not data: return False
            return data.get('storage',None) == 'nosql'
        return False

class RegionPropertyPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.key = data['key']
        self.value = data['value']
        self.default = data.get('default', 0)
    def is_satisfied(self, player, qdata):
        if (not player.home_region): return False
        data = player.get_abtest_region(player.home_region)
        if not data: return False
        return data.get(self.key, self.default) == self.value

class GamebucksBalancePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.value = data['value']
        self.method = data.get('method', '>=')
        assert self.method == '>='
    def is_satisfied(self, player, qdata):
        return player.resources.gamebucks >= self.value

class HasItemPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.item_name = data['item_name']
        self.min_count = data.get('min_count', 1)
        self.level = data.get('level', None)
        self.min_level = data.get('min_level', None)
        self.check_mail = data.get('check_mail', False) # also check mailbox attachments
        self.check_crafting = data.get('check_crafting', False)
    def is_satisfied(self, player, qdata):
        return player.has_item(self.item_name, level = self.level, min_level = self.min_level, min_count = self.min_count, check_mail = self.check_mail, check_crafting = self.check_crafting)

class HasItemSetPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.item_set = data['item_set']
        self.min_count = data.get('min',-1)
    def is_satisfied(self, player, qdata):
        if (self.item_set not in player.stattab.item_sets): return False
        min_count = self.min_count
        if min_count < 0:
            # pull max from gamedata
            spec = player.get_abtest_item_set(self.item_set)
            min_count = len(spec['members'])
        return len(player.stattab.item_sets[self.item_set]) >= min_count

class HasAliasPredicate(Predicate):
    def is_satisfied(self, player, qdata):
        return bool(player.alias)

class HasMentorPredicate(Predicate):
    def is_satisfied(self, player, qdata):
        return bool(player.mentor_player_id_cache)

class HasTitlePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.name = data['name']
    def is_satisfied(self, player, qdata):
        title = player.get_abtest_title(self.name)
        for PRED in ('show_if','requires'):
            if PRED in title and not read_predicate(title[PRED]).is_satisfied(player, qdata):
                return False
        return True

class UsingTitlePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.name = data.get('name',None)
    def is_satisfied(self, player, qdata):
        if self.name is None:
            return (player.title and player.get_abtest_title(player.title))
        else:
            return player.title == self.name

class PlayerLevelPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.level = data['level']
    def is_satisfied(self, player, qdata):
        return player.level() >= self.level

class NewBirthdayPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.tag = data['tag']
    def is_satisfied(self, player, qdata):
        if player.cooldown_active('birthday_' + self.tag):
            return False

        now_unix = player.get_absolute_time()
        today = time.gmtime(now_unix)
        if 'birthday_' + self.tag in player.history:
            if player.history['birthday_' + self.tag] >= today.tm_year:
                return False

        if player.birthday:
            birthday = time.gmtime(player.birthday)
            birthday_unix = SpinConfig.cal_to_unix((today.tm_year, birthday.tm_mon, birthday.tm_mday))
            start_unix = now_unix - 604800 # 7 days
            return (start_unix <= birthday_unix) and (birthday_unix <= now_unix)

        return False

class ArmySizePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.trigger_qty = data['trigger_qty']
        self.method = data.get('method', '>=')
        self.include_queued = data.get('include_queued', True)
        self.squad_id = data.get('squad_id', 'ALL')

    def is_satisfied(self, player, qdata):
        army_size = player.get_army_space_usage_by_squad()[str(self.squad_id)]

        if not self.include_queued:
            army_size -= player.get_manufacture_queue_space_usage()

        if self.method == '>=':
            return army_size >= self.trigger_qty
        elif self.method == '==':
            return army_size == self.trigger_qty
        elif self.method == '<':
            return army_size < self.trigger_qty
        else:
            raise Exception('unknown method '+self.method)

# FOR GUI PURPOSES ONLY! NOT GUARANTEED ACCURATE!
class IsInAlliancePredicate(Predicate):
    def is_satisfied2(self, session, player, qdata, override_time = None):
        assert player is session.player
        return session.alliance_id_cache >= 0

class LadderPlayerPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
    def is_satisfied(self, player, qdata):
        return player.is_ladder_player()

class ViewingBaseDamagePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.value = data['value']
        self.method = data.get('method', '>=')
        self.assert_owner = data.get('assert_owner', None)
    def is_satisfied2(self, session, player, qdata, override_time = None):
        if self.assert_owner == 'self_home':
            assert session.viewing_base is player.my_home
        base_damage = session.viewing_base.calc_base_damage()
        if self.method == '>=':
            return base_damage >= self.value
        else:
            raise Exception('unknown method '+self.method)

class ViewingBaseObjectDestroyedPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.spec = data['spec']
    def is_satisfied2(self, session, player, qdata, override_time = None):
        for obj in session.viewing_base.iter_objects():
            if obj.spec.name == self.spec and obj.is_destroyed():
                return True
        return False

class PlayerPreferencePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        self.key = data['key']
        self.value = bool(data['value'])
    def is_satisfied(self, player, qdata):
        return player.player_preferences and \
               (bool(player.player_preferences.get(self.key, False)) == self.value)

class HomeBasePredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
    def is_satisfied2(self, session, player, qdata, override_time = None):
        return bool(session.home_base)

class TrustLevelPredicate(Predicate):
    def __init__(self, data):
        Predicate.__init__(self, data)
        # sync with loginserver.py
        self.min_level = {'TRUST_ANONYMOUS_GUEST': 0,
                          'TRUST_UNVERIFIED': 5,
                          'TRUST_VERIFIED': 10}[data['min_level']]
    def is_satisfied2(self, session, player, qdata, override_time = None):
        return session.player.trust_level >= self.min_level

# instantiate a Predicate object from JSON
def read_predicate(data):
    kind = data['predicate']
    if kind == 'AND': return AndPredicate(data)
    elif kind == 'OR': return OrPredicate(data)
    elif kind == 'NOT': return NotPredicate(data)
    elif kind == 'ALWAYS_TRUE': return AlwaysTruePredicate(data)
    elif kind == 'ALWAYS_FALSE': return AlwaysFalsePredicate(data)
    elif kind == 'RANDOM': return RandomPredicate(data)
    elif kind == 'TUTORIAL_COMPLETE': return TutorialCompletePredicate(data)
    elif kind == 'RETAINED': return RetainedPredicate(data)
    elif kind == 'LOGGED_IN_RECENTLY': return LoggedInRecentlyPredicate(data)
    elif kind == 'SESSION_LENGTH_TREND': return SessionLengthTrendPredicate(data)
    elif kind == 'TIME_IN_GAME': return TimeInGamePredicate(data)
    elif kind == 'ACCOUNT_CREATION_TIME': return AccountCreationTimePredicate(data)
    elif kind == 'ALL_BUILDINGS_UNDAMAGED': return AllBuildingsUndamagedPredicate(data)
    elif kind == 'OBJECT_UNDAMAGED': return ObjectUndamagedPredicate(data)
    elif kind == 'OBJECT_UNBUSY': return ObjectUnbusyPredicate(data)
    elif kind == 'FOREMAN_IS_BUSY': return ForemanIsBusyPredicate(data)
    elif kind == 'BASE_TYPE': return BaseTypePredicate(data)
    elif kind == 'BASE_RICHNESS': return BaseRichnessPredicate(data)
    elif kind == 'BUILDING_QUANTITY': return BuildingQuantityPredicate(data)
    elif kind == 'BUILDING_LEVEL': return BuildingLevelPredicate(data)
    elif kind == 'UNIT_QUANTITY': return UnitQuantityPredicate(data)
    elif kind == 'TECH_LEVEL': return TechLevelPredicate(data)
    elif kind == 'QUEST_COMPLETED': return QuestCompletedPredicate(data)
    elif kind == 'QUEST_ACTIVE': return QuestActivePredicate(data)
    elif kind == 'AURA_ACTIVE': return AuraActivePredicate(data)
    elif kind == 'AURA_INACTIVE': return AuraInactivePredicate(data)
    elif kind == 'COOLDOWN_ACTIVE': return CooldownActivePredicate(data)
    elif kind == 'COOLDOWN_INACTIVE': return CooldownInactivePredicate(data)
    elif kind == 'ABTEST': return ABTestPredicate(data)
    elif kind == 'ANY_ABTEST': return AnyABTestPredicate(data)
    elif kind == 'LIBRARY': return LibraryPredicate(data)
    elif kind == 'AI_BASE_ACTIVE': return AIBaseActivePredicate(data)
    elif kind == 'AI_BASE_SHOWN': return AIBaseShownPredicate(data)
    elif kind == 'PVP_AGGRESSED_RECENTLY': return PvPAggressedRecentlyPredicate(data)
    elif kind == 'PURCHASED_RECENTLY': return PurchasedRecentlyPredicate(data)
    elif kind == 'PLAYER_HISTORY': return PlayerHistoryPredicate(data, data['key'], data['value'], data['method'])
    elif kind == 'GAMEDATA_VAR': return GamedataVarPredicate(data, data['name'], data['value'], data.get('method', None))
    elif kind == 'ATTACKS_LAUNCHED': return PlayerHistoryPredicate(data, 'attacks_launched', data['number'], ">=")
    elif kind == 'ATTACKS_VICTORY': return PlayerHistoryPredicate(data, 'attacks_victory', data['number'], ">=")
    elif kind == 'CONQUESTS': return PlayerHistoryPredicate(data, data['key'], data['value'], data['method'])
    elif kind == 'UNITS_MANUFACTURED': return PlayerHistoryPredicate(data, 'units_manufactured', data['number'], ">=")
    elif kind == 'LOGGED_IN_TIMES': return PlayerHistoryPredicate(data, 'logged_in_times', data['number'], ">=")
    elif kind == 'RESOURCES_HARVESTED_TOTAL':
        return PlayerHistoryPredicate(data, 'harvested_'+data['resource_type']+'_total', data['amount'], ">=")
    elif kind == 'RESOURCES_HARVESTED_AT_ONCE':
        return PlayerHistoryPredicate(data, 'harvested_'+data['resource_type']+'_at_once', data['amount'], ">=")
    elif kind == 'FRIENDS_JOINED':
        return FriendsJoinedPredicate(data, 'friends_in_game', data['number'], ">=")
    elif kind == 'AI_INSTANCE_GENERATION': return AIInstanceGenerationPredicate(data)
    elif kind == 'FRAME_PLATFORM': return FramePlatformPredicate(data)
    elif kind == 'FACEBOOK_LIKES_SERVER':
        return FacebookLikesPredicate(data)
    elif kind == 'FACEBOOK_LIKES_CLIENT':
        return AlwaysTruePredicate(data)
    elif kind == 'BROWSER_NAME':
        return BrowserNamePredicate(data)
    elif kind == 'BROWSER_OS':
        return BrowserOSPredicate(data)
    elif kind == 'BROWSER_VERSION':
        return BrowserVersionPredicate(data)
    elif kind == 'BROWSER_HARDWARE':
        return BrowserHardwarePredicate(data)
    elif kind == 'BROWSER_CAP':
        return BrowserCapPredicate(data)
    elif kind == 'PRICE_REGION':
        return PriceRegionPredicate(data)
    elif kind == 'USER_ID':
        return UserIDPredicate(data)
    elif kind == 'FACEBOOK_ID':
        return FacebookIDPredicate(data)
    elif kind == 'FACEBOOK_APP_NAMESPACE':
        return FacebookAppNamespacePredicate(data)
    elif kind == 'COUNTRY_TIER':
        return CountryTierPredicate(data)
    elif kind == 'COUNTRY':
        return CountryPredicate(data)
    elif kind == 'EVENT_TIME':
        return EventTimePredicate(data)
    elif kind == 'ABSOLUTE_TIME':
        return AbsoluteTimePredicate(data)
    elif kind == 'TIME_OF_DAY':
        return TimeOfDayPredicate(data)
    elif kind == 'HAS_ATTACKED':
        return HasAttackedPredicate(data)
    elif kind == 'HAS_DEPLOYED':
        # note: from the server's point of view, has_attacked and has_deployed are the same thing
        # (on the client, has_attacked true and has_deployed false only occurs during the network
        # round-trip between asking for and receiving confirmation of the attack)
        return HasAttackedPredicate(data)
    elif kind == 'BASE_SIZE':
        return BaseSizePredicate(data)
    elif kind == 'HOME_REGION':
        return HomeRegionPredicate(data)
    elif kind == 'REGION_PROPERTY':
        return RegionPropertyPredicate(data)
    elif kind == 'GAMEBUCKS_BALANCE':
        return GamebucksBalancePredicate(data)
    elif kind == 'HAS_ITEM':
        return HasItemPredicate(data)
    elif kind == 'HAS_ITEM_SET':
        return HasItemSetPredicate(data)
    elif kind == 'NEW_BIRTHDAY':
        return NewBirthdayPredicate(data)
    elif kind == 'HAS_TITLE':
        return HasTitlePredicate(data)
    elif kind == 'USING_TITLE':
        return UsingTitlePredicate(data)
    elif kind == 'HAS_ALIAS':
        return HasAliasPredicate(data)
    elif kind == 'HAS_MENTOR':
        return HasMentorPredicate(data)
    elif kind == 'PLAYER_LEVEL':
        return PlayerLevelPredicate(data)
    elif kind == 'LADDER_PLAYER':
        return LadderPlayerPredicate(data)
    elif kind == 'IS_IN_ALLIANCE':
        return IsInAlliancePredicate(data)
    elif kind == 'VIEWING_BASE_DAMAGE':
        return ViewingBaseDamagePredicate(data)
    elif kind == 'VIEWING_BASE_OBJECT_DESTROYED':
        return ViewingBaseObjectDestroyedPredicate(data)
    elif kind == 'PLAYER_PREFERENCE':
        return PlayerPreferencePredicate(data)
    elif kind == 'HOME_BASE':
        return HomeBasePredicate(data)
    elif kind == 'ARMY_SIZE':
        return ArmySizePredicate(data)
    elif kind == 'TRUST_LEVEL':
        return TrustLevelPredicate(data)
    raise Exception('unknown predicate %s' % repr(data))

# evaluate a "cond" expression in the form of [[pred1,val1], [pred2,val2], ...]
def eval_cond(chain, session, player, qdata = None, override_time = None):
    for pred, val in chain:
        if read_predicate(pred).is_satisfied2(session, player, qdata, override_time = override_time):
            return val
    return None

def eval_cond_or_literal(chain, session, player, qdata = None, override_time = None):
    if type(chain) is not list:
        return chain
    return eval_cond(chain, session, player, qdata, override_time = override_time)
