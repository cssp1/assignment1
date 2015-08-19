#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# convert JSON metrics log files to CSV

# the script can process "-metrics.json", "-credits.json", and "-machine.json" log files,
# and applies some minor special-case handling to each of these.

# this script is run automatically by aws/daily-metrics.sh to upload log files to Amazon S3

import SpinJSON
import sys, os, string
import csv
import getopt
import SpinConfig
import SpinUpcache # for purchase classifier

import locale # for pretty number printing only
locale.setlocale(locale.LC_ALL, '')

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

# UTILITIES

# increment value of d[key], assuming that the current amount is zero
# if d[key] doesn't exist
def dict_increment(d, key, amount):
    d[key] = d.setdefault(key, 0) + amount

# In order for the output CSV files to have a fixed column order, we have to list out the data columns
# explicitly in the order we want them written out. There is one list of data columns for each kind of
# JSON file:

data_fields = {
    "metrics": ["ptime", "time", "code", "event_name",
                "user_id","anon_id",
                "billing_amount", "billing_description",
                "browser_name", "browser_os", "browser_version",
                "framerate", "framerate_cap",
                "country", "locale", "facebook_id", "name", "first_name", "last_name", "gender",
                "host", "ip", "last_login_ip", "location", "method", "origin", "playtime",
                "redirected_to", "referer", "referrer", "returning", "time_to_assetload", "time_to_running",
                "url", "user_agent", "viewed_url",
                "level", "tech_type", "unit_type", "building_type", "resource_type", "speedup_type", "fb_price", "sku",
                "capacity", "amount_added", "harvested_amount", "cost_time",
                "mission_id", "mission_count", "menu_name",
                "opponent_level", "opponent_type", "opponent_user_id", "battle_outcome",
                "attacker_user_id", "attacker_level",
                "account_creation_time", "last_login_time", "scm_version",
                "gain_amount", "units_lost", "units_killed",
                "time_to_loading", "time_to_load_page", "time_to_assetload_essential",
                "logged_in_times", "campaign_name", "age_group", "recipient_fb_id", "sender_fb_id", "sender_user_id",
                "recipient_user_id",
                "facebook_request_id", "created_time", "facebook_post_id",
                "server_time_offset", "gain_xp", "order_id", "referring_user_id", "combat_level", "tutorial_state", "base_damage", "combat_dps","pvp_balance","player_rating","opponent_rating",
                "canvas_width", "canvas_height", "is_paying_user",
                ] + ["cost_"+res for res in gamedata['resources']] + ["gain_"+res for res in gamedata['resources']],
    "credits": ["ptime", "time", "code", "event_name", "user_id", "billing_amount", "billing_description", "order_id"],
    "gamebucks": ["ptime", "time", "code", "event_name", "user_id", "gamebucks_price", "billing_description", "money_spent"],
    "machine": ["ptime", "time", "active_sessions", "process_memory_mb", "loadavg_15min",
                "machine_mem_used_mb", "machine_mem_free_mb", "machine_swap_used_mb", "machine_swap_free_mb",
                "disk_space_used_gb", "disk_space_free_gb", "disk_space_total_gb", "error", "hostname", "server_name"
                ],
    }

# Do not print these data fields into the output CSV, since they are not meaningful for metrics analysis
IGNORE_FIELDS = ["game_id", "session_id", "location", "timeout_duration"]

# ignore events coming from users with these IDs - used to filter out developer accounts
IGNORE_USERS = SpinConfig.config.get('developer_user_id_list', [])

# this dictionary keeps track of the SpinPunch user_id associated with new visitors to the site
# who were initially assigned an "anonymous" ID by index.php before they logged in
ANON_ID_MAP = {}

# this dictionary counts how many events of each kind happened
TOTALS = {}

time_range = [-1,-1]

# (more aggregate metrics could be computed here)

TIMERS = ['time_to_assetload_essential', 'time_to_assetload', 'time_to_loading', 'time_to_RUNNING']
timer_sums = {}
timer_counts = {}
for name in TIMERS:
    timer_sums[name] = 0.0
    timer_counts[name] = 0

BATTLE_DATA = {}
unique_users = set()
unique_new_users = set()
unique_paying_users = set()

REVENUE = 0
REFUNDS = 0

