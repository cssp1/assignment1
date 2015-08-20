#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import re, os
import time, calendar, urllib
import SpinJSON


# Unfortuantely the load() functions duplicate much of what preprocess.py does. We should eventually unify them.

# regular expression that matches C++-style comments (see gamedata/preprocess.py for a better explanation)
comment_remover = re.compile('(?<!tp:|ps:|: "|":"|=\\\\")//.*?$')
slurp_detector = re.compile('@"([^"]+)"')
include_detector = re.compile('^#include "(.+)"')
include_stripped_detector = re.compile('^#include_stripped "(.+)"')

# returns UTF8 string
def load_fd_raw(fd, stripped = False, verbose = False, path = None, override_game_id = None):
    js = ''
    contents_cache = {}
    for line in fd:
        line = comment_remover.sub('', line)
        # look for @"filename" and replace with "contents-of-that-file"
        match = slurp_detector.search(line)
        if match:
            filename = match.group(1).replace('$HOME', os.getenv('HOME'))
            if filename in contents_cache:
                contents = contents_cache[filename]
            else:
                try:
                    contents = open(filename).read().strip()
                except:
                    if verbose:
                        sys.stderr.write('config file "%s" is missing\n' % filename)
                    contents = '' # silently continue with empty field

                contents_cache[filename] = contents
            line = slurp_detector.sub('"'+contents+'"', line)

        # detect #include directives
        include_match = include_detector.search(line)
        include_stripped_match = include_stripped_detector.search(line)
        match = include_match or include_stripped_match
        if match:
            assert path

            # get the name of the file to include from the regular expression
            filename = os.path.join(path, match.group(1))

            if '$GAME_ID' in filename:
                filename = filename.replace('$GAME_ID', game(override_game_id = override_game_id))

            # replace the line with the contents of the included file
            line = load_fd_raw(open(filename), stripped = (match is include_stripped_match), path = os.path.dirname(filename))

        js += line
    if stripped:
        js = '{'+js+'}'
    return js

# returns JSON object
def load_fd(fd, stripped = False, verbose = False, path = None, override_game_id = None):
    raw = load_fd_raw(fd, stripped, verbose, path, override_game_id = override_game_id)
    return SpinJSON.loads(raw)

def load(filename, stripped = False, verbose = False, override_game_id = None):
    return load_fd(open(filename), stripped = stripped, verbose = verbose, path = os.path.dirname(filename), override_game_id = override_game_id)

def gameserver_dir():
    e = os.getenv('SPIN_GAMESERVER')
    if e: return e
    return '../gameserver'

# global, used by code that imports SpinConfig
config = load(os.path.join(gameserver_dir(), 'config.json'))

def reload():
    # reload config file
    global config
    try:
        new_config = load(os.path.join(gameserver_dir(), 'config.json'))
        config = new_config
    except:
        pass

# return identifier for this game (e.g. "mf" or "tr")
def game(override_game_id = None):
    if override_game_id:
        id = override_game_id
    else:
        id = config['game_id']
    # strip off "test" suffix
    if id.endswith('test'):
        id = id[:-4]
    return id

def game_id_long(override_game_id = None):
    id = game(override_game_id=override_game_id)
    return {'mf':'marsfrontier',
            'mf2':'marsfrontier2',
            'tr':'thunderrun',
            'bfm':'battlefrontmars',
            'dv':'daysofvalor',
            'sg':'summonersgate',
            'em':'warclanempire'}[id]

# return the path (relative to gameserver/) of the master gamedata file
def gamedata_filename(extension = '.json', locale = None, override_game_id = None):
    if override_game_id:
        gid = override_game_id
    else:
        gid = game()
    return os.path.join(gameserver_dir(), '../gamedata/%s/built/gamedata-%s%s%s' % (gid, gid, ('-'+locale) if locale else '', extension))

