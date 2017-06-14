#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Import CSV file from Wufoo survey

import sys, time, getopt, csv
import SpinConfig
import SpinSQLUtil
from SpinHTTP import ip_matching_key
import MySQLdb

time_now = int(time.time())

def questions_schema(sql_util):
    return {'fields': [('survey_id', 'VARCHAR(32) NOT NULL'),
                       ('question_id', 'INT4 NOT NULL'),
                       ('ui_prompt', 'VARCHAR(1000) NOT NULL'),
                       ('ui_short', 'VARCHAR(255)'),
                       ],
            'indices': {'master': {'unique':True, 'keys':[('survey_id','ASC'),('question_id','ASC')]}}}
def responses_schema(sql_util):
    return {'fields': [('survey_id', 'VARCHAR(32) NOT NULL'),
                       ('question_id', 'INT4 NOT NULL'),
                       ('user_id', 'INT4'),
                       ('time', 'INT8'),
                       ('ip','VARCHAR(255)'),
                       ('raw','VARCHAR(1000) NOT NULL'),
                       ('intval','INT4'),
                       ('raw_long','TEXT'),
                       ],
            'indices': {'master': {'unique':True, 'keys':[('survey_id','ASC'),('question_id','ASC'),('user_id','ASC')]},
                        'by_user_id': {'unique':False, 'keys':[('user_id','ASC')]}}}

RESP_INTVAL = {
    'Very Important': 5,
    'Somewhat important': 4,
    "Don't Know / Don't Care": 3,
    'Not Very Important': 2,
    'Not at all important': 1,
    'Yes': 1,
    'No': 0
    }

if __name__ == '__main__':
    verbose = True
    dry_run = False
    game_id = SpinConfig.game()
    dbname = None
    survey_id = None

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'q', ['dry-run','dbname=','survey-id='])

    for key, val in opts:
        if key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--dbname': dbname = val
        elif key == '--survey-id': survey_id = val

    if not survey_id:
        raise Exception('must provide survey_id')

    if len(args) < 1:
        raise Exception('give me a CSV file')

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    if dbname is None:
        dbname = '%s_upcache' % game_id
    cfg = SpinConfig.get_mysql_config(dbname)
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    cur = con.cursor(MySQLdb.cursors.DictCursor)

    questions_table = cfg['table_prefix']+game_id+'_survey_questions'
    responses_table = cfg['table_prefix']+game_id+'_survey_responses'
    for table, schema in ((questions_table, questions_schema(sql_util)),
                          (responses_table, responses_schema(sql_util))):
        sql_util.ensure_table(cur, table, schema)

    if not dry_run:
        cur.execute('DELETE FROM %s WHERE survey_id = %%s' % sql_util.sym(questions_table), [survey_id])
        cur.execute('DELETE FROM %s WHERE survey_id = %%s' % sql_util.sym(responses_table), [survey_id])
        con.commit()

    csv_reader = csv.reader(open(args[0]))
    header_map = None
    col_user_id = None
    col_time = None
    col_ip = None
    col_completion_status = None
    questions = None

    seen_user_ids = set()
    seen_ips = set()

    for row in csv_reader:
        if questions is None:
            questions = {} # map from integer (question_id) to prompt string
            #print 'HEADER',
            #print row
            for i, entry in enumerate(row):
                # find important columns
                if entry == 'Player Number': col_user_id = i
                elif entry == 'Date Created': col_time = i
                elif entry == 'IP Address': col_ip = i
                elif entry == 'Completion Status': col_completion_status = i
                elif entry in ('Entry Id', 'Created By', 'Last Updated', 'Updated By',
                               'Last Page Accessed'):
                    pass # ignore
                else:
                    # otherwise, this is a question column
                    questions[i] = entry

            if col_user_id is None: raise Exception('no user_id column')
            if col_time is None: raise Exception('no time column')
            if col_ip is None: raise Exception('no ip column')
            if col_completion_status is None: raise Exception('no completion_status column')

            # now we have all the questions. Insert into questions table
            if not dry_run:
                cur.executemany("INSERT INTO "+sql_util.sym(questions_table) + \
                                " (survey_id, question_id, ui_prompt) VALUES (%s,%s,%s)",
                                [(survey_id, question_id, prompt) for \
                                 question_id, prompt in questions.iteritems()])
                con.commit()

            continue

        # grab individual responses
        if row[col_completion_status] != '1':
            print 'skipping incomplete survey'
            continue

        s_user_id = row[col_user_id]
        if not s_user_id:
            print 'skipping missing user_id'
            continue
        try:
            user_id = int(s_user_id)
        except ValueError:
            print 'skipping invalid user_id', s_user_id
            continue

        if user_id in seen_user_ids:
            print 'skipping duplicate user_id', user_id
            continue

        ip = row[col_ip]
        if not ip:
            print 'skipping missing IP'
            continue
        ip = ip_matching_key(ip)

        if ip in seen_ips:
            print 'skipping duplicate IP', ip
            continue

        timestamp = None # XXX long(mktime_tz(parsedate_tz(row[col_time])))


        for question_id in questions:
            raw = row[question_id]
            if raw.isdigit():
                intval = int(raw)
            elif raw in RESP_INTVAL:
                intval = RESP_INTVAL[raw]
            else:
                intval = None
            if len(raw) > 255:
                raw_long = raw
                raw = raw[:252]+'...'
            else:
                raw_long = None
            if not dry_run:
                cur.execute("INSERT INTO "+sql_util.sym(responses_table) + \
                            " (survey_id, question_id, user_id, time, ip, raw, intval, raw_long)" + \
                            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            [survey_id, question_id, user_id, timestamp, ip, raw, intval, raw_long])


        seen_user_ids.add(user_id)
        seen_ips.add(ip)
        #print 'ROW'
        #print row

    con.commit()
