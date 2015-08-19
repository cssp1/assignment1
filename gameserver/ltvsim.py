#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Monte Carlo player LTV simulation tool

import sys, time, math, random, bisect, getopt, traceback
import SpinJSON, SpinConfig, SpinUpcacheIO, SpinParallel, SpinS3

def gammln(xx):
    cof = [76.18009173,-86.50532033,24.01409822,
           -1.231739516,0.120858003e-2,-0.536382e-5]
    x = xx-1
    tmp=x+5.5
    tmp -= (x+0.5)*math.log(tmp)
    ser=1
    for j in xrange(len(cof)):
        x += 1
        ser += cof[j]/x
    return -tmp+math.log(2.50662827465*ser)

def poidev(xm):
    if xm < 12:
        g = math.exp(-xm)
        em = 0
        t = random.random()
        while t > g:
            em += 1
            t *= random.random()
        return em
    else:
        sq = math.sqrt(2*xm)
        alxm = math.log(xm)
        g = xm*alxm - gammln(xm+1)

        first = True
        while first or random.random()>t:
            y = math.tan(math.pi*random.random())
            em = sq*y+xm
            while em < 0:
                y = math.tan(math.pi*random.random())
                em = sq*y+xm
            em = int(em)
            t=0.9*(1.0+y*y)*math.exp(em*alxm-gammln(em+1)-g)
            first = False

        return int(em)

#for i in xrange(50):
#    print >> sys.stderr, poidev(100)

def birthday_to_birth_time(birthday):
    m, d, y = map(int, birthday.split('/'))
    return SpinConfig.cal_to_unix((y,m,d))

def pretty_money(f):
    return '$%0.2f' % f

time_now = int(time.time())
EVAL_DAYS = [1, 2, 5, 7, 14, 30, 60, 90, 120, 180]
AXES = [#{'name':'country_tier','values':['1','2']},
    {'name':'country', 'values':['us']}, # ,'gb','au']},
    {'name':'age_group','values':SpinConfig.AGE_GROUPS.values() + ['MISSING'],
        'mandatory': lambda(player): ('birthday' in player and 'account_creation_time' in player),
         'readfunc': lambda(player): SpinConfig.AGE_GROUPS.get(SpinConfig.years_old_to_age_group((player['account_creation_time'] - birthday_to_birth_time(player['birthday']))/(365*24*60*60)),'MISSING')}
        ]

def get_key(axes, player):
    k = []
    for axis in axes:
        if 'mandatory' in axis:
            if not axis['mandatory'](player): return None
        else:
            if axis['name'] not in player: return None
        if 'readfunc' in axis:
            try:
                val = axis['readfunc'](player)
            except:
                sys.stderr.write('readfunc error '+traceback.format_exc())
                return None
        else:
            val = player[axis['name']]
        if type(val) is unicode: val = str(val)
        if type(val) is int and len(axis['values']) == 1 and type(axis['values'][0]) is list:
            # range comparison
            r = axis['values'][0]
            if r[0] >= 0 and val < r[0]: return None
            if r[1] >= 0 and val > r[1]: return None
            # reset val to represent a match
            val = '%d-%d' % (r[0], r[1])
        elif len(axis['values']) == 1 and (axis['values'][0] == 'ALL'):
            val = 'ALL' # reset val
        else:
            if val not in axis['values']: return None
        k.append(':'.join([axis['name'],str(val)]))
    return '|'.join(k)

def parse_axes(s):
    return [{'name':ax.split(':')[0], 'values':[str(ax.split(':')[1])]} for ax in s.split('|')]

# return a new "blank" model entry suitable for starting summations
def init_model_entry():
    return {'total_receipts': 0.0,
            'by_day': dict([(str(day), {'count': 0, 'paycount':0, 'logsum': 0.0, 'linsum': 0.0, 'spends': []}) for day in EVAL_DAYS]) }

# iterate through a portion of upcache, accumulating statistics for each bucket
def build_model_map(reader, segnum, axes, spend_categories):
    data = {}
    CATEGORIES = [cat+'_at_time' for cat in spend_categories] if spend_categories else ['money_spent_at_time']

    for player in reader.iter_segment(segnum):
        if ('account_creation_time' not in player): continue

        k = get_key(axes, player)
        if k is None: continue

        if k not in data:
            data[k] = init_model_entry()

        for day in EVAL_DAYS:
            if player['account_creation_time'] > (time_now - day*24*60*60):
                continue # account is not old enough to have valid data

            d = data[k]['by_day'][str(day)]

            d['count'] += 1

            if 'money_spent_at_time' not in player: continue

            mysum = 0.0

            for cat in CATEGORIES:
                if cat not in player: continue
                for sage, amount in player[cat].iteritems():
                    age = int(sage)
                    if age >= day*24*60*60: continue # spend is in the future
                    if 'gamebucks' in cat: amount *= 0.01
                    mysum += amount

            if mysum <= 0: continue
            d['paycount'] += 1
            d['linsum'] += mysum
            d['spends'].append(mysum)
            d['logsum'] += math.log(mysum)
        data[k]['total_receipts'] += player.get('money_spent',0)

    return data

