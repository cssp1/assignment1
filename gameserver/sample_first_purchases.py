#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# sample script for dumping info out of upcache (the userdb/playerdb cache)

# load some standard Python libraries
import sys, time, bisect, csv

import SpinJSON # fast JSON library
import SpinConfig
import SpinS3 # S3 authentication library
import SpinUpcacheIO # library for reading upcache in a streaming fashion
import SpinUpcache # utilities for working with upcache entries

# load gamedata so we can reference it if necessary
# e.g. gamedata['units']['motion_cannon']['armor']
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

time_now = int(time.time())

# return an iterator that streams the entire userdb one entry at a time
def stream_userdb():
    bucket, name = SpinConfig.upcache_s3_location(SpinConfig.game())
    return SpinUpcacheIO.S3Reader(SpinS3.S3(SpinConfig.aws_key_file()),
                                  bucket, name).iter_all()

# main program
if __name__ == '__main__':

    # list of fields you want to output to CSV. You have to specify this in advance.
    CSV_FIELDS = ['user_id', 'account_creation_time', 'money_spent',
                  'acquisition_campaign',
                  'player_level_now', gamedata['townhall']+'_level_now',
                  'made_second_purchase', 'pvp_attacks_suffered', 'n_visits'
                  ] + sum([[N+'_purchase_time', N+'_purchase_amount', N+'_purchase_currency', N+'_purchase_category', N+'_purchase_subcategory',
                            'account_age_at_'+N+'_purchase', 'player_level_at_'+N+'_purchase', gamedata['townhall']+'_level_at_'+N+'_purchase'] for N in ('first','second')],[])

    # initialize CSV writer object
    writer = csv.DictWriter(sys.stdout, CSV_FIELDS, dialect='excel')

    # write the header row
    writer.writerow(dict((fn,fn) for fn in CSV_FIELDS))

    # fetch upcache and prepare to stream it
    userdb = stream_userdb()

    # some parameters to control the iteration

    IGNORE_TIER_4 = False # True to ignore Tier 4 users
    IGNORE_NONSPENDERS = True

    # ignore accounts created before this date, -1 to disable
    ACCOUNT_CREATION_MIN = -1 # calendar.timegm((2012,6,1,0,0,0))

    # loop through all users. 'user' will be set to the upcache entry for one user on each loop iteration.
    for user in userdb:

        # If you just want to see what fields are available in upcache, uncomment the following line
        # (and be prepared for a deluge of console output)
        #sys.stderr.write(repr(sorted(user.keys()))+'\n')

        # If you are curious about how upcache is generated, see SpinUpcache.py.
        # The complete list of all cached fields is visible in get_csv_fields() near the top of that file.

        # Note: not all upcache entries have values for all possible fields. Usually whenever a
        # field is missing, you can assume it has a reasonable default value. E.g., if money_spent
        # is missing, then treat it the same as if money_spent = $0.00. HOWEVER, certain fields
        # have a different meaning for "missing" and "zero", the most important of these being
        # retained_Xd and spend_Xd. If the field is MISSING, it means the account is not old
        # enough to "qualify" for being considered (e.g. a 4-day-old account will not have a
        # retained_7d or spend_7d value, because it isn't old enough yet to contribute to those metrics).
        # This is DIFFERENT from a ZERO value, which means the account is old enough, but wasn't retained or
        # had zero spend. When in doubt, ask Dan about this. It is VERY important to understand
        # when missing and zero values have different meanings.

        # The variable "csv_obj" is the data that will be output to CSV, in the form of a Python dictionary
        # mapping CSV column names to values (either numeric or strings).
        # it is OK to omit any field - the CSV will just have a blank for that column
        # it is NOT ok to add any fields beyond what is listed in CSV_FIELDS above

        # note: really old upcache entries may be missing an account_creation_time
        # let's just ignore those, because they are hard to use for meaningful metrics
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

        # intialize csv_obj to an empty dictionary
        csv_obj = {}

        # pull some data out of the upcache entry
        csv_obj['user_id'] = user['user_id']

        # now stick the creation time into the CSV object
        csv_obj['account_creation_time'] = creat

        # user.get(x,y) means "look for field 'x' in user, and return its value. But if user
        # is MISSING a value for 'x', then return 'y' as the default.
        csv_obj['money_spent'] = user.get('money_spent', 0)
        csv_obj['acquisition_campaign'] = user.get('acquisition_campaign', 'MISSING')
        csv_obj['player_level_now'] = user.get('player_level', 1)
        csv_obj[gamedata['townhall']+'_level_now'] = user.get(gamedata['townhall']+'_level', 1)

        csv_obj['pvp_attacks_suffered'] = user.get('attacks_suffered', 0)
        if 'sessions' in user:
            csv_obj['n_visits'] = len(user['sessions'])
        csv_obj['made_second_purchase'] = int(len(user.get('money_spent_at_time',{})) > 1)

        for N, index in (('first',1),('second',2)):
            # crawl through purchase history with this handy utility
            # function that "sees through" alloy purchases to the
            # following use of alloys
            purchase = SpinUpcache.find_nth_purchase(user, index)
            if not purchase:
                continue # data missing or unparseable

            # suck data out of the purchase history entry
            csv_obj[N+'_purchase_time'] = purchase['time']
            csv_obj['account_age_at_'+N+'_purchase'] = purchase['age']
            if 'dollar_amount' in purchase:
                # direct FB Credits purchase
                csv_obj[N+'_purchase_amount'] = purchase['dollar_amount']
                csv_obj[N+'_purchase_currency'] = 'fbcredits'
            elif 'gamebucks_amount' in purchase:
                # alloy expenditure
                csv_obj[N+'_purchase_amount'] = (purchase['gamebucks_amount']/gamedata['store']['gamebucks_per_fbcredit'])*0.07
                csv_obj[N+'_purchase_currency'] = 'alloys'

            # use utility function to classify type of purchase
            cat, subcat = SpinUpcache.classify_purchase(gamedata, purchase['description'])
            csv_obj[N+'_purchase_category'] = cat
            csv_obj[N+'_purchase_subcategory'] = subcat

            # check age against time series to determine what the player's level and CC level were at the time of purchase

            # note, purchases that result in gaining player or CC levels are recorded at the *higher* level you reach
            # to report the accurate level the user was at when they initiated the purchase process, bring it forward in time a bit
            reference_age = purchase['age'] - 15

            for KEY in ('player_level', gamedata['townhall']+'_level'):
                SERIES = KEY + '_at_time'
                if SERIES in user:
                    increments = sorted([int(st) for st, v in user[SERIES].iteritems()])
                    where = bisect.bisect(increments, reference_age) - 1
                    if where < 0:
                        value = 1
                    else:
                        value = user[SERIES][str(increments[where])]
                    csv_obj[KEY+'_at_'+N+'_purchase'] = value

        # skip people for whom we have no data
        if 'first_purchase_time' not in csv_obj: continue


        #if (time_now - creat) < (7*24*60*60): continue
        # csv_obj['spend_7d'] = sum([age_spend[1] for age_spend in user.get('money_spent_at_time', {}).iteritems() if int(age_spend[0]) < (7*24*60*60)], 0.0)

        # output one line of CSV based on the contents of csv_obj
        writer.writerow(csv_obj)
