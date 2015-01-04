#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# tool for managing bases/quarries/hives on the Regional Map

import SpinSyncChatClient
import SpinNoSQL
import SpinUserDB
import SpinConfig
import SpinJSON
import SpinNoSQLId
from Region import Region
import Sobol
import sys, getopt, time, random, copy

time_now = int(time.time())
event_time_override = None
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
gamedata['ai_bases'] = SpinConfig.load(SpinConfig.gamedata_component_filename("ai_bases_compiled.json"))

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
                 'spec': obj['spec'],
                 'xy': obj['xy'], }
        if obj.get('level',1) != 1: props['level'] = obj['level']
        for FIELD in ('orders','patrol','equipment','produce_start_time','produce_rate','contents'):
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
                      'upgrade_total_time', 'upgrade_start_time', 'upgrade_done_time',
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

class LockManager (object):
    SETUP_LOCK_OWNER = 667 # fake user_id we will use to take locks with
    BEING_ATTACKED = 2 # lock state constant

    def __init__(self, db, dry_run):
        self.db = db
        self.dry_run = dry_run
        self.locks = {}
        self.player_locks = {}
        self.verbose = 0
    def acquire(self, region_id, base_id):
        lock = (region_id, base_id)
        if self.dry_run: return True
        if nosql_client.map_feature_lock_acquire(region_id, base_id, self.SETUP_LOCK_OWNER) != self.BEING_ATTACKED:
            if self.verbose: print 'ACQUIRE (fail) ', lock
            return False
        if self.verbose: print 'ACQUIRE', lock
        self.locks[lock] = 1
        return True
    def create(self, region, base_id):
        lock = (region_id, base_id)
        if self.dry_run: return
        if self.verbose: print 'CREATE', lock
        self.locks[lock] = 1
    def acquire_player(self, user_id):
        if self.dry_run: return True
        if nosql_client.player_lock_acquire_attack(user_id, -1, owner_id = self.SETUP_LOCK_OWNER) != self.BEING_ATTACKED:
            if self.verbose: print 'ACQUIRE PLAYER (fail)', user_id
            return False
        if self.verbose: print 'ACQUIRE PLAYER', user_id
        self.player_locks[user_id] = 1
        return True
    def forget(self, region_id, base_id):
        if self.dry_run: return
        lock = (region_id, base_id)
        del self.locks[lock]
    def release(self, region_id, base_id, base_generation = -1):
        if self.dry_run: return
        lock = (region_id, base_id)
        del self.locks[lock]
        if self.verbose: print 'RELEASE', lock
        nosql_client.map_feature_lock_release(region_id, base_id, self.SETUP_LOCK_OWNER, generation = base_generation)
    def release_player(self, user_id, generation = -1):
        if self.dry_run: return
        del self.player_locks[user_id]
        if self.verbose: print 'RELEASE PLAYER', user_id
        nosql_client.player_lock_release(user_id, generation, self.BEING_ATTACKED, expected_owner_id = self.SETUP_LOCK_OWNER)
    def release_all(self):
        for lock in self.locks.keys():
            self.release(lock[0], lock[1])
        for user_id in self.player_locks.keys():
            self.release_player(user_id)

def get_existing_map_by_type(db, region_id, base_type):
    return dict([(x['base_id'], x) for x in nosql_client.get_map_features_by_type(region_id, base_type)])
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

def clear_base(db, lock_manager, region_id, base_id, dry_run = True):
    print 'CLEAR', base_id
    if not dry_run:
        if not lock_manager.acquire(region_id, base_id):
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