# return the path (relative to gameserver/) to a single included gamedata source file
def gamedata_component_filename(name, override_game_id = None):
    if override_game_id:
        game_id = override_game_id
    else:
        game_id = game()

    # check overlay built first
    trial = os.path.join(gameserver_dir(), '../gamedata/%s/built/%s_%s' % (game_id, game_id, name))
    if os.path.exists(trial): return trial

    # check overlay non-built second
    trial = os.path.join(gameserver_dir(), '../gamedata/%s/%s_%s' % (game_id, game_id, name))
    if os.path.exists(trial): return trial

    return os.path.join(gameserver_dir(), '../gamedata/%s' % name)

# return (bucket, prefix) for upcache files in S3
def upcache_s3_location(game_id):
    return 'spinpunch-upcache', '%s-upcache' % game_id_long(game_id)

# return default location to look for this computer's AWS key file
def aws_key_file():
    my_hostname = os.uname()[1].split('.')[0]
    return os.path.join(os.getenv('HOME'), '.ssh', my_hostname+'-awssecret')

# gamedata locales to check for a specific user locale, in order of preference
def locales_to_try(locale):
    if locale == 'null': return [None] # developer override
    return [locale, 'en_US', None]

# misc. global tables (might want to move these to SpinUpcache later)

# COUNTRY TIERS - reflect average level of AD BID PRICES
# targeting based on http://nanigansblog.files.wordpress.com/2012/02/nanigans_facebookcountrytargeting_cpcreach3.png
# NOTE: some small countries (Bahrain, Brunei, etc) are omitted, they will be assigned to Tier 4
country_tier_map = {
'at': 1, 'dk': 1, 'fi': 1, 'gb': 1, 'nl': 1, 'no': 1, 'nz': 1, 'za': 1, 'au': 1, 'se': 1,
'ca': 2, 'us': 2,
'be': 3, 'br': 3, 'ch': 3, 'de': 3, 'es': 3, 'fr': 3, 'gr': 3, 'hk': 3, 'hu': 3, 'ie': 3, 'il': 3, 'it': 3, 'pe': 3, 'pr': 3, 'pt': 3, 'ro': 3, 'sa': 3, 'sg': 3, 'sk': 3, 've': 3,
'al': 4, 'ar': 4, 'ba': 4, 'bg': 4, 'cl': 4, 'co': 4, 'cr': 4, 'do': 4, 'dz': 4, 'eg': 4, 'ge': 4, 'gt': 4, 'hr': 4, 'id': 4, 'in': 4, 'jo': 4, 'lt': 4, 'ma': 4, 'me': 4, 'mk': 4, 'mx': 4, 'my': 4, 'ng': 4, 'pa': 4, 'ph': 4, 'pk': 4, 'pl': 4, 'rs': 4, 'sv': 4, 'th': 4, 'tn': 4, 'tr': 4, 'vn': 4,
'kr': 4, # for English-language games at least
'ae': 4, 'am': 4, 'ax': 4, 'ba': 4
}

# PRICE REGIONS - reflect average willingness to pay/price elasticity groups
price_region_map = {
'at': 'A', 'dk': 'A', 'fi': 'A', 'gb': 'A', 'nl': 'A', 'no': 'A', 'nz': 'A', 'za': 'A', 'au': 'A', 'se': 'A', 'kw': 'A', 'gg': 'A', 'im': 'A', 'qa': 'A', 'bh': 'A', 'mq': 'A',
'ca': 'B', 'us': 'B', 'is': 'B', 'ly': 'B', 'kr': 'B', 'tw': 'B',
'be': 'C', 'br': 'C', 'ch': 'C', 'de': 'C', 'es': 'C', 'fr': 'C', 'gr': 'C', 'hk': 'C', 'hu': 'C', 'ie': 'C', 'il': 'C', 'it': 'C', 'pe': 'C', 'pr': 'C', 'pt': 'C', 'ro': 'C', 'sa': 'C', 'sg': 'C', 'sk': 'C', 've': 'C',
'al': 'D', 'ar': 'D', 'ba': 'D', 'bg': 'D', 'cl': 'D', 'co': 'D', 'cr': 'D', 'do': 'D', 'dz': 'D', 'eg': 'D', 'ge': 'D', 'gt': 'D', 'hr': 'D', 'id': 'D', 'in': 'D', 'jo': 'D', 'lt': 'D', 'ma': 'D', 'me': 'D', 'mk': 'D', 'mx': 'D', 'my': 'D', 'ng': 'D', 'pa': 'D', 'ph': 'D', 'pk': 'D', 'pl': 'D', 'rs': 'D', 'sv': 'D', 'th': 'D', 'tn': 'D', 'tr': 'D', 'vn': 'D',
'ae': 'D', 'am': 'D', 'ax': 'D', 'ba': 'D', 'lb': 'D', 'np': 'D'
}

