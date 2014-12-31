#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# sample script for dumping info out of upcache (the userdb/playerdb cache)

# load some standard Python libraries
import sys, time, bisect, csv, copy, math

import SpinJSON # fast JSON library
import SpinConfig
import SpinS3 # S3 authentication library
import SpinUpcacheIO # library for reading upcache in a streaming fashion
import SpinUserDB

# load gamedata so we can reference it if necessary
# e.g. gamedata['units']['motion_cannon']['armor']
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

time_now = int(time.time())

def get_leveled_quantity(qty, level):
    if type(qty) == list:
        return qty[level-1]
    return qty

# return an iterator that streams the entire userdb one entry at a time
def stream_userdb():
    bucket, name = SpinConfig.upcache_s3_location(SpinConfig.game())
    return SpinUpcacheIO.S3Reader(SpinS3.S3(SpinConfig.aws_key_file()),
                                  bucket, name).iter_all()

driver = SpinUserDB.S3Driver(game_id = 'mf', key_file = SpinConfig.aws_key_file(),
                             userdb_bucket = 'spinpunch-prod-userdb',
                             playerdb_bucket = 'spinpunch-mfprod-playerdb')

# 0.55 -> deviation -1.13
# 0.50 -> deviation -0.77
# 0.40 -> deviation -0.10
# 0.37 -> deviation +0.37
# 0.25 -> deviation +1.51 sd 2.25
# 0.25 (NOpvp) -> losers 11.62%, mean deviation = +1.29, RMS deviation = 2.052963
# 0.25 (YESpvp) -> losers 9.91%, mean deviation = +1.51, RMS deviation = 2.252234
# 0.20 (NOpvp) ->  losers 3.61%, mean deviation = +2.06, RMS deviation = 2.608003
# 0.20 (YESpvp) -> losers 2.89%, mean deviation = +2.28, RMS deviation = 2.827710
# 0.20 (YESpvp,YESharvest) -> losers 2.37%, mean deviation = +2.46, RMS deviation = 3.008991

#XP_SCALE=0.200000, N=21850, losers 0.86%, mean deviation = +2.64, RMS deviation = 2.984100

XP_SCALE = 0.18 # LOWER this to RAISE the deviation

new_player_xp = copy.deepcopy(gamedata['player_xp'])
new_player_xp['harvest'] = 0.002
new_player_xp['collect_deposit'] = 0.002
new_player_xp['loot'] = 0.002
new_player_xp['research'] = 0
new_player_xp['buildings'][gamedata['townhall']] = 0.010
new_player_xp['buildings']['level_1'] = 0.03
new_player_xp['quest_reward_resources'] = 0.002

#new_player_xp['level_xp'] = [int(x*XP_SCALE) for x in new_player_xp['level_xp']]
# principles:
# - make it only take 1XP to get to level 1, so starting conditions work
# - make level 2 around 1340XP so that you get promoted to level 2 around end of tutorial (CC L2)
# - short linear segment between level 2 and level 7 to "catch up" to old exponential curve
# - exponential growth starts at level 8
#new_player_xp['level_xp'] = [0,1,1340,1440,1550,1660,1780,1900] + 42*[0]
#for i in xrange(8,50):
#    new_player_xp['level_xp'][i] = int(new_player_xp['level_xp'][7]*math.pow(1.34, i-7))

# under new XP rules, end of tutorial lands you at 1,318 to 1,432 XP
# under old XP rules, it was about 3,600 XP from the tutorial

#new_player_xp['level_xp'] = [0,1] + 48*[0]
#for i in xrange(2,50):
#    new_player_xp['level_xp'][i] = int(XP_SCALE*1340*math.pow(1.34, i-1))

# Ian's new table (see 121130_newXP_calibration.xlsx)
new_player_xp['level_xp'] = [0, 1, 323, 433, 580, 777, 1042, 1396, 1871, 2507, 3359, 4502, 6032, 8084, 10832, 14515, 18579, 23781, 30440, 38963, 49873, 63838, 81712, 104592, 133877, 171363, 219344, 280761, 359374, 459999, 588798, 753662, 964687, 1234800, 1580544, 2023096, 2589563, 3314640, 5303424, 8485479, 25456436]

sys.stderr.write('LEVEL_XP\n%s\n'% repr(new_player_xp['level_xp']))

# YES harvest/outcrop XP
# YES loot XP
# NO research XP
# YES buildings XP
# YES quest XP (resource-based)

def compute_new_xp(player):
    xp = {'starting_conditions':0} # XXX new starting condition = 0 gamedata['starting_conditions']['xp']}

    xp['loot'] = int(new_player_xp['loot'] * player['history'].get('resources_looted',0))

    DEPOSIT_FACTOR = 0.07 # accounts for iron deposits (not recorded in player history) - based on average amount
    xp['harvesting'] = int(new_player_xp['harvest'] * (1.0+DEPOSIT_FACTOR) * player['history'].get('resources_harvested',0))

    xp['research'] = 0
    for name, level in player['tech'].iteritems():
        for lev in xrange(1,level+1):
            if name in gamedata['starting_conditions']['tech'] and lev <= gamedata['starting_conditions']['tech'][name]:
                continue
            cost = get_leveled_quantity(gamedata['tech'][name]['cost_water'], lev) + get_leveled_quantity(gamedata['tech'][name]['cost_iron'], lev)
            xp['research'] += int(new_player_xp['research'] * cost)

    xp['buildings'] = 0
    for obj in player['my_base']:
        if obj['spec'] in gamedata['buildings']:
            if obj['spec'] in new_player_xp['buildings']:
                spec = gamedata['buildings'][obj['spec']]
                start_lev = 1
                for item in gamedata['starting_conditions']['buildings']:
                    if item['spec'] == obj['spec']:
                        start_lev = max(start_lev, item.get('level',1)+1)
                        break
                for lev in xrange(start_lev,obj.get('level',1)+1):
                    coeff = new_player_xp['buildings'][obj['spec'] if lev != 1 else 'level_1']
                    cost = get_leveled_quantity(spec['build_cost_water'], lev) + get_leveled_quantity(spec['build_cost_iron'], lev)
                    xp['buildings'] += int(coeff * cost)

    xp['quests'] = 0
    for name, data in player['completed_quests'].iteritems():
        if name not in gamedata['quests']: continue
        quest = gamedata['quests'][name]
        xp['quests'] += int(new_player_xp['quest_reward_resources'] * (quest.get('reward_iron',0)+quest.get('reward_water',0)))

    sys.stderr.write(repr(xp)+'\n')
    return xp

