# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import os
import sys

def daemonize():
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    fd = os.open('/dev/null', os.O_RDWR)
    os.dup2(fd, 0)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    if fd > 2:
        os.close(fd)
