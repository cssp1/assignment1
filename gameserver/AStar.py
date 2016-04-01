#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this is a quick-and-dirty A* pathfinder for navigating squads around the regional map
# the interface and implementation are as close as possible to the client's AStar.js for simplicity.

import Region
import BinaryHeap

ASTAR_MAX_ITER = 999999
PASS = 0
NOPASS = float('inf')

def hex_slanted(a):
    # transform to "slanted" coordinate system for easier distance computation
    new_x = a[0] - int(a[1]/2)
    return (new_x, a[1])

def hex_distance(a, b):
    a2 = hex_slanted(a)
    b2 = hex_slanted(b)
    dx = b2[0]-a2[0]
    dy = b2[1]-a2[1]
    dd = dx+dy
    return max(abs(dx), abs(dy), abs(dd))

def heuristic_manhattan(start_pos, cur_pos, end_pos):
    # Manhattan distance
    return abs(end_pos[0] - cur_pos[0]) + abs(end_pos[1] - cur_pos[1])

# wrap a path_checker into a version that is_blocked() can call with only the current cell as the argument
def path_checker_to_cell_checker(path_checker, cur_path):
    return lambda cell, pc=path_checker: pc(cell, cur_path+[cell.pos,])

class AStarCell(object):
    def __init__(self, pos):
        self.pos = pos
        self.block_count = 0 # count of obstacles overlapping this point

        # list of references to obstacles that are blocking here
        self.blockers = None # optional - only used by hex map right now

        self.heapscore = 0 # for insertion into BinaryHeap

        # The following fields are specific to one query.
        # In order to avoid having to re-initialize the entire grid before each query,
        # we use a "mailbox" technique to do just-in-time initialization if serial mismatches.
        self.serial = 0
        self.f = 0
        self.g = 0
        self.h = 0
        self.visited = False
        self.closed = False
        self.parent = None
    def get(self, serial):
        if self.serial != serial:
            self.f = 0
            self.g = 0
            self.h = 0
            self.visited = False
            self.closed = False
            self.parent = None
            self.serial = serial
        return self
    def is_blocked(self, checker = None):
        if checker: return checker(self)
        return NOPASS if self.block_count > 0 else PASS
    def is_empty(self): return self.block_count <= 0
    def block(self): self.block_count += 1
    def unblock(self): self.block_count -= 1

class AStarMap(object):
    def __init__(self, size, terrain_func = None):
        self.size = size
        self.terrain_func = terrain_func
        self.needs_cleanup = False
        self.generation = 0
        self.n_alloc = 0
        self.map = [None,]*self.size[1] # columns of lazily-allocated rows of lazily-allocated AStarCells
        self.clear()
    def clear(self):
        for y in xrange(self.size[1]):
            self.map[y] = None
        self.needs_cleanup = False
        self.n_alloc = 0
        self.generation += 1
    def cell(self, xy):
        if self.map[xy[1]] is None:
            self.map[xy[1]] = [None,]*self.size[0]
        if self.map[xy[1]][xy[0]] is None:
            self.map[xy[1]][xy[0]] = AStarCell(xy)
            self.n_alloc += 1
            self.needs_cleanup = True
        return self.map[xy[1]][xy[0]]
    def free_cell(self):
        self.needs_cleanup = True
    def cell_if_unblocked(self, xy, checker = None):
        if xy[0] >= 0 and xy[0] < self.size[0] and \
           xy[1] >= 0 and xy[1] < self.size[1]:
            if self.terrain_func and self.terrain_func(xy): return None
            c = self.cell(xy)
            if c.is_blocked(checker) == NOPASS: return None
            return c
        return None
    def is_blocked(self, xy, checker = None):
        if xy[0] >= 0 and xy[0] < self.size[0] and \
           xy[1] >= 0 and xy[1] < self.size[1]:
            if self.terrain_func and self.terrain_func(xy): return NOPASS
            if self.map[xy[1]] is None: return PASS
            c = self.map[xy[1]][xy[0]]
            if c is None: return PASS
            return c.is_blocked(checker)
        return NOPASS

