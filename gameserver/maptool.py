#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# tool for managing bases/quarries/hives on the Regional Map

import SpinSyncChatClient
import SpinNoSQL
import SpinUserDB
import SpinConfig
import SpinJSON
import SpinNoSQLId
import SpinNoSQLLockManager
import SpinSingletonProcess
import ControlAPI
import AIBaseRandomizer
from Region import Region
from AStar import SquadPathfinder
import Raid
import Sobol
import sys, getopt, time, random, copy, math

def do_CONTROLAPI(args): return ControlAPI.CONTROLAPI(args, spin_user = 'maptool', verbose = False)

time_now = int(time.time())
event_time_override = None
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
gamedata['server'] = SpinConfig.load_fd(open(SpinConfig.gamedata_component_filename('server.json')))

# XXX make db_client a global
nosql_client = None
nosql_id_generator = SpinNoSQLId.Generator()
chat_client = None

throttle = 0.1
verbose = True

sobol_gen = None


# libraries need to be set to read in CCW order
MODERN_SPRITE_ROTATIONS = { 'curve':['roadway_curve4','roadway_curve3','roadway_curve2','roadway_curve1'],
                            'straight_road': ['roadway_ns','roadway_ew','roadway_ns','roadway_ew'],
                            'faded':['roadway_ns_ll','roadway_ew_lr','roadway_ns_ur','roadway_ew_ul'],
                            '3way':['roadway_t1','roadway_t3','roadway_t2','roadway_t4'],
                            'dirt':['dirt_road_ns1','dirt_road_ew1','dirt_road_ns1','dirt_road_ew1'] }
SPRITE_ROTATIONS = {
    "mf": {},
    "mf2": { "curve": ["city_ruins_roadway_curve1","city_ruins_roadway_curve4","city_ruins_roadway_curve2","city_ruins_roadway_curve3"],
             "straight_road": ['city_ruins_roadway_ns',"city_ruins_roadway_ew",'city_ruins_roadway_ns','city_ruins_roadway_ew'],
             "bump": ['city_ruins_roadway_speed_bump1','city_ruins_roadway_speed_bump2',
                      'city_ruins_roadway_speed_bump1','city_ruins_roadway_speed_bump2'],
             "dirt":['dirt_road_ns1','dirt_road_ew1','dirt_road_ns1','dirt_road_ew1'] },
    "tr": MODERN_SPRITE_ROTATIONS,
    "dv": MODERN_SPRITE_ROTATIONS,
    "bfm": MODERN_SPRITE_ROTATIONS,
}

# mapping from the first two elements of the rotation matrix to the amount by which indices shift in above table
SPRITE_ROTATION_SHIFT = { (0,1): 1, (0,-1): 3, (1,0): 0, (-1,0): 2 }

# return proper rotated version of a sprite according to the xform
def rotate_scenery_sprite(xform, scene):
    table = SPRITE_ROTATIONS.get(SpinConfig.game(), MODERN_SPRITE_ROTATIONS)
    for name, sprites in table.iteritems():
        if scene in sprites:
            rotshift = SPRITE_ROTATION_SHIFT[(xform[0],xform[1])]
            return sprites[(sprites.index(scene)+rotshift) % 4]
    return scene


def do_throttle():
    if throttle > 0:
        time.sleep(throttle)
    # also use this opportunity to update client time
    time_now = int(time.time())
    if nosql_client: nosql_client.set_time(time_now)

def random_letter():
    return chr(ord('A') + int(26*random.random()))

def feature_expired(feature):
    base_expire_time = feature.get('base_expire_time', -1)
    return (base_expire_time > 0 and time_now >= base_expire_time)

def pretty_feature(feature):
    base_id = feature.get('base_id', 'unknown')
    base_type = feature.get('base_type', 'unknown')
    base_ui_name = feature.get('base_ui_name', 'unknown')
    try:
        base_ui_name = base_ui_name.encode('ascii')
    except UnicodeEncodeError:
        base_ui_name = '<UNICODE>'
    map_loc = feature.get('base_map_loc', None)
    if not map_loc: map_loc = [-1,-1]
    base_landlord_id = str(feature.get('base_landlord_id', 'unknown'))
    base_expire_time = feature.get('base_expire_time', -1)
    exp_hours = (base_expire_time - time_now)/3600.0 if base_expire_time > 0 else -1
    expired = 'EXPIRED' if feature_expired(feature) else ''
    return '%s%5s %s %-14s [%3d,%3d] (owner %6s) exp in %5.1f hrs' % (expired, base_id, base_type, base_ui_name, map_loc[0], map_loc[1], base_landlord_id, exp_hours)

def get_leveled_quantity(qty, level):
    if type(qty) == list:
        return qty[level-1]
    return qty


# use chatserver CONTROLAPI mechanism to tell running gameservers about map feature changes
def broadcast_map_update(region_id, base_id, data, originator):
    assert region_id and base_id

    if not chat_client: return

    if data is None:
        data = {'base_id':base_id, 'DELETED':1}
    elif 'base_id' not in data:
        data['base_id'] = base_id

    chat_client.chat_send({'channel':'CONTROL',
                           'sender':{'secret':SpinConfig.config['proxy_api_secret'],
                                     'server':'maptool',
                                     'method':'broadcast_map_update',
                                     'args': { 'region_id': region_id, 'base_id': base_id, 'data': data,
                                               'server': 'maptool', 'originator': originator },
                                     },
                           'text':''}, log = False)

ENVIRONMENT_OWNER_ID = -1 # must match server.py's EnvironmentOwner.user_id

def nosql_write_all_objects(region_id, base_id, owner_id, objlist):
    batch_mobile = []
    batch_fixed = []

    for obj in objlist:
        spec = gamedata['buildings'].get(obj['spec'], gamedata['units'].get(obj['spec'], gamedata['inert'].get(obj['spec'], None)))
        assert spec

        props = {'obj_id':obj['obj_id'],
                 'owner_id':ENVIRONMENT_OWNER_ID if obj.get('owner',owner_id) == 'environment' else owner_id,
                 'base_id':base_id,
                 'kind': spec['kind'],
                 'spec': obj['spec']}

        if obj.get('level',1) != 1: props['level'] = obj['level']
        for FIELD in ('xy','stack','orders','patrol','equipment','produce_start_time','produce_rate','contents'):
            if FIELD in obj: props[FIELD] = obj[FIELD]

        if spec['kind'] == 'mobile':
            batch_mobile.append(props)
        else:
            batch_fixed.append(props)

    nosql_client._save_objects(region_id, 'fixed', batch_fixed)
    nosql_client._save_objects(region_id, 'mobile', batch_mobile)

def nosql_read_all_objects(region_id, base_id, base_landlord_id):
    ret = []
    for state in nosql_client.get_mobile_objects_by_base(region_id, base_id) + nosql_client.get_fixed_objects_by_base(region_id, base_id):
        props = { 'obj_id': state['obj_id'],
                  'xy': state['xy'],
                  'spec': state['spec']
                  }
        for FIELD in ('level', 'hp_ratio', 'tag', 'metadata', 'creation_time', 'repair_finish_time', 'disarmed',
                      'upgrade_total_time', 'upgrade_start_time', 'upgrade_done_time', 'squad_id',
                      'orders','patrol','equipment','produce_start_time','produce_rate','contents'):
            if FIELD in state:
                props[FIELD] = state[FIELD]

        if state['owner_id'] == ENVIRONMENT_OWNER_ID:
            props['owner'] = 'environment'
        else:
            # no explicit owner
            if state['owner_id'] != base_landlord_id:
                print "found object owned by", state['owner_id'], "in base belonging to", base_landlord_id

        ret.append(props)
    return ret

def get_existing_map_by_type(db, region_id, base_type):
    return dict([(x['base_id'], x) for x in nosql_client.get_map_features_by_type(region_id, base_type)])
def get_existing_map_by_type_spatially(db, region_id, base_type):
    return dict([(tuple(x['base_map_loc']), x) for x in nosql_client.get_map_features_by_type(region_id, base_type)])

def get_existing_map_by_base_id(db, region_id, base_id):
    x = nosql_client.get_map_feature_by_base_id(region_id, base_id)
    if not x: return {}
    return {x['base_id']:x}
def get_existing_map_by_landlord_and_type(db, region_id, user_id, base_type):
    return dict([(x['base_id'], x) for x in nosql_client.get_map_features_by_landlord_and_type(region_id, user_id, base_type)])
def get_existing_map_by_loc(db, region_id, loc):
    return dict([(x['base_id'], x) for x in nosql_client.get_map_features_by_loc(region_id, loc)])

def get_population(db, region_id, base_type):
    base_types = [base_type,] if base_type != 'ALL' else ['home','quarry','hive','squad']
    print '%-16s ' % region_id + ' '.join(['%s: %-4d' % (btype, nosql_client.count_map_features_by_type(region_id, btype)) for btype in base_types])

def print_all(db, lock_manager, region_id, base_type, dry_run = True):
    map_cache = get_existing_map_by_type(db, region_id, base_type)
    for base_id, feature in sorted(map_cache.items(), key = lambda id_f: id_f[1]['base_id']):
        print pretty_feature(feature)

def clear_all(db, lock_manager, region_id, base_type, dry_run = True):
    map_cache = get_existing_map_by_type(db, region_id, base_type)
    for base_id, feature in map_cache.iteritems():
        clear_base(db, lock_manager, region_id, base_id, dry_run=dry_run)

def clear_base(db, lock_manager, region_id, base_id, dry_run = True, already_locked = False):
    print 'CLEAR', base_id
    if not dry_run:
        if (not already_locked) and (not lock_manager.acquire(region_id, base_id)):
            print '(locked, skipping)'
            return
        nosql_client.drop_all_objects_by_base(region_id, base_id)
        nosql_client.drop_map_feature(region_id, base_id)
        lock_manager.forget(region_id, base_id)

def get_random_rotation(ncells):
    r = random.random()
    if r < 0.25: #no rotation
        xform = [1,0,0,1,0,0]
    elif r < 0.50: # 90 degrees rotation
        xform = [0,1,-1,0,0,ncells[0]]
    elif r < 0.75: # 180 degree rotation
        xform = [-1,0,0,-1,ncells[0],ncells[1]]
    else: # 270 degree rotation
        xform = [0,-1,1,0,ncells[1],0]
    return xform

def transform(m, xy):
    return [int(m[0]*xy[0]+m[1]*xy[1]+m[4]),
            int(m[2]*xy[0]+m[3]*xy[1]+m[5])]

def transform_deployment_buffer(m, buf):
    if type(buf) is dict and buf['type'] == 'polygon':
        newbuf = copy.deepcopy(buf)
        newbuf['vertices'] = [transform(m, v) for v in buf['vertices']]
    else:
        newbuf = buf
    return newbuf