def upcache_reader(upcache_path, info = None):
    if upcache_path.startswith('s3:'):
        reader = SpinUpcacheIO.S3Reader(SpinS3.S3(SpinConfig.aws_key_file()), SpinConfig.upcache_s3_location(SpinConfig.game())[0],
                                        upcache_path.split(':')[1],
                                        info = info)
        return reader
    else:
        return SpinUpcacheIO.LocalReader(upcache_path, info = info)

def build_model_slave(input):
    reader = upcache_reader(input['upcache_path'], info = input['upcache_info'])
    return build_model_map(reader, input['segnum'], input['query_axes'], input['spend_categories'])

def build_model_map_parallel(upcache_path, query_axes, parallel, spend_categories = None):
    reader = upcache_reader(upcache_path)
    if parallel <= 1:
        return [build_model_map(reader, segnum, query_axes, spend_categories) for segnum in xrange(reader.num_segments())]
    else:
        return SpinParallel.go([{'upcache_path':upcache_path, 'upcache_info': reader.info,
                                 'spend_categories':spend_categories,
                                 'segnum':segnum, 'query_axes':query_axes} for segnum in xrange(reader.num_segments())],
                               [sys.argv[0], '--build-model-slave'], on_error = 'break', nprocs = parallel)

# combine the output of build_model_map into one big model
def build_model_reduce(blocks, axes, modelname, verbose = True):
    model = {'name': modelname,
             'by_demo': {}}
    for data in blocks:
        for k, v in data.iteritems():
            if k not in model['by_demo']:
                model['by_demo'][k] = init_model_entry()
            model['by_demo'][k]['total_receipts'] += v['total_receipts']
            for day in EVAL_DAYS:
                for FIELD in model['by_demo'][k]['by_day'][str(day)].iterkeys():
                    model['by_demo'][k]['by_day'][str(day)][FIELD] += v['by_day'][str(day)][FIELD] # works on the spend list too!

    for k, entry in model['by_demo'].iteritems():
        if verbose:
            print >> sys.stderr, k, \
                  'N by day:', [str(day)+'/'+str(entry['by_day'][str(day)]['count']) for day in EVAL_DAYS], \
                  'Npaying by day:', [str(day)+'/'+str(entry['by_day'][str(day)]['paycount']) for day in EVAL_DAYS]

        for day in EVAL_DAYS:
            v = entry['by_day'][str(day)]
            # build spend cdf
            if len(v['spends']) > 0:
                v['spends'].sort()
                v['spend_cdf'] = []
                i = 0
                while i < len(v['spends']):
                    spend = v['spends'][i]
                    next = 1
                    while i+next < len(v['spends'])-1 and v['spends'][i+next] == spend:
                        next += 1
                    prob = (len(v['spends'])-i*1.0)/len(v['spends'])
                    v['spend_cdf'].append([spend, prob])
                    i += next
            v['linavg'] = v['linsum']/v['paycount'] if v['paycount'] > 0 else 0
            v['is_paying_user'] = v['paycount']/(1.0*v['count']) if v['count'] > 0 else 0
    return model

def estimate_ltv_chart(model, check_demographic = None, **kwargs):
    demos = [check_demographic,] if (check_demographic is not None) else model['by_demo'].keys()
    for demo in demos:
        for ltv_day in EVAL_DAYS:
            kwargs['verbose'] = True
            estimate_ltv(model, demo, ltv_day, **kwargs)

def estimate_ltv(model, demographic, ltv_day, n_installs = 5000, n_trials = 10000,
                 fudge_is_paying_user = 1, fudge_receipts = 1,
                 browser_bounce_rate = 0, verbose = True):
            v = model['by_demo'][demographic]
            future = v['by_day'][str(ltv_day)]

            if verbose:
                print >> sys.stderr, demographic, 'model entry for day %-3s:' % ltv_day, 'N', future['count'], 'Npaying', future['paycount'], \
                      'is_payer_d%d' % ltv_day, '%.2f%%' % (100.0*future['is_paying_user']), \
                      'receipts/payer_d%d' % ltv_day, pretty_money(future['linavg'])