# FACAEBOOK GAME FAN PAGES - dictionary of fan page IDs for strategy games, to track user "likes"
FACEBOOK_GAME_FAN_PAGES_VERSION = 2 # increment this number each time a change is made, to avoid trusting stale data in upcache
FACEBOOK_GAME_FAN_PAGES = {
    'mars_frontier':'235938246460875',
    'thunder_run':'141835099310946',
    'war_star_empire':'633274570056000',
    'thunder_run_days_of_valor':'294870984023668',
    'battlefront_mars':'1436033100000042',
    'summoners_gate':'653216284776703',
    'war_commander':'166402620131249',
    'battle_pirates':'323061097715783',
    'total_domination':'330939280268735',
    'edgeworld':'329450857071583',
    'vega_conflict':'349144321859865',
    'light_nova':'153463478093125',
    'wasteland_empires':'151467404968108',
    'soldiers_inc':'482177521871037',
    'warzone':'172417542894731',
    'contract_wars':'207598916027565',
    'admiral':'321969256735',
    'ninja_kingdom':'170996059738810',
    'throne_rush':'221609908005798',
    'backyard_monsters':'304561816235995',
    'knights_clash_heroes':'180681162111398',
    'under_fire':'641964019177419',
    'dragons_of_atlantis':'325789367434394',
    'kingdoms_of_camelot':'308882969123771',
    'pirates_tides_of_fortune':'109358109188776',
    'social_empires':'162772593825182',
    'war_mercenaries':'105098466327305',
    'clash_of_clans':'447775968580065',
    'sparta_war_of_empires':'674913419214092',
    'jungle_heat':'642817249078505',
    'battlefront_heroes':'127918567418514',
    'red_crucible_2':'126605594124234',
    'stormfall_age_of_war':'450552231662626',
    'boom_beach':'249340185214120',
    'world_of_tanks':'494440040376',
    'war_thunder':'362712050429431'
    }


def game_launch_date(override_game_id = None):
    return { 'mf': 1326794980, # 2012 Jan 17
             'tr': 1368662400, # (1368662400) 2013 May 16 Turkey test release, (1369891026) 2013 May 30 -Tier 1/2 release
             'mf2': 1388096233, # 2013 Dec 26 - Tier 1/2 release
             'bfm': 1407024000, # (1403728087) 2014 June 26 - Tier 4 release, (1407024000) 2014 August 3 - Tier 1/2 release
             'sg': 1414403421, # (1414403421) 2014 Oct 27 server set up, but not opened yet
             'dv': 1440046752, # Un-sandboxed Thu Aug 20 04:59:32 UTC 201
             }[override_game_id or game()]

ACCOUNT_LAPSE_TIME = 7*24*60*60 # consider an account "lapsed" if this much time has passed since last logout
# originally 3 days, changed to 7 days on 2014 Nov 2

# NEW multi-interval account lapse tracking (not all code has been updated for this yet)
ACCOUNT_LAPSE_TIMES = {
    '3d': 3*24*60*60,
    '7d': 7*24*60*60,
    '28d': 28*24*60*60,
    }

AGE_GROUPS = {'17O13': '13-17',
              '24O18': '18-24',
              '34O25': '25-34',
              '44O35': '35-44',
              '54O45': '45-54',
              '64O55': '55-64'}

def years_old_to_age_group(years):
    if years >= 65: return 'MISSING'
    elif years >= 55: return '64O55'
    elif years >= 45: return '54O45'
    elif years >= 35: return '44O35'
    elif years >= 25: return '34O25'
    elif years >= 18: return '24O18'
    elif years >= 13: return '17O13'
    else: return 'MISSING'

