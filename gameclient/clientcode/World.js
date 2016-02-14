goog.provide('World');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('AStar');
goog.require('Base');
goog.require('Citizens');
goog.require('CombatEngine');
goog.require('GameTypes');
goog.require('GameObjectCollection');
goog.require('WallManager');

/** Encapsulates the renderable/simulatable "world"
    XXXXXX remove non-base version and replace with a "blank" world type
    @constructor
    @param {Base.Base|null} base
    @param {GameObjectCollection.GameObjectCollection|null} objects
*/
World.World = function(base, objects) {
    /** @type {Base.Base|null} */
    this.base = base;

    /** @type {GameObjectCollection.GameObjectCollection|null} */
    this.objects = objects;

    /** @type {?AStar.AStarRectMap} current A* map for playfield movement queries */
    this.astar_map = (base ? new AStar.AStarRectMap(base.ncells(), null, ('allow_diagonal_passage' in gamedata['map'] ? gamedata['map']['allow_diagonal_passage'] : true)) : null);

    /** @type {?AStar.CachedAStarContext} current A* context for playfield movement queries */
    this.astar_context = (base ? new AStar.CachedAStarContext(this.astar_map,
                                                              {heuristic_name:gamedata['client']['astar_heuristic'],
                                                               iter_limit:gamedata['client']['astar_iter_limit'][is_ai_user_id_range(base.base_landlord_id) ? 'pve':'pvp'],
                                                               use_connectivity:(!!gamedata['client']['astar_use_connectivity'])}) : null);

    // note: astar_map is used for A* pathing and building placement queries ("is this cell blocked?")
    // combat-engine targeting queries ("list all objects near this point") are done using MapAccelerator
    this.voxel_map_accel = new VoxelMapAccelerator.VoxelMapAccelerator((base ? base.ncells() : [0,0]), (base ? gamedata['client']['map_accel_chunk'] : 1));
    this.team_map_accel = new TeamMapAccelerator.TeamMapAccelerator();

    this.MAP_DEBUG = 0;

    /** @type {Object<string, number>} stats tracking for map queries */
    this.map_queries_by_tag = {'ticks': 0};

    /** @type {WallManager.WallManager|null} */
    this.wall_mgr = null;
    if(base) { // note: gamedata is not available on first load
        var wall_spec = gamedata['buildings']['barrier'];
        if(wall_spec && (wall_spec['collide_as_wall'] || player.get_any_abtest_value('enable_wall_manager', gamedata['client']['enable_wall_manager']))) {
            this.wall_mgr = new WallManager.WallManager(base.ncells(), wall_spec);
        }
    }

    /** @type {CombatEngine.CombatEngine|null} */
    this.combat_engine = (base ? new CombatEngine.CombatEngine() : null);

    /** @type {Citizens.Context|null} */
    this.citizens = null; // army units walking around the base
    this.citizens_dirty = false;
};

World.World.prototype.dispose = function() {
    if(this.citizens) {
        this.citizens.dispose();
        this.citizens = null;
    }
};

World.World.prototype.lazy_update_citizens = function() { this.citizens_dirty = true; };
World.World.prototype.do_update_citizens = function(player) {
    if(this.citizens) {
        var data_list;
        if(this.citizens_dirty) { // need to tell Citizens about changes to army contents
            this.citizens_dirty = false;
            data_list = [];
            goog.object.forEach(player.my_army, function(obj) {
                if((obj['squad_id']||0) == SQUAD_IDS.BASE_DEFENDERS) {
                    data_list.push(new Citizens.UnitData(obj['obj_id'], obj['spec'], obj['level']||1, ('hp_ratio' in obj ? obj['hp_ratio'] : 1)));
                }
            }, this);
        } else {
            data_list = null; // no update to army contents
        }
        this.citizens.update(data_list);
    }
};

World.World.prototype.map_query_stats = function() {
    console.log("MAP QUERIES:");
    for(var k in this.map_queries_by_tag) {
        if(k == 'ticks') { continue; }
        var msec = 1000.0*this.map_queries_by_tag[k]/(1.0*this.map_queries_by_tag['ticks']);
        if(msec >= 0.1) {
            console.log(k + ' ' + msec.toFixed(1) + 'ms per tick');
        }
    }
};
