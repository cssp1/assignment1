#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for use by the game server to calculate auto-resolve battle results

# return two lists of arguments to call the server functions destroy_object()
# and object_combat_updates(), respectively.

def resolve(session):
    objects_destroyed = []
    combat_updates = []

    # XXXXXX insert algorithm here
    for obj in session.iter_objects():
        pass

    return objects_destroyed, combat_updates
