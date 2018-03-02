#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Encapsulate the state to support the "Alliance Help" system for speeding up upgrades

# Right now we are transitioning away from a "Legacy" serialized format that is a single integer:
# -1 means no status, 0 means "help requested", >0 means "help completed"

# The new serialized format will be a JSON dictionary. But first we need to deploy code that can read both.

class UpgradeHelp(object):
    def __init__(self, state = None):
        self.help_requested = False
        self.help_request_expire_time = -1

        self.help_completed = False
        self.time_saved = -1

        if state is not None:
            self.unpersist_state(state)

    def persist_state(self):
        # for now, only emit the legacy format
        if self.help_completed:
            return max(1, self.time_saved)
        elif self.help_requested:
            return 0
        return -1

    def unpersist_state(self, state):
        if state in (None, -1):
            return # blank

        # legacy format
        if isinstance(state, int):
            if state == 0:
                self.help_requested = True
            elif state > 0:
                self.help_completed = True
                self.time_saved = state
        elif isinstance(state, dict):
            self.help_requested = state.get('help_requested',False)
            self.help_request_expire_time = state.get('help_request_expire_time',-1)
            self.help_completed = state.get('help_completed',False)
            self.time_saved = state.get('time_saved',-1)
        else:
            raise ValueError('invalid state %r' % state)