def auto_level_hive_objects(objlist, owner_level, owner_tech, xform = [1,0,0,1,0,0]):
    ret = []
    powerplants = []
    for src in objlist:
        spec_name = src['spec']
        spec = gamedata['units'][spec_name] if spec_name in gamedata['units'] else gamedata['buildings'][spec_name]

        dst = {'obj_id': nosql_id_generator.generate(), 'spec':spec['name']}
        if 'xy' in src: dst['xy'] = transform(xform, src['xy'])
        if 'stack' in src: dst['stack'] = src['stack'] # for raids only
        if 'orders' in src:
            dst['orders'] = []
            for order in src['orders']:
                if 'dest' in order and order['dest']:
                    order = copy.copy(order)
                    order['dest'] = transform(xform, order['dest'])
                dst['orders'].append(order)
        if 'patrol' in src: dst['patrol'] = src['patrol']
        if 'equipment' in src: dst['equipment'] = copy.deepcopy(src['equipment'])

        if 'production_capacity' in spec:
            dst['produce_start_time'] = 1
            dst['produce_rate'] = 999999

        if 'provides_power' in spec:
            powerplants.append(dst)

        level = src.get('force_level', -1)
        if level <= 0:
            # auto-compute level by table
            if 'ai_bases' not in gamedata:
                gamedata['ai_bases'] = SpinConfig.load(SpinConfig.gamedata_component_filename("ai_bases_compiled.json"))

            if spec['name'] in gamedata['ai_bases']['auto_level']:
                ls = gamedata['ai_bases']['auto_level'][spec['name']]
                index = min(max(owner_level-1, 0), len(ls)-1)
                level = ls[index]
            else:
                level = 1

            if spec['kind'] == 'mobile':
                level = max(level, owner_tech.get(spec['level_determined_by_tech'],1))

        dst['level'] = level
        ret.append(dst)

    if len(powerplants) > 0:
        # level up powerplants to meet power req
        while True:
            power_produced = 0
            power_consumed = 0
            for obj in ret:
                if obj['spec'] in gamedata['buildings']:
                    spec = gamedata['buildings'][obj['spec']]
                    if 'provides_power' in spec:
                        power_produced += get_leveled_quantity(spec['provides_power'], obj['level'])
                    if 'consumes_power' in spec:
                        power_consumed += get_leveled_quantity(spec['consumes_power'], obj['level'])
            if power_consumed <= power_produced: break
            incr = False
            for obj in powerplants:
                if obj['level'] >= len(gamedata['buildings'][obj['spec']]['build_time']):
                    # can't go up any more
                    pass
                else:
                    incr = True
                    obj['level'] += 1
            if not incr: break
    return ret


def extend_all_quarries(db, lock_manager, region_id, dry_run = True):
    map_cache = get_existing_map_by_type(db, region_id, 'quarry')
    quarries = SpinConfig.load(SpinConfig.gamedata_component_filename("quarries_compiled.json"))
    for base_id, feature in map_cache.iteritems():
        exp_time = feature.get('base_expire_time', -1)
        if exp_time < 0 or (exp_time >= time_now + quarries['override_duration'] - 3600):
            print 'GOOD, SKIPPING', pretty_feature(feature)
            continue
        print 'EXTENDING', pretty_feature(feature)
        if not dry_run:
            if not lock_manager.acquire(region_id, base_id):
                print '(locked, skipping)'
                continue

            base_data = feature
            if base_data.get('base_expire_time', -1) > 0:
                base_data['base_expire_time'] = time_now + quarries['override_duration']
                base_data['base_generation'] = base_data.get('base_generation',0)+1

            nosql_client.update_map_feature(region_id, base_id, {'base_expire_time':base_data.get('base_expire_time',-1)})
            lock_manager.release(region_id, base_id, base_generation = base_data.get('base_generation',-1))


valentina_mail_serial = 0
def make_valentina_mail(user_id, subject='', body='', days_to_claim=3, attachments=[]):
    global valentina_mail_serial
    valentina_mail_serial += 1
    message = {'type':'mail',
               'expire_time': (time_now + days_to_claim*24*60*60) if (days_to_claim >= 0) else -1,
               'from_name': 'Valentina', 'to': [user_id],
               'subject': subject, 'body': body }
    if attachments:
        message['attachments'] = attachments
    return message

def refund_units(db, region_id, feature, objlist, user_id, days_to_claim = 7, ui_name = '', reason = 'expired', dry_run = True):
    if len(objlist) < 1: return # nothing to return
    if user_id < 1100: return # AI user
    if feature['base_type'] != 'squad':
        raise Exception('cannot refund units from a feature that is not a squad')
    squad_id = int(feature['base_id'].split('_')[1])
    cargo = feature.get('cargo',None)
    cargo_source = feature.get('cargo_source',None)

    # two paths: first choice is to use CONTROLAPI CustomerSupport to return the squad intact
    # if that fails (e.g. if server is not running), then break the squad and send the units by mail

    try:
        if verbose: print 'DOCK', pretty_feature(feature), 'to', user_id, repr(objlist), 'cargo', cargo
        if not dry_run:
            do_CONTROLAPI({'user_id': user_id, 'method': 'squad_dock_units',
                           'units': SpinJSON.dumps(objlist),
                           'cargo': SpinJSON.dumps(cargo),
                           'cargo_source': SpinJSON.dumps(cargo_source),
                           'squad_id': squad_id})
        del objlist[:] # clear them out
        return # done!
    except ControlAPI.ControlAPIException: pass
    except ControlAPI.ControlAPIGameException: pass

    # fallback path: send by mail

    units = {}
    for obj_data in objlist:
        if obj_data['spec'] not in gamedata['units']: continue
        spec = gamedata['units'][obj_data['spec']]
        units[spec['name']] = 1 + units.get(spec['name'],0)

    if (not units) and (not cargo): return # nothing to return

    attachments = []
    for name, qty in units.iteritems():
        item_name = 'packaged_'+name
        item_spec = gamedata['items'][item_name]
        while qty > 0:
            stack = min(qty, item_spec.get('max_stack',1))
            at = {'spec':item_name}
            if stack > 1: at['stack'] = stack
            attachments.append(at)
            qty -= stack
    if cargo:
        for res, amount in cargo.iteritems():
            attachments.append({'spec': res, 'stack': amount})

    if attachments and verbose: print 'REFUND (mail)', pretty_feature(feature), 'to', user_id, repr(attachments)

    if reason == 'expired':
        message_subject = 'Quarry '+ui_name+' Depleted'
        message_body = 'Quarry '+ui_name+' has reached depletion.'
    elif reason == 'abandoned':
        message_subject = 'Quarry '+ui_name+' Evacuated'
        message_body = 'Quarry '+ui_name+' has been evacuated.'
    elif reason == 'squad':
        sq = gamedata['strings']['squads']['squad']
        message_subject = sq+' '+ui_name+' Returned'
        message_body = sq+' '+ui_name+' has returned to base.'
    else:
        raise Exception('unhandled refund reason: '+reason)

    if attachments:
        message_body += '\n\nOur forces have returned. We should re-deploy them soon, before they expire.'

    message = make_valentina_mail(user_id, days_to_claim = days_to_claim,
                                  subject = message_subject,
                                  body = message_body, attachments = attachments)

    if not dry_run:
        nosql_client.msg_send([message])

def expire_all_quarries(db, lock_manager, region_id, dry_run = True):
    map_cache = get_existing_map_by_type(db, region_id, 'quarry')
    for base_id, feature in map_cache.iteritems():
        expire_quarry(db, lock_manager, region_id, base_id, feature, dry_run = dry_run)

def expire_quarry(db, lock_manager, region_id, base_id, feature, dry_run = True):
    print 'EXPIRING', pretty_feature(feature)

    if not lock_manager.acquire(region_id, base_id):
        print '(locked, skipping)'
        return

    # should not be needed - can't put units into a quarry base (only a guard squad)
    # objlist = nosql_read_all_objects(region_id, base_id, feature.get('base_landlord_id',-1)) # actually only needs mobile objects
    # refund_units(db, region_id, feature, objlist, feature.get('base_landlord_id',-1), ui_name = feature.get('base_ui_name','unknown'), days_to_claim = 7, reason = 'expired', dry_run = dry_run)

    if not dry_run:
        nosql_client.drop_all_objects_by_base(region_id, base_id)
        nosql_client.drop_map_feature(region_id, base_id)
        lock_manager.forget(region_id, base_id)

def abandon_quarry(db, lock_manager, region_id, base_id, days_to_claim_units = 3, feature = None, dry_run = True):
    if not feature:
        map_cache = get_existing_map_by_base_id(db, region_id, base_id)
        if base_id not in map_cache:
            print 'quarry not found'
            return False
        feature = map_cache[base_id]

    if not lock_manager.acquire(region_id, base_id):
        print base_id, '(quarry is locked, skipping)'
        return False

    # recall defending squad
    guards = get_existing_map_by_loc(db, region_id, feature['base_map_loc'])
    for guard_id, guard in guards.iteritems():
        if guard['base_type'] != 'squad': continue
        if not recall_squad(db, lock_manager, region_id, guard.get('base_landlord_id',-1), guard_id, feature = guard, days_to_claim_units = days_to_claim_units, dry_run = dry_run):
            print '(unable to recall quarry guards, skipping)'
            return False

    base_objects = nosql_read_all_objects(region_id, base_id, feature.get('base_landlord_id',-1))
    base_data = feature # for NoSQL regions, the entire base data block is in map_cache

    owner_id = feature.get('base_landlord_id', -1)

    # reset ownership
    feature['base_landlord_id'] = base_data['base_landlord_id'] = base_data.get('base_creator_id', gamedata['territory']['default_quarry_landlord_id'])

    feature['base_last_conquer_time'] = base_data['base_last_conquer_time'] = time_now
    feature['base_last_landlord_id'] = base_data['base_last_landlord_id'] = owner_id

    # should not be needed - can't put units into a quarry base (only a guard squad)
    # refund_units(db, region_id, feature, base_objects, owner_id, ui_name = feature.get('base_ui_name','unknown'), days_to_claim = days_to_claim_units, reason = 'abandoned', dry_run = dry_run)
    # if refund_units() is used, need to individual drop the returned ones

    if not dry_run:
        new_props = {'base_landlord_id':base_data['base_landlord_id'],
                     'base_last_conquer_time':base_data['base_last_conquer_time'],
                     'base_last_landlord_id':base_data['base_last_landlord_id']}
        # update objects with new owner
        for obj in base_objects:
            nosql_client._update_object(region_id,
                                        'mobile' if (obj['spec'] in gamedata['units']) else 'fixed',
                                        {'obj_id':obj['obj_id'],'owner_id':feature['base_landlord_id']}, True)
            #nosql_write_all_objects(region_id, base_id, feature['base_landlord_id'], base_objects)
        nosql_client.update_map_feature(region_id, base_id, new_props)
    lock_manager.release(region_id, base_id, base_generation = base_data.get('base_generation',-1))
    print 'ABANDONED', pretty_feature(base_data)
    return True

