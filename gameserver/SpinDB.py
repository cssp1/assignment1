# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# command protocol for client/server db connection

import SpinAmp

default_secret_read_only = 'asdf'
default_secret_full = 'fdsa'

# maximum byte length of individual requests or responses, set by AMP protocol
MSG_LIMIT = 60000

# the old player_lock_* functions are emulated by the new lock_* functions by passing 'pUSERID' as the lock_id
def emulate_player_lock_id(user_id): return 'p%d' % user_id

# ID of global lock corresponding to a base
def base_lock_id(region_id, base_id): return 'b'+region_id+':'+base_id
def is_base_lock_id(lock_id): return lock_id[0]=='b'
def parse_base_lock_id(lock_id):
    assert is_base_lock_id(lock_id)
    # returns region_id, base_id
    return lock_id[1:].split(':')


def encode_query_field(x):
    if isinstance(x, int):
        return 'd'+str(x)
    elif isinstance(x, float):
        return 'f'+str(x)
    elif isinstance(x, str) or isinstance(x, unicode):
        assert ':' not in x # prevent injection attacks that mess with delimiter chars
        return 's'+str(x)
    else:
        raise Exception("don't know how to encode "+repr(x))

def decode_query_field(x):
    if x[0] == 'd':
        return int(x[1:])
    elif x[0] == 'f':
        return float(x[1:])
    elif x[0] == 's':
        return x[1:]
    else:
        raise Exception("don't know how to decode "+x)

# although these are just Twisted AMP Commands, we must define them
# generically because they are used by both the server side (under
# twisted.protocols.amp) and client side - under the ampy module, which
# is not compatible with Twisted's objects.