# list of new XP totals for players at CC level 5+
ballers = {'5+':[]}

# main program
if __name__ == '__main__':

    # list of fields you want to output to CSV. You have to specify this in advance.
    CSV_FIELDS = ['user_id', 'cc_level', 'money_spent', 'old_xp', 'old_level',
                  'new_xp_buildings', 'new_xp_quests', 'new_xp_loot', 'new_xp_harvesting', 'new_xp_total',
                  'new_level']

    # initialize CSV writer object
    writer = csv.DictWriter(sys.stdout, CSV_FIELDS, dialect='excel')

    # write the header row
    writer.writerow(dict((fn,fn) for fn in CSV_FIELDS))

    # fetch upcache and prepare to stream it
    userdb = stream_userdb()

    # some parameters to control the iteration

    IGNORE_TIER_4 = False # True to ignore Tier 4 users
    IGNORE_NONSPENDERS = False
    IGNORE_CHURNED = True
    MIN_CC_LEVEL = 2
    MIN_OLD_LEVEL = 7

    # ignore accounts created before this date, -1 to disable
    ACCOUNT_CREATION_MIN = -1 # calendar.timegm((2012,6,1,0,0,0))

    N = 0
    sum_delta = 0.0
    sum_delta2 = 0.0
    losers = 0

    try:
        for user in userdb:

            if 'account_creation_time' not in user: continue
            creat = user['account_creation_time']

            if creat < 1: continue # also ignore account_creation_time values that don't look reasonable

            # check the account creation time against ACCOUNT_CREATION_MIN
            if (ACCOUNT_CREATION_MIN > 0) and (creat < ACCOUNT_CREATION_MIN):
                continue # ignore this user, because it was created before the cutoff date

            # let's say we want to ignore users from Tier 4
            if IGNORE_TIER_4 and user.get('country_tier', 'unknown') == '4':
                # it's a Tier 4 user, ignore and move on to the next user
                continue

            if IGNORE_NONSPENDERS and user.get('money_spent',0) <= 0:
                continue

            if IGNORE_CHURNED and (('last_login_time' not in user) or (time_now - user['last_login_time'] >= 7*24*60*60)):
                continue

            cc_level = user.get(gamedata['townhall']+'_level',1)
            if cc_level < MIN_CC_LEVEL:
                continue

            if user.get('player_level',1) < MIN_OLD_LEVEL:
                continue

            csv_obj = {}

            csv_obj['user_id'] = user['user_id']

            csv_obj['old_level'] = user.get('player_level',1)
            csv_obj['cc_level'] = cc_level
            csv_obj['money_spent'] = user.get('money_spent', 0)

            player = SpinJSON.loads(driver.sync_download_player(user['user_id']))

            csv_obj['old_xp'] = player['resources'].get('xp',0)

            new_xp = compute_new_xp(player)
            csv_obj['new_xp_total'] = sum(new_xp.itervalues(), 0)
            for FIELD in ('buildings', 'quests', 'loot', 'harvesting'):
                csv_obj['new_xp_'+FIELD] = new_xp.get(FIELD,0)

            csv_obj['new_level'] = bisect.bisect(new_player_xp['level_xp'], csv_obj['new_xp_total']) - 1

            writer.writerow(csv_obj)

            if cc_level >= 2:
                if str(cc_level) not in ballers: ballers[str(cc_level)] = []
                ballers[str(cc_level)].append(csv_obj['new_xp_total'])
                if cc_level >= 5:
                    ballers['5+'].append(csv_obj['new_xp_total'])

            delta = csv_obj['new_level'] - csv_obj['old_level']
            N += 1
            if delta < 0: losers += 1
            sum_delta += delta
            sum_delta2 += delta*delta

    finally:
        if N > 0:
            sys.stderr.write('XP_SCALE=%f, N=%d, losers %.2f%%, mean deviation = %+.2f, RMS deviation = %f\n\n%s\n' % (XP_SCALE, N, 100.0*(losers/float(N)),sum_delta/float(N), math.sqrt(sum_delta2/float(N)), repr(new_player_xp['level_xp'])))
        for lev in sorted(ballers.keys()):
            tbl = ballers[lev]
            if len(tbl) >= 4:
                tbl.sort()
                sys.stderr.write('\nBALLERS CC L%s (N=%d): 0th %d - 25th %d - 50th %d - 75th %d - 100th %d\n' %
                                 (lev, len(tbl), tbl[0], tbl[int(0.25*len(tbl))], tbl[int(0.5*len(tbl))], tbl[int(0.75*len(tbl))], tbl[-1]))