def spawn_all_quarries(db, lock_manager, region_id, force_rotation = False, dry_run = True):
    region_data = gamedata['regions'][region_id]
    if (not region_data.get('spawn_quarries',True)): return

    quarries = SpinConfig.load(SpinConfig.gamedata_component_filename("quarries_compiled.json"))

    global_qty_scale = 1.0
    if 'region_pop' in quarries:
        global_qty_scale *= quarries['region_pop'].get(region_id,1.0)
    if global_qty_scale <= 0: return

    player_pop = None # player population, used for scaling the spawn
    player_pop_factor = None # fullness of player population relative to pop_soft_cap, used for scaling the spawn

    map_cache = get_existing_map_by_type(db, region_id, 'quarry')
    name_idx = 0

    spawn_list = quarries.get('spawn_for_'+region_id, quarries['spawn'])
    for spawn_data in spawn_list:
        if not spawn_data.get('active',1): continue
        template = quarries['templates'][spawn_data['template']]

        if 'num_by_region' in spawn_data and region_id in spawn_data['num_by_region']:
            base_qty = spawn_data['num_by_region'][region_id]
        else:
            base_qty = spawn_data['num']
        if base_qty <= 0: continue

        # get list of start,end spawn times
        if 'spawn_times' in spawn_data:
            spawn_times = spawn_data['spawn_times']
        else:
            spawn_times = [[spawn_data.get('start_time',-1), spawn_data.get('end_time',-1)]] # this defaults to [[start_time,end_time]] or [[-1,-1]] if none is specified

        do_spawn = False
        for start_time, end_time in spawn_times:
            # restrict time range by any start/end times provided within the template itself
            if template.get('start_time',-1) > 0:
                start_time = max(start_time, template['start_time']) if (start_time > 0) else template['start_time']
            if template.get('end_time',-1) > 0:
                end_time = min(end_time, template['end_time']) if (end_time > 0) else template['end_time']

            if ((start_time < 0) or ((event_time_override or time_now) >= start_time)) and \
               ((end_time < 0) or ((event_time_override or time_now) < end_time)):
                do_spawn = True # found a valid spawn time
                break

        if not do_spawn:
            #if verbose: print 'not spawning quarry template', spawn_data['template'], 'because current time is outside its start/end_time range(s)'
            continue

        local_qty_scale = 1

        if 'quarry_num_scale_by_player_pop' in region_data:
            if player_pop is None: # cache this
                player_pop = nosql_client.count_map_features_by_type(region_id, 'home')
                player_pop_factor = min(max(float(player_pop) / region_data['pop_soft_cap'], 0), 1)
                if 'min_player_pop_factor' in region_data:
                    player_pop_factor = max(player_pop_factor, region_data['min_player_pop_factor'])
                if verbose: print 'player_pop_factor', player_pop_factor

            # move local_qty_scale proportionally toward local_qty_scale * player_pop_factor
            local_qty_scale *= (1.0 + region_data['quarry_num_scale_by_player_pop'] * (player_pop_factor - 1.0))

        if local_qty_scale <= 0:
            if verbose: print 'not spawning quarry template', spawn_data['template'], 'because local_qty_scale is', local_qty_scale
            continue

        # spawn at least one as long as base_qty is above zero
        qty = max(spawn_data.get('num_min',1), int(base_qty * global_qty_scale * local_qty_scale))

        for i in xrange(qty):
            if spawn_quarry(quarries, map_cache, db, lock_manager, region_id, (spawn_data['id_start']+i), i, name_idx,
                            spawn_data.get('distribution', {'func':'uniform'}), spawn_data['template'], template, spawn_data['resource'],
                            start_time = start_time, end_time = end_time, region_player_pop = player_pop if region_data.get('hive_num_scale_by_player_pop',False) else None,
                            force_rotation = force_rotation, dry_run = dry_run):
                do_throttle()
            name_idx += 1