# return UNIX time counter for first second of this year/month/day
def cal_to_unix(ymd):
    year, mon, mday = ymd
    return calendar.timegm(time.struct_time([year, mon, mday, 0, 0, 0, -1, -1, -1]))
def unix_to_cal(unix):
    st = time.gmtime(unix)
    return st.tm_year, st.tm_mon, st.tm_mday

def pretty_print_time(sec):
    d = int(sec/86400)
    sec -= 86400*d
    h = int(sec/3600)
    sec -= 3600*h
    m = int(sec/60)
    sec -= 60*m
    ret = ''
    if d > 0:
        ret += '%02dd' % d
    if h > 0:
        ret += '%02dh' % h
    ret += '%02dm%02ds' % (m, sec)
    return ret

# find current PvP season/week/day based on gamedata

# "seasons" = gamedata['matchmaking']['season_starts']
# t = time you want to find the season for
def get_pvp_season(seasons, t):
    for i in xrange(len(seasons)):
        if seasons[i] > t:
            return i
    return len(seasons)

# origin = gamedata['matchmaking']['week_origin']
# t = time you want to find the week for
def get_pvp_week(origin, t):
    return int((t-origin)//(7*24*60*60))

def get_pvp_day(origin, t):
    return int((t-origin)//(24*60*60))



# get mongodb connection info
# returns a dictionary d where
# d['connect_args'], d['connect_kwargs'] are the things you should pass to pymongo.MongoClient() to set up the connection
# d['dbname'] is the database where your stuff is, and d['table_prefix'] should be prepended to all collection names.
def get_mongodb_config(dbname):
    # figure out parent/child relationships and implicit databases
    parents = {}
    implicit = set()
    for name, data in config['mongodb_servers'].iteritems():
        if 'delegate_tables' in data:
            for expr, sub_name in data['delegate_tables'].iteritems():
                parents[sub_name] = data
                if sub_name not in config['mongodb_servers']:
                    implicit.add(sub_name)
    if dbname not in config.get('mongodb_servers',{}) and (dbname not in implicit):
        raise Exception('config.json: no mongodb_servers entry nor implicit entry for db '+dbname)
    return parse_mongodb_config(dbname, config['mongodb_servers'].get(dbname, {}), parent = parents.get(dbname, None))

# get name for child instance that handles a specific table
def get_mongodb_delegate_for_table(dbconfig, table_name):
    for delegate_re, delegate_name in dbconfig.get('delegate_tables',{}).iteritems():
        if re.compile(delegate_re).match(table_name):
            return delegate_name
    return None

def get_credentials(filename):
    filename = filename.replace('$HOME', os.getenv('HOME'))
    try:
        fd = open(filename, 'r')
        username = fd.readline().strip()
        password = fd.readline().strip()
    except Exception as e:
        raise Exception('config.json: error reading credentials file %s: %s' % (filename, e))
    return username, password

def parse_mongodb_config(dbname, cfg, parent = None):
    if parent is None: parent = {}
    dbname = cfg.get('dbname', dbname) # note! parent's dbname does NOT override this!
    credentials = cfg.get('credentials', parent.get('credentials', None))
    if credentials:
        username, password = get_credentials(credentials)
    else:
        username = cfg.get('username', parent.get('username', None))
        password = cfg.get('password', parent.get('password', None))
    host = cfg.get('host', parent.get('host', None))
    port = cfg.get('port', parent.get('port', 27017))
    if not (host and username and (password is not None)):
        raise Exception('invalid mongodb config for "%s": %s' % (dbname, repr(cfg)))

    table_prefix = cfg.get('table_prefix', parent.get('table_prefix', ''))
    connect_url = 'mongodb://%s:%s@%s:%s/%s' % tuple([urllib.quote(x, '') for x in [username,password,host,str(port),dbname]])
    return {'connect_args':[], 'connect_kwargs':{'host':connect_url},
            'host':host, 'port':port, 'username':username, 'password':password,
            'dbname': dbname, 'table_prefix': table_prefix, 'delegate_tables':cfg.get('delegate_tables',parent.get('delegate_tables', {})),
            'maintenance_window': cfg.get('maintenance_window',None)}

def get_mysql_config(dbname):
    if dbname not in config.get('mysql_servers',{}):
        raise Exception('config.json: no mysql_servers entry for db '+dbname)
    return parse_mysql_config(dbname, config['mysql_servers'][dbname])
def parse_mysql_config(dbname, cfg):
    dbname = cfg.get('dbname', dbname)
    if 'credentials' in cfg:
        username, password = get_credentials(cfg['credentials'])
    else:
        username = cfg['username']
        password = cfg['password']
    port = cfg.get('port',3306)
    table_prefix = cfg.get('table_prefix', '')
    return {'connect_args':(cfg['host'], username, password, dbname), 'connect_kwargs':{'use_unicode': True, 'charset': 'utf8'},
            'host':cfg['host'], 'port':port, 'username':username, 'password':password,
            'dbname': dbname, 'table_prefix': table_prefix, 'maintenance_window': cfg.get('maintenance_window',None)}

def get_pgsql_config(dbname):
    if dbname not in config.get('pgsql_servers',{}):
        raise Exception('config.json: no pgsql_servers entry for db '+dbname)
    return parse_pgsql_config(dbname, config['pgsql_servers'][dbname])
def parse_pgsql_config(dbname, cfg):
    dbname = cfg.get('dbname', dbname)
    if 'credentials' in cfg:
        username, password = get_credentials(cfg['credentials'])
    else:
        username = cfg['username']
        password = cfg['password']
    port = cfg.get('port',5432)
    table_prefix = cfg.get('table_prefix', '')
    return {'connect_args':['host=%s user=%s password=%s dbname=%s client_encoding=UTF8' % (cfg['host'], username, password, dbname)], 'connect_kwargs':{},
            'host':cfg['host'], 'port':port, 'username':username, 'password':password,
            'dbname': dbname, 'table_prefix': table_prefix, 'maintenance_window': cfg.get('maintenance_window',None)}

# check if current time is within db config maintenance window
def in_maintenance_window(cfg, time_now = None):
    if not cfg['maintenance_window']: return False
    if time_now is None: time_now = int(time.time())
    st = time.gmtime(time_now)
    today_range = [calendar.timegm(time.struct_time([st.tm_year, st.tm_mon, st.tm_mday, hm[0], hm[1], 0, -1,-1,-1])) for hm in cfg['maintenance_window']['daily']]
    #print time_now, today_range
    return (time_now >= today_range[0] and time_now < today_range[1])


if __name__ == '__main__':
    if 1:
        cfg = {'maintenance_window': { 'daily': [[6,0],[7,30]] } }
        assert not in_maintenance_window(cfg, 1397515997)
        assert in_maintenance_window(cfg, 1397544797)

    import sys, getopt
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['get','put','force','launch-date'])
    mode = 'test'
    force = False
    for key, val in opts:
        if key == '--get': mode = 'get'
        elif key == '--put': mode = 'put'
        elif key == '--force': force = True
        elif key == '--launch-date': mode = 'launch-date'

    if mode in ('get','put'):
        import SpinS3
        s3 = SpinS3.S3(aws_key_file(), verbose=False, use_ssl=True)
        s3_bucket = 'spinpunch-config'
        s3_name = 'config-%s.json' % game_id_long()
        s3_mtime = s3.exists('spinpunch-config', s3_name)
        local_mtime = os.path.getmtime('config.json')

    if mode == 'get':
        if s3_mtime and (local_mtime > s3_mtime) and (not force):
            print 'refusing to overwrite more recent local file. Use --force to override.'
            sys.exit(1)
        s3.get_file(s3_bucket, s3_name, 'config.json')
        print 'downloaded', s3_name, 'to config.json'
    elif mode == 'put':
        if s3_mtime and (local_mtime < s3_mtime) and (not force):
            print 'refusing to overwrite more recent file in S3. Use --force to override.'
            sys.exit(1)
        s3.put_file(s3_bucket, s3_name, 'config.json', streaming = False)
        print 'uploaded config.json to', s3_name
    elif mode == 'launch-date':
        print game_launch_date()
    else:
        load('config.json', verbose = True)
        print 'config.json OK!'
