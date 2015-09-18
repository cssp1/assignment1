#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
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