PURCHASE_CATEGORIES = list(set(SpinUpcache.PURCHASE_CATEGORY_MAP.itervalues()))

rev_by_category = {}
for cat in PURCHASE_CATEGORIES:
    rev_by_category[cat] = {}


# just to make sure data field names are always consistent, use this
# function to set them to lower case and replace spaces and dashes
# with underscores
def conform_name(name):
    name = name.lower()
    name = name.replace(' ', '_')
    name = name.replace('-', '_')
    # correct misspelling
    if name == "referrer":
        name = "referer"
    return name

# Python's CSV library doesn't like handling Unicode characters.
# This function replaces any non-ASCII characters with X to ensure safe CSV output
def sanitize_text(text):
    ret = ''
    for i in range(len(text)):
        o = ord(text[i])
        if (o >= 0) and (o < 128):
            ret += text[i]
        else:
            ret += 'X'
    return ret

if __name__ == "__main__":
    # use the getopt library to parse command-line arguments
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['mode=', 'include-developers', 'sms-output=', 'totals-only', 'payers-only', 'categories'])
    if len(args) < 1:
        print 'usage: %s foo.json > foo.csv' % sys.argv[0]
        sys.exit(1)

    infiles = args

    # mode = kind of JSON file that we are processing
    mode = 'metrics'

    # whether or not to include users listed in IGNORE_USERS
    include_developers = False
    do_categories = False
    include_nonpayers = True

    # optional file to write brief (SMS message) stats to
    sms_output = None

    do_csv = True

    for key, val in opts:
        if key == '--mode':
            mode = val
        elif key == '--include-developers':
            include_developers = True
        elif key == '--sms-output':
            sms_output = val
        elif key == '--totals-only':
            do_csv = False
        elif key == '--categories':
            do_categories = True
        elif key == '--payers-only':
            include_nonpayers = False

    FIELDS = data_fields[mode]

    if 0 or do_csv:
        # we make TWO passes through the JSON log files. The first pass collects all the names of
        # data columns that will go into the CSV output, and also builds the ANON_ID_MAP to associate
        # user IDs with anonymous visitors. The second pass performs the actual CSV conversion.

        # first pass
        for filename in infiles:
            for line in open(filename).xreadlines():
                obj = SpinJSON.loads(line)
                for key in obj.keys():
                    key = conform_name(key)
                    if key in IGNORE_FIELDS:
                        continue
                    if not (key in FIELDS):
                        # we encountered a new data field name that wasn't listed in FIELDS.
                        # make a note of this so we can go back and add it later
                        sys.stderr.write('NEW KEY %s\n' % key)
                        FIELDS.append(key)

                # link an anonymous ID with a real user_id when we see the associate_user_id event
                if obj.has_key('event_name') and obj['event_name'].endswith('associate_user_id'):
                    ANON_ID_MAP[obj['anon_id']] = obj['user_id']

        #sys.stderr.write(repr(FIELDS)+'\n')
        if do_csv:
            # ok now get ready to write the CSV file
            writer = csv.DictWriter(sys.stdout, FIELDS, dialect='excel')

            # write the header row with field names
            writer.writerow(dict((fn,fn) for fn in FIELDS))

    # second pass through JSON files
    for filename in infiles:
        for line in open(filename).xreadlines():
            obj = SpinJSON.loads(line)
            out = {}

            # gather each field in the log line by name
            for key in obj.keys():
                val = obj[key]
                key = conform_name(key)
                if not key in IGNORE_FIELDS:
                    # clean out non-ASCII characters so the CSV writer won't barf
                    if isinstance(val, str) or isinstance(val, unicode):
                        val = sanitize_text(val)
                    out[key] = val

            # for any events that are tagged by an anonymous ID (anon_id) but not a user_id,
            # look in the anonymous ID map to see if we know who the user is
            if out.has_key('anon_id') and (not out.has_key('user_id')):
                anon_id = out['anon_id']
                if anon_id in ANON_ID_MAP:
                    # tag the event with the user's actual user_id
                    out['user_id'] = ANON_ID_MAP[anon_id]
                    #sys.stderr.write('matched anon ID '+anon_id+' to '+repr(ANON_ID_MAP[anon_id])+'\n')
                else:
                    pass
                    #sys.stderr.write('dangling anon ID '+anon_id+'\n')

            # ignore developer accounts and spurious messages from AI players
            if (not include_developers) and out.has_key('user_id') and ((out['user_id'] in IGNORE_USERS) or (out['user_id'] < 1100)):
                continue

            if out.has_key('time'):
                t = int(out['time'])
                if time_range[0] < 0:
                    time_range[0] = t
                    time_range[1] = t
                else:
                    time_range[0] = min(time_range[0], t)
                    time_range[1] = max(time_range[1], t)

            # update the TOTALS (total number of events for each unique event_name)
            if out.has_key('event_name'):
                ename = out['event_name']
                if TOTALS.has_key(ename):
                    TOTALS[ename] += 1
                else:
                    TOTALS[ename] = 1

                # NOTE: right here would be a good place to extract any other metrics!
                if ename == '3830_battle_end':
                    dict_increment(BATTLE_DATA, 'total', 1)
                    if out['opponent_type'] == 'ai':
                        dict_increment(BATTLE_DATA, 'vs_ai', 1)
                        dict_increment(BATTLE_DATA, 'vs_%d' % out['opponent_user_id'], 1)
                    else:
                        dict_increment(BATTLE_DATA, 'vs_human', 1)

                elif ename == '1000_billed':
                    rev = out.get('billing_amount',0)
                    REVENUE += rev
                    # stick the user into paying_users, in case they were not paying upon login
                    unique_paying_users.add(int(out['user_id']))

                    descr = out.get('billing_description', '')
                    catname, subcat = SpinUpcache.classify_purchase(gamedata, descr)
                    c = rev_by_category[catname]
                    c[subcat] = c.get(subcat,0.0) + rev

                elif ename == '1310_order_refunded':
                    rev = out.get('billing_amount',0)
                    REVENUE -= rev
                    REFUNDS += rev

                elif ename == '1400_gamebucks_spent':
                    if mode != "gamebucks": continue
                    if ((not include_nonpayers) and (out.get('money_spent',0) <= 0)): continue
                    rev = out.get('gamebucks_price',0)
                    REVENUE += rev
                    descr = out.get('billing_description', '')
                    catname, subcat = SpinUpcache.classify_purchase(gamedata, descr)
                    c = rev_by_category[catname]
                    c[subcat] = c.get(subcat,0) + rev

                elif ename == '0115_logged_in':
                    unique_users.add(int(out['user_id']))
                    if out.has_key('is_paying_user') and out['is_paying_user']:
                        unique_paying_users.add(int(out['user_id']))
                    if out.has_key('returning') and not out['returning']:
                        unique_new_users.add(int(out['user_id']))

                elif ename in ('0020_page_view', '0030_request_permission', '0100_authenticated_visit', '0940_unsupported_browser'):
                    if out.has_key('returning') and out['returning'] == 0:
                        u = ename + ' (nonreturning)'
                        if u in TOTALS:
                            TOTALS[u] += 1
                        else:
                            TOTALS[u] = 1

                if mode == 'metrics':
                    for prop in TIMERS:
                        if out.has_key(prop):
                            val = float(out[prop])
                            if val > 0:
                                timer_sums[prop] += val
                                timer_counts[prop] += 1

            # write the output row to the CSV file
            if do_csv:
                try:
                    writer.writerow(out)
                except:
                    sys.stderr.write('PROBLEM ROW: '+repr(out)+'\n')
                    raise

    prefix = string.join([os.path.basename(filename) for filename in infiles], ' ')

    # processing done! write the "TOTALS" information and any other aggregate metrics to stderr
    # (the S3 uploader script collects anything written here and sends it to DATE-totals.txt)
    sys.stderr.write(prefix+' TOTALS:\n')
    keys = TOTALS.keys()
    keys.sort()
    for ename in keys:
        sys.stderr.write('%-40s\t%6d\n' % (ename, TOTALS[ename]))

    if mode == 'metrics':
        # if you want to add reporting of more aggregate metrics, write them to sys.stderr here
        sys.stderr.write('\n'+prefix+' METRICS AGGREGATES:\n')
        if time_range[0] > 0:
            sys.stderr.write('%-25s %.2f\n' % ('Hours of data:', (time_range[1]-time_range[0])/3600.0))
        sys.stderr.write('%-25s $%.2f\n' % ('Revenue:', REVENUE))
        sys.stderr.write('%-25s %d\n' % ('Unique NEW user logins:', len(unique_new_users)))
        sys.stderr.write('%-25s %d\n' % ('Unique user logins:', len(unique_users)))
        sys.stderr.write('%-25s %d\n' % ('Unique paying user logins:', len(unique_paying_users)))
        if len(unique_users) > 0:
            sys.stderr.write('%-25s $%.3f\n' % ('Average Revenue/DAU:', REVENUE/len(unique_users)))
        if len(unique_paying_users) > 0:
            sys.stderr.write('%-25s $%.3f\n' % ('Average Revenue/Paying DAU:', REVENUE/len(unique_paying_users)))

        for name in TIMERS:
            if timer_counts[name] > 0:
                sys.stderr.write('%-50s %3.2f sec\n' % ('Average '+name+':', timer_sums[name]/timer_counts[name]))

        for name, num, denom in [
            ['Tutorial Completion Rate (0399/140):',
             '0399_tutorial_complete', '0140_tutorial_oneway_ticket'],
            ['Friend Invite Acceptances per Prompt (7120/7100):',
             '7120_friend_invite_accepted', '7100_invite_friends_attempted'],
            ['Auth rate (0100/0030, new visits only):',
             '0100_authenticated_visit (nonreturning)', '0030_request_permission (nonreturning)'],
            ['Unsupported Browser Bounce Rate (0940/0100, new visits only):',
             '0940_unsupported_browser (nonreturning)', '0100_authenticated_visit (nonreturning)'],
            ]:
            if TOTALS.get(denom, 0) > 0:
                ratio = float(TOTALS.get(num,0))/float(TOTALS.get(denom,0))
                sys.stderr.write('%-40s\t%4.1f%%  (N = %d)\n' % (name, 100.0*ratio, TOTALS.get(denom,0)))

        if 0:
            sys.stderr.write('\nBATTLES:\n')
            for key in sorted(BATTLE_DATA.keys()):
                sys.stderr.write('%-40s\t%6d\n' % (key, BATTLE_DATA[key]))

        if sms_output:
            sms = open(sms_output, 'a')
            sms.write('DAU %s Rev $%.2f' % (locale.format('%d', len(unique_users), True),REVENUE))

    elif mode == 'credits' or mode == 'gamebucks':
        rev_pattern = '$%7.2f' if mode == 'credits' else '%7.2f'
        rev_divisor = 100.0 if mode == 'gamebucks' else 1

        sys.stderr.write('\n'+prefix+' '+mode.upper()+' AGGREGATES:\n')
        sys.stderr.write(('Total '+mode.upper()+' Receipts:   '+rev_pattern+'\n') % ((REVENUE+REFUNDS)/rev_divisor))
        if REFUNDS > 0:
            sys.stderr.write(('-     '+mode.upper()+' Refunds:   '+rev_pattern+'\n') % (REFUNDS/rev_divisor))
        sys.stderr.write(('Net   '+mode.upper()+' Receipts:   '+rev_pattern+'\n') % (REVENUE/rev_divisor))
        if (time_range[1]-time_range[0]) > 1:
            day_rev = REVENUE*24.0/((time_range[1]-time_range[0])/3600.0)
            sys.stderr.write('\nProjected 24hr net receipts:  '+(rev_pattern % (day_rev/rev_divisor))+'\n')

        if REVENUE > 0 and do_categories:
            sys.stderr.write('\nPurchases by Category:\n')
            for cat in sorted(PURCHASE_CATEGORIES):
                rev = rev_by_category[cat]
                total = sum(rev.itervalues())
                sys.stderr.write(('\n\n\t%-60s\t%6.1f%%    '+rev_pattern+'\n') % (cat.upper(), 100.0*total/REVENUE, total/rev_divisor))
                sys.stderr.write('\t------------------------------------------------------------------------\n')
                if len(rev) > 0:
                    for s in sorted(rev.keys(), key = lambda s: -rev[s]):
                        r = rev[s]
                        sys.stderr.write(('\t%-75s\t%6.1f%%    '+rev_pattern+'\n') % (s, 100.0*r/total, r/rev_divisor))
