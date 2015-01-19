#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# utility to perform regression of userdb variables against each other
# dependencies: SciPy and NumPy libraries, ols.py, logistic_regression.py

# get fast JSON library if available
try: import simplejson as json
except: import json

import time, calendar
import FastGzipFile
import SpinConfig
import numpy
import ols, logistic_regression
import scipy.stats

verbose = True
gamedata = json.load(open(SpinConfig.gamedata_filename()))

cerberus_farmers = set([10986, 1416, 4664, 16805, 10055, 4498, 30717, 9756, 17019, 51975, 14840, 12380, 10388, 14724, 52655, 15358, 12462, 31023, 61982, 31659, 24341, 8534, 51456, 41138, 13328, 17394, 59531, 39183, 25563, 37823, 33213, 19750, 13588, 44874, 25595, 8689, 42049, 57254, 14427, 51072])

if __name__ == "__main__":
    time_now = time.time()

    # read all user/player data from upcache
    print "reading userdb...",
    dbfile = FastGzipFile.Reader('logs/upcache.sjson.gz')

    # QUERY PARAMETERS

    # ignore accounts created before this date (March 21, 2012)
    RESTRICT_TIME = calendar.timegm((2012,5,23,0,0,0)) # or -1 to disable
    RESTRICT_COUNTRY = None # = 'us' etc. to only look at one country
    RESTRICT_FARMERS = False # only look at AI farmers
    RESTRICT_PAYING_BEFORE = -1 # calendar.timegm((2012,4,13,0,0,0)) # ignore accounts that paid something before this date (for testing T4 offerwall)
    IGNORE_T4 = False # ignore Tier 4 accounts
    WHALE_LINE = 7.0 # dollar receipt level that makes you a whale
    IGNORE_NONPAYERS = False # ignore non-paying accounts
    REQUIRE_TECH = None
#    REQUIRE_TECH = { 'excavator_droid_production': 1 } # ignore accounts that don't meet this tech requirement
    IGNORE_WHALES = False # ignore whale accounts
    CAP_WHALES = True # treat any spend beyond whale line as spend = whale line
    IGNORE_NONWHALES = False # ignore non-whale accounts
    IGNORE_ONETIME_VISITORS = False # ignore users who never came back after the first visit
    LOGISTIC = False # use logistic regression intead of ordinary linear least squares

    # DEPENDENT VARIABLE
    # uncomment only ONE of these
    # note: when regressing a binary variable (is_paying_user, retained_Xd, etc),
    # it is better to use logistic regression than ordinary linear regression

#    y_name = 'is_paying_user'; LOGISTIC = True
#    y_name = 'tech:motion_cannon_production'; LOGISTIC = True
#    y_name = 'tech:blaster_droid_production'; LOGISTIC = True
#    y_name = 'tech:excavator_droid_production'; LOGISTIC = True
#    y_name = 'quest:build_storage:completed'; LOGISTIC = True
#    y_name = gamedata['townhall']+'_level'
#    y_name = 'attacks_launched'
#    y_name = 'attacks_launched>1'; LOGISTIC = True
#    y_name = 'units_manufactured'
#    y_name = 'money_spent'
    y_name = 'money_spent_per_day'