#                      'lin_ltv_est_d%d' % ltv_day, pretty_money(future['is_paying_user']*future['linavg'])

            if future['paycount'] < 100 or ('spend_cdf' not in future):
                print demographic, 'WARNING: the model\'s Npaying (%d) at day %d is too low for accurate simulation results, skipping!' % (future['paycount'], ltv_day)
                return

            waterfall = future['spend_cdf']
            waterfall_cdf = [1.0-x[1] for x in waterfall]

            # weighted average receipts/user
            # computed_avg = sum([waterfall[i][0]*(waterfall[max(i-1,0)][1]-waterfall[i][1]) for i in xrange(len(waterfall))], 0.0)
            # print >> sys.stderr, 'computed_avg', pretty_money(computed_avg)

            # simulate a big chunk of ad spend that yields 5000 (n_installs) users -> 50 payers

            trials = []
            n_accounts = int((1-browser_bounce_rate) * n_installs)
            for i in xrange(n_trials):
                mctotal = fudge_receipts * monte_carlo(n_accounts, fudge_is_paying_user*future['is_paying_user'], waterfall, waterfall_cdf)
                mcavg = mctotal/n_installs
                trials.append(mcavg)
                trials.sort()
            if verbose: print demographic,
            print 'simulated %3d-day old accounts:' % ltv_day,
            if n_installs != n_accounts:
                print n_installs, 'installs',
            print 'N', '%5d' % n_accounts, 'Npaying', '%3d' % int(fudge_is_paying_user*future['is_paying_user']*n_accounts), '%-14s' % ('is_payer_d%d' % ltv_day), '%.2f%%' % (100.0*fudge_is_paying_user*future['is_paying_user']), ':', '%-22s' % ('receipts/account_d%d' %ltv_day), '       ', '90% conf', pretty_money(trials[int(n_trials*0.1)]), '... 75% conf', pretty_money(trials[int(n_trials*0.25)]), '... 50% conf', pretty_money(trials[int(n_trials*0.5)])


def monte_carlo(N, is_payer, waterfall, cdf):
    total = 0.0
    if is_payer >= 1:
        N_payers = N
    else:
        N_payers = poidev(is_payer*N)
    for i in xrange(N_payers):
        r = random.random()
        k = bisect.bisect(cdf, r) - 1
        total += waterfall[k][0]
    return total

def check_campaign(model, upcache_path, check_campaign_name, check_demographic,
                   check_creation_range = None, n_trials = 10000,
                   ltv_day = None, observation_day = None, n_installs = None,
                   fudge_is_paying_user = 1, fudge_receipts = 1,
                   parallel = 1):
    if observation_day is not None: assert observation_day < ltv_day
    DAYS = [ltv_day,] if ltv_day is not None else EVAL_DAYS
    assert check_demographic
    assert upcache_path
    demo_axes = parse_axes(check_demographic)
    query_axes = demo_axes + [{'name':'acquisition_campaign', 'values': [check_campaign_name]}]
    if check_creation_range:
        query_axes.append({'name':'account_creation_time', 'values': [check_creation_range]})

    print 'Scanning upcache for users matching:', query_axes

    campaign = build_model_reduce(build_model_map_parallel(upcache_path, query_axes, parallel), query_axes, 'campaign', verbose = False)

    print "Comparing actual results of campaign", '"'+check_campaign_name+'"', "in demographic", '"'+check_demographic+'"',
    if check_creation_range:
        print "for accounts created within", check_creation_range,
    print "vs simulation:"

    for k, v in campaign['by_demo'].iteritems():
        max_campaign_installs = 0
        for day in DAYS:
            c = v['by_day'][str(day)]
            if c['count'] > 0:
                print 'actual    %3d-day old accounts:' % day, 'N', '%5d' % c['count'], 'Npaying', '%3d' % c['paycount'], '%-14s' % ('is_payer_d%d' % day), '%.2f%%' % (100.0*c['is_paying_user']), ':', '%-22s' % ('receipts/account_d%d' % day), pretty_money((c['linsum']/c['count']) if c['count']>0 else 0)
                max_campaign_installs = max(max_campaign_installs, c['count'])
            do_compare = True
            if do_compare and n_installs > 0:
                estimate_ltv(model, check_demographic, ltv_day = day,
                             n_installs = n_installs if (n_installs > 0) else max_campaign_installs,
                             n_trials = n_trials, browser_bounce_rate = 0,
                             fudge_receipts = fudge_receipts, fudge_is_paying_user = fudge_is_paying_user,
                             verbose = False)

