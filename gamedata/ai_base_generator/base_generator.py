#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# instructions for running this script:
# go to the gamedata/ directory
# PYTHONPATH=../gameserver ./make_ai_base_example.py
# (optional: use > to write output to a file instead of printing to the console)

import SpinJSON # JSON reading/writing library
import SpinConfig
import sys, getopt, random # import some misc. Python libraries
import tr_base_generator_helper as bgh



# load in gamedata
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
ncells =180

class cannotFindCoordinateError(Exception):
    # def __init__(self):
#
    def __str__(self):
        return "Error"




BASE_LAYOUT = { "sectors": [{"cluster": "toc_cluster", "positioning": "near_the_middle" },
                             {"cluster": "supply_cluster", "positioning": "at_the_side", "protection": "barriers_and_turrets" },
                             {"cluster": "barracks_cluster", "positioning": "at_the_side", "protection": "barriers" }] }

if __name__ == '__main__':
    #townhall_level = 1 # this is a parameter that controls the townhall level

    opts, args = getopt.gnu_getopt(sys.argv, '', ['townhall-level=', 'base-difficulty=', 'randomness=', 'num-clusters=', 'num-sectors='])

    baseDifficulty = 1    # assumes difficulty = 1
    randomness = 0        # scale 0-10 with 0 being no randomness
    numclusters = 5
    num_sectors = 4    # 4X4 grid
    for key, val in opts:
        if key == '--townhall-level':
            townhall_level = int(val)
        elif key == '--base-difficulty':
            baseDifficulty = int(val)
        elif key == '--randomness':
            randomness = int(val)
        elif key == '--num-clusters':
            numclusters = int(val)
        elif key == '--num-sectors':
            num_sectors = int(val)
    if '--townhall-level' not in opts:
        townhall_level = int(baseDifficulty/2)
        if townhall_level > 6:
            townhall_level = 6
    unitsInBaseCount = 0
    maxUnitsInBaseCount = gamedata['buildings']["toc"]["provides_space"][townhall_level-1]
    # If you need to load an EXISTING base JSON file, here is how to do it:
    if len(args) > 1:
        filename = args[1]
        # SpinConfig.load reads JSON, and strips out comments
        old_base = SpinConfig.load(filename, stripped = True)
        # at this point, "old_base" will be a Python data structure (actually a dictionary)
        # that contains everything that was in the JSON file you loaded
        print old_base

    usedClusterXYpairs= []
    sceneryList = [name for name,data in gamedata['inert'].iteritems() if (("desert" in data.get('base_climates',[])) and ("home" in data.get('base_types',[])) and data.get('auto_spawn',False))]
    buildingsList = [name for name,data in gamedata['buildings'].iteritems() if (not data.get('developer_only', False))]
    buildingsList.remove("toc")    #shouldn't be able to have more than one
    buildingsList.remove("scanner")
    ### GET RID OF DEVELOPER ONLY buildings
    unitList = gamedata['units'].keys()
    turrets = []
    for building in buildingsList:
           try:

               if gamedata['buildings'][building]["history_category"]=="turrets":
                   #print "gamedata['buildings']['building']['history_category']:",gamedata['buildings'][building]['history_category']
                   turrets.append(building)
           except:
               pass
    randTurret = "mg_tower"
    CLUSTERS = { "toc_cluster": { "buildings": [["toc", [0,0]],    # when place coords randomly add x and y values
 # (add more here)
                                          ] },
            "supply_cluster": {"buildings":[["supply_depot",[-5,0]],
                                            ["supply_yard",[5,0]],
                                            ]},
            "fuel_cluster": {"buildings":[["fuel_depot",[0,-5]],
                                            ["fuel_yard",[0,5]]]},
            "generator_cluster":{"buildings":[["generator",[0,5]],
                                                ["generator",[0,-5]]]},
            "army_training_cluster":{"buildings": [["barracks",[0,8]],
                                                    ["academy",[0,-7]]]},
            "vehicle_training_cluster":{"buildings": [["motor_pool",[8,0]],
                                                    ["maintenance_bay",[-7,0]]]},
            "aircraft_training_cluster":{"buildings": [["airfield",[8,0]],
                                                    ["flight_center",[-7,0]]]},
            "leftovers_cluster":{"buildings": [["transmitter",[9,0]],
                                                    ["warehouse",[0,0]]]},
            "defense_cluster1":{"buildings": [["mg_tower",[-3,0]],
                                                ["mortar_emplacement",[4,0]]],
                                                    "type": "defensive"},
            "defense_cluster2":{"buildings": [["mg_tower",[0,4]],
                                                ["tow_emplacement",[0,-3]]],
                                                "type": "defensive"},
            }
    #print turrets
    if baseDifficulty > 1:
        CLUSTERS["fuel_cluster"]["buildings"].append([turrets[random.randint(0,len(turrets)-1)],[-9,0]])
        CLUSTERS["supply_cluster"]["buildings"].append([turrets[random.randint(0,len(turrets)-1)],[0,8]])
        CLUSTERS["toc_cluster"]["buildings"].append([randTurret, [-15,-15]])
        CLUSTERS["toc_cluster"]["buildings"].append([randTurret, [15,15]])
        CLUSTERS["toc_cluster"]["buildings"].append([randTurret, [15,-15]])
        CLUSTERS["toc_cluster"]["buildings"].append([randTurret, [-15,15]])


    # let's create a fresh AI base JSON structure from scratch
    base = {'scenery': [], 'buildings': [], 'units': [], 'deployment_buffer':{"type":"polygon"}}

    def getXYpair(xmin=40, xmax=160,ymax=160,ymin=40,width=10):
        try:
            x = random.randint(xmin+(width/2),xmax-(width/2))
        except ValueError:
            x = xmin
        try:
            y = random.randint(ymin+(width/2),ymax-(width/2))
        except ValueError:
            y = ymin
        return [x,y]
    # #3X3 grid
