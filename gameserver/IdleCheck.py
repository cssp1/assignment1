#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for use by the game server to perform anti-bot CAPTCHA checks
import random

# return status codes
STATUS_NO_RESULT = 0
STATUS_SEND_AGAIN = -1
STATUS_SUCCESS = 1
STATUS_FAIL = 2

class IdleCheck(object):


    @classmethod
    def make_question(cls):
        # return two strings: (ui_question, ui_answer)
        a = random.randint(1,10)
        b = random.randint(1,10)
        ui_answer = '%d' % (a + b)
        ui_question = '%d + %d = ?' % (a, b)
        return (ui_question, ui_answer)

    def __init__(self, config, state, cur_time):
        self.config = config

        # state that persists across logins
        self.last_end_playtime = 0 # playtime at which last check finished
        self.last_end_time = -1 # clock time at which last check finished
        self.start_time = -1 # start clock time of this check
        self.tries = 0 # number of questions sent this check
        self.timeouts = 0 # number of timeouts this check
        self.inflight = {} # mapping from tag -> answer for outstanding questions

        self.history = [] # time-ordered list of results {"time": UNIX_TIMESTAMP, "result": "fail"/"success"}

        if state:
            self.last_end_playtime = state.get('last_end_playtime', self.last_end_playtime)
            self.last_end_time = state.get('last_end_time', self.last_end_time)
            self.start_time = state.get('start_time', self.start_time)
            self.tries = state.get('tries', self.tries)
            self.timeouts = state.get('timeouts', self.timeouts)
            # note: inflight state is not preserved across logins
            self.history = state.get('history', self.history)

        self.prune_history(cur_time)

    def serialize(self):
        return {'last_end_playtime': self.last_end_playtime,
                'last_end_time': self.last_end_time,
                'start_time': self.start_time,
                'tries': self.tries,
                'timeouts': self.timeouts,
                # note: inflight state is not preserved 'inflight': self.inflight,
                'history': self.history}

    def prune_history(self, cur_time):
        limit = self.config.get('keep_history_for', 604800)
        self.history = filter(lambda x: cur_time - x['time'] < limit, self.history)

    def forced_check_needed(self): return self.last_end_playtime < 0

    def check_needed(self, login_time, cur_time, playtime):
        if self.start_time > 0: # in progress
            if not self.inflight:
                # new login - need to send a new question
                return True
            return False

        # last_end_playtime -1 to manually trigger
        if self.last_end_playtime < 0:
            return True

        # wait for interval
        if playtime - self.last_end_playtime < self.config['interval']:
            return False # not time yet
        return True

    def stop_check(self, login_time, cur_time, playtime, is_success):
        self.last_end_playtime = playtime
        self.last_end_time = cur_time
        self.start_time = -1
        self.inflight = {}
        self.tries = 0
        self.timeouts = 0
        self.history.append({'time': cur_time, 'result': 'success' if is_success else 'fail'})

    # return a status code
    def timeout(self, login_time, cur_time, playtime):
        if self.start_time > 0 and cur_time - self.start_time >= self.config['timeout']:
            self.timeouts += 1
            if self.timeouts >= self.config['max_timeouts']: # too many timeouts, count as failure
                self.stop_check(login_time, cur_time, playtime, False)
                return STATUS_FAIL
            else:
                self.start_time = cur_time
                return STATUS_SEND_AGAIN
        return STATUS_NO_RESULT

    # return the response to send the client
    def start_check(self, login_time, cur_time, playtime):
        if self.start_time < 0:
            self.start_time = cur_time
            self.inflight = {}
            self.tries = 0
            self.timeouts = 0

        tag = str(random.randint(0, 1<<31))

        ui_question, answer = self.make_question()
        self.inflight[tag] = {'ui_question': ui_question, 'answer': answer}

        return {'tag': tag, 'try': self.tries, 'timeouts': self.timeouts, 'ui_question': ui_question}

    # return a status code
    def got_response(self, login_time, cur_time, playtime, response):
        if self.start_time < 0 or (response['tag'] not in self.inflight): return STATUS_NO_RESULT
        is_correct = response['answer'] == self.inflight[response['tag']]['answer']

        if is_correct:
            self.stop_check(login_time, cur_time, playtime, True)
            return STATUS_SUCCESS

        # answer is incorrect
        self.tries += 1
        if self.tries >= self.config['max_tries']: # too many mistakes, count as failure
            self.stop_check(login_time, cur_time, playtime, False)
            return STATUS_FAIL

        return STATUS_SEND_AGAIN # ask again