commands = {
    'authenticate': { 'arguments': [['secret', 'string'],
                                    ['identity', 'string']],
                      'response': [['state', 'integer']]
                      },

    'get_user_id_range': { 'arguments': [],
                           'response': [['min', 'integer'], ['max', 'integer']] },

    'facebook_id_lookup_single': { 'arguments': [['facebook_id', 'string'],
                                                 ['add_if_missing', 'boolean']],
                                   'response': [['user_id', 'integer']]
                                   },
    'facebook_id_lookup_batch': { 'arguments': [['facebook_ids', 'string'], # strings separated by ':'
                                                ['add_if_missing', 'boolean']],
                                  'response': [['user_ids', 'string']] # ints separated by ':'
                                  },

    # PLAYERDB/BASEDB LOCKING
    # Note: userdb is not really protected by locks, since it is more of a cache, and only written on logout
    'lock_release': { 'arguments': [['lock_id', 'string'],
                                    # generation number to compare on next lock_acquire_attack()
                                    # -1 means "no update"
                                    # IF YOU MODIFY ANY STATE, YOU MUST PASS IN THE INCREMENTED GENERATION HERE
                                    # otherwise other players spying on you with stale data might acquire an attack lock and overwrite the changes!
                                    ['generation', 'integer'],
                                    ['expected_state', 'integer'],
                                    ['expected_owner_id', 'integer']
                                    ],
                      'response': [['state', 'integer']] },

    # prevent lock from timing out, and update generation numbers. Also optionally check for new player mail messages.
    'lock_keepalive_batch': { 'arguments': [['lock_ids', 'string'], # strings separated by ':'
                                            ['generations', 'string'], # ints separated by ':'
                                            ['expected_states', 'string'], # ints separated by ':'
                                            ['check_messages', 'boolean']],
                              'response': [['messages', 'string']] }, # ints separated by ':', 1 if message pending, 0 otherwise

    # get current lock state
    'lock_get_state_batch': { 'arguments': [['lock_ids', 'string']], # strings separated by ':'
                              'response': [['states', 'string']] }, # (state,owner) pairs separated by ':' state0:owner0:state1:owner1:...
    # mutually exclusive write lock
    'lock_acquire_login': { 'arguments': [['lock_id', 'string'],
                                          ['owner_id', 'integer']], # user_id of player causing the lock to be taken, -1 if unknown
                            'response': [['state', 'integer'], ['generation', 'integer']] },
    # mutually exclusive write lock, created from an open lock
    'lock_acquire_attack': { 'arguments': [['lock_id', 'string'],
                                           ['owner_id', 'integer'], # user_id of player causing the lock to be taken, -1 if unknown

                                           # before acquiring lock, compare this to the generation submitted on last lock_release
                                           # if a previous lock_release sent a higher generation, fail to acquire the lock
                                           # so that we don't over-write the state with stale data
                                           # -1 skips the comparison
                                           ['generation', 'integer'],

                                           ],
                             'response': [['state', 'integer']] },

    # generic player message queueing system
    # 'msglist' is a list of messages to queue, with fields:
    # 'to': list of recipient user_ids
    # 'critical': bool, whether or not to prevent the message from being pruned/garbage-collected
    # 'unique_per_sender': string, if non-empty, replace any pre-existing message from this sender (with matching unique_per_sender value) with this one
    # 'type': string, mandatory for dispatching
    # the dbserver will add its own 'msg_id' value to the message
    'msg_send': { 'arguments': [['msglist', 'unicode']], # JSON format
                  'response': [['success', 'boolean']] },

    # receive all messages for a player as a JSON list. Optionally uses the "long result" mechanism.
    'msg_recv': { 'arguments': [['to', 'integer'],
                                ['type_filter', 'string'] # ':' separated list of message types to retrieve, defaults to all if blank
                                ],
                  # returns JSON list of messages in "result" if it fits in a single packet, otherwise use "long result" mechanism
                  'response': [['result', 'string'],
                               ['long_len', 'integer']] },

    # confirm receipt and delete queued messages. idlist is the 'msg_id' value from msg_recv results
    'msg_ack': { 'arguments': [['to', 'integer'],
                               ['idlist', 'string']], # msg_ids separated by ':'
                 'response': [['success', 'boolean']] },


    # retrieve a random set of players whose rating values lie within a range
    # uses the "long result" mechanism to return arbitrarily large numbers of IDs
    'player_cache_query': { 'arguments': [['fields', 'string'], # array of fields to query with
                                          ['minima', 'string'], # parallel array of minimum values of each field
                                          ['maxima', 'string'], # parallel array of maximum values of each field
                                          ['operators','string'], # parallel array of comparison operators ('in','!in')
                                          ['max_ret', 'integer']], # max number of users to return
                               'response': [['result', 'string'], # user_ids separated by ':'
                                            ['long_len', 'integer']]
                               },

    # the "long result" mechanism gets around AMP's stupid 65kb message size limit by buffering a JSON response
    # and then retrieving it in pieces. Of course this means that calls cannot be interleaved.
    'get_long_result': { 'arguments': [['start', 'integer'],
                                       ['end', 'integer'],
                                       ['finish', 'boolean']],
                         'response': [['substr', 'string']] },

    # the "player cache" maintains a (possibly inaccurate and out-of-date) cache of certain player/user database
    # fields that the game server needs to access very efficiently (e.g. when populating friend info on login)
    'player_cache_update': { 'arguments': [['user_id', 'integer'],
                                           ['props', 'unicode'],
                                           ['overwrite', 'boolean']],
                             'response': [['success', 'boolean']] },
    'player_cache_lookup_batch': { 'arguments': [['user_ids', 'string'], # ints separated by ':'
                                                 ['fields', 'string']], # :-separated array of fields to get, blank for all
                                   'response': [['result', 'unicode'], # JSON list of properties
                                                ['long_len', 'integer']]
                                   },

    # get score rankings of particular players
    'player_cache_get_scores': { 'arguments': [['user_ids', 'string'], # :-separated array of user IDs
                                               ['fields', 'string']], # :-separated array of score_* fields to query
                                 'response': [['result', 'unicode'], # JSON format: per-user array of [{'absolute':1234567,'rank':2,'percentile':0.242}, ...] parallel array to 'fields'
                                              ['long_len', 'integer']]
                                 },
    # get identities and rankings of top-ranked players
    'player_cache_get_leaders': { 'arguments': [['field', 'string'], # score_* field to query
                                                ['max_ret', 'integer']], # number of results to return
                                  'response': [['result', 'unicode']] # JSON format: [array of {absolute/user_id/facebook_first_name/facebook_id}, in rank order]
                                  },

    # the dbserver keeps track of how many users have been assigned to each cohort for each A/B test
    # this function attempts to assign a user up to the limits specified, returns 1 or 0 for success on each test
    'abtest_join_cohorts': { 'arguments': [['tests', 'string'], # array of strings separated by ':'
                                           ['cohorts', 'string'], # array of strings separated by ':'
                                           ['limits', 'string']], # array of ints separated by ':'
                             'response': [['results', 'string']] # 1 of 0 separated by ':'
                             },

    'map_region_create': { 'arguments': [['region_id', 'string']],
                           'response': [['success', 'boolean']] },
    'map_region_drop': { 'arguments': [['region_id', 'string']],
                         'response': [['success', 'boolean']] },

    # the "map cache" maintains the official map territory information that says what feature (base or squad) is where
    'map_cache_update': { 'arguments': [['region_id', 'string'],
                                        ['base_id', 'string'],
                                        ['props', 'unicode'],  # JSON to associate with base_id
                                        ['exclusive', 'integer'], # fail if something already exists within N radius of base_map_loc
                                        ],
                          'response': [['success', 'boolean']] },
    # lock/unlock mutex on map feature
    'map_cache_lock_acquire': { 'arguments': [['region_id', 'string'],
                                              ['base_id', 'string'],
                                              ['owner_id', 'integer'], # user_id of player causing the lock to be taken, -1 if unknown
                                              ['generation', 'integer'],
                                              ],
                                'response': [['state', 'integer']] },
    'map_cache_lock_keepalive_batch': { 'arguments': [['region_id', 'string'], # strings separated by ':'
                                                      ['base_ids', 'string'], # strings separated by ':'
                                                      ['generations', 'string']], # ints separated by ':'
                                        'response': [['success', 'boolean']] },
    'map_cache_lock_release': { 'arguments': [['region_id', 'string'],
                                              ['base_id', 'string'],
                                              ['generation', 'integer'],
                                              ['expected_owner_id', 'integer']
                                              ],
                                'response': [['state', 'integer']] },
    'map_cache_query': { 'arguments': [['region_id', 'string'],
                                       ['fields', 'string'], # array of fields to query with
                                       ['minima', 'string'], # parallel array of minimum values of each field (using encode_query_field())
                                       ['maxima', 'string'], # parallel array of maximum values of each field (using encode_query_field())
                                       ['updated_since', 'integer'], # if >0, only return bases updated since this time, (INCLUDING deleted bases)
                                       ['max_ret', 'integer']], # max number of bases to return
                         'response': [['result', 'unicode'], # JSON list of [base1properties, base2properties, ...]
                                                             # NOTE: a deleted base will have properties {"base_id": "xxx", "DELETED": 1}
                                      ['long_len', 'integer'], # if result does not fit in a single AMP packet, long_len will be >0 and you'll have
                                                               # to call get_long_result() to retrieve it
                                      ['db_time', 'integer'] # database clock time when response was generated
                                      ]
                         },

    # same as map_cache_query, except it only returns the number of entries that satisfy the query,
    # but it returns that number for ALL regions, in the form {"region1": count1, "region2": count2, ... }
    'map_cache_population_query': { 'arguments': [['fields', 'string'],
                                                  ['minima', 'string'],
                                                  ['maxima', 'string']],
                                    'response': [['result', 'unicode'],
                                                 ['long_len', 'integer']]
                                    },

    'map_cache_occupancy_check': { 'arguments': [['region_id', 'string'],
                                                 ['coordlist', 'string']],
                                    'response': [['blocked', 'boolean']]
                                    }
}

# users must call either init_for_twisted_amp() or init_for_ampy(), which
# fills CMD with the instantiated Command objects appropriate for that API

CMD = {}

def init_for_twisted_amp():
    global CMD
    CMD = SpinAmp.init_for_twisted_amp(commands)
def init_for_ampy():
    global CMD
    CMD = SpinAmp.init_for_ampy(commands)