#    y_name = 'spend_5d'
#    y_name = 'time_in_game'
#    y_name = 'is_whale'; LOGISTIC = True
#    y_name = 'retained_3d'; LOGISTIC = True
#    y_name = 'time_to_first_purchase'
#    y_name = 'visits_1d'
#    y_name = 'visits_last_24h'
#    y_name = 'visited_last_24h'; LOGISTIC = True
#    y_name = 'harvested_total'
#    y_name = 'days_since_last_login'

    # INDEPENDENT VARIABLES
    # uncomment the ones you want to incorporate into the regression
    # 'field': the userdb field that we will look at
    # 'xvars': list of independent variables that this userdb field creates
    # 'valuemap': list of values for those independent variables indexed by the userdb['field'] value

    VARIABLES = [
#        {'field': 'country_tier', 'xvars': ['country_tier'], 'valuemap': {'1':[4.0], '2':[3.0], '3':[2.0], '4': [1.0]} },
#        {'field': 'country', 'xvars': ['country_tier'], 'valuemap': {'1':[4.0], '2':[3.0], '3':[2.0], '4': [1.0]} },
#        {'field': 'T001_harvester_cap', 'xvars': ['high_cap'], 'valuemap': {'1':[1.0], '0':[0.0] } },
#        {'field': 'T009_chrome_audio', 'xvars': ['chrome_audio'], 'valuemap': {'chrome_audio_on': [1.0], 'chrome_audio_off': [0.0]} },
#        {'field': 'T010_flashy_loot', 'xvars': ['flashy_loot'], 'valuemap': {'flashy_loot_on':[1.0], 'flashy_loot_off': [0.0]} },
#        {'field': 'T012_flashy2', 'xvars': ['flashy_loot2'], 'valuemap': {'flashy2_on':[1.0], 'flashy2_off': [0.0]} },
#        {'field': 'T011_ai_bases', 'xvars': ['ai_many', 'ai_timeroff'], 'valuemap': {'ai_normal': [0.0,0.0],
#                                                                                      'ai_notimer': [0.0,1.0],
#                                                                                      'ai_many': [1.0, 0.0],
#                                                                                      'ai_many_notimer': [1.0, 1.0]} },
#        {'field': 'T017_sexy_motion_cannon', 'xvars': ['sexy'], 'valuemap': {'ugly_motion_cannon':[0.0],'sexy_motion_cannon':[1.0]}},
#         {'field': 'T015_offer_wall_t4', 'xvars': ['offerwall'], 'valuemap': {'t4_offerwall_off':[0.0],'t4_offerwall_on':[1.0]} },
#         {'field': 'T018_protection_time', 'xvars': ['prot_time'], 'valuemap': {'normal_prot_time':[0.0],'long_prot_time':[1.0]} },
#         {'field': 'T019_sirenum', 'xvars': ['sirenum'], 'valuemap': {'no_sirenum':[0.0],'yes_sirenum':[1.0]} },
#         {'field': 'T020_chat', 'xvars': ['chat'], 'valuemap': {'chat_off':[0.0],'chat_on':[1.0]} },
#         {'field': 'T022_excavator_stats', 'xvars': ['excavator_strong'], 'valuemap': {'weak_excavator':[0.0],'strong_excavator':[1.0]} },
#         {'field': 'T023_turret_stats', 'xvars': ['weak_turrets'], 'valuemap': {'strong_turrets':[0.0],'weak_turrets':[1.0]} },

#        {'field': 'T024A_webaudio_chrome', 'xvars': ['new_audio_chrome'], 'valuemap': {'new_audio': [1.0], 'old_audio': [0.0]} },
#        {'field': 'T024B_flashaudio_firefox', 'xvars': ['new_audio_firefox'], 'valuemap': {'new_audio': [1.0], 'old_audio': [0.0]} },
#        {'field': 'T024C_flashaudio_explorer', 'xvars': ['new_audio_explorer'], 'valuemap': {'new_audio': [1.0], 'old_audio': [0.0]} },

#        {'field': 'T025_protection_loot', 'xvars': ['new_loot_system'], 'valuemap': {'old_system':[0.0],'new_system':[1.0]} },
#        {'field': 'T026_excavator2', 'xvars': ['strong_excavator2'], 'valuemap': {'weak_excavator2':[0.0],'strong_excavator2':[1.0]} },
#        {'field': 'T027_unit_time', 'xvars': ['short_build_time'], 'valuemap': {'short_unit_time':[1.0],'long_unit_time':[0.0]} },
#        {'field': 'T034_new_ai_bases', 'xvars': ['new_ai_bases'], 'valuemap': {'old_ai_bases':[0.0],'new_ai_bases':[1.0]} },
#        {'field': 'T036_bldg_repair_price', 'xvars': ['new_high_price'], 'valuemap': {'old_prices':[0.0],'new_prices':[1.0]} },
#        {'field': 'T043_new_tutorial', 'xvars': ['new_tutorial'], 'valuemap': {'new_tutorial':[1.0],'old_tutorial':[0.0]} },
        {'field': 'canvas_height', 'xvars': ['canvas_height_550'], 'valuemap': 'canvas_height_550' },
#        {'field': 'canvas_height', 'xvars': ['canvas_height'], 'valuemap': 'continuous', 'ignore_missing': True },
#        {'field': 'likes_backyard_monsters', 'xvars':['likes_backyard'], 'valuemap': {0:[0.0],1:[1.0]}},
#        {'field': 'likes_battle_pirates', 'xvars':['likes_battlepir'], 'valuemap': {0:[0.0],1:[1.0]}},
#        {'field': 'likes_edgeworld', 'xvars':['likes_edgeworld'], 'valuemap': {0:[0.0],1:[1.0]}},
#        {'field': 'likes_wasteland_empires', 'xvars':['likes_wasteemp'], 'valuemap': {0:[0.0],1:[1.0]}},
#        {'field': 'likes_war_commander', 'xvars':['likes_warcommander'], 'valuemap': {0:[0.0],1:[1.0]}},

#        {'field': 'likes_EW_WC', 'xvars':['likes_EW_WC'], 'valuemap': {0:[0.0],1:[1.0]}},

#        {'field': 'friends_in_game', 'xvars':['friends_in_game'], 'valuemap': 'continuous'},
#        {'field': 'attacks_launched', 'xvars':['pvp_ratio'], 'valuemap': 'continuous'},
#        {'field': 'acquired_on_weekend', 'xvars':['acquired_on_weekend'], 'valuemap': {0:[0.0],1:[1.0]}},
#        {'field': 'account_creation_hour', 'xvars':['acq_3am-8am','acq_9am-2pm', 'acq_9pm-2am'],
#         'valuemap': {3:[1,0,0],4:[1,0,0],5:[1,0,0],6:[1,0,0],7:[1,0,0],8:[1,0,0],
#                      9:[0,1,0],10:[0,1,0],11:[0,1,0],12:[0,1,0],13:[0,1,0],14:[0,1,0],
#                      15:[0,0,0],16:[0,0,0],17:[0,0,0],18:[0,0,0],19:[0,0,0],20:[0,0,0],
#                      21:[0,0,1],22:[0,0,1],23:[0,0,1],0:[0,0,1],1:[0,0,1],2:[0,0,1],
#                      } },
#        {'field': 'timezone', 'xvars':['tz_Eastern', 'tz_Central', 'tz_Mountain'], 'valuemap': { -10:[0,0,0], -9:[0,0,0], -8:[0,0,0], -7:[0,0,1], -6:[0,1,0], -5:[1,0,0], -4:[1,0,0], -3:[1,0,0], -2:[1,0,0], 2:[0,0,0], 1:[1,0,0], 0:[1,0,0], 3:[0,0,0], 5:[0,0,0], 4:[0,0,0], 7:[0,0,0],8:[0,0,0] } }
#        {'field': 'browser_os', 'xvars':['runs_windows'], 'valuemap': {'Mac':[0.0],'Windows':[1.0],'Linux':[0.0],'iOS':[0.0],'an unknown OS':[0.0]}},

        ]

    # concatenate list of xvars produced by each userdb field
    x_names = sum([t['xvars'] for t in VARIABLES], [])
    xs = []
    ys = []

    # scan userdb
    for line in dbfile.xreadlines():
        user = json.loads(line)

        # throw out very old entries with missing pieces of critical data
        if 'account_creation_time' not in user: continue
        if 'last_login_time' not in user: continue

        # skip userdb entries that do not match the query
        if user['account_creation_time'] < RESTRICT_TIME: continue
        if IGNORE_T4 and user.get('country_tier', '4') in ['4']:
            continue
        if IGNORE_WHALES and user.get('money_spent',0) >= WHALE_LINE: continue
        if IGNORE_NONWHALES and user.get('money_spent',0) < WHALE_LINE: continue
        if IGNORE_NONPAYERS and user.get('money_spent',0) < 0.01: continue
        if RESTRICT_COUNTRY and user.get('country','') != RESTRICT_COUNTRY: continue
        if IGNORE_ONETIME_VISITORS and (user['last_login_time'] == user['account_creation_time']):
            continue

        if RESTRICT_PAYING_BEFORE > 0 and user.get('time_of_first_purchase',time_now) < RESTRICT_PAYING_BEFORE:
            continue

        if REQUIRE_TECH and len(REQUIRE_TECH) > 0:
            if 'tech' not in user: continue
            fail = False
            for name, level in REQUIRE_TECH.iteritems():
                if user['tech'].get(name,0) < level:
                    fail = True
                    break
            if fail:
                continue

        if RESTRICT_FARMERS and (user['user_id'] not in cerberus_farmers):
            continue

