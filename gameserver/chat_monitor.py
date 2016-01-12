#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# run periodically to scan chat logs for inappropriate messages not already reported

import sys, os, time, getopt, subprocess, re
import SpinConfig
import SpinJSON
import SpinNoSQL
import SpinSingletonProcess
import SpinReminders
import ChatFilter

time_now = int(time.time())

def get_likelihoods(strings):
    "Run the machine-learning model on a list of strings, returning a list of badness probabilities"
    env = os.environ.copy()
    # find libraries in gameserver directory :(
    env['PYTHONPATH'] = env.get('PYTHONPATH','')+':'+os.path.dirname(__file__)
    proc = subprocess.Popen(['ChatMom/train.py', '--resume=good', '--infer=-', '--quiet=1', '--parallel=1'],
                            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    blob = ('\n'.join(strings + [''])).encode('utf-8')
    stdoutdata, stderrdata = proc.communicate(input=blob)
    if proc.returncode != 0:
        msg = 'ChatMom execution failed:\n%s' % (stderrdata)
        if 0:
            raise Exception(msg)
        else: # return all zeroes
            sys.stderr.write(msg)
            return [0,] * len(strings)
    return map(float, stdoutdata.split('\n')[:-1])

def make_reports(verbose, dry_run, nosql_client, row_confidence_list, reason):
    sent = []
    for row, confidence in row_confidence_list:
        skip = False

        # check if this message has already been reported
        if nosql_client.chat_report_get_one_by_message_id(row['id']):
            skip = True

        if verbose:
            print ('%s%s (%-4s flag %.3f): %s: %s' % \
                   (('SKIPPING' if skip else 'REPORTING'),
                    (' (dry-run)' if dry_run else ''),
                    reason, confidence, row['sender']['chat_name'], row['text'])).encode('utf-8')

        if skip: continue
        if not dry_run:
            nosql_client.chat_report(row['channel'], -1, 'ChatMom', row['sender']['user_id'], row['sender']['chat_name'],
                                     time_now, row['time'], row['id'], '*** '+row['text']+' ***',
                                     confidence = confidence, source = reason)
        sent.append(row)
    return sent

if __name__ == '__main__':
    game_id = SpinConfig.game()
    verbose = True
    dry_run = False
    incremental = True
    lookback = 2*3600 # look back this far in time
    prob_threshold = 0.9 # minimum probability for a machine-learning flag to cause a report

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:q', ['dry-run','lookback=','incremental=','threshold='])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--lookback': lookback = int(val)
        elif key == '--incremental': incremental = bool(int(val))
        elif key == '--threshold': prob_threshold = float(val)

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
    cf = ChatFilter.ChatFilter(gamedata['client']['chat_filter'])

    with SpinSingletonProcess.SingletonProcess('chat_monitor-%s' % game_id):

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))

        start_time = time_now - lookback
        end_time = time_now - 5

        if incremental:
            # find most recent already-converted action
            bookmark = nosql_client.chat_monitor_bookmark_get('ALL')
            if bookmark:
                start_time = max(start_time, bookmark)

        if verbose:
            print 'start_time', start_time, 'end_time', end_time

        qs = {'time':{'$gt':start_time, '$lte': end_time},
              '$or':[{'channel':{'$regex':'r:.*', '$not': re.compile(r'r:prison.*')}},
                     {'channel':{'$in':['global_english','global_t123']}}]
              }

        flagged_rule = [] # list of (message,confidence) flagged by the rule-based filter
        unknown = [] # messages not flagged by the rule-based filter that need further inspection

        for row in nosql_client.chat_buffer_table().find(qs):
            row = nosql_client.decode_chat_row(row)

            message_type = row['sender'].get('type', 'default')

            # check chat template to see whether it is a player-originated
            # chat message (which will have a %body for body text
            # replacement) or a system-generated message (e.g. unit
            # donation traffic). Ignore system messages.

            template = gamedata['strings']['chat_templates'].get(message_type, '%body')
            if '%body' not in template: continue
            if 'text' not in row: continue # bad data
            if len(row['text']) < 3: continue # too short

            if cf.is_bad(row['text']):
                if verbose:
                    print ('rule-based flag: %s: %s' % (row['sender']['chat_name'], row['text'])).encode('utf-8')
                flagged_rule.append((row,1))
            else:
                unknown.append(row)

        flagged_ml = []

        if unknown and (prob_threshold > 0) and (prob_threshold <= 1):
            if verbose:
                print 'Running ChatMom on', len(unknown), 'strings...',
                sys.stdout.flush()
            unknown_probs = get_likelihoods([r['text'] for r in unknown])
            if verbose:
                print
                #print unknown_probs
            for row, prob in zip(unknown, unknown_probs):
                if prob >= prob_threshold:
                    if verbose:
                        print ('ML flag (%.3f): %s: %s' % (prob, row['sender']['chat_name'], row['text'])).encode('utf-8')
                    flagged_ml.append((row,prob))

        sent = make_reports(verbose, dry_run, nosql_client, flagged_rule, 'rule') + \
               make_reports(verbose, dry_run, nosql_client, flagged_ml, 'ml')

        if not dry_run:
            nosql_client.chat_monitor_bookmark_set('ALL', end_time)
        if sent and ('chat_report_recipients' in SpinConfig.config):
            SpinReminders.send_reminders('chat_monitor.py', SpinConfig.config['chat_report_recipients'],
                                         '%s Chat Report (see [PCHECK](https://%sprod.spinpunch.com/PCHECK) )' % (SpinConfig.game_id_long().upper(), SpinConfig.game()),
                                         'ChatMom reported %d possible instance(s) of abuse:\n%s' % (len(sent), '\n'.join('***'+x['text']+'***' for x in sent)),
                                         dry_run = dry_run)
