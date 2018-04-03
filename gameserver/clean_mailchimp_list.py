#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# unsubscribe dead users from a MailChimp list
# this keeps down the number of active subscribers (which we pay for)

import sys, time, getopt, re
import SpinJSON
import SpinConfig
import requests
from SpinMailChimp import mailchimp_api, mailchimp_api_batch, subscriber_hash, parse_mailchimp_time

time_now = int(time.time())
requests_session = requests.Session()

if __name__ == '__main__':
    list_name = None
    min_age_days = 30 # always keep users updated or added within this many days
    drop_country_tiers = [] # list of tiers to unsubscribe
    drop_email_re = None # regexp of addresses to unsubscribe
    dry_run = False
    verbose = True

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:q', ['list-name=','min-age-days=','drop-country-tier=','drop-email-regexp=','dry-run'])
    for key, val in opts:
        if key == '--list-name': list_name = val
        elif key == '--min-age-days': min_age_days = int(val)
        elif key == '--drop-country-tier': drop_country_tiers.append(int(val))
        elif key == '--drop-email-regexp': drop_email_re = re.compile(val)
        elif key == '--dry-run': dry_run = True
        elif key == '-q': verbose = False

    if not list_name:
        print '--list-name= is required'
        sys.exit(1)

    # get all our current lists
    if verbose: print 'querying existing MailChimp lists...'
    lists = mailchimp_api(requests_session, 'GET', 'lists', {'fields': 'lists.name,lists.id,lists.stats', 'count': 999})['lists']
    lists_by_name = dict((ls['name'], ls) for ls in lists)

    if list_name not in lists_by_name:
        print 'cannot find list named "%s"', list_name
        sys.exit(1)

    list_id = lists_by_name[list_name]['id']
    member_count = lists_by_name[list_name]['stats']['member_count']

    if verbose: print ('list "%s" currently has' % list_name), member_count, 'subscribers'
    if member_count < 1:
        sys.exit(0) # already empty

    BATCH_SIZE = 100
    to_clean = []
    for offset in range(0, member_count+1, BATCH_SIZE):
        if verbose:
            print 'querying', offset, '-', offset + BATCH_SIZE

        ret = mailchimp_api(requests_session, 'GET', 'lists/%s/members' % list_id,
                            {'fields': 'members.email_address,members.status,members.stats,members.timestamp_signup,members.last_changed,members.merge_fields',
                             'status': 'subscribed',
                             'offset': offset, 'count': BATCH_SIZE})
        for member in ret['members']:
            if member['status'] != 'subscribed':
                continue # member already unsubscribed. No action.
            if member['stats']['avg_click_rate'] > 0 or \
               member['stats']['avg_open_rate'] > 0:
                continue # member has responded. Don't unsubscribe.

            # maybe act differently on different country tiers?
            country_tier = None
            if member['merge_fields'].get('COUNTRY'):
                country_tier = SpinConfig.country_tier_map.get(member['merge_fields']['COUNTRY'], 4)
            elif member['merge_fields'].get('TIER'):
                country_tier = int(member['merge_fields']['TIER'])

            if country_tier is not None and int(country_tier) in drop_country_tiers:
                # if using --drop-country-tier, always unsubscribe regardless of age
                pass
            elif drop_email_re and drop_email_re.match(member['email_address'].lower()):
                # if using --drop-email-regexp and it matches, always unsubscribe regardless of age
                pass
            else:
                if member['timestamp_signup']:
                    signup_time = parse_mailchimp_time(member['timestamp_signup'])
                    if signup_time >= time_now - min_age_days * 86400:
                        continue # member signed up recently. Don't unsubscribe.

                last_changed_time = parse_mailchimp_time(member['last_changed'])
                if last_changed_time >= time_now - min_age_days * 86400:
                    continue # member was updated recently. Don't unsubscribe.

            to_clean.append(member)

    if not to_clean:
        sys.exit(0)

    if verbose:
        print 'removing', len(to_clean), 'stale members...'

    if not dry_run:
        # do the first one as a single call, to make sure the API works
        mailchimp_api(requests_session, 'PATCH', 'lists/%s/members/%s' % (list_id, subscriber_hash(to_clean[0]['email_address'])),
                      {'fields': 'email_address,status'},
                      data = {'status': 'unsubscribed'})
        to_clean = to_clean[1:]

        # the batch call does not return any result immediately
        batches = [to_clean[i:i+BATCH_SIZE] for i in xrange(0, len(to_clean), BATCH_SIZE)]
        for batch in batches:
            if not dry_run:
                mailchimp_api_batch(requests_session,
                                    [{'method': 'PATCH', 'path': 'lists/%s/members/%s' % (list_id, subscriber_hash(member['email_address'])),
                                      'body': SpinJSON.dumps({'status': 'unsubscribed'})} for member in batch])