def auto_level_hive_objects(objlist, owner_level, owner_tech, xform):
    ret = []
    powerplants = []
    for src in objlist:
        spec_name = src['spec']
        spec = gamedata['units'][spec_name] if spec_name in gamedata['units'] else gamedata['buildings'][spec_name]

        dst = {'obj_id': nosql_id_generator.generate(), 'xy':transform(xform, src['xy']), 'spec':spec['name']}
        if 'orders' in src:
            dst['orders'] = []
            for order in src['orders']:
                if 'dest' in order:
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
    if user_id < 1100: return # AI user

    # first try to refund units directly to my_base - if it works, don't send them as attachments
    if feature['base_type'] == 'squad':
        to_add = []
        squad_id = int(feature['base_id'].split('_')[1])
        for obj in objlist:
            if obj['spec'] not in gamedata['units']: continue
            props = {'spec': obj['spec'],
                     'xy': [90,90],
                     'squad_id': squad_id}
            for FIELD in ('obj_id', 'hp_ratio', 'level'):
                if FIELD in obj:
                    props[FIELD] = obj[FIELD]
            to_add.append(props)

        if to_add and lock_manager.acquire_player(user_id):
            try:
                player_data = SpinJSON.loads(SpinUserDB.driver.sync_download_player(user_id))

                # force items with squad_ids not in player.squads into reserves, to avoid accidentally giving the player more squads than allowed
                player_squads = player_data.get('squads',{})
                for item in to_add:
                    if str(item['squad_id']) not in player_squads:
                        item['squad_id'] = -1

                if verbose: print 'REFUND (my_base)', pretty_feature(feature), 'to', user_id, repr(to_add)
                player_data['my_base'] += to_add
                player_data['generation'] = player_data.get('generation',0)+1

                if not dry_run:
                    SpinUserDB.driver.sync_write_player(user_id, SpinJSON.dumps(player_data, pretty=True, newline=True, double_precision=5))

                objlist = [] # hand off ownership to avoid duping

            finally:
                lock_manager.release_player(user_id, generation = player_data.get('generation',-1))

    units = {}
    to_remove = []
    for obj_data in objlist:
        if obj_data['spec'] not in gamedata['units']: continue
        spec = gamedata['units'][obj_data['spec']]
        units[spec['name']] = 1 + units.get(spec['name'],0)
        to_remove.append(obj_data)

    attachments = []
    for name, qty in units.iteritems():
        item_name = 'packaged_'+name
        item_spec = gamedata['items'][item_name]
        while qty > 0:
            stack = min(qty, item_spec.get('stack_max',1))
            at = {'spec':item_name}
            if stack > 1: at['stack'] = stack
            attachments.append(at)
            qty -= stack

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
        # send the mail and do the object removal as atomically as possible to avoid duping
        nosql_client.msg_send([message])
        for obj_data in to_remove: objlist.remove(obj_data)
        nosql_client.drop_mobile_objects_by_base(region_id, feature['base_id'])

def expire_all_quarries(db, lock_manager, region_id, dry_run = True):
    map_cache = get_existing_map_by_type(db, region_id, 'quarry')
    for base_id, feature in map_cache.iteritems():
        expire_quarry(db, lock_manager, region_id, base_id, feature, dry_run = dry_run)

def expire_quarry(db, lock_manager, region_id, base_id, feature, dry_run = True):
    print 'EXPIRING', pretty_feature(feature)

    if not lock_manager.acquire(region_id, base_id):
        print '(locked, skipping)'
        return

    objlist = nosql_read_all_objects(region_id, base_id, feature.get('base_landlord_id',-1)) # actually only needs mobile objects

    refund_units(db, region_id, feature, objlist, feature.get('base_landlord_id',-1), ui_name = feature.get('base_ui_name','unknown'), days_to_claim = 7, reason = 'expired', dry_run = dry_run)

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

    refund_units(db, region_id, feature, base_objects, owner_id, ui_name = feature.get('base_ui_name','unknown'), days_to_claim = days_to_claim_units, reason = 'abandoned', dry_run = dry_run)

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
    if (not gamedata['regions'][region_id].get('spawn_quarries',True)): return
    map_cache = get_existing_map_by_type(db, region_id, 'quarry')
    quarries = SpinConfig.load(SpinConfig.gamedata_component_filename("quarries_compiled.json"))
    name_idx = 0

    spawn_list = quarries.get('spawn_for_'+region_id, quarries['spawn'])
    for spawn_data in spawn_list:
        if not spawn_data.get('active',1): continue
        template = quarries['templates'][spawn_data['template']]
        resource = spawn_data['resource']
        distribution = spawn_data.get('distribution', {'func':'uniform'})
        id_start = spawn_data['id_start']
        qty = spawn_data['num']

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

        if do_spawn:
            for i in xrange(qty):
                if spawn_quarry(quarries, map_cache, db, lock_manager, region_id, (id_start+i), i, name_idx, distribution, spawn_data['template'], template,
                                resource,
                                start_time = start_time, end_time = end_time,
                                force_rotation = force_rotation, dry_run = dry_run):
                    do_throttle()
                name_idx += 1
        else:
            if verbose: print 'not spawning quarry template', spawn_data['template'], 'because current time is outside its start/end_time range(s)'