#     sectors = [getXYpair(0,60,60,0),getXYpair(60,120,60,0),\
#             getXYpair(120,180,60,0),getXYpair(0,60,120,60),\
#             getXYpair(120,180,120,60),getXYpair(0,60,180,120),\
#             getXYpair(60,120,180,120),getXYpair(120,180,180,120)]
    sectors = []
    for x in range(1,num_sectors):
        xval = x*(ncells/num_sectors)
        if (x<60) or (x>130):
            for y in range(1,num_sectors):
                if (y<60) or (y>130):
                    yval = y*(ncells/num_sectors)
                    sectors.append(getXYpair(xval-randomness,xval+randomness,yval+randomness,yval-randomness))
#     print sectors
    def getGridsize(spec):
        return gamedata['buildings'][spec]["gridsize"]
    def pickSector():
        if len(sectors)>0:
            i = random.randint(0,len(sectors)-1)
            sector = sectors[i]
            usedClusterXYpairs.append(sector)
            sectors.pop(i)    # can't do remove because the value will already be changed
            return sector


    def makeRandomRoad(base):
        i = random.randint(0,1)
        gridsize = 10
        if i==1:
            yCoor = random.randint(0,ncells)

            for x in range(gridsize/2,ncells,gridsize):
                base['scenery'].append({"xy": [x,yCoor],
                                "spec": "roadway_ew"})
        else:
            xCoor = random.randint(0,ncells)
            for y in range(gridsize/2,ncells,gridsize):
                base['scenery'].append({"xy": [xCoor,y],
                                    "spec": "roadway_ns"})

    def insertBuilding(spec,xy, force_level_increase=0, trials=0):
        gridsize = getGridsize(spec)
        #offset = 1
        #print "xy in insert building", xy
        if bgh.is_building_location_valid(xy, gridsize, base):
            if spec in turrets:
                base['buildings'].append({ "xy": xy,
                                        "spec":spec,
                                        "force_level" : baseDifficulty-1})
            else:
                base['buildings'].append({ "xy": xy,
                                            "spec":spec,
                                            "force_level" : townhall_level+force_level_increase
        })

        else:
            if spec == "barrier":
                pass
                #insertBuilding(spec,[xy[0]+offset, xy[1]+offset],force_level_increase)
            else:
                #print "about to recurse..."
                insertBuilding(spec, getXYpair(0,ncells,ncells,0),force_level_increase, trials+1)


    def protectBuilding():
        i = random.randint(0,(len(base['buildings'])-1))
        if (base['buildings'][i]["spec"]!="barrier"):
