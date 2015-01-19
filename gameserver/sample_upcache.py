#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# campaign -> spend_7d

# sample script for dumping info out of upcache (the userdb/playerdb cache)

# get fast JSON library if available
try: import simplejson as json
except: import json
import SpinConfig

# load some standard Python libraries
import sys, time, calendar
import csv

# load SpinPunch Upcache S3 access library
import SpinS3, SpinUpcacheIO

# load gamedata so we can reference it if necessary
# e.g. gamedata['units']['motion_cannon']['armor']
gamedata = json.load(open(SpinConfig.gamedata_filename()))

time_now = int(time.time())

def stream_userdb():
    bucket, name = SpinConfig.upcache_s3_location(SpinConfig.game())
    return SpinUpcacheIO.S3Reader(SpinS3.S3(SpinConfig.aws_key_file()),
                                  bucket, name).iter_all()

# main program
if __name__ == '__main__':

    # days at which to evaluate spend_dX
    SPEND_MARKS = (0,1,3,5,7,14,30,60,90,120)

    # list of fields you want to output to CSV. You have to specify this in advance.
    CSV_FIELDS = ['user_id', 'country', 'birthday', 'gender', 'account_creation_time', 'money_spent',
                  'kpi_cc2_d1', 'kpi_cc3_d10', 'kpi_5hrs_d7', 'kpi_paid_d14', 'kpi_paid2_d14',
                  ] + \
                  ['spend_d%d'%x for x in SPEND_MARKS] + \
                  ['spend_history']

    # initialize CSV writer object
    writer = csv.DictWriter(sys.stdout, CSV_FIELDS, dialect='excel')

    # write the header row
    writer.writerow(dict((fn,fn) for fn in CSV_FIELDS))

    # fetch upcache and prepare to stream it
    userdb = stream_userdb()

    # some parameters to control the iteration

    IGNORE_TIER_34 = True # True to ignore Tier 3 and 4 users

    # ignore accounts created before this date (2012 October 1)
    ACCOUNT_CREATION_MIN = calendar.timegm((2012,10,1,0,0,0)) # or -1 to disable

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

        # ignore users from low tiers
        if IGNORE_TIER_34:
            if user.get('country_tier', 'unknown') in ('3', '4'):
                # it's a Tier 3/4 user, ignore and move on to the next user
                continue

        # intialize csv_obj to an empty dictionary
        csv_obj = {}

        # pull some data out of the upcache entry
        csv_obj['user_id'] = user['user_id']
        csv_obj['account_creation_time'] = creat

        # pull some optional (possibly missing) data out of upcache
        if 'country' in user: csv_obj['country'] = user['country']
        if 'birthday' in user: csv_obj['birthday'] = user['birthday']
        if 'gender' in user: csv_obj['gender'] = user['gender'][0] # only write first letter, for brevity

        # CAN GET MORE FIELDS HERE, SEE SpinUpcache.py FOR A LIST!

        # user.get(x,y) means "look for field 'x' in user, and return its value. But if user
        # is MISSING a value for 'x', then return 'y' as the default.
        csv_obj['money_spent'] = user.get('money_spent', 0.0)

        # uncomment this to skip non-payers
        #if csv_obj['money_spent'] < 0.01: continue

        # function that returns cumulative spend up to and including day x
        def get_spend_at_day(user, x):
            return sum([age_spend[1] for age_spend in user.get('money_spent_at_time', {}).iteritems() if int(age_spend[0]) < ((x+1)*24*60*60)], 0)
        for day in SPEND_MARKS:
            # only evalulate spend_dX if account is at least X days old
            if  (time_now - creat) >= day*24*60*60:
                csv_obj['spend_d%d' % day] = get_spend_at_day(user, day)

        # compile a mapping of day number to individual spend amount on that day
        spend_history = {}
        for age, spend in user.get('money_spent_at_time', {}).iteritems():
            day = int(age)/(24*60*60) # convert age in seconds to age in days
            spend_history[day] = spend_history.get(day, 0.0) + spend

        # make spend_history cumulative, by adding up all spend on PRIOR days
        cum_spend_history = {}
        for age, spend in spend_history.iteritems():
            cum_spend_history[age] = sum([age_spend[1] for age_spend in spend_history.iteritems() if int(age_spend[0]) <= int(age)], 0.0)

        # serialize cum_spend_history into a string that alternates DAY,SPEND,DAY,SPEND,...
        csv_obj['spend_history'] = ','.join(['%d,%0.2f' % (int(day), cum_spend_history[d]) for d in sorted(cum_spend_history.keys())])

        # compute KPIs

        # kpi_paid_d14 = made any payment by end of 14th day
        csv_obj['kpi_paid_d14'] = 1 if len(filter(lambda age_spend: (int(age_spend[0]) < 14*24*60*60 and age_spend[1] > 0), user.get('money_spent_at_time',{}).iteritems())) >= 1 else 0
        # kpi_pad2_d14 = made two or more payments by end of 14th day
        csv_obj['kpi_paid2_d14'] = 1 if len(filter(lambda age_spend: (int(age_spend[0]) < 14*24*60*60 and age_spend[1] > 0), user.get('money_spent_at_time',{}).iteritems())) >= 2 else 0

        # kpi_cc2_d1 = upgraded to CC level 2 by end of first day
        if gamedata['townhall']+'_level_at_time' in user:
            csv_obj['kpi_cc2_d1'] = 1 if len(filter(lambda age_level: (int(age_level[0]) < 24*60*60 and age_level[1] >= 2), user[gamedata['townhall']+'_level_at_time'].iteritems())) else 0

            # kpi_cc3_d10 = upgraded to CC level 3 by end of 10th day
            csv_obj['kpi_cc3_d10'] = 1 if len(filter(lambda age_level: (int(age_level[0]) < 10*24*60*60 and age_level[1] >= 3), user[gamedata['townhall']+'_level_at_time'].iteritems())) else 0

        # kpi_5hrs_d7 = spent at least 5 hours in game by end of 7th day
        time_spent = 0.0
        # add up session times started within first 7 days
        for start, end in user.get('sessions',[]):
            if start > 0 and end > 0:
                if (start - creat) >= 7*14*60*60: break
                time_spent += (end - start)
        csv_obj['kpi_5hrs_d7'] = 1 if (time_spent >= 5*60*60) else 0

        # output one line of CSV based on the contents of csv_obj
        writer.writerow(csv_obj)