#        if user.get('T043_new_tutorial',None) != 'new_tutorial':
#            continue

        #if 'timezone' not in user: continue

        # skip userdb entries that are missing any of the independent variables
        missing = False
        for t in VARIABLES:
            if t['field'] not in user:
                missing = True
                break
        if missing: continue


        # pull out the value of the dependent variable
        if y_name.startswith('retained_'):
            days = int(y_name.split('_')[1][:-1])
            if (time_now - user['account_creation_time']) < days*24*60*60:
                # account not old enough to determine retained_Xd
                continue
            if user['last_login_time'] == user['account_creation_time']:
                # user never came back after first visit
                retained = 0.0
            else:
                retained = 1.0 if (user['last_login_time'] - user['account_creation_time']) >= days*24*60*60 else 0.0
            yval = retained
        elif y_name.startswith('spend_') or y_name.startswith('visits_'):
            if y_name.startswith('visits_last_'):
                if 'sessions' not in user: continue
                hours = int(y_name.split('_')[2][:-1])
                window_close = time_now
                window_open = time_now - hours*60*60
                yval = 0
                for t, tout in user['sessions']:
                    if t >= window_open and t < window_close:
                        yval += 1
            elif y_name.startswith('visits_'):
                days = int(y_name.split('_')[1][:-1])
                if (time_now - user['account_creation_time']) < days*24*60*60:
                    continue
                yval = user.get(y_name, 0.0)
            else:
                yval = user.get(y_name, 0.0)
        elif y_name.startswith('visited_last_'):
            if 'sessions' not in user: continue
            hours = int(y_name.split('_')[2][:-1])
            window_close = time_now
            window_open = time_now - hours*60*60
            yval = 0
            for t, tout in user['sessions']:
                if t >= window_open and t < window_close:
                    yval = 1
                    break
        elif y_name == 'money_spent':
            yval = user.get('money_spent', 0.0)
            # cap spending at whale line
            if CAP_WHALES:
                if yval > WHALE_LINE: yval = WHALE_LINE
        elif y_name == 'money_spent_per_day':
            yval = user.get('money_spent', 0.0) / (float(time_now - user['account_creation_time'])/(24*60*60))
        elif y_name == 'time_to_first_purchase':
            if 'time_of_first_purchase' not in user: continue
            yval = user['time_of_first_purchase'] - user['account_creation_time']
        elif y_name == 'is_paying_user':
            yval = 1 if user.get('money_spent', 0) > 0 else 0
        elif y_name == 'is_whale':
            yval = 1.0 if user.get('money_spent',0) >= WHALE_LINE else 0.0
        elif y_name == 'harvested_total':
            yval = user.get('harvested_water_total',0) + user.get('harvested_iron_total',0)