def spawn_quarry(quarries, map_cache, db, lock_manager, region_id, id_num, id_serial, name_idx, distribution, template_name, template, resource,
                 start_time = -1, end_time = -1, force_rotation = False,
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
        owner_tech = gamedata['ai_bases']['bases'][str(owner_id)].get('tech',{})

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
                if 'dest' in order:
                    order = copy.copy(order)
                    order['dest'] = transform(xform, order['dest'])
                obj['orders'].append(order)

        if 'patrol' in p: obj['patrol'] = p['patrol']
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
    map_dims = gamedata['regions'][region_id]['dimensions']
    bzone = max(gamedata['territory']['border_zone_ai'], 2)
    if distribution['func'] == 'uniform':
        sample_loc = [int(bzone + (map_dims[D] - 2*bzone)*random.random()) for D in xrange(2)]
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
        if nosql_client.create_map_feature(region_id, base_id, base_info, originator = LockManager.SETUP_LOCK_OWNER, exclusive = 1):
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
                                            'aura_strength': aura['strength']}])

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
    if (not gamedata['regions'][region_id].get('spawn_hives',True)): return
    map_cache = get_existing_map_by_type(db, region_id, 'hive')
    hives = SpinConfig.load(SpinConfig.gamedata_component_filename("hives_compiled.json"))
    name_idx = 0

    spawn_list = hives.get('spawn_for_'+region_id, hives['spawn'])
    num_spawned_by_type = {}

    for spawn_data in spawn_list:
        if not spawn_data.get('active',1): continue
        template = hives['templates'][spawn_data['template']]
        id_start = spawn_data['id_start']

        if 'num_by_region' in spawn_data and region_id in spawn_data['num_by_region']:
            base_pop = spawn_data['num_by_region'][region_id]
        else:
            base_pop = spawn_data['num']

        pop = int(hives['region_pop'].get(region_id,1.0)*base_pop)

        # get list of start,end spawn times
        if 'spawn_times' in spawn_data:
            spawn_times = spawn_data['spawn_times']
        else:
            spawn_times = [[spawn_data.get('start_time',-1), spawn_data.get('end_time',-1)]]

        do_spawn = False
        for start_time, end_time in spawn_times:
            # restrict time range by any start/end times provided within the template itself
            if template.get('start_time',-1) > 0:
                start_time = max(start_time, template['start_time']) if (start_time > 0) else template['start_time']
            if template.get('end_time',-1) > 0:
                end_time = min(end_time, template['end_time']) if (end_time > 0) else template['end_time'] # this defaults to [[start_time,end_time]] or [[-1,-1]] if none is specified

            if ((start_time < 0) or ((event_time_override or time_now) >= start_time)) and \
               ((end_time < 0) or ((event_time_override or time_now) < end_time)):
                do_spawn = True # found a valid spawn time
                break

        if do_spawn:
            for i in xrange(pop):
                if spawn_hive(hives, map_cache, db, lock_manager, region_id, (id_start+i), name_idx, spawn_data['template'], template,
                              start_time = start_time, end_time = end_time,
                              force_rotation = force_rotation, dry_run = dry_run):
                    num_spawned_by_type[spawn_data['template']] = num_spawned_by_type.get(spawn_data['template'],0) + 1
                    do_throttle()
                name_idx += 1
        else:
            if verbose: print 'not spawning hive template', spawn_data['template'], 'because current time is outside its start/end_time range(s)'

    num_total = sum(num_spawned_by_type.itervalues(),0)
    if num_total > 0:
        print 'TOTAL SPAWNED %d:' % num_total
        for k in sorted(num_spawned_by_type.keys()):
            print k, num_spawned_by_type[k]


