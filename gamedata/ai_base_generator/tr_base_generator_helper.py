#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import random
import SpinJSON # JSON reading/writing library
import SpinConfig
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
ncells = 180
def makeRiflemenCluster(base,x,y):
    base['units'].append({
        "xy": [x,y],
        "patrol": 1,
        "force_level": 8, "spec":  "rifleman",
        "orders": [{
           "dest": [x-23,y+1],
           "state": 6,
           "aggressive": False
         },{
           "dest": [x+12,y-2],
           "state": 6,
           "patrol_origin": 1
         },{
           "dest": [x+23,y-1],
           "state": 6,
           "aggressive": False
         }]
      })
    base['units'].append({
        "xy": [x+4,y-9],
        "patrol": 1,
        "force_level": 8, "spec":  "rifleman",
        "orders": [{
           "dest": [x-19,y-8],
           "state": 6,
           "aggressive": False
         },{
           "dest": [x+16,y-11],
           "state": 6,
           "patrol_origin": 1
         },{
           "dest": [x+27,y-10],
           "state": 6,
           "aggressive": False
         }]
      })
    base['units'].append({
        "xy": [x+4,y-5],
        "patrol": 1,
        "force_level": 8, "spec":  "rifleman",
        "orders": [{
           "dest": [x+4-23,y-4],
           "state": 6,
           "aggressive": False
         },{
           "dest": [x+4+12,y-7],
           "state": 6,
           "patrol_origin": 1
         },{
           "dest": [x+27,y-6],
           "state": 6,
           "aggressive": False
         }]
      })
    base['units'].append({
        "xy": [x+8,y-4],
        "patrol": 1,
        "force_level": 8, "spec":  "rifleman",
        "orders": [{
           "dest": [x+8-23,y-3],
           "state": 6,
           "aggressive": False
         },{
           "dest": [x+20,y-6],
           "state": 6,
           "patrol_origin": 1
         },{
           "dest": [x+31,y-5],
           "state": 6,
           "aggressive": False
         }]
      })
    base['units'].append({
        "xy": [x+8,y-9],
        "patrol": 1,
        "force_level": 8, "spec":  "rifleman",
        "orders": [{
           "dest": [x+8-23,y-9+1],
           "state": 6,
           "aggressive": False
         },{
           "dest": [x+8+12,y-9-2],
           "state": 6,
           "patrol_origin": 1
         },{
           "dest": [x+8+23,y-9-1],
           "state": 6,
           "aggressive": False
         }]
      })
    base['units'].append({
        "xy": [x,y-5],
        "patrol": 1,
        "force_level": 8, "spec":  "rifleman",
        "orders": [{
           "dest": [x-23,y-4],
           "state": 6,
           "aggressive": False
         },{
           "dest": [x+12,y-7],
           "state": 6,
           "patrol_origin": 1
         },{
           "dest": [x+23,y-6],
           "state": 6,
           "aggressive": False
         }]
      })
    base['units'].append({
        "xy": [x+12,y-4],
        "patrol": 1,
        "force_level": 8, "spec":  "rifleman",
        "orders": [{
           "dest": [x-11,y+1-4],
           "state": 6,
           "aggressive": False
         },{
           "dest": [x+24,y-2-4],
           "state": 6,
           "patrol_origin": 1
         },{
           "dest": [x+35,y-1-4],
           "state": 6,
           "aggressive": False
         }]
      })
    base['units'].append({
        "xy": [x-1,y-9],
        "patrol": 1,
        "force_level": 8, "spec":  "rifleman",
        "orders": [{
           "dest": [x-1-23,y-8],
           "state": 6,
           "aggressive": False
         },{
           "dest": [x-1+12,y-11],
           "state": 6,
           "patrol_origin": 1
         },{
           "dest": [x-1+23,y-10],
           "state": 6,
           "aggressive": False
         }]
      })
    base['units'].append({
        "xy": [x+8,y],
        "patrol": 1,
        "force_level": 8, "spec":  "rifleman",
        "orders": [{
           "dest": [x+8-23,y+1],
           "state": 6,
           "aggressive": False
         },{
           "dest": [x+20,y-2],
           "state": 6,
           "patrol_origin": 1
         },{
           "dest": [x+31,y-1],
           "state": 6,
           "aggressive": False
         }]

      })
def placeBarrier(base):
    pass

def is_building_location_valid(ji, gridsize, base, ignore_perimeter=False, ignore_collision= False):
        gs2 = [int(gridsize[0]/2), int(gridsize[1]/2)]

        lo = [ji[1]-gs2[1], ji[0]-gs2[0]]
        hi = [ji[1]+gs2[1], ji[0]+gs2[0]]

        # XXX hack until we fix bound calculations
        if gridsize[1] == 2: hi[0] -= 1
        if gridsize[0] == 2: hi[1] -= 1

        ncells = gamedata['map']['ncells']
        mid = int(ncells/2)
#         def get_base_radius():    #XXXXXXX check on the base_size param value
#             assert base_size >= 0 and base_size < len(gamedata['map']['base_perimeter'])
#             return int(gamedata['map']['base_perimeter'][base_size]/2)
        rad = 180

        if ignore_perimeter:
            # just clamp against bounds
            if (ji[0] < 0) or (ji[0] >= ncells) or \
               (ji[1] < 0) or (ji[1] >= ncells):
                return False

        else:
            # clamp against base perimeter
            if (lo[0] < mid-rad) or (hi[0] > mid+rad) or \
               (lo[1] < mid-rad) or (hi[1] > mid+rad):
                return False
        # XXX check for collisions with other buildings
        if not ignore_collision:
            for obj in base['buildings']:    # range(len(base['buildings']))

                    #print obj
                    other_size = gamedata['buildings'][obj["spec"]]["gridsize"]
                    #obj = obj["spec"]
                    #other_size = base['buildings'][obj]["xy"]
                    #print other_size
                    obj_y = obj["xy"][1]
                    obj_x = obj["xy"][0]
                    other_lo = [obj_y - int(other_size[1]/2), obj_x - int(other_size[0]/2)]
                    other_hi = [obj_y + int(other_size[1]/2), obj_x + int(other_size[0]/2)]
                    if other_size[0] == 2: other_hi[1] -= 1
                    if other_size[1] == 2: other_hi[0] -= 1
                    if ((lo[0] < other_lo[0]) and (hi[0] > other_lo[0])) or \
                       ((lo[0] >= other_lo[0]) and (lo[0] < other_hi[0])):
                        if ((lo[1] < other_lo[1]) and (hi[1] > other_lo[1])) or \
                           ((lo[1] > other_lo[1]) and (lo[1] < other_hi[1])):
                            return False
        return True
