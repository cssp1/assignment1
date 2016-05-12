#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

BOLD = '\033[1m'
YELLOW = '\033[93m'
GREEN = '\033[92m'
RED = '\033[91m'
ENDC = '\033[0m'

def bold(x): return BOLD+x+ENDC
def red(x): return RED+x+ENDC
def green(x): return GREEN+x+ENDC
def yellow(x): return YELLOW+x+ENDC