def spawn_hive(hives, map_cache, db, lock_manager, region_id, id_num, name_idx, template_name, template,
               start_time = -1, end_time = -1, force_rotation = False,
               dry_run = True):

    owner_id = template['owner_id']
    owner_level = gamedata['ai_bases']['bases'][str(owner_id)]['resources']['player_level']
    if 'tech' in template:
        owner_tech = template['tech']
    else:
        owner_tech = gamedata['ai_bases']['bases'][str(owner_id)].get('tech', {})

    region_min_level = hives['region_min_level'].get(region_id,0)
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
    if (end_time > 0) and ((event_time_override or time_now) + duration >= end_time):
        duration = min(duration, end_time - (event_time_override or time_now))

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

    for p in template.get('scenery',[]):
        obj = {'obj_id': nosql_id_generator.generate(),
               'spec': rotate_scenery_sprite(xform, p['spec']),
               'xy': transform(xform, p['xy']), 'owner': 'environment' }
        base_data['my_base'].append(obj)

    print 'SPAWNING hive', template_name, pretty_feature(feature)

    success = False

    # place on map with rejection sampling
    map_dims = gamedata['regions'][region_id]['dimensions']
    mid = (int(map_dims[0]/2), int(map_dims[1]/2))
    minrange = 0
    maxrange = map_dims[0]/2 - gamedata['territory']['border_zone_ai']

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
        if nosql_client.create_map_feature(region_id, base_id, feature, originator = LockManager.SETUP_LOCK_OWNER, exclusive = 1):
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

    print 'RECALLED', pretty_feature(feature)
    return True

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
        print 'usage: maptool.py REGION_ID home|hives|quarries ACTION [options]'
        print 'Actions:'
        print '    info          Print info about existing hives or quarries'
        print '    maint         Perform all hourly maintenance (weeding, expiring, spawning)'
        print '    spawn         Spawn hives or quarries as indicated by gamedata JSON, leaving existing unexpired bases alone'
        print '    extend        Extend lifetimes of all existing quarries to last at least quarries["override_duration"] seconds'
        print '    weed          Remove "weeds" (churned players) from the map, abandoning and refunding quarries they own'
        print '    abandon       Have the owner abandon this quarry, refunding units as appropriate'
        print '    expire        Force all quarries to expire immediately, and send units back to owners'
        print '    pluck         Remove a player from the regional map, abandoning and refunding all owned quarries'
        print '    clear         Delete all hives or quarries (DANGEROUS! - requires --yes-i-am-sure flag)'
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

    assert region_id in gamedata['regions']

    if gamedata['regions'][region_id].get('storage','basedb') != 'nosql':
        print "%s: basedb (non nosql) regions are not supported anymore" % region_id
        sys.exit(1)

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']),
                                         map_update_hook = broadcast_map_update,
                                         log_exception_func = lambda x: sys.stderr.write(x+'\n'))
    nosql_client.set_time(time_now)
    db = nosql_client

    lock_manager = LockManager(db, dry_run)

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
            assert base_type == 'ALL'
            print "====== %s ======" % region_id

            # 1. run low-level database maintenance (bust stale locks)
            print "%s: busting stale map feature locks..." % region_id
            nosql_client.do_region_maint(region_id)

            # 2. weed expired bases
            print "%s: weeding expired hives/quarries..." % region_id
            weed_expired_bases(db, lock_manager, region_id, ['hive','quarry'], dry_run=dry_run)

            # 3. weed churned players
            print "%s: weeding players churned for more than %d days..." % (region_id, threshold_days)
            weed_churned_players(db, lock_manager, region_id, threshold_days, skip_quarry_owners = skip_quarry_owners, dry_run=dry_run)

            # 4. weed orphaned squads
            print "%s: weeding orphan squads..." % region_id
            weed_orphan_squads(db, lock_manager, region_id, dry_run=dry_run)

            # 5. weed orphaned units
            print "%s: weeding orphan objects..." % region_id
            weed_orphan_objects(db, lock_manager, region_id, dry_run=dry_run)

            # 6. update turf war
            if 'alliance_turf' in gamedata['quarries_client'] and gamedata['regions'][region_id].get('enable_turf_control',False):
                print "%s: turf update..." % region_id
                update_turf(db, lock_manager, region_id, dry_run=dry_run)

            # 7. respawn hives/quarries
            print "%s: spawning hives..." % region_id
            spawn_all_hives(db, lock_manager, region_id, force_rotation=force_rotation, dry_run=dry_run)
            print "%s: spawning quarries..." % region_id
            spawn_all_quarries(db, lock_manager, region_id, force_rotation=force_rotation, dry_run=dry_run)

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
                    print 'please specitfy base_id'
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
