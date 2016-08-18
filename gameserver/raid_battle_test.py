#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Simple self-contained simulator for unit vs unit balance in battles
# Intended to help decide how DPS/HP/COST should vary with tier and unit category

# NOTE: throughout this script, we measure "Damage Per Victory" (DPV) as the key efficiency stat.
# This is the damage that your attacking army suffers in order to kill a defending army.
# If multiple attacks are required, because the defending army is stronger than you,
# it accumulates the damage taken in all attacks.

# DPV is expressed in units of resource cost (e.g. a Tier 1 unit takes BASE_COST damage to raise to full health).
# "ROI" would be proportional to 1/DPV.

# In the simulation runs, we compare attacks against dissimilar armies with the "baseline" DPV that results from
# fighting a mirror copy of your own army.

import sys, getopt, random, copy
from math import pow, log, sqrt
import ANSIColor

verbose = 3 # set to 1, 2, or 3 to print more detailed output

# "power" combines the effect of DPS * damage_vs for rock/paper/scissors categories
BASE_POWER_BETTER = 8 # vs. category you are strong against
BASE_POWER_EQUAL = 7 # vs. same category
BASE_POWER_WORSE = 6 # vs. category you are weak against

# starting cost, HP, and space of a Tier 1 unit
BASE_COST = 10
BASE_HP = 30
BASE_SPACE = 1

# multiplicative increase in DPS, HP, and cost per tier
TIER_POWER_INC = 1.55
TIER_HP_INC = 1.55
TIER_COST_INC = 1.5 # = per-tier economy growth rate (dictated by the master balance spreadsheet - do not change this!)

# simulate this size army
ARMY_SIZE = 6

# generate unit stats
UNIT_CATS = ['roc', 'pap', 'sci']
UNITS = {}

for tier in (1,2,3):
    for cat in UNIT_CATS:
        specname = 'tier%d_%s' % (tier, cat)
        UNITS[specname] = {'hp': int(BASE_HP*pow(TIER_HP_INC,tier-1)),
                           'cost': int(BASE_COST*pow(TIER_COST_INC,tier-1)),
                           'space': BASE_SPACE,
                           'defense': {cat: 1},
                           'offense': {'roc': int(pow(TIER_POWER_INC,tier-1) * (BASE_POWER_EQUAL if cat == 'roc' else (BASE_POWER_BETTER if cat == 'pap' else BASE_POWER_WORSE))),
                                       'pap': int(pow(TIER_POWER_INC,tier-1) * (BASE_POWER_EQUAL if cat == 'pap' else (BASE_POWER_BETTER if cat == 'sci' else BASE_POWER_WORSE))),
                                       'sci': int(pow(TIER_POWER_INC,tier-1) * (BASE_POWER_EQUAL if cat == 'sci' else (BASE_POWER_BETTER if cat == 'roc' else BASE_POWER_WORSE)))
                                       }
                           }