#             try:
#                 (gamedata['buildings'][base['buildings'][i]["spec"]]["history_category"]!="turrets")
#             except:

                [x,y] = base['buildings'][i]["xy"]
                offset = 3

                halfGridSize= ((getGridsize(base['buildings'][i]["spec"]))[0]/2)
                distanceFromBuilding = halfGridSize + offset
                coords = [x-distanceFromBuilding, y-distanceFromBuilding]
                while coords[0] != (x+distanceFromBuilding):
                    insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
                    coords[0]+=2
                    #print coords
                while coords[1] != y+distanceFromBuilding:
                    insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
                    coords[1]+=2
                    #print coords
                while coords[0] != (x-distanceFromBuilding):
                    insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
                    coords[0]-=2
                    #print coords
                while coords[1] != y-distanceFromBuilding:
                    insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
                    coords[1]-=2
                    #print coords
        else:
            protectBuilding()
    def get_leveled_quantity(qty, level):
        if type(qty) == list:
            return qty[level-1]
        return qty
    def insertTurretWithBarriers(board, turretList):
        i = random.randint(0,(len(turretList)-1))
        [x,y] = pickSector()
        #print "[x,y]",[x,y]
        insertBuilding(turretList[i],[x,y])
        offset = 4
        halfGridSize= ((getGridsize(turretList[i]))[0]/2)
        distanceFromBuilding = halfGridSize + offset
        coords = [x-distanceFromBuilding, y-distanceFromBuilding]
        #print "coords:", coords
        while coords[0] != (x+distanceFromBuilding):

            insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
            coords[0]+=2

        while coords[1] != y+distanceFromBuilding:
            insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
            coords[1]+=2

        while coords[0] != (x-distanceFromBuilding):
            insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
            coords[0]-=2

        while coords[1] != y-distanceFromBuilding:
            insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
            coords[1]-=2


    def insertCluster(cluster, xy):
        if numclusters >0:
            if bgh.is_building_location_valid(xy, getClusterGridSize(cluster,xy), base):
                for building in CLUSTERS[cluster]["buildings"]:
                    insertBuilding(building[0],[xy[0]+(building[1][0]),xy[1]+(building[1][1])])
                if random.randint(0,1):
                    protectCluster(CLUSTERS[cluster],xy)
                numclusters -1
            elif len(sectors)>0:
                insertCluster(cluster, pickSector())

    def protect(thingprotectingPos, maxPosList, offset=2):
        xmax = maxPosList[1]+offset
        xmin = maxPosList[0]-offset
        ymax = maxPosList[2]+offset
        ymin = maxPosList[3]-offset
        # halfGridSize =(gridsize[0]/2)# ,(gridsize[1]/2)]
        # distanceFromBuilding = halfGridSize + offset# ,halfGridSize[1] + offset]
        coords = [maxPosList[0]-offset, maxPosList[3]-offset]
#         print "called protect"
        while coords[0] <= (xmax):

            insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
            coords[0]+=2
#             print "coords:",coords
        while coords[1] <= ymax:
            insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
            coords[1]+=2

        while coords[0] >= (xmin):
            insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
            coords[0]-=2
#             print "coords:",coords
        while coords[1] >= ymin:
            insertBuilding("barrier",(coords[0],coords[1]),baseDifficulty-townhall_level)
            coords[1]-=2
#             print "coords:",coords
    def getClusterGridSize(cluster,xy):
        coordsWithGridsize= []
        for building in CLUSTERS[cluster]['buildings']:
            #print "looping in protectCluster"
            buildGridSize = getGridsize(building[0])
            buildRelCoords = building[1]
#             print "xy:",xy
#             print "buildGridSize:",buildGridSize
#             print "buildRelCoords:",buildRelCoords
            coordsWithGridsize.append((xy[0]+buildRelCoords[0]+(buildGridSize[0]/2), xy[1]+buildRelCoords[1]+(buildGridSize[1]/2)))
            coordsWithGridsize.append((xy[0]+buildRelCoords[0]-(buildGridSize[0]/2), xy[1]+buildRelCoords[1]-(buildGridSize[1]/2)))

        Xlist = sorted(coordsWithGridsize, key = lambda x:x[0],reverse =True)
#         print "Xlist:",Xlist
        bigX = Xlist[0][0]
        littleX = Xlist[-1][0]
        Ylist = sorted(coordsWithGridsize, key = lambda x:x[1],reverse =True)
        bigY = Ylist[0][1]
        littleY = Ylist[-1][1]
        gridsize = [bigX-littleX,bigY-littleY]