class AStarHexMap(AStarMap):
    def num_neighbors(self): return 6
    def get_unblocked_neighbors(self, node, checker, ret):
        x, y = node.pos
        odd = (y%2) > 0
        ret[0] = self.cell_if_unblocked([x-1,y], checker) # left
        ret[1] = self.cell_if_unblocked([x+1,y], checker) # right
        ret[2] = self.cell_if_unblocked([x+odd-1,y-1], checker) # upper-left
        ret[3] = self.cell_if_unblocked([x+odd,y-1], checker) # upper-right
        ret[4] = self.cell_if_unblocked([x+odd-1,y+1], checker) # lower-left
        ret[5] = self.cell_if_unblocked([x+odd,y+1], checker) # lower-right
    def unblock_hex_maybe(self, xy, blocker):
        if self.is_blocked(xy):
            cell = self.cell(xy)
            if cell.blockers and blocker in cell.blockers:
                self.block_hex(xy, -1, blocker)
    def block_hex(self, xy, value, blocker):
        assert blocker
        if xy[0] >= 0 and xy[0] < self.size[0] and xy[1] >= 0 and xy[1] < self.size[1]:
            cell = self.cell(xy)
            if cell:
                if value > 0:
                    cell.block()
                    if cell.blockers is None:
                        cell.blockers = [blocker]
                    else:
                        cell.blockers.append(blocker)

                elif value < 0:
                    cell.unblock()
                    cell.blockers.remove(blocker)
                    if len(cell.blockers) == 0:
                        cell.blockers = None

                if cell.is_empty():
                    self.free_cell(xy)

        self.generation += 1

class AStarContext(object):
    def __init__(self, map, heuristic_name = 'manhattan', iter_limit = -1):
        self.serial = 1
        self.map = map
        self.iter_limit = iter_limit
        if heuristic_name:
            self.heuristic = heuristic_manhattan
        else:
            raise Exception('unknown A* heuristic '+heuristic_name)
    def search(self, start_pos, end_pos, path_checker = None):
        self.serial += 1;

        start = self.map.cell(start_pos)
        end = self.map.cell(end_pos)

        if (not start) or (not end): return [] # to or from a cell that's not on the map

        # note: assume that all nodes pushed onto the openHeap already have been initialized via get()
        # sort by node.f
        openHeap = BinaryHeap.BinaryHeap()
        openHeap.push(start, start.get(self.serial).f)

        iter = 0

        # keep track of closest node to endpoint, so that we can
        # return a partial path in case all complete paths are blocked
        best_node = None
        best_h = float('inf')

        # preallocate for speed
        neighbors = [None,]*self.map.num_neighbors()

        while openHeap.size() > 0 and iter < ASTAR_MAX_ITER:
            iter +=1
            if iter >= ASTAR_MAX_ITER:
                raise Exception('infinite loop in astar.search()!')
            elif self.iter_limit > 0 and iter >= self.iter_limit:
                break # give up

            # Grab the lowest f(x) to process next.  Heap keeps this sorted for us.
            currentNode = openHeap.pop()

            # End case -- result has been found, return the traced path
            if currentNode is end:
                curr = currentNode
                end_ret = []

                while curr.parent is not None:
                    end_ret.append(curr.pos)
                    curr = curr.parent

                return list(reversed(end_ret))

            # Normal case -- move currentNode from open to closed, process each of its neighbors
            currentNode.get(self.serial).closed = True

            # wrap path_checker into a version that is_blocked() can call with only the current cell as the argument
            cell_checker = None
            if path_checker:
                cur_path = []
                c = currentNode
                while c.parent is not None:
                    cur_path.append(c.pos)
                    c = c.parent
                cur_path = list(reversed(cur_path))
                cell_checker = path_checker_to_cell_checker(path_checker, cur_path)

            # get references to neighbor cells
            self.map.get_unblocked_neighbors(currentNode, cell_checker, neighbors)

            for neighbor in neighbors:
                if(neighbor is None or neighbor.get(self.serial).closed):
                    # not a valid node to process, skip to next neighbor
                    continue

                cost = neighbor.is_blocked(cell_checker)
                if(cost == NOPASS): continue # completely blocked

                # g score is the shortest distance from start to current node, we need to check if
                #   the path we have arrived at this neighbor is the shortest one we have seen yet
                # 1 is the distance from a node to its neighbor.  This could be variable for weighted paths.
                gScore = currentNode.g + 1 + cost # add cost on top of normal movement
                beenVisited = neighbor.visited

                if (not beenVisited) or (gScore < neighbor.g):
                    # Found an optimal (so far) path to this node.  Take score for node to see how good it is.
                    neighbor.visited = True
                    neighbor.parent = currentNode
                    neighbor.h = neighbor.h or self.heuristic(start.pos, neighbor.pos, end.pos)
                    neighbor.g = gScore
                    neighbor.f = neighbor.g + neighbor.h

                    # keep track of "best" node seen so far, in case we fail to find a path all the way to the target
                    if neighbor.h < best_h:
                        best_h = neighbor.h
                        best_node = neighbor

                    if not beenVisited:
                        # Pushing to heap will put it in proper place based on the 'f' value.
                        openHeap.push(neighbor, neighbor.f)
                    else:
                        # Already seen the node, but since it has been rescored we need to reorder it in the heap
                        openHeap.rescoreElement(neighbor, neighbor.f)

        # No result was found -- empty array signifies failure to find path
        ret = []
        if best_node is not None:
            curr = best_node
            while curr.parent is not None:
                ret.append(curr.pos)
                curr = curr.parent
            ret = list(reversed(ret))
        return ret

