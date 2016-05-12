#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import sys, getopt, random, copy, math
import ANSIColor

verbose = 0

# XXX check within-tier increments

BASE_POWER_EQUAL = 5
BASE_POWER_BETTER = 10
BASE_POWER_WORSE = 2
BASE_COST = 10
BASE_HP = 10
BASE_SPACE = 1

TIER_POWER_INC = 2.2
TIER_HP_INC = 2.2
TIER_COST_INC = 1.5

ARMY_SIZE = 24

UNIT_CATS = ['roc', 'pap', 'sci']
UNITS = {}
for tier in (1,2,3):
    for cat in UNIT_CATS:
        specname = 'tier%d_%s' % (tier, cat)
        UNITS[specname] = {'hp': int(BASE_HP*math.pow(TIER_HP_INC,tier-1)),
                           'cost': int(BASE_COST*math.pow(TIER_COST_INC,tier-1)),
                           'space': BASE_SPACE,
                           'defense': {cat: 1},
                           'offense': {'roc': int(math.pow(TIER_POWER_INC,tier-1) * (BASE_POWER_EQUAL if cat == 'roc' else (BASE_POWER_BETTER if cat == 'pap' else BASE_POWER_WORSE))),
                                       'pap': int(math.pow(TIER_POWER_INC,tier-1) * (BASE_POWER_EQUAL if cat == 'pap' else (BASE_POWER_BETTER if cat == 'sci' else BASE_POWER_WORSE))),
                                       'sci': int(math.pow(TIER_POWER_INC,tier-1) * (BASE_POWER_EQUAL if cat == 'sci' else (BASE_POWER_BETTER if cat == 'roc' else BASE_POWER_WORSE)))
                                       }
                           }

def make_army(tier, portion, fullness = 1):
    army = []
    qty = dict((cat, int(ARMY_SIZE//BASE_SPACE * portion[cat] * fullness)) for cat in UNIT_CATS)
    for cat in UNIT_CATS:
        for i in range(qty[cat]):
            specname = 'tier%d_%s' % (tier, cat)
            assert specname in UNITS
            army.append({'spec': specname, 'hp': UNITS[specname]['hp'], 'max_hp': UNITS[specname]['hp']})
    return army

def army_cost(army):
    cost = 0
    for unit in army:
        spec = UNITS[unit['spec']]
        hp_ratio = unit['hp']/unit['max_hp']
        cost += hp_ratio * spec['cost']
    return cost

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

    # pick side to shoot first (gives ~30% advantage!)
    first_shooter = randgen.choice([0,1])

    randomness = 0.4 # 0.9
    random_streak = -1
    random_streak_side = -1

    while True:

        # pick side to shoot
        if random_streak > 0:
            i = random_streak_side
            random_streak -= 1
        else:
            i = first_shooter ^ (iter % 2) # alternate sides

            # to add randomness to battles, sometimes allow one side to shoot consecutively
            # a few times (just randomizing the shooter on each iteration doesn't disturb outcomes enough)
            if randomness > 0 and randgen.random() > randomness:
                random_streak = 5
                random_streak_side = i

        offense = sides[i]
        defense = sides[1-i]

        if len(defense) < 1:
            winner = i; break
        elif len(offense) < 1:
            winner = 1-i; break

        shooter = randgen.choice(offense)
        target = randgen.choice(defense)

        shooter_spec = UNITS[shooter['spec']]
        target_spec = UNITS[target['spec']]

        coeff = 1
        for tag in target_spec['defense']:
            if tag in shooter_spec['offense']:
                coeff *= target_spec['defense'][tag] * shooter_spec['offense'][tag]
        #coeff = int(coeff)
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

        total_damage[1-i] += dmg

        if target['hp'] <= 0:
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

def analyze(army_a, army_b):
    randgen = random.Random()

    SAMPLES = 100
    wins = 0
    damage_samples = []
    n_attacks_samples = []

    for i in xrange(SAMPLES):
        # make mutable copies
        a, b = [copy.copy(x) for x in army_a], [copy.copy(x) for x in army_b]
        a_damage = 0.0
        n_attacks = 0
        iter = 0
        while iter < 99:

            winner, total_damage = fight(a, b, randgen = randgen)
            a_damage += total_damage[0] # add damage
            n_attacks += 1 # add attack

            if winner == 0:
                if iter == 0:
                    wins += 1 # only count wins on first battle
                break
            else:
                # resurrect dead army, keeping damage count
                assert len(a) == 0
                a = [copy.copy(x) for x in army_a]
            iter += 1

        damage_samples.append(a_damage)
        n_attacks_samples.append(n_attacks)

    if wins == SAMPLES:
        win_odds = float('inf')
        log_win_odds = float('inf')
    elif wins == 0:
        win_odds = 0
        log_win_odds = -float('inf')
    else:
        win_odds = wins / float(SAMPLES - wins)
        log_win_odds = math.log(win_odds)

    win_variance = (wins/float(SAMPLES)) * ((SAMPLES-wins)/float(SAMPLES))

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

def test_efficiency(reason, bounds, a, b, eff_baseline):
    wins, log_win_odds, median_damage, avg_n_attacks, win_variance = analyze(a,b)
    efficiency = 1.0/median_damage

    # relative efficiency compared to baseline
    reff = efficiency/eff_baseline

    ui_result = '%-32s: %5.2f vs baseline (goal %.1f-%.1f), %.1f attacks, wins %d/%d SD %.2f' % (reason, reff, bounds[0], bounds[1], avg_n_attacks, wins[0], wins[1], math.sqrt(win_variance))
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

    # DPV = Damage Per Victory, Efficiency = 1/DPV

    eff_baseline = 1.0/(analyze(tier1_balanced, tier1_balanced)[2])
    print 'eff_baseline', eff_baseline

    # all else being equal, against the same opponent:

    test_efficiency('Slightly better-matched army, same tier', [1.3,2.0], tier1_roc, tier1_sci, eff_baseline)
    test_efficiency('Perfectly better-matched army, same tier', [4.0,8.0], tier1_roc_only, tier1_sci_only, eff_baseline)
    test_efficiency('Better-matched army, lower tier', [0.5,0.8], tier1_roc, tier2_sci, eff_baseline)
    test_efficiency('Next-lower-tier army', [0.25,0.5], tier1_balanced, tier2_balanced, eff_baseline)
    test_efficiency('Next-higher-tier army', [1.5,2.0], tier2_balanced, tier1_balanced, eff_baseline)
    test_efficiency('Two-higher-tier army', [2.0,4.0], tier3_balanced, tier1_balanced, eff_baseline)
    test_efficiency('Bigger army, same tier', [1.3,2.0], tier1_bigger, tier1_balanced, eff_baseline)
    test_efficiency('Bigger army, lower tier', [0.25,0.5], tier1_bigger, tier2_balanced, eff_baseline)