#            if yval > 0:
#                yval = math.log(float(yval))
        elif y_name.startswith('tech:'):
            tech_name = y_name.split(':')[1]
            if 'tech' not in user:
                continue
            if user['tech'].get(tech_name, 0) > 0:
                yval = 1
            else:
                yval = 0
        elif y_name.startswith('quest:'):
            yval = user.get(y_name,0)
        elif y_name == 'days_since_last_login':
            if 'last_login_time' in user:
                yval = float(time_now - user['last_login_time'])/(24*60*60)
            else:
                continue
        elif y_name == 'time_in_game':
            if 'time_in_game' in user:
                yval = float(user['time_in_game'])
            else:
                continue
        elif y_name == 'attacks_launched>1':
            if 'attacks_launched' in user:
                yval = 1 if user['attacks_launched'] > 1 else 0
            else:
                continue
        elif y_name in ('attacks_launched' 'units_manufactured', gamedata['townhall']+'_level'):
            if y_name in user:
                yval = float(user[y_name])
            else:
                continue
        else:
            raise Exception('unhandled y %s' % y_name)

        # pull out the values of the independent variables
        xvals = []
        MISSING = False
        for t in VARIABLES:
            if t['valuemap'] == 'continuous':
                if t.get('ignore_missing', False) and t['field'] not in user:
                    MISSING = True
                    break
                if t['xvars'][0] == 'pvp_ratio':
                    if user['attacks_launched'] == 0:
                        val = 0
                    else:
                        val = float(user['attacks_launched_vs_human']) / user['attacks_launched']
                else:
                    val = float(user[t['field']])
                xvals += [val]
            elif t['valuemap'] == 'canvas_height_550':
                if 'canvas_height' not in user:
                    MISSING = True
                    break
                xvals += [1 if user['canvas_height'] >= 550 else 0]
            else:
                if user[t['field']] not in t['valuemap']:
                    raise Exception('unhandled value %s' % user[t['field']])
                xvals += map(float, t['valuemap'][user[t['field']]])

        if MISSING:
            continue

        ys.append(yval)
        xs.append(xvals)

    print len(ys), len(xs), 'samples'
    if len(ys) < 8:
        raise 'not enough samples, need at least 8 to perform regression'

    # do the regression
    if LOGISTIC:
        print 'logistic regression of', y_name, 'on', x_names
        print sum([1 for y in ys if y != 0]), 'true of', len(ys)

        ys_yes = []; ys_no = []
        for i in range(len(ys)):
            if xs[i][0]:
                ys_yes.append(ys[i])
            else:
                ys_no.append(ys[i])

        survivors_no = sum([1 for y in ys_no if y != 0])
        survivors_yes = sum([1 for y in ys_yes if y != 0])
        if len(ys_no) != 0:
            print x_names[0], 'false:', survivors_no, 'of', len(ys_no), '(%.1f%%)' % (100*float(survivors_no)/len(ys_no),)
        if len(ys_yes) != 0:
            print x_names[0], 'true:', survivors_yes, 'of', len(ys_yes), '(%.1f%%)' % (100*float(survivors_yes)/len(ys_yes),)


        # to check for significance, perform the regression twice, once without the variables and once with,
        # and then compute the P value by looking at the difference of -2*log(likelihood) on a chi squared CDF

        print 'ONLY CONSTANT'
        beta, J_bar, ll = logistic_regression.logistic_regression(numpy.transpose(numpy.array([[]]*len(ys))), numpy.array(ys), verbose = False)
        covmat = numpy.linalg.inv(J_bar)
        stderr = numpy.sqrt(numpy.diag(covmat))
        print 'odds =', numpy.exp(beta)
        print 'beta =', beta
        print 'stderr =', stderr
        print '-2LL =', -2.0*ll
        old_2LL = -2.0*ll

        print 'WITH VARIABLES'
        x_names = ['constant']+x_names
        beta, J_bar, ll = logistic_regression.logistic_regression(numpy.transpose(numpy.array(xs)), numpy.array(ys), verbose = False)
        covmat = numpy.linalg.inv(J_bar)
        stderr = numpy.sqrt(numpy.diag(covmat))
        print x_names
        print 'odds =', numpy.exp(beta)
        print 'beta =', beta
        print 'stderr =', stderr
        print 'beta/stderr =', beta/stderr
        print 'p =', (1-scipy.stats.t.cdf(abs(beta/stderr), len(ys)-(len(x_names)+1))) * 2
        print '-2LL =', -2.0*ll
        new_2LL = -2.0*ll

        chisq = old_2LL - new_2LL
        print 'chi squared =', chisq
        # number of degrees of freedom = number of independent variables added (not counting the constant)
        p = 1.0 - scipy.stats.chi2.cdf(chisq, len(x_names))
        print 'p = %0.3f' % p, '(SIGNIFICANT)' if p < 0.05 else '(not significant)'