class SquadPathfinder(object):
    def __init__(self, region):
        self.region = region
        self.occupancy = AStarHexMap(region.dimensions(), terrain_func = region.obstructs_squads)
        self.hstar_context = AStarContext(self.occupancy, heuristic_name = 'manhattan')

    # only blocked by non-squads
    def raid_path_checker(self, cell, path):
        if cell.block_count > 0:
            if any(feature['base_type'] != 'squad' for feature in cell.blockers):
                return NOPASS
        return PASS

    # return a path that ends on hex "dest", or if "dest" is blocked, an open hex immediately adjacent to it
    def squad_find_path_adjacent_to(self, src, dest, dest_feature = None, is_raid = False):
        assert is_raid # only handles the raid-squad special case for now
        path_checker = self.raid_path_checker

        # if dest is not blocked, try going directly there
        if not self.occupancy.is_blocked(dest):
            path = self.hstar_context.search(src, dest, path_checker)
            if path and len(path) >= 1 and hex_distance(path[-1], dest) == 0:
                return path # good path

        # try aiming for neighbor squares around "dest"
        best_path = None
        best_travel_time = -1
        for n in self.region.get_neighbors(dest):
            if not self.occupancy.is_blocked(n):
                path = self.hstar_context.search(src, n, path_checker)
                # path must lead INTO n
                if path and len(path) >= 1 and hex_distance(path[-1], n) == 0:
                    # good path
                    # trim off unnecessary extra moves at the end of the path that just circle around the destination hex
                    # note: need to check for blockage on this intermediate waypoint before changing the final destination to it,
                    # because it might be the destination of another moving squad, where we aren't allowed to land.
                    while len(path) >= 2 and hex_distance(path[-2], dest) == 1 and not self.occupancy.is_blocked(path[-2]):
                        path = path[0:len(path)-1]

                    travel_time = len(path) # player.squad_travel_time(squad_id, path)
                    if best_path is None or travel_time < best_travel_time:
                        best_path = path
                        best_travel_time = travel_time
        return best_path

# test code
if __name__ == '__main__':
    import SpinJSON, SpinConfig
    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
    region = Region.Region(gamedata, 'test256') # next(gamedata['regions'].iterkeys()))
    pf = SquadPathfinder(region)
    features = [{'base_map_loc':[132,137],'base_type':'quarry'},
                {'base_map_loc':[134,137],'base_type':'hive'}]
    for feature in features:
        pf.occupancy.block_hex(feature['base_map_loc'], 1, feature)

    print pf.squad_find_path_adjacent_to([131,137], [135,137], is_raid = True)