def optimize_sku_price(model, check_demographic, param, ltv_day = None, min_spend = 0):
    assert check_demographic in model['by_demo']
    assert ltv_day and str(ltv_day) in model['by_demo'][check_demographic]['by_day']
    c = model['by_demo'][check_demographic]['by_day'][str(ltv_day)]
    print >> sys.stderr, "N =", len(c['spends'])
    start, end, step = map(float, param.split(','))
    price = start
    while price <= end:
        sales = 0
        for entry in reversed(c['spends']):
            if price <= entry: sales += 1
            else: break
        print price, sales*price
        price += step

if __name__ == '__main__':
    if '--build-model-slave' in sys.argv:
        SpinParallel.slave(build_model_slave)
        sys.exit(0)

    build_model_name = None
    spend_categories = None
    upcache_path = None
    use_model_name = None
    monte_carlo_samples = 10000
    n_installs = 5000
    ltv_day = None
    observation_day = None
    browser_bounce_rate = 0.0
    check_campaign_name = None
    check_demographic = None
    check_creation_range = None
    optimize_sku_price_param = None
    min_spend = None
    fudge_receipts = 1
    fudge_is_paying_user = 1
    parallel = 1
    verbose = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['build-model=', 'spend-category=',
                                                      'use-model=', 'from-upcache=', 'monte-carlo-samples=', 'n-installs=',
                                                      'observation-day=', 'ltv-day=',
                                                      'browser-bounce-rate=',
                                                      'check-sku-price=',
                                                      'check-campaign=', 'check-demographic=', 'check-creation-range=',
                                                      'fudge-receipts=', 'fudge-is-paying-user=',
                                                      'optimize-sku-price=', 'min-spend=',
                                                      'parallel=',
                                                      'verbose'
                                                      ])

    for key, val in opts:
        if key == '--build-model': build_model_name = val
        elif key == '--spend-category':
            if spend_categories is None: spend_categories = []
            spend_categories.append(val)
        elif key == '--use-model': use_model_name = val
        elif key == '--from-upcache': upcache_path = val
        elif key == '--monte-carlo-samples': monte_carlo_samples = int(val)
        elif key == '--parallel': parallel = int(val)
        elif key == '--n-installs': n_installs = int(val)
        elif key == '--observation-day': observation_day = int(val)
        elif key == '--ltv-day': ltv_day = int(val)
        elif key == '--browser-bounce-rate': browser_bounce_rate = float(val)
        elif key == '--check-campaign': check_campaign_name = val
        elif key == '--check-demographic': check_demographic = val
        elif key == '--check-creation-range':
            s1, s2 = val.split('-')
            m1, d1, y1 = map(int, s1.split('/'))
            m2, d2, y2 = map(int, s2.split('/'))
            check_creation_range = [SpinConfig.cal_to_unix((y1,m1,d1)), SpinConfig.cal_to_unix((y2,m2,d2))]
        elif key == '--fudge-receipts': fudge_receipts = float(val)
        elif key == '--fudge-is-paying-user': fudge_is_paying_user = float(val)
        elif key == '--optimize-sku-price': optimize_sku_price_param = val
        elif key == '--min-spend': min_spend = float(val)
        elif key == '--verbose':
            verbose = True

    if build_model_name:
        print >> sys.stderr, 'Building model "%s" from upcache "%s" using axes: %s' % (build_model_name, upcache_path, repr(AXES))
        print >> sys.stderr, 'Restricted to spend categories:', spend_categories
        model = build_model_reduce(build_model_map_parallel(upcache_path, AXES, parallel, spend_categories=spend_categories), AXES, build_model_name)
        SpinJSON.dump(model, sys.stdout, pretty = True, newline = True)

    elif use_model_name:
        model = SpinJSON.load(open(use_model_name))
        print >> sys.stderr, 'Using model "%s"' % model['name']

        if check_campaign_name:
            check_campaign(model, upcache_path, check_campaign_name, check_demographic,
                           check_creation_range = check_creation_range,
                           ltv_day = ltv_day, observation_day = observation_day, n_installs = n_installs,
                           n_trials = monte_carlo_samples, parallel = parallel,
                           fudge_receipts = fudge_receipts, fudge_is_paying_user = fudge_is_paying_user)
        elif optimize_sku_price_param:
            optimize_sku_price(model, check_demographic, optimize_sku_price_param, ltv_day = ltv_day, min_spend = min_spend)
        else:
            estimate_ltv_chart(model, browser_bounce_rate = browser_bounce_rate,
                               n_installs = n_installs, n_trials = monte_carlo_samples,
                               check_demographic = check_demographic,
                               fudge_receipts = fudge_receipts, fudge_is_paying_user = fudge_is_paying_user,
                               verbose = verbose)

    else:
        print "Usage: Specify either --build-model=thunderrun.json --from-upcache=logs/thunderrun-upcache or"
        print "                      --use-model=thunderrun.json"
        sys.exit(1)