#        cdf = [[10.83,0.001],[6.64,0.01],[3.84,0.05],[2.71,0.10],[1.64,0.20],[-9999,'not significant']]
#        for x2, p in cdf:
#            if chisq >= x2:
#                print 'SIGNIFICANCE: p <', p
#                break

        if 0:
            import mlpy
            svm = mlpy.LibSvm()
            midpt = int(len(ys)/2)
            svm.learn(numpy.array(xs[:midpt]), numpy.array([1 if y != 0 else -1 for y in ys[:midpt]]))
            pred = svm.pred(numpy.array(xs[midpt:]))
            true = ys[midpt:]
            total = len(pred)
            total_yes = sum([1 for x in true if x != 0])
            total_no = sum([1 for y in true if y == 0])
            correct = 0
            correct_yes = 0
            correct_no = 0
            for i in xrange(len(pred)):
                print 'HERE', pred[i], true[i]
                if pred[i] == true[i]:
                    correct += 1
                    if true[i]:
                        correct_yes += 1
                    else:
                        correct_no += 1

            print 'SVM', correct, 'of', total, '(%.2f%%)' % (float(100.0*correct)/total)
            print 'YES', correct_yes,'of',total_yes
            print 'NO', correct_no,'of',total_no


    else:
        # ordinary linear least-squares regression
        o = ols.ols(numpy.array(ys), numpy.array(xs), y_varnm = y_name, x_varnm = x_names)
        o.summary()