#         print "bigX:",bigX
#         print "littleX:",littleX
#         print "bigY:",bigY
#         print "littleY", littleY
#         print "gridsize:",gridsize
        return gridsize


    def applySecTeams(secteam_chance = 1.0,level_range = [1,1]):
        TEAM_TYPES = {'supply_yard':'harvester',
                      'supply_depot':'storage',
                      'fuel_yard':'harvester',
                      'fuel_depot':'storage',
                      'generator':'generator',
                      'mg_tower':'turret',
                      'mortar_emplacement':'turret',
                      'tow_emplacement':'turret',

                      'tesla_coil':'turret',
                      'energy_plant':'energy_plant',
                      'water_storage':'storage','iron_storage':'storage',
                      'water_harvester':'harvester','iron_harvester':'harvester'
                      }

        for obj in base['buildings']:
            team_type = TEAM_TYPES.get(obj['spec'], None)
            if team_type:
                if 'equipment' not in obj: obj['equipment'] = {}
                if 'defense' not in obj['equipment']: obj['equipment']['defense'] = []

                # clear out existing secteams and anti_missiles
                to_remove = []
                for entry in obj['equipment']['defense']:
                    if ('secteam' in entry) or ('anti_missile' in entry):
                        to_remove.append(entry)
                for entry in to_remove: obj['equipment']['defense'].remove(entry)

                equip_list = []

                if random.random() < secteam_chance:
                    if obj['spec'] == 'tesla_coil':
                        equip_list.append('tesla_anti_missile_L5')
                        if 0:
                            equip_list.append('ai_warbird_secteam_L2')
                    else:
                        if 1:
                            level = int(level_range[0] + int((level_range[1]-level_range[0]+1)*random.random()))
                            specname = '%s_secteam_L%d' % (team_type, level)
                            equip_list.append(specname)

                    for specname in equip_list:
                        if specname not in gamedata['items']:
                            sys.stderr.write('bad specname '+specname+'\n')
                            sys.exit(1)
                        obj['equipment']['defense'].append(specname)

                # clean up empty equip lists
                if len(obj['equipment']['defense']) < 1: del obj['equipment']['defense']
                if len(obj['equipment']) < 1: del obj['equipment']
    def protectCluster(cluster,xy):
        coordsWithGridsize= []
        for building in cluster['buildings']:
            #print "looping in protectCluster"
            buildGridSize = getGridsize(building[0])
            buildRelCoords = building[1]
            #print "xy:",xy
            coordsWithGridsize.append((xy[0]+buildRelCoords[0]+(buildGridSize[0]/2), xy[1]+buildRelCoords[1]+(buildGridSize[1]/2)))
            coordsWithGridsize.append((xy[0]+buildRelCoords[0]-(buildGridSize[0]/2), xy[1]+buildRelCoords[1]-(buildGridSize[1]/2)))

        Xlist = sorted(coordsWithGridsize, key = lambda x:x[0],reverse =True)
#         print "Xlist:",Xlist
        bigX = Xlist[0][0]
        littleX = Xlist[-1][0]
        Ylist = sorted(coordsWithGridsize, key = lambda x:x[1],reverse =True)
        bigY = Ylist[0][1]
        littleY = Ylist[-1][1]
#         print "bigX:",bigX
#         print "littleX:",littleX
#         print "bigY:",bigY
#         print "littleY", littleY
#         print "gridsize:",gridsize

        protect(xy,[littleX,bigX,bigY,littleY])


    def guaranteeGeneratorStrength():
        powerplants = []
        for building in base["buildings"]:
                if building["spec"]=="generator":
                    #print building
                    powerplants.append(building)
        #print "powerplants:",powerplants
        if len(powerplants) > 0:
            # level up powerplants to meet power req
            while True:
                power_produced = 0
                power_consumed = 0
                for obj in base['buildings']:
                    if obj['spec'] in gamedata['buildings']:
                        spec = gamedata['buildings'][obj['spec']]
                        if 'provides_power' in spec:
                            power_produced += get_leveled_quantity(spec['provides_power'], obj['force_level'])
                        if 'consumes_power' in spec:
                            power_consumed += get_leveled_quantity(spec['consumes_power'], obj['force_level'])
                if power_consumed <= power_produced: break
                for obj in powerplants:
                    #print "obj['spec']:",obj['spec']
                    if obj['force_level'] >= len(gamedata['buildings'][obj['spec']]['build_time']):
                        # can't go up any more
                        pass
                    else:
                        obj['force_level'] += 1


