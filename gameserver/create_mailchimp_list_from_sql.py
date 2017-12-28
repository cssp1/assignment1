#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# create a Mailchimp list of players from SQL query results
# this is used to create mailing lists to target churned players for reacquisition

# example usage:
# ./create_mailchimp_list_from_sql.py -g dv --list-name '20171227 DV Reacq <6mo'   --cohorts 5 --min-spend 100 --min-balance 1 --churned-for 90 --active-within 180
# ./create_mailchimp_list_from_sql.py -g dv --list-name '20171227 DV Reacq 6-12mo' --cohorts 5 --min-spend 100 --min-balance 1 --churned-for 180 --active-within 360
# ./create_mailchimp_list_from_sql.py -g dv --list-name '20171227 DV Reacq >12mo'  --cohorts 5 --min-spend 100 --min-balance 1 --churned-for 360

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinSQLUtil, MySQLdb
import requests
from SpinMailChimp import mailchimp_api, mailchimp_api_batch, subscriber_hash

time_now = int(time.time())
requests_session = requests.Session()
gamedata = None

MERGE_FIELDS = [
    {'name': 'Cohort', 'tag': 'COHORT', 'type': 'text', 'public': False},
    {'name': 'Country', 'tag': 'COUNTRY', 'type': 'text', 'public': False},
    {'name': 'Country Tier', 'tag': 'TIER', 'type': 'text', 'public': False},
    {'name': 'Full Name', 'tag': 'FULLNAME', 'type': 'text', 'public': True},
    {'name': 'Account Creation Date', 'tag': 'ACCT_CREAT', 'type': 'date', 'options': {'date_format': 'MM/DD/YYYY'}, 'public': False},
    {'name': 'Gamebucks Balance', 'tag': 'BALANCE', 'type': 'number', 'public': False},
    {'name': 'Player ID', 'tag': 'PLAYER_ID', 'type': 'number', 'public': False},
    {'name': 'Townhall Level', 'tag': 'TOWNHALL', 'type': 'number', 'public': False},
    ]

def create_list(list_name, game_name, dry_run = False):
    if dry_run:
        return '000'

    ret = mailchimp_api(requests_session, 'POST', 'lists', data = {
        'name': list_name,
        'contact': {"city": "Palo Alto",
                    "zip": "94301",
                    "address1": "855 El Camino Real, Palo Alto, CA",
                    "company": "Battlehouse",
                    "phone": "226 808 5115",
                    "state": "CA",
                    "country": "US",
                    "address2": ""
                    },
        'permission_reminder': 'You are receiving this email because you play '+ game_name,
        'campaign_defaults': {'from_name': game_name,
                              'subject': 'Online War Strategy Tips from Battlehouse Games',
                              'language': 'en',
                              'from_email': 'no-reply@battlehousemail.com'},
        'email_type_option': False})
    return ret['id']

def ensure_merge_fields(list_id, dry_run = False):
    result = mailchimp_api(requests_session, 'GET', 'lists/%s/merge-fields' % list_id)
    cur_fields_by_tag = dict((field['tag'], field) for field in result['merge_fields'])
    for field in MERGE_FIELDS:
        if field['tag'] not in cur_fields_by_tag:
            if dry_run:
                print 'would add field', field['tag']
            else:
                mailchimp_api(requests_session, 'POST', 'lists/%s/merge-fields' % list_id,
                              data = field)
        else:
            cur = cur_fields_by_tag[field['tag']]
            for k, v in field.iteritems():
                if cur[k] != field[k]:
                    print 'disagree:', k, cur[k], field[k]
                    if not dry_run:
                        mailchimp_api(requests_session, 'PATCH', 'lists/%s/merge-fields/%s' % (list_id, cur['merge_id']),
                                      data = {k: field[k]})

def player_to_cohort(pinfo, num_cohorts):
    """ Assign a cohort code to a player based on user_id """
    n = pinfo['user_id'] % num_cohorts
    return chr(ord('A') + n)

def player_to_member(pinfo, cohort_id):
    assert pinfo['email']
    assert pinfo['account_creation_time'] > 0
    assert pinfo['gamebucks_balance']

    ret =  {'email_address': pinfo['email'],
            'status': 'subscribed',
            'merge_fields':
            {"COHORT": cohort_id,
             "COUNTRY": pinfo['country'],
             "TIER": SpinConfig.country_tier_map.get(pinfo['country'], 4),
             "ACCT_CREAT": time.strftime('%m/%d/%Y', time.gmtime(pinfo['account_creation_time'])),
             "BALANCE": pinfo['gamebucks_balance'],
             "PLAYER_ID": pinfo['user_id'],
             }
            }
    if pinfo['country'] not in (None, 'unknown'):
        ret['merge_fields']['COUNTRY'] = pinfo['country']
        if 0: # this seems to confuse MailChimp
            if 'location' not in ret:
                ret['location'] = {}
            ret['location']['country_code'] = pinfo['country']
    if pinfo.get('last_login_ip'):
        ret['ip_signup'] = pinfo['last_login_ip']
    if pinfo.get('timezone') is not None:
        ret['location']['gmtoff'] = pinfo['timezone']
    if pinfo[gamedata['townhall']+'_level']:
        ret['merge_fields']['TOWNHALL'] = pinfo[gamedata['townhall']+'_level']
    if pinfo.get('locale'):
        ret['language'] = pinfo['locale'][0:2]
    if pinfo.get('facebook_name'):
        ret['merge_fields']['FULLNAME'] = pinfo['facebook_name']
    return ret