# generate an army (list of units) of a given tier
# "portion" is a dictionary with the category composition to use (values should add up to 1)
def make_army(tier, portion, fullness = 1):
    army = []
    qty = dict((cat, int(ARMY_SIZE//BASE_SPACE * portion[cat] * fullness + 0.5)) for cat in UNIT_CATS)
    print qty
    for cat in UNIT_CATS:
        for i in range(qty[cat]):
            specname = 'tier%d_%s' % (tier, cat)
            assert specname in UNITS
            army.append({'spec': specname, 'hp': UNITS[specname]['hp'], 'max_hp': UNITS[specname]['hp']})
    return army

# calculate resource cost of an army, scaled by health
def army_cost(army):
    cost = 0
    for unit in army:
        spec = UNITS[unit['spec']]
        hp_ratio = unit['hp']/unit['max_hp']
        cost += hp_ratio * spec['cost']
    return cost

# simulate a single battle between two armies, until one of them is totally dead
def fight(a, b, randgen = None):
    if randgen is None:
        randgen = random.Random()

    if verbose >= 2:
        print 'COST', army_cost(a), a
        print 'vs'
        print 'COST', army_cost(b), b

    sides = [a,b]
    total_damage = [0,0]
    iter = 0
    winner = None

    while True:

        for i in (0,1):
            if len(sides[i]) < 1:
                # one of the armies is totally dead
                winner = 1-i; break
        if winner is not None: break

        # uniformly choose next shooter from all living units
        shooter_i = randgen.randint(0, len(sides[0]) + len(sides[1]) - 1)
        if shooter_i < len(sides[0]):
            i = 0
            defense = sides[1]
            shooter = sides[0][shooter_i]
        else:
            i = 1
            defense = sides[0]
            shooter = sides[1][shooter_i - len(sides[0])]
        # then choose target uniformly from all living units on the other side
        target = randgen.choice(defense)

        shooter_spec = UNITS[shooter['spec']]
        target_spec = UNITS[target['spec']]

        coeff = 1
        for tag in target_spec['defense']:
            if tag in shooter_spec['offense']:
                coeff *= target_spec['defense'][tag] * shooter_spec['offense'][tag]
        #coeff = int(coeff) # should we quantize damage values?
        assert coeff > 0

        old_hp = target['hp']
        #assert old_hp > 0
        target['hp'] = max(0, target['hp'] - coeff)

        # record damage to defense side
        if target['hp'] < old_hp:
            dmg = (old_hp - target['hp'])/(1.0*target['max_hp']) * target_spec['cost']
        else:
            dmg = 0

        #print i, shooter, 'shoots', target, 'coeff', coeff, 'old_hp', old_hp, 'new_hp', target['hp'], 'dmg', dmg

        # accumulate damage into the total for this side
        total_damage[1-i] += dmg

        if target['hp'] <= 0:
            # remove dead unit
            defense.remove(target)
            #print 'DEAD', 1-i, target, len(defense), 'left'

        iter += 1
        if iter >= 9999:
            raise Exception('runaway iteration')

    assert winner is not None

    if verbose >= 2:
        print 'END:'
        print sides[0]
        print sides[1]
        print 'DMG'
        print total_damage

    return winner, total_damage

# run many engagements between two armies.
# for each engagement, if army_a loses, refresh the units back to full health and fight again, until army_b is dead.
# (but keep count of the total damage for all battles in each engagement)
def analyze(army_a, army_b):
    randgen = random.Random()

    SAMPLES = 1000 # number of engagements to simulate
    wins = 0
    damage_samples = []
    n_attacks_samples = []

    for i in xrange(SAMPLES):
        # make mutable copies of the armies
        a, b = [copy.copy(x) for x in army_a], [copy.copy(x) for x in army_b]
        a_damage = 0.0
        n_attacks = 0
        iter = 0
        while iter < 99: # make up to 99 attacks until army_a wins

            winner, total_damage = fight(a, b, randgen = randgen)
            a_damage += total_damage[0] # add damage
            n_attacks += 1 # add attack

            if winner == 0:
                if iter == 0:
                    wins += 1 # only count wins on first attack
                break
            else:
                # resurrect the dead army_a, keeping damage counter
                assert len(a) == 0
                a = [copy.copy(x) for x in army_a]
            iter += 1

        damage_samples.append(a_damage)
        n_attacks_samples.append(n_attacks)

    # calculate odds of winning on first attack
    if wins == SAMPLES:
        win_odds = float('inf')
        log_win_odds = float('inf')
    elif wins == 0:
        win_odds = 0
        log_win_odds = -float('inf')
    else:
        win_odds = wins / float(SAMPLES - wins)
        log_win_odds = log(win_odds)

    win_variance = (wins/float(SAMPLES)) * ((SAMPLES-wins)/float(SAMPLES))

    # calculate median damage per victory
    damage_samples.sort()
    median_damage = (damage_samples[SAMPLES//2-1] + damage_samples[SAMPLES//2])/2.0
    #median_n_attacks = (n_attacks_samples[SAMPLES//2-1] + n_attacks_samples[SAMPLES//2])/2.0
    avg_n_attacks = (1.0*sum(n_attacks_samples))/SAMPLES

    if verbose >= 1:
        print 'COST', army_cost(army_a), army_a
        print 'vs'
        print 'COST', army_cost(army_b), army_b

        print 'wins', wins, '/', SAMPLES, 'ln(odds)', log_win_odds, 'median damage', median_damage, 'avg #attacks', avg_n_attacks
    return (wins,SAMPLES), log_win_odds, median_damage, avg_n_attacks, win_variance

# harness to run simulations on army "a" vs army "b" and compare damage-per-victory against the baseline
# print result in green if it is within "bounds", otherwise red.
def test_efficiency(reason, bounds, a, b, dpv_baseline):
    wins, log_win_odds, median_damage, avg_n_attacks, win_variance = analyze(a,b)

    # relative DPV compared to baseline
    reff = median_damage/dpv_baseline

    ui_result = '%-42s: %5.2f vs baseline (goal %.2f-%.2f), %.1f attacks, wins %d/%d SD %.2f' % (reason, reff, bounds[0], bounds[1], avg_n_attacks, wins[0], wins[1], sqrt(win_variance))
    if bounds[0] <= reff <= bounds[1]: # good
        ui_result = ANSIColor.green(ui_result)
    else:
        ui_result = ANSIColor.red(ui_result)

    print ui_result

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'v', ['verbose'])
    for key, val in opts:
        if key in ('-v','--verbose'): verbose += 1

    print 'UNITS'
    for specname in sorted(UNITS.keys()):
        print specname, UNITS[specname]

    # make some armies of various tiers and compositions
    print 'ARMIES'
    tier1_balanced = make_army(1, {'roc':0.34, 'pap':0.34, 'sci':0.34})
    tier1_bigger = make_army(1, {'roc':0.34, 'pap':0.34, 'sci':0.34}, fullness = 2.0)
    tier1_roc = make_army(1, {'roc':0.66, 'pap':0.166, 'sci':0.166})
    tier1_roc_only = make_army(1, {'roc':1, 'pap':0, 'sci':0})
    tier1_pap = make_army(1, {'roc':0.166, 'pap':0.66, 'sci':0.166})
    tier1_pap_only = make_army(1, {'roc':0, 'pap':1, 'sci':0})
    tier1_sci = make_army(1, {'roc':0.166, 'pap':0.166, 'sci':0.66})
    tier1_sci_only = make_army(1, {'roc':0, 'pap':0, 'sci':1})

    tier2_balanced = make_army(2, {'roc':0.34, 'pap':0.34, 'sci':0.34})
    tier2_sci = make_army(2, {'roc':0.166, 'pap':0.166, 'sci':0.66})

    tier3_balanced = make_army(3, {'roc':0.34, 'pap':0.34, 'sci':0.34})

    # DPV = Damage Per Victory

    dpv_baseline = analyze(tier1_balanced, tier1_balanced)[2]
    print 'dpv_baseline', dpv_baseline

    # TARGET DPV ranges that we want to control balance towards
    # all else being equal, against the same opponent:
    TARGET_DPV_INC = [2.26,2.9] # goal DPV increase per level below target (must be >= economy growth^2)
    TARGET_DPV_DEC = [1.0/2.3,0.8] # goal DPV decrease per level above target (must be >= 1/DPV_INC)
    BETTER_ARMY_DEC = [0.5,0.85] # target DPV decrease by having a perfectly better-matched army

    if 1:
        test_efficiency('vs. tier N+2 army', [pow(TARGET_DPV_INC[0],2), pow(TARGET_DPV_INC[1],2)],
                        tier1_balanced, tier3_balanced, dpv_baseline)
        test_efficiency('vs. tier N+1 army', TARGET_DPV_INC,
                        tier1_balanced, tier2_balanced, dpv_baseline)

        test_efficiency('Same army, same tier', [0.9,1.1], tier1_balanced, tier1_balanced, dpv_baseline)

        test_efficiency('vs. tier N-1 army', TARGET_DPV_DEC,
                        tier2_balanced, tier1_balanced, dpv_baseline)

        test_efficiency('vs. tier N-2 army', [pow(TARGET_DPV_DEC[0],2), pow(TARGET_DPV_DEC[1],2)],
                        tier3_balanced, tier1_balanced, dpv_baseline)

        test_efficiency('Slightly better-matched army, same tier', [pow(BETTER_ARMY_DEC[0],0.5), pow(BETTER_ARMY_DEC[1],0.5)],
                        tier1_roc, tier1_sci, dpv_baseline)

    if 1:
        test_efficiency('Perfectly better-matched army, same tier', BETTER_ARMY_DEC,
                        tier1_roc_only, tier1_sci_only, dpv_baseline)

    if 1:
        test_efficiency('Better-matched army, lower tier', [BETTER_ARMY_DEC[0]*TARGET_DPV_INC[0],
                                                            BETTER_ARMY_DEC[1]*TARGET_DPV_INC[1]],
                        tier1_roc, tier2_sci, dpv_baseline)

        test_efficiency('Bigger army, same tier', [0.4, 0.8],
                        tier1_bigger, tier1_balanced, dpv_baseline)
#        test_efficiency('Bigger army, lower tier', [0.5*TARGET_DPV_INC[0], 0.8*TARGET_DPV_INC[1]],
#                        tier1_bigger, tier2_balanced, dpv_baseline)