#     let's add some scenery objects
    #-------------------------------------------
    for item in range(5):
        randomSceneryIndex = random.randint(0, len(sceneryList)-1)
        scenerySpec = sceneryList[randomSceneryIndex]
        base['scenery'].append({"xy": getXYpair(),
                                "spec": scenerySpec})

    # let's add some buildings
    #-------------------------------------------
    tocXY = getXYpair(80,110,110,80)
    insertCluster("toc_cluster",tocXY)
    insertCluster("generator_cluster",pickSector())
    insertCluster("supply_cluster",pickSector())
    insertCluster("fuel_cluster",pickSector())

#     insertCluster("army_training_cluster", pickSector())
#     insertCluster("vehicle_training_cluster", pickSector())
#     insertCluster("leftovers_cluster", pickSector())
    while (len(sectors)>5-baseDifficulty) and (len(sectors)>0):
#         print "sectors:",sectors
        xy = pickSector()
#         print "xy in while loop:", xy
        clusterkeys = CLUSTERS.keys()
        clusterkeys.remove("toc_cluster")
        if baseDifficulty < 3:
            clusterkeys.remove("defense_cluster1")
            clusterkeys.remove("defense_cluster2")
        index = random.randint(0, len(clusterkeys)-1)    # the -1 prevents indexing outside the list
        clusterSpec = clusterkeys[index]
        cluster = CLUSTERS[clusterSpec]
        insertCluster(clusterSpec,xy)



    # let's add some units
    #-------------------------------------------
        # check out the hives document to get some more info

    for unit in range((townhall_level*9)+10):
        randomUnitIndex = random.randint(0, len(unitList)-1)
        unitSpec = unitList[randomUnitIndex]
        [c,d] = getXYpair()
        TrueFalse = [True,False]    ##### NEED TO ADD MAX VALUE
        if unitSpec== "stinger_gunner": unitForce=8
        else: unitForce=townhall_level
        unitsInBaseCount += gamedata['units'][unitSpec]["consumes_space"]
        if unitsInBaseCount <= maxUnitsInBaseCount:
            base['units'].append({"xy": [c,d],
                                  "spec": unitSpec,
                                  # note: please use "force_level" rather than "level" so that it overrides the server's auto-leveling code
                                  "force_level": unitForce,
                                  "patrol":1,
                                  "orders": [{
                                      "dest":[[c+1,d-12],[c-12,d+1]][random.randint(0,1)],
                                      "state":random.randint(1,6),
                                      "aggressive": TrueFalse[random.randint(0,1)]
                                  },{
                                      "dest":[[c-1,d+12],[c+12,d-1]][random.randint(0,1)],
                                      "state":6,
                                      "patrol_origin": 1,
                                      "aggressive": TrueFalse[random.randint(0,1)]
                                  },{
                                      "dest":[[c+3,d],[c,d+3]][random.randint(0,1)],
                                      "state":6,
                                      "aggressive": TrueFalse[random.randint(0,1)]
                                  }]
                                  })
        else:
            unitsInBaseCount -= gamedata['units'][unitSpec]["consumes_space"]
            break


    [a,b] = getXYpair(xmin=50, xmax=150)
    bgh.makeRiflemenCluster(base,a,b)
    #bgh.makeRandomRoad(base)
#     for k in range(baseDifficulty*2-3):
#         protectBuilding()
    #insertTurretWithBarriers(base, turrets)
    guaranteeGeneratorStrength()
    if baseDifficulty > 4:
        applySecTeams(secteam_chance = .5,level_range = [1,baseDifficulty/2])
    [f,g] = getXYpair(0,180,180,0)
    while not((f <30) or (f>140)or (g <30) or (g>140)):
        [f,g] = getXYpair(0,180,180,0)
    base['deployment_buffer']["vertices"]=[[f,g],[f+20,g],[f+20,g+40],[f,g+40]]
    # convert the Python data structure into a string for final output
    output_json = SpinJSON.dumps(base, pretty = True)[1:-1]+'\n' # note: get rid of surrounding {}
#     print "worked!"
    print output_json,


    # in case you want to write the output to a particular file, here is how to do it:
#    atom = AtomicFileWrite.AtomicFileWrite(output_filename, 'w')
#    atom.fd.write(output_json)
#    atom.complete()