def add_players_to_list(list_id, pinfo_list, num_cohorts):
    if len(pinfo_list) == 1:
        # non-batch
        return [mailchimp_api(requests_session, 'PUT',  'lists/%s/members/%s' % (list_id, subscriber_hash(pinfo_list[0]['email'])),
                              data = player_to_member(pinfo_list[0], player_to_cohort(pinfo_list[0], num_cohorts)))]

    batch = [{'method': 'PUT', 'path': 'lists/%s/members/%s' % (list_id, subscriber_hash(pinfo['email'])),
              'body': SpinJSON.dumps(player_to_member(pinfo, player_to_cohort(pinfo, num_cohorts)))} \
             for pinfo in pinfo_list]
    return mailchimp_api_batch(requests_session, batch)

def upcache_table(sql_util, game_id):
    # note: assumes table_prefix equals '$GAMEID_upcache'
    return sql_util.sym(game_id + '_upcache') + '.' + sql_util.sym(game_id + ('_upcache_lite' if game_id == 'mf' else '_upcache'))

if __name__ == '__main__':
    game_id = SpinConfig.game()
    list_name = None
    min_spend = 100.0
    min_balance = 1
    churned_for_days = 30
    active_within_days = 999999
    num_cohorts = 5
    dry_run = False
    print_player_ids = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['list-name=','min-spend=','churned-for=','active-within=','cohorts=','min-balance=','dry-run','print-player-ids'])
    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '--list-name': list_name = val
        elif key == '--min-spend': min_spend = float(val)
        elif key == '--min-balance': min_balance = int(val)
        elif key == '--churned-for': churned_for_days = int(val)
        elif key == '--active-within': active_within_days = int(val)
        elif key == '--cohorts': num_cohorts = int(val)
        elif key == '--dry-run': dry_run = True
        elif key == '--print-player-ids': print_player_ids = True

    if not list_name:
        print '--list-name= is required'
        sys.exit(1)

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
    cfg = SpinConfig.get_mysql_config(SpinConfig.game()+'_upcache') # note: use "native" connection, not game_id
    sql_util = SpinSQLUtil.MySQLUtil()
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    cur = con.cursor(MySQLdb.cursors.DictCursor)

    print 'querying for candidate', game_id, 'players...'
    cur.execute('SELECT user_id, LOWER(email) AS email, facebook_name, locale, country, last_login_ip, account_creation_time, gamebucks_balance, ' + \
                gamedata['townhall']+'_level ' + \
                'FROM ' + upcache_table(sql_util, game_id) + ' ' + \
                'WHERE email IS NOT NULL AND ' + \
                ' account_creation_time IS NOT NULL AND ' + \
                ' money_spent >= %s AND ' + \
                ' gamebucks_balance >= %s AND ' + \
                ' last_login_time <= %s AND ' + \
                ' last_login_time >= %s',
                [min_spend, min_balance, time_now - churned_for_days * 86400, time_now - active_within_days * 86400])
    candidate_list = cur.fetchall()
    candidates_by_email = dict((c['email'], c) for c in candidate_list)
    con.commit()
    print 'got', len(candidates_by_email), 'candidates'
    del candidate_list

    # eliminate ones that are active in other games within last 30 days (note: fixed at 30 days, not dependent on churned_for_days)
    for other_game_id in ('mf','tr','mf2','bfm','sg','dv','fs'):
        if other_game_id != game_id:
            print 'checking for recent play in', other_game_id, '...'
            cur.execute('SELECT LOWER(email) AS email FROM ' + upcache_table(sql_util, other_game_id) + ' ' + \
                        'WHERE last_login_time >= %s AND LOWER(email) IN %s',
                        [time_now - 30*86400, candidates_by_email.keys()])
            elimination_list = cur.fetchall()
            con.commit()
            if len(elimination_list) > 0:
                print 'eliminating', len(elimination_list), 'candidates'
                for elim in elimination_list:
                    del candidates_by_email[elim['email']]

    print len(candidates_by_email), 'candidates remaining'

    if len(candidates_by_email) < 1:
        sys.exit(0)

    # get all our current lists
    print 'querying existing MailChimp lists...'
    lists = mailchimp_api(requests_session, 'GET', 'lists', {'fields': 'lists.name,lists.id', 'count': 999})['lists']
    lists_by_name = dict((ls['name'], ls['id']) for ls in lists)

    if list_name in lists_by_name:
        list_id = lists_by_name[list_name]
        print 'using existing list %s (%s)' % (list_name, list_id)
    else:
        print 'creating list', list_name, '...'
        if dry_run:
            list_id = '000'
        else:
            list_id = create_list(list_name, gamedata['strings']['game_name'])
        lists_by_name[list_name] = list_id
        print 'created list %s (%s)' % (list_name, list_id)

    print 'ensuring merge fields are up to date...'
    ensure_merge_fields(list_id, dry_run = dry_run)

    candidate_list = candidates_by_email.values()
    # candidate_list = candidate_list[:1]
    print 'adding', len(candidate_list), 'players...'
    if not dry_run:
        ret = add_players_to_list(list_id, candidate_list, num_cohorts)
    # print ret

    if print_player_ids:
        print sorted([int(x['user_id']) for x in candidate_list])