def spawn_quarry(quarries, map_cache, db, lock_manager, region_id, id_num, id_serial, name_idx, distribution, template_name, template, resource,
                 start_time = -1, end_time = -1, force_rotation = False, region_player_pop = None,
                 dry_run = True):

    base_id = 'q%d' % id_num

    base_info = map_cache.get(base_id, None)
    if base_info:
        if verbose: print 'SKIPPING (EXISTING)', pretty_feature(base_info)
        return

    duration_range = template.get('duration_range', quarries['default_duration_range'])
    duration = int(duration_range[0] + (duration_range[1]-duration_range[0])*random.random())

    # clamp duration to end time
    if (end_time > 0) and ((event_time_override or time_now) + duration >= end_time):
        duration = min(duration, end_time - (event_time_override or time_now))

    assign_climate = template.get('base_climate', None)
    owner_id = template['default_landlord_id']
    if 'tech' in template:
        owner_tech = template['tech']
    else:
        owner_tech = {} # this was never used gamedata['ai_bases']['bases'][str(owner_id)].get('tech',{})

    # optionally apply a random rotation
    if template.get('rotatable',False) or force_rotation:
        xform = get_random_rotation(template.get('base_ncells', None) or gamedata['map']['default_ncells'])
    else:
        xform = [1,0,0,1,0,0]

    base_data = {
        'base_id': base_id,
        'base_landlord_id': owner_id,
        'base_map_loc': None,
        'base_type': 'quarry',
        'base_ui_name': '%s%s-%04d' % (random_letter(), random_letter(), id_num), # ui_name
        'base_richness': template['base_richness'],
        'base_icon': template['icon'].replace('%RESOURCE', resource),
        'base_climate': assign_climate,
        'base_creation_time': time_now,
        'base_creator_id': owner_id,
        'base_expire_time': time_now + duration,
        'base_template': template_name
        }

    ncells = None
    if 'base_ncells' in template:
        ncells = base_data['base_ncells'] = template['base_ncells']
    if not ncells:
        ncells = gamedata['map']['default_ncells']

    if 'base_resource_loot' in template: base_data['base_resource_loot'] = template['base_resource_loot']

    if 'base_size' in template: base_data['base_size'] = template['base_size']
    base_data['deployment_buffer'] = transform_deployment_buffer(xform, template.get('deployment_buffer', 0))

    # make a copy with just the properties for map_cache
    base_info = base_data.copy()

    # finish rest of basedb properties
    base_data['base_region'] = region_id
    base_data['base_generation'] = 0

    nosql_id_generator.set_time(int(time.time()))

    base_data['my_base'] = []
    for p in template['buildings']:
        spec = p['spec']
        if spec == '%RESOURCE_harvester':
            spec = gamedata['resources'][resource]['harvester_building']
        assert spec in gamedata['buildings']
        obj = {'obj_id': nosql_id_generator.generate(),
               'spec':  spec,
               'xy': transform(xform, p['xy']) }
        if 'force_level' in p: obj['level'] = p['force_level']
        elif p.get('level',1)!=1: obj['level'] = p['level']
        if 'equipment' in p:
            obj['equipment'] = copy.deepcopy(p['equipment'])
        spec = gamedata['buildings'][obj['spec']]
        if 'production_capacity' in spec:
            obj['contents'] = get_leveled_quantity(spec['production_capacity'], obj.get('level',1))
            obj['produce_start_time'] = -1
            obj['produce_rate'] = -1
        base_data['my_base'].append(obj)

    for p in template['units']:
        if 'force_level' in p:
            level = p['force_level']
        else:
            level = max(p.get('level', 1), owner_tech.get(gamedata['units'][p['spec']]['level_determined_by_tech'],1))

        obj = {'obj_id': nosql_id_generator.generate(),
               'spec': p['spec'],
               'xy': transform(xform, p['xy']),
               'level': level }
        if 'orders' in p:
            obj['orders'] = []
            for order in p['orders']:
                if 'dest' in order and order['dest']:
                    order = copy.copy(order)
                    order['dest'] = transform(xform, order['dest'])
                obj['orders'].append(order)

        if 'patrol' in p: obj['patrol'] = p['patrol']
        if 'equipment' in p:
            obj['equipment'] = copy.deepcopy(p['equipment'])
        base_data['my_base'].append(obj)

    for p in template.get('scenery',[]):
        obj = {'obj_id': nosql_id_generator.generate(),
               'spec': rotate_scenery_sprite(xform, p['spec']).replace('%RESOURCE', resource),
               'xy': transform(xform, p['xy']),
               'owner': 'environment' }
        base_data['my_base'].append(obj)

    print 'SPAWNING', pretty_feature(base_info)

    success = False

    # place on map with rejection sampling against locations of other map features
    region_data = gamedata['regions'][region_id]
    map_dims = region_data['dimensions']
    bzone = max(gamedata['territory']['border_zone_ai'], 2)
    if distribution['func'] == 'uniform':

        midpt = [map_dims[0]//2, map_dims[1]//2]
        maxranges = [midpt[0] - bzone, midpt[1] - bzone]

        # when entering a low-population region, prefer placing hives close to the center of the map
        # note: use the same formula used for placing player bases geographically, which scales differently than the spawn number scaling
        if region_player_pop is not None:
            cap = region_data.get('pop_hard_cap',-1)
            if cap > 0:
                # "fullness": ratio of the current population to centralize_below_pop * pop_hard_cap
                fullness = region_player_pop / float(cap * gamedata['territory'].get('centralize_below_pop', 0.5))
                if fullness < 1:
                    # keep radius above a minimum, and raise it with the square root of fullness since open area grows as radius^2
                    maxranges = [max(gamedata['territory'].get('centralize_min_radius',10), int(math.sqrt(fullness) * x)) for x in maxranges]


        sample_loc = [int(midpt[D] + maxranges[D]*(2*random.random()-1)) for D in xrange(2)]
        print maxranges, sample_loc

    elif distribution['func'] == 'sobol':
        global sobol_gen
        if sobol_gen is None:
            sobol_gen = Sobol.Sobol(dimensions=2, skip=0)
        p = sobol_gen.get(distribution['start'] + id_serial * distribution['inc'])
        sample_loc = [int(bzone + (map_dims[D] - 2*bzone)*p[D]) for D in xrange(2)]

    else: raise Exception('unknown distribution type '+distribution['func'])

    for trial in xrange(10):
        trial_loc = [min(max(sample_loc[0] + (-1 if ((trial%2)==0) else 1) * (trial/2),bzone),map_dims[0]-bzone),
                     min(max(sample_loc[1], bzone), map_dims[1]-bzone)]
        if Region(gamedata, region_id).obstructs_bases(trial_loc): continue
        base_info['base_map_loc'] = trial_loc
        if not assign_climate:
            base_info['base_climate'] = Region(gamedata, region_id).read_climate_name(base_info['base_map_loc'])
        if dry_run: break
        if nosql_client.create_map_feature(region_id, base_id, base_info, originator = SpinNoSQLLockManager.LockManager.SETUP_LOCK_OWNER, exclusive = 1):
            lock_manager.create(region_id, base_id)
            break
        base_info['base_map_loc'] = None
        base_info['base_climate'] = assign_climate

    if base_info['base_map_loc']:
        base_data['base_map_loc'] = base_info['base_map_loc']
        base_data['base_climate'] = base_info['base_climate']
        nosql_client.drop_all_objects_by_base(region_id, base_id) # clear out any expired objects
        nosql_write_all_objects(region_id, base_id, base_data['base_landlord_id'], base_data['my_base'])
        print 'SPAWNED', pretty_feature(base_info)
        lock_manager.release(region_id, base_id)
        success = True
    else:
        print 'COULD NOT FIND OPEN MAP LOCATION near', sample_loc

    return success

def alliance_display_name(info):
    ret = info['ui_name']
    if len(info.get('chat_tag','')) > 0:
        ret += ' ['+info['chat_tag']+']'
    return ret

def update_turf(db, lock_manager, region_id, dry_run = True):
    # get all quarries
    map_cache = get_existing_map_by_type(db, region_id, 'quarry')
    landlord_ids = list(set([x['base_landlord_id'] for x in map_cache.itervalues() if x.get('base_landlord_id',-1) > 0]))
    print "LANDLORD_IDS", landlord_ids
    # get mapping of landlord to alliance_id
    landlord_alliance_ids = dict(zip(landlord_ids, nosql_client.get_users_alliance(landlord_ids)))
    print "LANDLORD_ALLIANCE_IDS", landlord_alliance_ids

    total_points = 0
    alliance_points = {}
    for feature in map_cache.itervalues():
        template = gamedata['quarries_client']['templates'][feature['base_template']]
        points = template.get('turf_points',0)
        if points > 0:
            total_points += points
            alliance_id = landlord_alliance_ids[feature['base_landlord_id']]
            if alliance_id >= 0:
                alliance_points[alliance_id] = alliance_points.get(alliance_id,0) + points
    print "TOTAL POINTS", total_points
    print "ALLIANCE_POINTS", alliance_points
    points_to_win = int(total_points/2.0)+1

    if True:
        leaders = sorted(alliance_points.items(), key = lambda id_points: -id_points[1])

        # remember previous winning alliance
        prev_winner_id = -1
        prev_winner_info = None

        prev_turf = nosql_client.alliance_turf_get_by_region(region_id)
        if prev_turf:
            if prev_turf[0]['points'] >= points_to_win and (len(prev_turf) < 2 or prev_turf[0]['points'] != prev_turf[1]['points']):
                prev_winner_id = prev_turf[0]['alliance_id']
                prev_winner_info = nosql_client.get_alliance_info(prev_winner_id)

        # store leaderboard
        nosql_client.alliance_turf_clear(region_id) # racy :(
        rank = -1
        last_points = -1
        for i in xrange(len(leaders)):
            id, points = leaders[i]
            if points != last_points:
                rank += 1
            nosql_client.alliance_turf_update(region_id, rank, id, {'points':points,
                                                                    'next_check':time_now + gamedata['quarries_client']['alliance_turf']['check_interval']})
            last_points = points

        if chat_client:
            # tell game servers to tell game clients to update their turf state
            chat_client.chat_send({'channel':'CONTROL',
                                   'sender': {'secret':SpinConfig.config['proxy_api_secret'],
                                              'method':'broadcast_turf_update',
                                              'args':{'region_id':region_id,
                                                      'data':nosql_client.alliance_turf_get_by_region(region_id)}},
                                   }, log = False)
        if len(leaders) < 1:
            print "No participating alliances"
            if chat_client and (total_points > 0):
                # send chat announcement to regional channel
                chat_client.chat_send({'channel':'r:%s' % region_id,
                                       'sender':{'server':'maptool',
                                                 'chat_name': 'Region',
                                                 'user_id': -1,
                                                 'type': 'alliance_turf_no_participation',
                                                 'points_to_win': str(points_to_win),
                                                 'region_name': gamedata['regions'][region_id]['ui_name']
                                                 },
                                       'text':''}, log = True)
            return
        if (leaders[0][1] < points_to_win):
            print "INSUFFICIENT POINTS! no winner (has %d needs %d)" % (leaders[0][1], points_to_win)
            if chat_client and (total_points > 0):
                # send chat announcement to regional channel
                leader_info = nosql_client.get_alliance_info(leaders[0][0])
                chat_client.chat_send({'channel':'r:%s' % region_id,
                                       'sender':{'server':'maptool',
                                                 'chat_name': 'Region',
                                                 'user_id': -1,
                                                 'type': 'alliance_turf_insufficient_points',
                                                 'points_to_win': str(points_to_win),
                                                 'alliance_points': str(leaders[0][1]),
                                                 'alliance_id': leaders[0][0],
                                                 'alliance_name': alliance_display_name(leader_info),
                                                 'region_name': gamedata['regions'][region_id]['ui_name']
                                                 },
                                       'text':''}, log = True)
            return

        if len(leaders) >= 2 and (leaders[0][1] == leaders[1][1]):
            print "TIE! no winner"
            return

        winner_id = leaders[0][0]
        winner_info = nosql_client.get_alliance_info(winner_id)
        print "WINNING ALLIANCE", winner_id, winner_info['ui_name']

        # send award to all members in the region
        reward = gamedata['quarries_client']['alliance_turf'].get('reward',None)
        if reward:
            award_players = []
            member_ids = nosql_client.get_alliance_member_ids(winner_id)
            # query player cache for home regions
            pcache = dict(zip(member_ids, nosql_client.player_cache_lookup_batch(member_ids, fields=['home_region'])))
            print "PCACHE", pcache
            for player_id, info in pcache.iteritems():
                if info.get('home_region',None) == region_id:
                    print "AWARD FOR PLAYER", player_id
                    award_players.append(player_id)
            if award_players:
                for aura in reward['auras']:
                    regions = aura.get('regions',None)
                    if regions is not None and region_id not in regions: continue
                    end_time = time_now + aura['duration']
                    if aura.get('start_time',-1) > 0 and (time_now < aura['start_time']): continue
                    if aura.get('end_time',-1) > 0:
                        if (time_now >= aura['end_time']): continue
                        end_time = min(end_time, aura['end_time'])
                    nosql_client.msg_send([{'to':award_players,
                                            'type': 'apply_aura',
                                            'expire_time': end_time,
                                            'end_time': end_time,
                                            'aura_name': aura['spec'],
                                            'aura_level': aura.get('level',1),
                                            'aura_strength': aura.get('strength',1)}])

                if chat_client:
                    if (winner_id != prev_winner_id) and (total_points > 0):
                        # send chat announcement to regional channel
                        chat_client.chat_send({'channel':'r:%s' % region_id,
                                               'sender':{'server':'maptool',
                                                         'chat_name': 'Region',
                                                         'user_id': -1,
                                                         'type': 'alliance_turf_winner_transition' if (prev_winner_id >= 0 and winner_id != prev_winner_id) else 'alliance_turf_winner',
                                                         'alliance_id': winner_id,
                                                         'alliance_name': alliance_display_name(winner_info),
                                                         'alliance_points': str(leaders[0][1]),
                                                         'prev_alliance_id': prev_winner_id,
                                                         'prev_alliance_name': alliance_display_name(prev_winner_info) if prev_winner_info else 'unknown',
                                                         'region_name': gamedata['regions'][region_id]['ui_name']
                                                         },
                                               'text':''}, log = True)
                    else:
                        print "winner same as before, no chat announcement"
                        pass

def weed_expired_bases(db, lock_manager, region_id, base_types, dry_run = True):
    for base_id in nosql_client.get_expired_map_feature_ids_by_types(region_id, base_types):
        clear_base(db, lock_manager, region_id, base_id, dry_run = dry_run)

def expire_all_hives(db, lock_manager, region_id, dry_run = True):
    map_cache = get_existing_map_by_type(db, region_id, 'hive')
    for base_id, feature in map_cache.iteritems():
        clear_base(db, lock_manager, region_id, base_id, dry_run = dry_run)

def spawn_all_hives(db, lock_manager, region_id, force_rotation = False, dry_run = True):
    region_data = gamedata['regions'][region_id]
    if (not region_data.get('spawn_hives',True)): return

    hives = SpinConfig.load(SpinConfig.gamedata_component_filename("hives_compiled.json"))

    global_qty_scale = 1.0
    if 'region_pop' in hives:
        global_qty_scale *= hives['region_pop'].get(region_id,1.0)
    if global_qty_scale <= 0: return

    player_pop = None # player population, used for scaling the spawn
    player_pop_factor = None # fullness of player population relative to pop_soft_cap, used for scaling the spawn

    map_cache = get_existing_map_by_type(db, region_id, 'hive')
    name_idx = 0

    spawn_list = hives.get('spawn_for_'+region_id, hives['spawn'])
    num_spawned_by_type = {}

    for spawn_data in spawn_list:
        if not spawn_data.get('active',1): continue
        template = hives['templates'][spawn_data['template']]

        if 'num_by_region' in spawn_data and region_id in spawn_data['num_by_region']:
            base_qty = spawn_data['num_by_region'][region_id]
        else:
            base_qty = spawn_data['num']
        if base_qty <= 0: continue

        # get list of start,end spawn times
        if 'spawn_times' in spawn_data:
            spawn_times = spawn_data['spawn_times']
        else:
            spawn_times = [[spawn_data.get('start_time',-1), spawn_data.get('end_time',-1)]]

        repeat_interval = spawn_data.get('repeat_interval',None)

        do_spawn = False
        ref_time = event_time_override or time_now
        for start_time, end_time in spawn_times:
            # restrict time range by any start/end times provided within the template itself
            if template.get('start_time',-1) > 0:
                start_time = max(start_time, template['start_time']) if (start_time > 0) else template['start_time']
            if template.get('end_time',-1) > 0:
                end_time = min(end_time, template['end_time']) if (end_time > 0) else template['end_time'] # this defaults to [[start_time,end_time]] or [[-1,-1]] if none is specified

            if ((start_time > 0) and (ref_time < start_time)): continue # in the future
            if repeat_interval:
                delta = (ref_time - start_time) % repeat_interval
                if ((end_time > 0) and (delta >= (end_time - start_time))): continue # outside a run
            else:
                if ((end_time > 0) and (ref_time >= end_time)): continue # in the past

            do_spawn = True # found a valid spawn time
            break

        if not do_spawn:
            #if verbose: print 'not spawning hive template', spawn_data['template'], 'because current time is outside its start/end_time range(s)'
            continue

        local_qty_scale = 1

        if 'hive_num_scale_by_player_pop' in region_data:
            if player_pop is None: # cache this
                player_pop = nosql_client.count_map_features_by_type(region_id, 'home')
                player_pop_factor = min(max(float(player_pop) / region_data['pop_soft_cap'], 0), 1)
                if 'min_player_pop_factor' in region_data:
                    player_pop_factor = max(player_pop_factor, region_data['min_player_pop_factor'])
                if verbose: print 'player_pop_factor', player_pop_factor

            # move local_qty_scale proportionally toward local_qty_scale * player_pop_factor
            local_qty_scale *= (1.0 + region_data['hive_num_scale_by_player_pop'] * (player_pop_factor - 1.0))

        if local_qty_scale <= 0:
            if verbose: print 'not spawning hive template', spawn_data['template'], 'because local_qty_scale is', local_qty_scale
            continue

        # spawn at least one as long as base_qty is above zero
        qty = max(spawn_data.get('num_min',1), int(base_qty * global_qty_scale * local_qty_scale))

        for i in xrange(qty):
            if spawn_hive(hives, map_cache, db, lock_manager, region_id, (spawn_data['id_start']+i), name_idx, spawn_data['template'], template,
                          start_time = start_time, end_time = end_time, repeat_interval = repeat_interval, region_player_pop = player_pop if region_data.get('hive_num_scale_by_player_pop',False) else None,
                          force_rotation = force_rotation, dry_run = dry_run):
                num_spawned_by_type[spawn_data['template']] = num_spawned_by_type.get(spawn_data['template'],0) + 1
                do_throttle()
            name_idx += 1

    num_total = sum(num_spawned_by_type.itervalues(),0)
    if num_total > 0:
        print 'TOTAL SPAWNED %d:' % num_total
        for k in sorted(num_spawned_by_type.keys()):
            print k, num_spawned_by_type[k]


def spawn_hive(hives, map_cache, db, lock_manager, region_id, id_num, name_idx, template_name, template,
               start_time = -1, end_time = -1, repeat_interval = None, force_rotation = False, region_player_pop = None,
               dry_run = True):

    owner_id = template['owner_id']
    owner_level = gamedata['ai_bases_client']['bases'][str(owner_id)]['resources']['player_level']
    if 'tech' in template:
        owner_tech = template['tech']
    else:
        owner_tech = {} # this was never used gamedata['ai_bases']['bases'][str(owner_id)].get('tech', {})

    region_min_level = hives.get('region_min_level',{}).get(region_id,0)
    if owner_level < region_min_level: return

    base_id = 'v%d' % (id_num)

    feature = map_cache.get(base_id, None)

    if feature:
        if verbose: print 'SKIPPING (EXISTING)', pretty_feature(feature)
        return

    alphabet = gamedata['strings']['icao_alphabet']
    if 'ui_name' in template:
        ui_name = template['ui_name']
    else:
        ui_name = '%s-%04d' % (alphabet[name_idx%len(alphabet)], id_num)

    duration = int(hives['duration'] * (1.0 - hives['randomize_duration'] * random.random()))

    # clamp duration to end time
    ref_time = (event_time_override or time_now)
    if (end_time > 0):
        if repeat_interval:
            delta = (ref_time - start_time) % repeat_interval
            run_end_time = ref_time + (end_time - start_time - delta)
        else:
            run_end_time = end_time
        if (ref_time + duration >= run_end_time):
            duration = min(duration, run_end_time - ref_time)

    assign_climate = template.get('base_climate', None)

    # optionally apply a random rotation
    if template.get('rotatable',False) or force_rotation:
        xform = get_random_rotation(template.get('base_ncells', None) or gamedata['map']['default_ncells'])
    else:
        xform = [1,0,0,1,0,0]

    base_data = {
        'base_id': base_id,
        'base_landlord_id': owner_id,
        'base_creator_id': owner_id,
        'base_map_loc': None,
        'base_type': 'hive',
        'base_ui_name': ui_name,
        'base_creation_time': time_now,
        'base_expire_time': time_now + duration,
        'base_icon': 'hive',
        'base_climate': assign_climate,
        'base_template': template_name
        }
    if 'base_richness' in template: base_data['base_richness'] = template['base_richness']
    if 'base_resource_loot' in template: base_data['base_resource_loot'] = template['base_resource_loot']
    if 'base_size' in template: base_data['base_size'] = template['base_size']

    ncells = None
    if 'base_ncells' in template:
        ncells = base_data['base_ncells'] = template['base_ncells']
    if not ncells:
        ncells = gamedata['map']['default_ncells']

    # note: hives default to NO deployment buffer, because travel time prevents spam tactics
    base_data['deployment_buffer'] = transform_deployment_buffer(xform, template.get('deployment_buffer', 0))

    # make copy of the set of properties that go into map_cache
    feature = base_data.copy()

    # now add the detailed properties that go only to basedb
    base_data['base_region'] = region_id
    base_data['base_generation'] = 0

    nosql_id_generator.set_time(int(time.time()))

    base_data['my_base'] = auto_level_hive_objects(template['buildings'] + template['units'], owner_level, owner_tech, xform)
    if template.get('randomize_defenses',False):
        AIBaseRandomizer.randomize_defenses(gamedata, base_data['my_base'], random_seed = 1000*time.time(), ui_name = template_name)

    for p in template.get('scenery',[]):
        obj = {'obj_id': nosql_id_generator.generate(),
               'spec': rotate_scenery_sprite(xform, p['spec']),
               'xy': transform(xform, p['xy']), 'owner': 'environment' }
        base_data['my_base'].append(obj)

    print 'SPAWNING hive', template_name, pretty_feature(feature)

    success = False

    # place on map with rejection sampling
    region_data = gamedata['regions'][region_id]
    map_dims = region_data['dimensions']
    mid = (int(map_dims[0]/2), int(map_dims[1]/2))
    minrange = 0
    maxrange = map_dims[0]/2 - gamedata['territory']['border_zone_ai']

    # when entering a low-population region, prefer placing hives close to the center of the map
    # note: use the same formula used for placing player bases geographically, which scales differently than the spawn number scaling
    if region_player_pop is not None:
        cap = region_data.get('pop_hard_cap',-1)
        if cap > 0:
            # "fullness": ratio of the current population to centralize_below_pop * pop_hard_cap
            fullness = region_player_pop / float(cap * gamedata['territory'].get('centralize_below_pop', 0.5))
            if fullness < 1:
                # keep radius above a minimum, and raise it with the square root of fullness since open area grows as radius^2
                maxrange = max(gamedata['territory'].get('centralize_min_radius',10), int(math.sqrt(fullness) * maxrange))

    for x in xrange(20):
        side = [1 if (random.random() > 0.5) else -1,
                1 if (random.random() > 0.5) else -1]

        feature['base_map_loc'] = (min(max(mid[0] + side[0]*int(minrange + (maxrange-minrange)*random.random()), 2), map_dims[0]-2),
                                   min(max(mid[1] + side[1]*int(minrange + (maxrange-minrange)*random.random()), 2), map_dims[1]-2))
        if not assign_climate:
            feature['base_climate'] = Region(gamedata, region_id).read_climate_name(feature['base_map_loc'])

        if Region(gamedata, region_id).obstructs_bases(feature['base_map_loc']):
            feature['base_map_loc'] = None
            feature['base_climate'] = assign_climate
            continue

        if dry_run: break
        if nosql_client.create_map_feature(region_id, base_id, feature, originator = SpinNoSQLLockManager.LockManager.SETUP_LOCK_OWNER, exclusive = 1):
            lock_manager.create(region_id, base_id)
            break
        feature['base_map_loc'] = None
        feature['base_climate'] = assign_climate

    if feature['base_map_loc']:
        base_data['base_map_loc'] = feature['base_map_loc']
        base_data['base_climate'] = feature['base_climate']

        if not dry_run:
            nosql_client.drop_all_objects_by_base(region_id, base_id) # clear out any objects hanging around from expired older base
            nosql_write_all_objects(region_id, base_id, owner_id, base_data['my_base'])

        lock_manager.release(region_id, base_id)
        success = True
    else:
        print 'COULD NOT FIND OPEN MAP LOCATION!'

    return success

def spawn_all_raids(db, lock_manager, region_id, dry_run = True):
    region_data = gamedata['regions'][region_id]
    if (not region_data.get('spawn_raids',True)): return

    raids = SpinConfig.load(SpinConfig.gamedata_component_filename("raids_compiled.json"))

    global_qty_scale = 1.0
    if 'region_pop' in raids:
        global_qty_scale *= raids['region_pop'].get(region_id,1.0)
    if global_qty_scale <= 0: return

    player_pop = None # player population, used for scaling the spawn
    player_pop_factor = None # fullness of player population relative to pop_soft_cap, used for scaling the spawn

    map_cache = get_existing_map_by_type(db, region_id, 'raid')
    name_idx = 0

    spawn_list = raids.get('spawn_for_'+region_id, raids['spawn'])
    num_spawned_by_type = {}

    for spawn_data in spawn_list:
        if not spawn_data.get('active',1): continue
        template = raids['templates'][spawn_data['template']]

        if 'num_by_region' in spawn_data and region_id in spawn_data['num_by_region']:
            base_qty = spawn_data['num_by_region'][region_id]
        else:
            base_qty = spawn_data['num']
        if base_qty <= 0: continue

        # get list of start,end spawn times
        if 'spawn_times' in spawn_data:
            spawn_times = spawn_data['spawn_times']
        else:
            spawn_times = [[spawn_data.get('start_time',-1), spawn_data.get('end_time',-1)]]

        repeat_interval = spawn_data.get('repeat_interval',None)

        do_spawn = False
        ref_time = event_time_override or time_now
        for start_time, end_time in spawn_times:
            # restrict time range by any start/end times provided within the template itself
            if template.get('start_time',-1) > 0:
                start_time = max(start_time, template['start_time']) if (start_time > 0) else template['start_time']
            if template.get('end_time',-1) > 0:
                end_time = min(end_time, template['end_time']) if (end_time > 0) else template['end_time'] # this defaults to [[start_time,end_time]] or [[-1,-1]] if none is specified

            if ((start_time > 0) and (ref_time < start_time)): continue # in the future
            if repeat_interval:
                delta = (ref_time - start_time) % repeat_interval
                if ((end_time > 0) and (delta >= (end_time - start_time))): continue # outside a run
            else:
                if ((end_time > 0) and (ref_time >= end_time)): continue # in the past

            do_spawn = True # found a valid spawn time
            break

        if not do_spawn:
            #if verbose: print 'not spawning raid template', spawn_data['template'], 'because current time is outside its start/end_time range(s)'
            continue

        local_qty_scale = 1

        if 'raid_num_scale_by_player_pop' in region_data:
            if player_pop is None: # cache this
                player_pop = nosql_client.count_map_features_by_type(region_id, 'home')
                player_pop_factor = min(max(float(player_pop) / region_data['pop_soft_cap'], 0), 1)
                if 'min_player_pop_factor' in region_data:
                    player_pop_factor = max(player_pop_factor, region_data['min_player_pop_factor'])
                if verbose: print 'player_pop_factor', player_pop_factor

            # move local_qty_scale proportionally toward local_qty_scale * player_pop_factor
            local_qty_scale *= (1.0 + region_data['raid_num_scale_by_player_pop'] * (player_pop_factor - 1.0))

        if local_qty_scale <= 0:
            if verbose: print 'not spawning raid template', spawn_data['template'], 'because local_qty_scale is', local_qty_scale
            continue

        # spawn at least one as long as base_qty is above zero
        qty = max(spawn_data.get('num_min',1), int(base_qty * global_qty_scale * local_qty_scale))

        for i in xrange(qty):
            if spawn_raid(raids, map_cache, db, lock_manager, region_id, (spawn_data['id_start']+i), name_idx, spawn_data['template'], template,
                          start_time = start_time, end_time = end_time, repeat_interval = repeat_interval,
                          duration = spawn_data['duration'] * (1.0 - spawn_data.get('randomize_duration',0) * random.random()),
                          region_player_pop = player_pop if region_data.get('raid_num_scale_by_player_pop',False) else None,
                          dry_run = dry_run):
                num_spawned_by_type[spawn_data['template']] = num_spawned_by_type.get(spawn_data['template'],0) + 1
                do_throttle()
            name_idx += 1

    num_total = sum(num_spawned_by_type.itervalues(),0)
    if num_total > 0:
        print 'TOTAL SPAWNED %d:' % num_total
        for k in sorted(num_spawned_by_type.keys()):
            print k, num_spawned_by_type[k]

def spawn_raid(raids, map_cache, db, lock_manager, region_id, id_num, name_idx, template_name, template,
               start_time = -1, end_time = -1, repeat_interval = None, duration = None, region_player_pop = None,
               dry_run = True):

    owner_id = template['owner_id']
    base_id = 'r%d' % (id_num)

    feature = map_cache.get(base_id, None)

    if feature:
        if verbose: print 'SKIPPING (EXISTING)', pretty_feature(feature)
        return

    alphabet = gamedata['strings']['icao_alphabet']
    if 'ui_name' in template:
        ui_name = template['ui_name']
    else:
        ui_name = '%s-%04d' % (alphabet[name_idx%len(alphabet)], id_num)

    # clamp duration to end time
    ref_time = (event_time_override or time_now)
    if (end_time > 0):
        if repeat_interval:
            delta = (ref_time - start_time) % repeat_interval
            run_end_time = ref_time + (end_time - start_time - delta)
        else:
            run_end_time = end_time
        if (ref_time + duration >= run_end_time):
            duration = min(duration, run_end_time - ref_time)

    assign_climate = template.get('base_climate', None)

    base_data = {
        'base_id': base_id,
        'base_landlord_id': owner_id,
        'base_creator_id': owner_id,
        'base_map_loc': None,
        'base_type': 'raid',
        'base_ui_name': ui_name,
        'base_creation_time': time_now,
        'base_expire_time': time_now + duration,
        'base_icon': 'raid',
        'base_climate': assign_climate,
        'base_template': template_name
        }
    if 'base_richness' in template: raise Exception('base_richness should not be used for raids')
    if 'base_resource_loot' in template: base_data['base_resource_loot'] = template['base_resource_loot']

    # make copy of the set of properties that go into map_cache
    feature = base_data.copy()

    # now add the detailed properties that go only to basedb
    base_data['base_region'] = region_id
    base_data['base_generation'] = 0

    nosql_id_generator.set_time(int(time.time()))

    base_data['my_base'] = auto_level_hive_objects(template.get('buildings',[]) + template.get('units',[]), 1, {})
    #if template.get('randomize_defenses',False):
    #    AIBaseRandomizer.randomize_defenses(gamedata, base_data['my_base'], random_seed = 1000*time.time(), ui_name = template_name)

    print 'SPAWNING raid', template_name, pretty_feature(feature)

    success = False

    # place on map with rejection sampling
    region_data = gamedata['regions'][region_id]
    map_dims = region_data['dimensions']
    mid = (int(map_dims[0]/2), int(map_dims[1]/2))
    minrange = 0
    maxrange = map_dims[0]/2 - gamedata['territory']['border_zone_ai']

    # when entering a low-population region, prefer placing hives close to the center of the map
    # note: use the same formula used for placing player bases geographically, which scales differently than the spawn number scaling
    if region_player_pop is not None:
        cap = region_data.get('pop_hard_cap',-1)
        if cap > 0:
            # "fullness": ratio of the current population to centralize_below_pop * pop_hard_cap
            fullness = region_player_pop / float(cap * gamedata['territory'].get('centralize_below_pop', 0.5))
            if fullness < 1:
                # keep radius above a minimum, and raise it with the square root of fullness since open area grows as radius^2
                maxrange = max(gamedata['territory'].get('centralize_min_radius',10), int(math.sqrt(fullness) * maxrange))

    for x in xrange(20):
        side = [1 if (random.random() > 0.5) else -1,
                1 if (random.random() > 0.5) else -1]

        feature['base_map_loc'] = (min(max(mid[0] + side[0]*int(minrange + (maxrange-minrange)*random.random()), 2), map_dims[0]-2),
                                   min(max(mid[1] + side[1]*int(minrange + (maxrange-minrange)*random.random()), 2), map_dims[1]-2))
        if not assign_climate:
            feature['base_climate'] = Region(gamedata, region_id).read_climate_name(feature['base_map_loc'])

        if Region(gamedata, region_id).obstructs_bases(feature['base_map_loc']):
            feature['base_map_loc'] = None
            feature['base_climate'] = assign_climate
            continue

        if dry_run: break
        if nosql_client.create_map_feature(region_id, base_id, feature, originator = SpinNoSQLLockManager.LockManager.SETUP_LOCK_OWNER, exclusive = 1):
            lock_manager.create(region_id, base_id)
            break
        feature['base_map_loc'] = None
        feature['base_climate'] = assign_climate

    if feature['base_map_loc']:
        base_data['base_map_loc'] = feature['base_map_loc']
        base_data['base_climate'] = feature['base_climate']

        if not dry_run:
            nosql_client.drop_all_objects_by_base(region_id, base_id) # clear out any objects hanging around from expired older base
            nosql_write_all_objects(region_id, base_id, owner_id, base_data['my_base'])

        lock_manager.release(region_id, base_id)
        success = True
    else:
        print 'COULD NOT FIND OPEN MAP LOCATION!'

    return success

def remove_player_from_map(db, lock_manager, region_id, user_id, feature = None, dry_run = True):
    base_id = 'h'+str(user_id)
    if not feature:
        map_cache = get_existing_map_by_base_id(db, region_id, base_id)
        if base_id not in map_cache:
            print 'base not found:', base_id
            return False
    if not lock_manager.acquire_player(user_id):
        print user_id, '(player is locked, skipping)'
        return False

    try:
        player_data = SpinJSON.loads(SpinUserDB.driver.sync_download_player(user_id))
    except Exception as e:
        print 'error downloading player', user_id, ':\n', e
        return False

    if player_data['home_region'] != region_id:
        print 'player', user_id, 'says home_region is', player_data['home_region'], 'base_region is', player_data['base_region'], 'base_map_loc is', player_data['base_map_loc'],
        if True: # player_data['home_region']:
            print 'deleting invalid map feature'
            if not dry_run:
                nosql_client.drop_mobile_objects_by_owner(region_id, user_id)
                nosql_client.drop_map_feature(region_id, base_id)
            return False
        else:
            print 'not removing'
        return False

    player_data['home_region'] = None
    player_data['base_region'] = None
    player_data['base_map_loc'] = None
    player_data['history']['map_placement_gen'] = -1 # signal that we were plucked
    player_data['generation'] = player_data.get('generation',0)+1

    # reset squads deployment state to avoid confusing server on next login
    if 'squads' in player_data:
        for squad_id, squad in player_data['squads'].iteritems():
            for FIELD in ('map_loc', 'map_path'):
                if FIELD in squad:
                    del squad[FIELD]

    if not dry_run:
        SpinUserDB.driver.sync_write_player(user_id, SpinJSON.dumps(player_data, pretty=True, newline=True, double_precision=5))
        # note: drop all remaining units
        nosql_client.drop_mobile_objects_by_owner(region_id, user_id)
        nosql_client.drop_map_feature(region_id, base_id)

        # keep player_cache in sync
        nosql_client.player_cache_update(user_id, {'home_region': player_data['home_region'], 'ladder_player': 0})

    lock_manager.release_player(user_id, generation = player_data.get('generation',-1))
    print 'REMOVED FROM MAP', pretty_feature(player_data)
    return True

def squad_ui_name(feature):
    if 'base_ui_name' in feature: return feature['base_ui_name']
    squad_id = int(feature['base_id'].split('_')[1])
    return '#%d' % squad_id

def recall_squad(db, lock_manager, region_id, user_id, base_id, days_to_claim_units = 3, feature = None, dry_run = True):
    if not feature:
        map_cache = get_existing_map_by_base_id(db, region_id, base_id)
        if base_id not in map_cache:
            print 'squad not found'
            return False
        feature = map_cache[base_id]

    if not lock_manager.acquire(region_id, base_id):
        print base_id, '(squad is locked, skipping)'
        return False

    squad_units = nosql_read_all_objects(region_id, base_id, user_id) # only mobile objects needed

    refund_units(db, region_id, feature, squad_units, user_id, ui_name = squad_ui_name(feature), days_to_claim = days_to_claim_units, reason = 'squad', dry_run = dry_run)

    if not dry_run:
        nosql_client.drop_mobile_objects_by_base(region_id, base_id)
        nosql_client.drop_map_feature(region_id, base_id)

    lock_manager.forget(region_id, base_id)

    if verbose:
        print 'RECALLED', pretty_feature(feature)
    return True

def resolve_raid_squads(db, lock_manager, region_id, dry_run = True):
    region = Region(gamedata, region_id)
    pf = SquadPathfinder(region)
    home_cache = get_existing_map_by_type_spatially(db, region_id, 'home')
    quarry_cache = get_existing_map_by_type_spatially(db, region_id, 'quarry')
    hive_cache = get_existing_map_by_type_spatially(db, region_id, 'hive')
    raid_cache = get_existing_map_by_type_spatially(db, region_id, 'raid')
    squad_cache = get_existing_map_by_type_spatially(db, region_id, 'squad')

    # set up map occupancy
    for cache in home_cache, quarry_cache, hive_cache, raid_cache, squad_cache:
        for loc, feature in cache.iteritems():
            if region.feature_blocks_map(feature, 'never'): # squad_block_mode
                pf.occupancy.block_hex(feature['base_map_loc'], 1, feature)

    # ignore non-raid squads
    raid_squads = filter(lambda squad: squad.get('raid'), squad_cache.itervalues())
    # ignore moving squads
    raid_squads = filter(lambda squad: ('base_map_path' not in squad) or (squad['base_map_path'][-1]['eta'] < time_now - gamedata['server'].get('map_path_fudge_time',4.0)), raid_squads)

    # for proper resolution ordering, sort by arrival time, earliest first
    raid_squads.sort(key = lambda squad: squad['base_map_path'][-1]['eta'] if 'base_map_path' in squad else -1)

    for squad in raid_squads:
        if not squad.get('raid'): continue # not a raid
        if 'base_map_path' in squad and squad['base_map_path'][-1]['eta'] >= time_now - gamedata['server'].get('map_path_fudge_time',4.0):
            continue # still moving
        loc = squad['base_map_loc']
        loc_key = tuple(loc)
        owner_id, squad_id = map(int, squad['base_id'][1:].split('_'))
        assert squad['base_landlord_id'] == owner_id

        if verbose: print 'RAID SQUAD', pretty_feature(squad), 'stationary'

        if loc_key in home_cache:
            home = home_cache[loc_key]
            if home['base_landlord_id'] == owner_id: # it's home!
                recall_squad(db, lock_manager, region_id, owner_id, squad['base_id'], feature = squad, dry_run = dry_run)
                continue
            else:
                print 'unhandled case - squad is at an enemy home base!'

        elif loc_key in raid_cache:
            raid = raid_cache[loc_key]
            print 'resolving raid at', pretty_feature(raid)
            squad_lock = lock_manager.acquire(region_id, squad['base_id'])
            raid_lock = lock_manager.acquire(region_id, raid['base_id'])
            if not (squad_lock and raid_lock):
                print 'could not get locks for both squad and raid, skipping'
                continue
            try:
                raid_units = nosql_client.get_mobile_objects_by_base(region_id, raid['base_id']) + \
                             nosql_client.get_fixed_objects_by_base(region_id, raid['base_id'])
                squad_units = nosql_client.get_mobile_objects_by_base(region_id, squad['base_id'])

                squad_update, raid_update, loot = Raid.resolve_raid(squad, raid, squad_units, raid_units)
                if verbose: print 'squad_update', squad_update, 'raid_update', raid_update

                if squad_update or raid_update or (raid_update is None):
                    # metrics - keep in sync between Raid.py and maptool.py implementations!
                    summary = Raid.make_battle_summary(gamedata, nosql_client, time_now, region_id, squad, raid,
                                                       squad['base_landlord_id'], raid['base_landlord_id'],
                                                       'victory', 'defeat',
                                                       squad_units, raid_units, loot)
                    if verbose: print SpinJSON.dumps(summary, pretty = True)
                    if not dry_run:
                        nosql_client.battle_record(summary, reason = 'resolve_raid_squads')

                if raid_update is None:
                    clear_base(db, lock_manager, region_id, raid['base_id'], dry_run = dry_run, already_locked = True)
                    raid_lock = None
                    del raid_cache[loc_key]
                    raid = None
                elif raid_update:
                    raid.update(raid_update)
                    if not dry_run:
                        nosql_client.update_map_feature(region_id, raid['base_id'], raid_update)

                if squad_update:
                    squad.update(squad_update)
                    if not dry_run:
                        nosql_client.update_map_feature(region_id, squad['base_id'], squad_update)

            finally:
                if squad_lock: lock_manager.release(region_id, squad['base_id'])
                if raid_lock: lock_manager.release(region_id, raid['base_id'])

        # auto-navigate the squad towards home
        home = nosql_client.get_map_feature_by_base_id(region_id, 'h'+str(owner_id))
        if not home:
            # squad's home base not found on map - just dock immediately
            recall_squad(db, lock_manager, region_id, owner_id, squad['base_id'], feature = squad, dry_run = dry_run)
            continue
        else:
            home = home_cache[tuple(home['base_map_loc'])] # look it up again so the dest_feature identity check works

        if 'base_map_path' in squad and squad['base_map_path'][0]['xy'] == home['base_map_loc']:
            if verbose: print 'using backtrack path'
            new_path = Raid.backtrack(squad, time.time())['base_map_path']
        else:
            if verbose: print 'pathfinding from scratch...'
            astar_solution = pf.raid_find_path_to(loc, home)
            if not astar_solution:
                print 'Squad return pathfinding unsuccessful!', pretty_feature(squad)
                recall_squad(db, lock_manager, region_id, owner_id, squad['base_id'], feature = squad, dry_run = dry_run)
                continue

            # set squad moving
            next_eta = time.time()
            new_path = [{'xy': squad['base_map_loc'], 'eta': next_eta}]
            for i, xy in enumerate(astar_solution):
                next_eta += float(1.0/(gamedata['territory']['unit_travel_speed_factor']*squad.get('travel_speed',1.0)))
                new_path.append({'xy': xy, 'eta': next_eta})

        if not lock_manager.acquire(region_id, squad['base_id']): # yes, there's a race condition here
            if verbose: print 'Squad locked, skipping'
            continue
        try:
            if verbose: print 'Squad moving back to home'
            # note: this will wait until the NEXT run of resolve() to actually dock the squad and units
            if not dry_run:
                nosql_client.move_map_feature(region_id, squad['base_id'], {'base_map_loc': new_path[-1]['xy'],
                                                                            'base_map_path': new_path},
                                              old_loc = squad['base_map_loc'], old_path=squad.get('base_map_path',None),
                                              exclusive = -1, reason = 'resolve')
        finally:
            lock_manager.release(region_id, squad['base_id'])

def abandon_quarries_and_remove_player_from_map(db, lock_manager, region_id, user_id, home_feature = None,
                                                skip_quarry_owners = False, days_to_claim_units = 30, reason = None, dry_run = True):
    my_quarries = get_existing_map_by_landlord_and_type(db, region_id, user_id, 'quarry').values()
    num_abandoned = 0
    if not skip_quarry_owners:
        for feature in my_quarries:
            if abandon_quarry(db, lock_manager, region_id, feature['base_id'], feature = feature, days_to_claim_units = days_to_claim_units, dry_run = dry_run):
                num_abandoned += 1

    if len(my_quarries) > num_abandoned:
        print 'still own some quarries, aborting', map(pretty_feature, my_quarries)
        return False

    my_squads = get_existing_map_by_landlord_and_type(db, region_id, user_id, 'squad').values()
    num_abandoned = 0
    for feature in my_squads:
        if recall_squad(db, lock_manager, region_id, user_id, feature['base_id'], feature = feature, days_to_claim_units = days_to_claim_units, dry_run = dry_run):
            num_abandoned += 1
    if len(my_squads) > num_abandoned:
        print 'still own some squads, aborting', map(pretty_feature, my_squads)
        return False


    if not remove_player_from_map(db, lock_manager, region_id, user_id, feature = home_feature, dry_run = dry_run):
        return False

    msg_body = None
    if reason == 'churned':
        msg_body = 'Welcome back, Commander.\n\nDuring your vacation, I moved our base to a safer location.'
    elif reason == 'nuked':
        msg_body = "Commander, our old home region was depleted.\n\nI've relocated our base to a fresh region."

    if msg_body:
        message = make_valentina_mail(user_id, days_to_claim = -1,
                                      subject = 'Base Repositioned',
                                      body = msg_body)
        # 'If you wish to move again, click our Transmitter building.'
        if not dry_run:
            nosql_client.msg_send([message])

    return True

def weed_churned_players(db, lock_manager, region_id, threshold_days, skip_quarry_owners = False, dry_run = True):
    map_cache = get_existing_map_by_type(db, region_id, 'home')
    if verbose: print len(map_cache), 'players on the map'
    player_ids = sorted([feature['base_landlord_id'] for feature in map_cache.itervalues()])
    result = nosql_client.player_cache_lookup_batch(player_ids, fields = ['last_login_time'])
    player_info = {}
    for i in xrange(len(player_ids)):
        player_info[player_ids[i]] = {'user_id': player_ids[i], 'feature': map_cache['h'+str(player_ids[i])], 'pcache': result[i]}

    churn_list = []
    for entry in player_info.itervalues():
        if entry['pcache'] is None: entry['pcache'] = {}
        if ('last_login_time' not in entry['pcache']):
            # was probably weeded by clean_player_cache.py
            # but note! this can be a race condition if player has logged in only once, was put on the map, and is still logged in.
            # to be safe, also check LOCK_STATE/LOCK_TIME in the map feature!
            if entry['feature'].get('LOCK_STATE',0) != 0 and (time_now - entry['feature'].get('LOCK_TIME',-1) < 4*60*60):
                print 'pcache had no last_login_time but base was locked recently:', entry['user_id']
                entry['pcache']['last_login_time'] = time_now
            else:
                entry['pcache']['last_login_time'] = -1 # was probably weeded by clean_player_cache.py

        if (time_now - entry['pcache']['last_login_time'] > threshold_days*24*60*60):
            churn_list.append(entry)

    if verbose: print len(map_cache) - len(churn_list), 'are still active'
    if verbose or churn_list:
        print len(churn_list), 'have not logged in for at least', threshold_days, 'days'

    for entry in churn_list:
        abandon_quarries_and_remove_player_from_map(db, lock_manager, region_id, entry['user_id'], home_feature = entry['feature'],
                                                    skip_quarry_owners = skip_quarry_owners, days_to_claim_units = 30, reason = 'churned', dry_run = dry_run)

def abandon_quarries_and_remove_all_players_from_map(db, lock_manager, region_id, reason = None, dry_run = True):
    map_cache = get_existing_map_by_type(db, region_id, 'home')
    print len(map_cache), 'players on the map'
    features = sorted(map_cache.values(), key = lambda x: x['base_landlord_id'])
    for feature in features:
        abandon_quarries_and_remove_player_from_map(db, lock_manager, region_id, feature['base_landlord_id'], home_feature = feature,
                                                    skip_quarry_owners = False, days_to_claim_units = 30, reason = reason, dry_run = dry_run)


def weed_orphan_squads(db, lock_manager, region_id, dry_run = True):
    # recall squads whose player owners are not on the map anymore
    players_in_map = set(int(x[1:]) for x in nosql_client.get_map_feature_ids_by_type(region_id, 'home'))
    orphan_squads = [x for x in nosql_client.get_map_feature_ids_by_type(region_id, 'squad') \
                     if int(x.split('_')[0][1:]) not in players_in_map]
    if orphan_squads:
        print "possible orphan squads:", orphan_squads
        for squad_id in orphan_squads:
            # check one last time to minimize race condition (it's still racy :( )
            owner_id = int(squad_id.split('_')[0][1:])
            if nosql_client.get_map_feature_by_base_id(region_id, 'h%d' % owner_id):
                continue
            print 'recalling orphan squad', squad_id
            recall_squad(db, lock_manager, region_id, owner_id, squad_id, dry_run=dry_run)

def weed_orphan_objects(db, lock_manager, region_id, dry_run = True):
    # clear out any mobile or fixed objects whose bases are not on the map anymore
    referenced_base_ids = set(nosql_client.get_base_ids_referenced_by_objects(region_id))
    valid_base_ids = set(nosql_client.get_map_feature_ids(region_id))
    orphan_base_ids = referenced_base_ids - valid_base_ids
    if orphan_base_ids:
        print "possible orphan units belong to bases", orphan_base_ids
        for base_id in orphan_base_ids:
            # NOTE! do NOT clear mobile objects whose owners are still on the map - this happens
            # when someone asynchronously kills their squad, but the owner hasn't run a ping_squads yet.
            if base_id[0] == 's' and nosql_client.get_map_feature_by_base_id(region_id, 'h%d' % int(base_id.split('_')[0][1:])):
                if verbose: print "preserving units in dead squad", base_id
                continue
            # check one last time to minimize race condition (it's still racy :( )
            if nosql_client.get_map_feature_by_base_id(region_id, base_id):
                continue
            print 'deleting units belonging to orphan base', base_id, '...',
            if not dry_run:
                num = nosql_client.drop_all_objects_by_base(region_id, base_id)
            else:
                num = 0
            print num

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'q', ['dry-run', 'throttle=', 'base-id=', 'user-id=', 'threshold-days=',
                                                       'score-week=', 'event-time-override=', 'quiet',
                                                       'force-rotation', 'skip-quarry-owners', 'yes-i-am-sure'])
    if len(args) < 3:
        print 'usage: maptool.py REGION_ID home|hives|quarries|raids ACTION [options]'
        print 'Actions:'
        print '    info          Print info about existing map features'
        print '    maint         Perform all hourly maintenance (weeding, expiring, spawning)'
        print '    spawn         Spawn hives, quarries, or raids as indicated by gamedata JSON, leaving existing unexpired bases alone'
        print '    extend        Extend lifetimes of all existing quarries to last at least quarries["override_duration"] seconds'
        print '    weed          Remove "weeds" (churned players) from the map, abandoning and refunding quarries they own'
        print '    abandon       Have the owner abandon this quarry, refunding units as appropriate'
        print '    expire        Force all quarries to expire immediately, and send units back to owners'
        print '    pluck         Remove a player from the regional map, abandoning and refunding all owned quarries'
        print '    clear         Delete all map features of this type (DANGEROUS! - requires --yes-i-am-sure flag)'
        print '    leaderboard   Print Quarry Resources leaderboard, requires --score-week'
        print 'Options:'
        print '    --dry-run              Print what changes would be made, but do not make them'
        print '    --throttle SEC         Pause SEC seconds between base manipulations to avoid overloading server'
        print '    --threshold-days NUM   For "weed" action, remove players from map if they have not logged in for at least NUM days (default: 30)'
        print '    --base-id ID           Only apply changes to this one base'
        print '    --user-id ID           Only apply changes to this one user'
        print '    --score-week WEEK      Choose week for scores display'
        print '    --event-time-override TIME   Act as if time is equal to UNIX time TIME'
        print '    --skip-quarry-owners   Do not weed players who own quarries (means that the refund/mail system is not used)'
        print '    --force-rotation       Rotate all bases even if not marked "rotatable"'
        print '    --yes-i-am-sure        Required when doing a "clear" operation since it is very destructive'
        print '    -q, --quiet            Reduce verbosity'
        sys.exit(1)

    region_id = args[0]
    base_type = {'hives':'hive','hive':'hive',
                 'quarries':'quarry','quarry':'quarry',
                 'raids':'raid','raid':'raid',
                 'home': 'home', 'squad': 'squad', 'ALL': 'ALL'}[args[1]]
    action = args[2]
    dry_run = False
    base_id = None
    user_id = None
    yes_i_am_sure = False
    threshold_days = 30
    skip_quarry_owners = False
    event_time_override = None
    force_rotation = False
    score_week = -1

    for key, val in opts:
        if key == '--dry-run':
            dry_run = True
        elif key == '--throttle':
            throttle = float(val)
        elif key == '--base-id':
            base_id = val
        elif key == '--user-id':
            user_id = int(val)
        elif key == '--threshold-days':
            threshold_days = int(val)
        elif key == '--score-week':
            score_week = int(val)
        elif key == '--skip-quarry-owners':
            skip_quarry_owners = True
        elif key == '--yes-i-am-sure':
            yes_i_am_sure = True
        elif key == '--force-rotation':
            force_rotation = True
        elif key == '--event-time-override':
            event_time_override = int(val)
        elif key == '-q' or key == '--quiet':
            verbose = False

    if region_id not in gamedata['regions']:
        sys.stderr.write('region not found: %s\n' % region_id)
        sys.exit(1)

    if gamedata['regions'][region_id].get('storage','basedb') != 'nosql':
        print "%s: basedb (non nosql) regions are not supported anymore" % region_id
        sys.exit(1)

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']),
                                         map_update_hook = broadcast_map_update,
                                         log_exception_func = lambda x: sys.stderr.write(x+'\n'))
    nosql_client.set_time(time_now)
    db = nosql_client

    lock_manager = SpinNoSQLLockManager.LockManager(nosql_client, dry_run)

    if ('chatserver' in SpinConfig.config) and action not in ('info', 'leaderboard', 'count'):
        # hook up chatserver so we can send broadcast notifications
        chat_client = SpinSyncChatClient.SyncChatClient(SpinConfig.config['chatserver']['chat_host'],
                                                        SpinConfig.config['chatserver']['chat_port'],
                                                        SpinConfig.config['chatserver']['secret_full'],
                                                        lambda x: sys.stderr.write(x+'\n'))

    try:
        if action == 'leaderboard':
            if score_week >= 0:
                raise Exception('needs to be ported to new SpinNoSQL APIs')
                leaders = db.player_cache_get_leaders('quarry_resources_%s_wk%d' % (region_id, score_week), 10)
                for i in xrange(min(10, len(leaders))):
                    leader = leaders[i]
                    print 'PLACE #%2d: user_id %7d social_id %15s name %8s L%2d with score %10d' % \
                          (i+1, leader['user_id'], leader.get('social_id', 'fb'+leader.get('facebook_id','???')), leader.get('ui_name', leader.get('facebook_name','unknown').split(' ')[0]), leader['player_level'],
                           leader['absolute'])
            else:
                print 'please specify --score-week'
        elif action == 'clear':
            if base_id is not None:
                clear_base(db, lock_manager, region_id, base_id, dry_run=dry_run)
            elif yes_i_am_sure:
                clear_all(db, lock_manager, region_id, base_type, dry_run=dry_run)
            else:
                print 'this is a very destructive operation, add --yes-i-am-sure if you want to proceed!'

        elif action == 'maint':
            # MASTER PER-REGION MAINTENANCE JOB
            with SpinSingletonProcess.SingletonProcess('maptool-region-maint-%s-%s' % (SpinConfig.config['game_id'], region_id)):
                assert base_type == 'ALL'
                raids_enabled = gamedata['regions'][region_id].get('spawn_raids', True) and len(gamedata['raids_client']['templates']) > 0

                print "====== %s ======" % region_id

                # 10. run low-level database maintenance (bust stale locks)
                print "%s: busting stale map feature locks..." % region_id
                nosql_client.do_region_maint(region_id)

                # 20. weed expired bases
                print "%s: weeding expired hives/quarries/raids..." % region_id
                weed_expired_bases(db, lock_manager, region_id, ['hive','quarry','raid'], dry_run=dry_run)

                # 30. weed churned players
                print "%s: weeding players churned for more than %d days..." % (region_id, threshold_days)
                weed_churned_players(db, lock_manager, region_id, threshold_days, skip_quarry_owners = skip_quarry_owners, dry_run=dry_run)

                # 40. weed orphaned squads
                print "%s: weeding orphan squads..." % region_id
                weed_orphan_squads(db, lock_manager, region_id, dry_run=dry_run)

                # 50. weed orphaned units
                print "%s: weeding orphan objects..." % region_id
                weed_orphan_objects(db, lock_manager, region_id, dry_run=dry_run)

                # 55. resolve raid squad issues
                if raids_enabled:
                    print "%s: resolving raid squads..." % region_id
                    resolve_raid_squads(db, lock_manager, region_id, dry_run=dry_run)

                # 60. update turf war
                if 'alliance_turf' in gamedata['quarries_client'] and gamedata['regions'][region_id].get('enable_turf_control',False):
                    print "%s: turf update..." % region_id
                    update_turf(db, lock_manager, region_id, dry_run=dry_run)

                # 70. respawn hives/quarries/raids
                print "%s: spawning hives..." % region_id
                spawn_all_hives(db, lock_manager, region_id, force_rotation=force_rotation, dry_run=dry_run)
                print "%s: spawning quarries..." % region_id
                spawn_all_quarries(db, lock_manager, region_id, force_rotation=force_rotation, dry_run=dry_run)
                if raids_enabled:
                    print "%s: spawning raids..." % region_id
                    spawn_all_raids(db, lock_manager, region_id, dry_run=dry_run)

        elif action == 'prune-stale-locks':
            nosql_client.do_region_maint(region_id)
        elif action == 'info':
            print_all(db, lock_manager, region_id, base_type, dry_run=dry_run)
        elif action == 'count':
            get_population(db, region_id, base_type)
        elif base_type == 'home':
            if action == 'pluck':
                if user_id:
                    abandon_quarries_and_remove_player_from_map(db, lock_manager, region_id, user_id, reason = 'nuked', dry_run=dry_run)
                elif yes_i_am_sure:
                    abandon_quarries_and_remove_all_players_from_map(db, lock_manager, region_id, reason = 'nuked', dry_run=dry_run)
                else:
                    print 'this is a very destructive operation, add --yes-i-am-sure if you want to proceed!'
            elif action == 'weed':
                weed_churned_players(db, lock_manager, region_id, threshold_days, skip_quarry_owners = skip_quarry_owners, dry_run=dry_run)
            else:
                print 'unknown action '+action
        elif base_type == 'squad':
            if action == 'recall':
                if base_id is not None:
                    recall_squad(db, lock_manager, region_id, int(base_id.split('_')[0][1:]), base_id, dry_run=dry_run)
                else:
                    print 'please specify base_id'
            elif action == 'resolve':
                assert base_id is None
                resolve_raid_squads(db, lock_manager, region_id, dry_run=dry_run)

            else:
                print 'unknown action '+action
        elif base_type == 'hive':
            if action == 'spawn':
                spawn_all_hives(db, lock_manager, region_id, force_rotation=force_rotation, dry_run=dry_run)
            elif action == 'expire':
                expire_all_hives(db, lock_manager, region_id, dry_run=dry_run)
            elif action == 'weed':
                weed_expired_bases(db, lock_manager, region_id, ['hive'], dry_run=dry_run)
            else:
                print 'unknown action '+action
        elif base_type == 'raid':
            if action == 'spawn':
                spawn_all_raids(db, lock_manager, region_id, dry_run=dry_run)
            else:
                print 'unknown action '+action
        elif base_type == 'quarry':
            if action == 'spawn':
                spawn_all_quarries(db, lock_manager, region_id, force_rotation=force_rotation, dry_run=dry_run)
            elif action == 'extend':
                extend_all_quarries(db, lock_manager, region_id, dry_run=dry_run)
            elif action == 'expire':
                if base_id is not None:
                    expire_quarry(db, lock_manager, region_id, base_id, None, dry_run=dry_run)
                else:
                    if yes_i_am_sure:
                        expire_all_quarries(db, lock_manager, region_id, dry_run=dry_run)
                    else:
                        print 'this is a very destructive operation, add --yes-i-am-sure if you want to proceed!'
            elif action == 'weed':
                weed_expired_bases(db, lock_manager, region_id, ['quarry'], dry_run=dry_run)
            elif action == 'abandon':
                if base_id is not None:
                    abandon_quarry(db, lock_manager, region_id, base_id, dry_run=dry_run)
                else:
                    print 'must specify base_id for action', action
            else:
                print 'unknown action '+action
        else:
            print 'unknown base type '+base_type
    finally:
        lock_manager.release_all()
        if chat_client:
            chat_client.disconnect()
            chat_client = None

    sys.exit(0)
