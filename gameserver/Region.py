#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# helper for reading region data out of gamedata

class Region:
    def __init__(self, gamedata, region_id):
        self.gamedata = gamedata
        self.region_id = region_id
    def is_nosql(self):
        return self.gamedata['regions'][self.region_id].get('storage','basedb')=='nosql'
    def dimensions(self):
        return self.gamedata['regions'][self.region_id]['dimensions']
    def in_bounds(self, xy):
        dimensions = self.dimensions()
        return xy[0] >= 0 and xy[0] < dimensions[0] and xy[1] >= 0 and xy[1] < dimensions[1]
    def get_neighbors(self, xy):
        odd = (xy[1]%2) > 0
        return filter(self.in_bounds, [[xy[0]-1,xy[1]], # left
                                       [xy[0]+1,xy[1]], # right
                                       [xy[0]+odd-1,xy[1]-1], # upper-left
                                       [xy[0]+odd,xy[1]-1], # upper-right
                                       [xy[0]+odd-1,xy[1]+1], # lower-left
                                       [xy[0]+odd,xy[1]+1]])
    def read_terrain(self, xy):
        dims = self.dimensions()
        terrain = self.gamedata['region_terrain'][self.gamedata['regions'][self.region_id]['terrain']]
        index = xy[1]*dims[0]+xy[0]
        encoded = ord(terrain[index])
        raw = encoded - 65
        return raw
    def read_climate_name(self, xy):
        return self.gamedata['territory']['tiles'][self.read_terrain(xy)]['climate']
    def read_climate(self, xy):
        return self.gamedata['climates'][self.read_climate_name(xy)]
    def obstructs_bases(self, xy):
        return self.read_climate(xy).get('obstructs_bases',False)
    def obstructs_squads(self, xy):
        return self.read_climate(xy).get('obstructs_squads',False)
    def feature_blocks_map(self, feature, squad_block_mode):
        return feature['base_type'] != 'squad' or (not feature.get('raid') and squad_block_mode != 'never')
    def feature_is_moving(self, feature, time_now, assume_moving = False):
        # add extra fudge time to reduce chance of race conditions
        # "assume_moving" is a hint to favor the most likely case for this check (giving "benefit of the doubt")
        # note: we must add at LEAST 1 sec of padding time, because the server_time resolution is integer seconds, while 'eta' can be fractional.
        fudge_time = (-1 if assume_moving else 1) * (self.gamedata['server'].get('map_path_fudge_time',0.25) + 1.0)
        return bool(feature.get('base_map_path',None)) and \
               feature['base_map_path'][-1]['eta'] > time_now + fudge_time
