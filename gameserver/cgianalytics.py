#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# CGI utilities
import cgi

if 0: # visible tracebacks as part of the server response (insecure!)
    import cgitb
    cgitb.enable()

import sys, os, time, calendar, string, math, bisect, copy, cStringIO, re
import traceback
import FastGzipFile
import SpinConfig
import SpinUpcache
import SpinUpcacheIO
import SpinWebUI
import SpinS3
import SpinJSON
import SkynetLib
import SkynetLTV
import SpinGoogleAuth
import FacebookAdScraper
import AtomicFileWrite
import multiprocessing
import subprocess

verbose = True

game_id = SpinConfig.game()

# argh, very awkward
if __name__ == "__main__":
    game_id = SpinConfig.game()
    if '-g' in sys.argv:
        game_id = sys.argv[sys.argv.index('-g')+1]

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
gamedata['ai_bases'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename("ai_bases_compiled.json", override_game_id = game_id)))
gamedata['loot_tables'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename("loot_tables.json", override_game_id = game_id)))

logs_dir = 'prodlogs' if os.path.exists('prodlogs') else 'logs'
enable_metrics = False
time_now = int(time.time())
# time at which we started recording building upgrade levels in player.history
BUILDING_HISTORY_TIME = calendar.timegm([2012,5,1,0,0,0,-1,-1,-1])
USE_S3_UPCACHE = 1
S3_KEYFILE = SpinConfig.aws_key_file()

def ad_data_path():
    return 'logs/%s-ad-data.json' % SpinConfig.game_id_long(game_id)

def pretty_print_date(unix_time):
    gmt = time.gmtime(unix_time)
    return '%d/%d/%d %02d:%02d:%02d UTC' % (gmt.tm_mon, gmt.tm_mday, gmt.tm_year,
                                            gmt.tm_hour, gmt.tm_min, gmt.tm_sec)

def get_userdb(info = None):
    bucket, basename = SpinConfig.upcache_s3_location(game_id)
    if USE_S3_UPCACHE:
        return SpinUpcacheIO.S3Reader(SpinS3.S3(S3_KEYFILE), bucket, basename, info = info)
    else:
        return SpinUpcacheIO.LocalReader('logs/'+basename, info = info)

def stream_userdb():
    reader = get_userdb()
    return reader.iter_all()


def has_ad_data():
    if USE_S3_UPCACHE:
        return True
    else:
        return os.path.exists(ad_data_path())

def stream_ad_data_local():
    for line in open(ad_data_path()).xreadlines():
        yield SpinJSON.loads(line)
def stream_ad_data_s3():
    for line in SpinS3.S3(S3_KEYFILE).get_open(SpinConfig.upcache_s3_location(game_id)[0], os.path.basename(ad_data_path())).readlines():
        yield SpinJSON.loads(line)

def stream_ad_data():
    if USE_S3_UPCACHE:
        return stream_ad_data_s3()
    else:
        return stream_ad_data_local()

class Slave(object):
    remote = True
    PROCS_PER_HOST = 1 # number of concurrent threads to run on each slave host - 0 for one, otherwise a multiple of num_cpus()
    hosts = SpinConfig.config['cgianalytics_hosts'] # ['myworker.example.com']
    ssh_key = os.getenv('HOME')+'/.ssh/analytics1.pem'
    ssh_args = ['ssh', '-i', ssh_key]

    def __init__(self):
        self.procs = []
        self.debug_local_results = None

    # make sure the slave's code and data are up to date before running analytics
    # for speed, we skip this if the mtime of a generated gamedata file on the slave is greater than our own copy
    def update_code_cmd(self):
        TEST_FILE = SpinConfig.gamedata_filename(extension='.json')
        test_mtime = int(os.path.getmtime(TEST_FILE))
        STAT_CMD = 'stat -c %Y '+TEST_FILE # note: stat -f %c on Mac OSX
        #sys.stderr.write('test_mtime is %d\n' % test_mtime)
        if 1:
            return '(cd %s/gameserver && if ((`%s` < %d)); then (../scmtool.sh force-up > /dev/null) && ./make-gamedata.sh -n -u > /dev/null; fi)' % (SpinConfig.game_id_long(game_id), STAT_CMD, test_mtime)
        else:
            return 'echo'

    def do_update_code(self, host):
        cmd = self.update_code_cmd()
        assert subprocess.call(self.ssh_args + [host,cmd]) == 0

    def start_slaves(self, arg, input, userdb, debug_slave_func):

        self.num_segments = userdb.num_segments()
        num_hosts = len(self.hosts)

        # partition list of segments into per-host lists to distribute the workload
        tasks = [range(i,self.num_segments,num_hosts) for i in xrange(num_hosts)]
        assert len(tasks) == num_hosts
        #sys.stderr.write('TASKS: '+repr(tasks)+'\n')

        input['userdb_info'] = userdb.info
        update_cmd = self.update_code_cmd()

        if not self.remote and self.PROCS_PER_HOST == 0:
            self.debug_local_results = []

        for i in xrange(len(tasks)):
            # run once per host
            host = self.hosts[i]

            task = tasks[i]
            input['segments'] = task

            if not self.remote and self.PROCS_PER_HOST == 0:
                # run inline
                self.debug_local_results += [debug_slave_func(input, userdb.info, seg) for seg in task]
                continue

            elif self.remote:
                # call via SSH
                slave_args = self.ssh_args + [host, update_cmd + ' && (cd %s/gameserver && ./cgianalytics.py %s)' % (SpinConfig.game_id_long(game_id), arg)]
            else:
                # call this script as a normal subprocess
                slave_args = [sys.argv[0], arg]

            proc = subprocess.Popen(slave_args,
                                    bufsize = 1024*1024,
                                    stdin = subprocess.PIPE,
                                    stdout = subprocess.PIPE,
                                    close_fds = True)

            proc.stdin.write(SpinJSON.dumps(input))
            proc.stdin.flush()
            #sys.stderr.write('flushed %d...\n' % seg)
            proc.stdin.close()
            self.procs.append(proc)

    def get_results(self):
        if self.debug_local_results is not None:
            return self.debug_local_results

        results = []
        for proc in self.procs:
            output = ''
            while True:
                r = proc.stdout.read(1024*1024)
                if not r: break
                output += r
            #sys.stderr.write('waiting term %d...\n' % seg)
            proc.wait()
            #sys.stderr.write('done %d...\n' % seg)
            try:
                output = SpinJSON.loads(output)
            except:
                #sys.stderr.write('BAD SLAVE OUTPUT: "'+output+'"\n')
                raise Exception('BAD SLAVE OUTPUT '+output+'\n')

            results += output
        self.procs = []
        for result in results:
            # awkward - funnel and graph return results differently - but we need to replace this with SpinParallel anyway, so live with it.
            if type(result) is not list:
                temp = [result]
            else:
                temp = result
            for r in temp:
                if r.get('error',False):
                    raise Exception('Error in slave process: '+str(r['error']))
        return results

    # this function is run in the slave process.
    # it takes JSON input on stdin and writes JSON output to stdout
    @classmethod
    def do_slave(cls, func):
        input = ''
        while True:
            r = sys.stdin.read(1024*1024)
            if not r: break
            input += r

        input = SpinJSON.loads(input)
        segments = input['segments']
        info = input['userdb_info']

        # concatenate output from all segments
        if cls.PROCS_PER_HOST != 0:
            pool = multiprocessing.Pool(int(multiprocessing.cpu_count() * cls.PROCS_PER_HOST))
            output = pool.map(g_call_func, [(func,input,info,seg) for seg in segments])
        else:
            output = [g_call_func((func, input, info, seg)) for seg in segments]
        sys.stdout.write(SpinJSON.dumps(output))

# stupid hack to work around how pool.map() only wants functions of one argument
def g_call_func(a):
    try:
        ret = a[0](*a[1:])
    except:
        ret = {'error': traceback.format_exc() }
    return ret


def get_any_abtest_value(user, key, default_value):
    for test_name, data in gamedata['abtests'].iteritems():
        if not data['active']: continue
        if test_name not in user: continue
        group = user[test_name]
        if group not in data['groups']: continue
        if key in data['groups'][group]:
            return data['groups'][group][key]
    return default_value

class Query (object):
    def __init__(self, q, name, offset = 0, sort_key = None):
        # copy it so caller can modify
        self.q = copy.deepcopy(q)
        self.name = name
        self.offset = offset
        self.sort_key = sort_key if (sort_key is not None) else self.name

    def __eq__(self, other):
        if self.name == other.name:
            assert self.q == other.q
            return True
        return False
    def __hash__(self):
        return hash(self.name)

    def serialize(self):
        return {'q':self.q, 'name':self.name, 'offset':self.offset, 'sort_key': self.sort_key}

    @staticmethod
    def deserialize(s):
        return Query(s['q'], s['name'], offset=s['offset'], sort_key=s['sort_key'])

    # true if this query can only return users acquired via Skynet ads
    def is_skynet_query(self):
        camp = self.q.get('acquisition_campaign', '')
        if type(camp) is list:
            if len(camp) == 1:
                camp = camp[0]
            else:
                camp = ''
        is_skynet_camp = camp.startswith('712') # 7120-7129 are used by Skynet

        if is_skynet_camp or \
           any(x.startswith('acquisition_ad_skynet') for x in self.q):
            if not all(x.startswith('acquisition_ad_skynet') or x == 'account_creation_time' or (is_skynet_camp and x == 'acquisition_campaign') for x in self.q):
                return False
            return True
        return False

    def match_acquisition_campaign_num(self, x, y):
        if x == y: return True # literal match
        # for numeric campaign codes, only compare first 4 digits
        if len(x)>0 and x[0].isdigit(): x = x[0:min(len(x),4)]
        if len(y)>0 and y[0].isdigit(): y = y[0:min(len(y),4)]
        if len(x) != len(y): return False
        for i in xrange(len(x)):
            if x[i] != y[i] and y[i] != '?':
                return False
        return True

    # compare leading 4 characters (if numeric), and use ! for negation
    def match_acquisition_campaign(self, val, user_val):
        if user_val in val: return True # early-out for exact match
        user_val = SpinUpcache.remap_facebook_campaigns(user_val)
        default_accept = True
        for v in val:
            invert = False
            if v[0] == '!':
                vcomp = v[1:]
                invert = True
            else:
                vcomp = v[0:]
                default_accept = False # if any element of val is non-inverting, then reject all by default
            if self.match_acquisition_campaign_num(user_val, vcomp):
                if invert:
                    return False
                else:
                    return True
        return default_accept
    def match_number_range(self, val, user_val):
        if user_val < 0 or user_val == 'MISSING': return False
        # check min
        if val[0] > 0 and user_val < val[0]: return False
        # check max
        if val[1] > 0 and user_val >= val[1]: return False
        return True


    def match_ads(self, data):
        for key, val in self.q.iteritems():
            if val == 'ALL' or val == ['ALL']:
                continue
            if key == 'acquisition_campaign':
                if not self.match_acquisition_campaign(val, data.get('Campaign','MISSING')):
                    return False
            elif key == 'account_creation_time':
                if not self.match_number_range(val, data.get('time', 'MISSING')):
                    return False
        return True

    def match_acquisition_ad_skynet(self, val, user_val):
        # match with OR on "val" list followed by AND on X_Y fields
        user_fields = user_val.split('_')
        any_match = False
        for v in val:
            match = True
            want_fields = v.split('_')
            for field in want_fields:
                if field[1:] == 'MISSING':
                    for f in user_fields:
                        if f[0] == field[0]:
                            match = False
                            break
                else:
                    if field[0] == '!':
                        if field[1:] in user_fields:
                            match = False
                            break
                    elif '.' in field:
                        # if the parameter has a . in it, interpret it as a regular expression
                        m = False
                        r = re.compile(field) # '^'+field.replace('?','.'))
                        for f in user_fields:
                            if r.search(f):
                                m = True
                                break
                        if not m:
                            match = False
                            break
                    else:
                        if field not in user_fields:
                            match = False
                            break
            if match:
                any_match = True
                break

        return any_match

    def match(self, user):
        creat = user.get('account_creation_time', -1)
        if creat > 0 and creat > time_now:
            # future user
            return False

        for key, val in self.q.iteritems():
            if val == 'ALL' or val == ['ALL']:
                continue

            if key.startswith('tech:'):
                player_tech = user.get('tech', {})
                tech_name = key.split(':')[1]
                if player_tech.get(tech_name,0) < int(val[0]):
                    return False
                else:
                    continue

            if key.startswith('abtest_value:'):
                unused, testval_key = key.split(':')
                user_val = get_any_abtest_value(user, testval_key, 'MISSING')
                #sys.stderr.write('TESTING: %s %s %s\n' % (testval_key, val, user_val))
                if type(val) is list:
                    if user_val not in val:
                        return False
                else:
                    if user_val != val:
                        return False
                continue

            if key.startswith('acquisition_ad_skynet'):
                user_val = user.get('acquisition_ad_skynet', '')

                # stick retargetings on the end, so that we expose the union of original+retargetings
                user_retargets = user.get('skynet_retargets', None)
                if user_retargets:
                    if user_val: user_val += '_'
                    user_val += '_'.join(user_retargets)

                if val and (not user_val): return False
                if type(val) is not list: val = [val]

                if not self.match_acquisition_ad_skynet(val, user_val):
                    return False
                continue

            if key == 'price_region':
                user_val = SpinConfig.price_region_map.get(user.get('country','unknown'), 'unknown')
            elif key in ('logged_in_times','money_spent'):
                user_val = user.get(key, 0)
            elif key == 'years_old' or key == 'age_group':
                if creat <= 0 or ('birthday' not in user):
                    user_val = 'MISSING'
                else:
                    try:
                        user_val = SpinUpcache.birthday_to_years_old(user['birthday'], creat)
                        if key == 'age_group':
                            user_val = SpinConfig.years_old_to_age_group(user_val)
                    except:
                        user_val = 'MISSING'
            elif key == 'exact_acquisition_campaign':
                user_val = user.get('acquisition_campaign', 'MISSING')
            else:
                user_val = user.get(key, 'MISSING')

            if type(val) == list:
                if key in ['account_creation_time', 'player_level', gamedata['townhall']+'_level', 'money_spent', 'num_purchases', 'logged_in_times', 'years_old'] or key.endswith('_progress') or (type(user_val) is int) or (type(user_val) is float):
                    if not self.match_number_range(val, user_val):
                        return False
                else:
                    if key == 'acquisition_campaign':
                        if not self.match_acquisition_campaign(val, user_val):
                            return False
                    else:
                        if user_val not in val:
                            return False
            elif type(val) in (str, unicode) and len(val) > 1:
                if val[0] == '!':
                    # negate
                    if user_val == val:
                        return False
                else:
                    if user_val != val:
                        return False
            else:
                if user_val != val:
                    return False
        return True

    def __repr__(self):
        return repr(self.q)


# convention: actions that happen within a day apply to the data point at midnight that day
# e.g. "Apr 13" data point is at Apr 13 00:00:00 and includes activity Apr 13 00:00:00 - Apr 13 23:59:59

class UserAccumulator (object):
    def __init__(self, tmin, tmax, interval, offset=0):
        self.tmin = tmin
        self.tmax = tmax
        self.interval = interval
        self.offset = offset
        self.sample_ts = range(tmin, tmax, interval)
    def finalize(self): pass

def add_dict(a, b):
    for key, val in b.iteritems():
        a[key] = a.get(key, 0) + val
def add_list(a, b):
    assert len(a) == len(b)
    for i in xrange(len(a)):
        a[i] += b[i]
def stringify_keys(a):
    ret = {}
    for key, val in a.iteritems():
        ret[repr(key)] = val
    return ret
def unstringify_keys(a):
    ret = {}
    for key, val in a.iteritems():
        ret[int(key)] = val
    return ret
def evalify_keys(a):
    ret = {}
    for key, val in a.iteritems():
        ret[eval(key)] = val
    return ret

# compute number of users "alive" at each sample time, and also compute K-Factor while we're at it
class UserCounter (UserAccumulator):
    def __init__(self, tmin, tmax, interval, offset, strict_kfactor_calc = True):
        UserAccumulator.__init__(self, tmin, tmax, interval, offset=offset)
        self.result = dict([[t,0] for t in self.sample_ts])
        self.k_num = dict([[t,0] for t in self.sample_ts])
        self.k_den = dict([[t,0] for t in self.sample_ts])
        self.strict_kfactor_calc = strict_kfactor_calc

    def add(self, user):
        creat = user.get('account_creation_time',-1) + self.offset
        if creat <= 0:
            return

        if self.strict_kfactor_calc:
            # K-Factor  = secondary / nonsecondary
            # only count users with confirmed secondary=1 (i.e. definitely referred by a campaign) as nonpaid
            sec = user.get('acquisition_secondary', 0)
        else:
            # K-factor = nonpaid / paid
            # count users with MISSING or non-numeric campaign data as nonpaid
            sec = user.get('acquisition_secondary', 0)
            if not sec:
                camp = user.get('acquisition_campaign', 'MISSING')
                if camp != 'MISSING' and SpinUpcache.remap_facebook_campaigns(camp) == 'MISSING':
                    # remap returns 'MISSING' for clicks that indicate the app was installed by ad, but we don't know which ad
                    sec = False
                else:
                    sec = (not camp[0:4].isdigit())

        # add 1 to result[x] for all x at sample times > our creation time
        # use 'bisect' function to do a binary search
        where = bisect.bisect(self.sample_ts,creat)
        for i in xrange(where, len(self.sample_ts)):
            self.result[self.sample_ts[i]] += 1
            if sec:
                self.k_num[self.sample_ts[i]] += 1
            else:
                self.k_den[self.sample_ts[i]] += 1

    def finalize(self):
        self.k_result = {}
        for t in self.sample_ts:
            if self.k_den[t] > 0:
                self.k_result[t] = float(self.k_num[t])/self.k_den[t]
            else:
                self.k_result[t] = 0

    def serialize(self):
        return {'result': stringify_keys(self.result),
                'k_num': stringify_keys(self.k_num),
                'k_den': stringify_keys(self.k_den)}

    def reduce(self, datalist):
        for data in datalist:
            add_dict(self.result, unstringify_keys(data['result']))
            add_dict(self.k_num, unstringify_keys(data['k_num']))
            add_dict(self.k_den, unstringify_keys(data['k_den']))

def max_cc_level(): return len(gamedata['buildings'][gamedata['townhall']]['build_time'])

class UserUniques (UserAccumulator):

    def __init__(self, tmin, tmax, interval, offset, do_extrapolate):
        UserAccumulator.__init__(self, tmin, tmax, interval, offset=offset)
        self.do_extrapolate = do_extrapolate
        self.au = dict([[t,0] for t in self.sample_ts])
        self.au_by_cc_level = [dict([[t,0] for t in self.sample_ts]) for i in xrange(max_cc_level())]
        self.tig = dict([[t,0] for t in self.sample_ts]) # time in game accumulated during that sample period
        self.new_users = dict([[t,0] for t in self.sample_ts])
        self.tutorial_completions = dict([[t,0] for t in self.sample_ts])
        self.paying_users = dict([[t,0] for t in self.sample_ts])

        # compute concurrent users more frequently than once per interval
        if interval in (3600, 86400):
            concurrent_interval = 3600 # sample each hour
            self.concurrent_sample_times = dict([[t,
                                             range(t, t+interval, concurrent_interval)
                                             ] for t in self.sample_ts])
            self.concurrent_samples = dict([[t,
                                             dict([[u,0] for u in self.concurrent_sample_times[t]])
                                             ] for t in self.sample_ts])
        else:
            self.concurrent_samples = None


    def add(self, user):
        sessions = user.get('sessions', None)
        if not sessions: return
        creat = user.get('account_creation_time',-1)

        if creat > 0 and gamedata['townhall']+'_level_at_time' in user:
            sorted_cc_times = sorted([int(st) for st,v in user[gamedata['townhall']+'_level_at_time'].iteritems()])
        else:
            sorted_cc_times = None

        covered = set()
        covered_concurrent = set()

        for i in xrange(len(sessions)):
            s = sessions[i]
            if s[0] < 0 or s[1] < 0: continue # not a complete session

            login_time = s[0] + self.offset
            logout_time = s[1] + self.offset
            if login_time < self.tmin or login_time >= self.tmax: continue

            # quantize this login time to a sample_t
            t = self.tmin + self.interval * int((login_time-self.tmin)/self.interval)

            if s[1] > s[0]:
                # add session to time-in-game accumulator
                self.tig[t] += s[1]-s[0]

                # mark whether or not the user was logged in at each concurrency sample time
                if self.concurrent_samples:
                    where_left = bisect.bisect(self.concurrent_sample_times[t], login_time) - 1
                    where_right = bisect.bisect(self.concurrent_sample_times[t], logout_time) - 1
                    if where_right > where_left:
                        # session straddles at least one sample time, meaning the user was logged in at the instant the sample was taken
                        for idx in xrange(where_left+1, where_right+1):
                            if idx >= 0:
                                concurrent_t = self.concurrent_sample_times[t][idx]
                                if concurrent_t not in covered_concurrent:
                                    covered_concurrent.add(concurrent_t)
                                    self.concurrent_samples[t][concurrent_t] += 1

            # add only once to DAU
            if t not in covered:
                covered.add(t)
                if self.do_extrapolate and t == self.sample_ts[-1] and self.offset == 0:
                    coverage = 1.0/((self.tmax - t)/float(self.interval))
                else:
                    coverage = 1

                self.au[t] += coverage
                if i == 0:
                    self.new_users[t] += coverage
                    if user.get('tutorial_state',None) == 'COMPLETE':
                        self.tutorial_completions[t] += coverage

                # find out if user was paying as of this time
                if user.get('money_spent',0) > 0:
                    if ('time_of_first_purchase' in user) and (user['time_of_first_purchase'] < t):
                        self.paying_users[t] += coverage
                    elif ('money_spent_at_time' in user) and (creat > 0):
                        first_purchase_age = min(map(int, user['money_spent_at_time'].iterkeys()))
                        if (first_purchase_age + creat) < t:
                            self.paying_users[t] += coverage

                # find CC level
                if sorted_cc_times:
                    where = bisect.bisect(sorted_cc_times, t-creat) - 1
                    if where < 0:
                        cc_level = 1
                    else:
                        cc_level = user[gamedata['townhall']+'_level_at_time'][str(sorted_cc_times[where])]
                    self.au_by_cc_level[cc_level-1][t] += coverage


    def serialize(self):
        return {'au': stringify_keys(self.au),
                'au_by_cc_level': map(stringify_keys, self.au_by_cc_level),
                'tig': stringify_keys(self.tig),
                'new_users': stringify_keys(self.new_users),
                'tutorial_completions': stringify_keys(self.tutorial_completions),
                'paying_users': stringify_keys(self.paying_users),
                'concurrent_samples': stringify_keys(dict([(k, stringify_keys(v)) for k,v in self.concurrent_samples.iteritems()])) if self.concurrent_samples else None
            }
    def reduce(self, datalist):
        for data in datalist:
            add_dict(self.au, unstringify_keys(data['au']))
            for i in xrange(len(self.au_by_cc_level)):
                add_dict(self.au_by_cc_level[i], unstringify_keys(data['au_by_cc_level'][i]))
            add_dict(self.tig, unstringify_keys(data['tig']))
            add_dict(self.new_users, unstringify_keys(data['new_users']))
            add_dict(self.tutorial_completions, unstringify_keys(data['tutorial_completions']))
            add_dict(self.paying_users, unstringify_keys(data['paying_users']))
            if self.concurrent_samples and data['concurrent_samples']:
                for k, v in self.concurrent_samples.iteritems():
                    add_dict(v, unstringify_keys(data['concurrent_samples'][str(k)]))

        if self.concurrent_samples:
            self.concurrent = dict([(t,max(self.concurrent_samples[t].itervalues())) for t in self.sample_ts])
        else:
            self.concurrent = None

class AdAccumulator (UserAccumulator): # steal fields from UserAccumulator
    def __init__(self, tmin, tmax, interval, offset):
        UserAccumulator.__init__(self, tmin, tmax, interval, offset=offset)
        self.period_spend = dict([[t,0.0] for t in self.sample_ts])
        self.has_data = False
    def add(self, data):
        self.has_data = True
        t = data['time'] + self.offset
        if t >= self.tmin and t < self.tmax:
            where = bisect.bisect(self.sample_ts, t) - 1
            if where >= 0 and where < len(self.sample_ts):
                self.period_spend[self.sample_ts[where]] += data['Spent']
    def finalize(self):
        self.cum_spend = dict([[t,0.0] for t in self.sample_ts])
        cum = 0.0
        for t in self.sample_ts:
            cum += self.period_spend[t]
            self.cum_spend[t] = cum

# based on money_spent_on_* metrics in server.py
SPEND_CATEGORY_MAP = {"ALL": ["_spent_at_time"],
                      "ALL_MIN_CC": ["_spent_at_time"],
                      # speedups are now attributed to the thing they are speeding up, as if it were an instant purchase
#                      "03_speedups": ["_spent_on_speedups_at_time"],

                      "01_building_upgrades": ["_spent_on_building_upgrades_at_time", "_spent_on_building_upgrade_speedups_at_time", "_spent_on_construct_speedups_at_time"],
                      "02_tech_research": ["_spent_on_techs_at_time", "_spent_on_research_speedups_at_time"],
#                      "03_base_repair": [],
                      "03_repairs_and_unit_production": ["_spent_on_base_repairs_at_time", "_spent_on_repair_speedups_at_time", "_spent_on_produce_speedups_at_time", "_spent_on_unit_repair_speedups_at_time"],
                      "04_resource_boosts": ["_spent_on_resource_boosts_at_time"],


                      "05_protection": ["_spent_on_protection_at_time"],
                      "06_random_items": ["_spent_on_random_items_at_time"],
                      "07_specific_items": ["_spent_on_items_at_time"],
                      "08_relocate_base": ["_spent_on_base_relocations_at_time"],
                      "09_gift_orders": ["_spent_on_gift_orders_at_time"],

#               "07_barriers": ["_spent_on_barrier_upgrades_at_time"],
#               "08_base_growth": ["_spent_on_base_growth_at_time"],

#                      "00_gamebucks": ["_spent_on_gamebucks_at_time"]
                      }
SPEND_CATEGORIES = sorted(SPEND_CATEGORY_MAP.keys())
SPEND_CURRENCIES = ['money', 'gamebucks']
def CURRENCY_UI_NAMES(): return {'money': 'Money', 'gamebucks': gamedata['store']['gamebucks_ui_name']}
CATEGORIZE_MONEY_SPENT = False # (SpinConfig.game() == 'mf') # don't bother breaking down money spent for old non-gamebucks MF users

class UserReceipts (UserAccumulator):
    INTERVALS = [60] # check spend by days 1,3,7,60

    CAT_MAP = SPEND_CATEGORY_MAP
    CATEGORIES = SPEND_CATEGORIES
    CURRENCIES = SPEND_CURRENCIES

    def __init__(self, tmin, tmax, interval, offset, do_extrapolate):
        UserAccumulator.__init__(self, tmin, tmax, interval, offset=offset)
        self.do_extrapolate = do_extrapolate
        self.period_receipts = dict([(currency,
                                      dict([(name, dict([[t,0.0] for t in self.sample_ts]))
                                            for name in self.CATEGORIES if (name.startswith('ALL') or currency == 'gamebucks' or CATEGORIZE_MONEY_SPENT)]))
                                     for currency in self.CURRENCIES])
        self.period_purchases = dict([[t,0] for t in self.sample_ts])
        if interval >= 24*60*60:
            self.by_age_num = dict([(i, dict([[t,0.0] for t in self.sample_ts])) for i in self.INTERVALS])
        else:
            self.by_age_num = None

    def serialize(self):
        ret = {'period_receipts': dict([(currency, dict([(name, stringify_keys(self.period_receipts[currency][name])) for name in self.period_receipts[currency].iterkeys()])) for currency in self.period_receipts.iterkeys()]),
               'period_purchases': stringify_keys(self.period_purchases)}
        if self.by_age_num:
            ret['by_age_num'] = stringify_keys(dict([(i, stringify_keys(self.by_age_num[i])) for i in self.INTERVALS]))
        return ret

    def reduce(self, datalist):
        for data in datalist:
            for currency in self.period_receipts.iterkeys():
                for cat in self.period_receipts[currency].iterkeys(): # CATEGORIES:
                    add_dict(self.period_receipts[currency][cat], unstringify_keys(data['period_receipts'][currency][cat]))
            add_dict(self.period_purchases, unstringify_keys(data['period_purchases']))
            if self.by_age_num:
                data_by_age_num = unstringify_keys(data['by_age_num'])
                for i in self.INTERVALS:
                    add_dict(self.by_age_num[i], unstringify_keys(data_by_age_num[i]))

    def add(self, user):
        for currency in self.period_receipts.iterkeys():
            for cat in self.period_receipts[currency].iterkeys(): # self.CATEGORIES:
                for history_category in [currency + x for x in self.CAT_MAP[cat]]:
                    if (history_category not in user): continue
                    if type(user[history_category]) is not dict: raise Exception('bad history_category %s on user %d' % (history_category, user['user_id']))
                    for ssec, amount in user[history_category].iteritems():
                        sec = int(ssec)
                        t = sec + user['account_creation_time'] + self.offset

                        if cat == 'ALL_MIN_CC' and cc_level_at_age(user, sec) < UserActivity.MIN_CC: continue

                        if t >= self.tmin and t < self.tmax:
                            samp_t = self.tmin + self.interval * int((t-self.tmin)/self.interval)
                            self.period_receipts[currency][cat][samp_t] += amount

                            if currency == 'money' and cat == "ALL":
                                self.period_purchases[samp_t] += 1

                            if currency == 'money' and cat == "ALL" and self.by_age_num:
                                age_days = sec/self.interval
                                for cur_t in self.sample_ts:
                                    if cur_t >= t:
                                        cur_age_days = (cur_t - user['account_creation_time'] - self.offset)/self.interval
                                        for i in self.INTERVALS:
                                            if cur_age_days < i and age_days < i:
                                                self.by_age_num[i][cur_t] += amount

    def finalize(self):
        # project to last period
        if self.do_extrapolate and self.offset == 0:
            for currency in self.period_receipts.iterkeys():
                for cat in self.period_receipts[currency].iterkeys(): # self.CATEGORIES:
                    self.period_receipts[currency][cat][self.sample_ts[-1]] /= (self.tmax - self.sample_ts[-1])/float(self.interval)

        self.cum_receipts = dict([[t,0.0] for t in self.sample_ts])
        self.avg_size = dict([[t,0.0] for t in self.sample_ts])
        cum = 0.0
        for t in self.sample_ts:
            cum += self.period_receipts["money"]["ALL"][t]
            self.cum_receipts[t] = cum
            if self.period_purchases[t] > 0:
                self.avg_size[t] = self.period_receipts["money"]["ALL"][t] / self.period_purchases[t]

class UserAttacks(UserAccumulator):
    KINDS = ['attacks_launched', 'attacks_launched_vs_human', 'revenge_attacks_launched_vs_human', 'attacks_suffered']

    def __init__(self, tmin, tmax, interval, offset):
        UserAccumulator.__init__(self, tmin, tmax, interval, offset=offset)
        self.period_attacks = dict([(kind, dict([[t,0] for t in self.sample_ts])) for kind in self.KINDS])
    def serialize(self):
        return {'period_attacks': dict([(kind, stringify_keys(self.period_attacks[kind])) for kind in self.KINDS])}
    def reduce(self, datalist):
        for data in datalist:
            for kind in self.KINDS:
                add_dict(self.period_attacks[kind], unstringify_keys(data['period_attacks'].get(kind, {})))
    def add(self, user):
        for kind in self.KINDS:
            history_category = kind+'_at_time'
            if (history_category not in user): continue
            for ssec, amount in user[history_category].iteritems():
                t = int(ssec) + user['account_creation_time'] + self.offset
                if t >= self.tmin and t < self.tmax:
                    samp_t = self.tmin + self.interval * int((t-self.tmin)/self.interval)
                    self.period_attacks[kind][samp_t] += amount

class UserActivity(UserAccumulator):
    # accumulate time samples that look like {'idle': 23554, 'pvp': 4534, ... }

    MIN_CC = 5 # ignore activity prior to CCL5 because tutorial stuff messes up data

    def __init__(self, tmin, tmax, interval, offset):
        UserAccumulator.__init__(self, tmin, tmax, interval, offset=offset)
        self.seen_states = set()
        self.activity_by_time = dict(((t,{}) for t in self.sample_ts))
        self.activity_gamebucks_by_time = dict(((t,{}) for t in self.sample_ts))
        self.seen_ais = set()
        self.ais_by_time = dict(((t,{}) for t in self.sample_ts))
        self.ai_gamebucks_by_time = dict(((t,{}) for t in self.sample_ts))
        self.ai_money_by_time = dict(((t,{}) for t in self.sample_ts))
    def get_states(self): return sorted(list(self.seen_states))
    def get_ais(self): return sorted(list(self.seen_ais))
    def serialize(self):
        return {'activity_by_time': stringify_keys(self.activity_by_time),
                'activity_gamebucks_by_time': stringify_keys(self.activity_gamebucks_by_time),
                'ais_by_time': stringify_keys(self.ais_by_time),
                'ai_gamebucks_by_time': stringify_keys(self.ai_gamebucks_by_time),
                'ai_money_by_time': stringify_keys(self.ai_money_by_time),
                }
    def fold_in(self, a, b, seen):
        for t in a:
            samp_a = a[t]
            samp_b = b[t]
            for k in samp_b:
                seen.add(k)
                samp_a[k] = samp_a.get(k,0) + samp_b[k]

    def reduce(self, datalist):
        for data in datalist:
            self.fold_in(self.activity_by_time, unstringify_keys(data['activity_by_time']), self.seen_states)
            self.fold_in(self.activity_gamebucks_by_time, unstringify_keys(data['activity_gamebucks_by_time']), self.seen_states)
            self.fold_in(self.ais_by_time, unstringify_keys(data['ais_by_time']), self.seen_ais)
            self.fold_in(self.ai_gamebucks_by_time, unstringify_keys(data['ai_gamebucks_by_time']), self.seen_ais)
            self.fold_in(self.ai_money_by_time, unstringify_keys(data['ai_money_by_time']), self.seen_ais)

    def add(self, user):
        if 'activity' not in user: return
        if 'account_creation_time' not in user: return
        for stime, data in user['activity'].iteritems():
            t = int(stime) + self.offset
            if cc_level_at_age(user, int(stime) - user['account_creation_time']) < self.MIN_CC: continue
            if t >= self.tmin and t < self.tmax:
                act = SpinUpcache.classify_activity(gamedata, data)
                if act is None: continue
                state = act['state']

                samp_t = self.tmin + self.interval * int((t-self.tmin)/self.interval)
                self.activity_by_time[samp_t][state] = self.activity_by_time[samp_t].get(state,0) + data['dt']
                self.activity_gamebucks_by_time[samp_t][state] = self.activity_gamebucks_by_time[samp_t].get(state,0) + data.get('gamebucks_spent',0)

                name = act.get('ai_tag', None) or act.get('ai_ui_name', None)
                if name:
                    self.ais_by_time[samp_t][name] = self.ais_by_time[samp_t].get(name,0) + data['dt']
                    self.ai_gamebucks_by_time[samp_t][name] = self.ai_gamebucks_by_time[samp_t].get(name,0) + data.get('gamebucks_spent',0)
                    self.ai_money_by_time[samp_t][name] = self.ai_money_by_time[samp_t].get(name,0) + data.get('money_spent',0)

class UserProgressCurve (UserAccumulator):
    DAYS=90
    LEVELS=8
    PLAYER_LEVELS=30

    def __init__(self, tmin, tmax, interval, offset):
        UserAccumulator.__init__(self, tmin, tmax, interval, offset=offset)
        self.by_day_num = {}
        self.by_day_den = {}
        self.by_level_num = {}
        self.by_level_den = {}
        self.by_plevel_num = {}
        self.by_plevel_den = {}
        self.LEVEL_FIELDS = [gamedata['townhall']+'_level'] + \
                            [catname+'_unlocked' for catname in gamedata['strings']['manufacture_categories']] + \
                            ['player_level']
        for field in self.LEVEL_FIELDS:
            self.by_day_num[field] = [0] * self.DAYS
            self.by_day_den[field] = [0] * self.DAYS
            self.by_level_num[field] = [0] * self.LEVELS
            self.by_level_den[field] = [0] * self.LEVELS
            self.by_plevel_num[field] = [0] * self.PLAYER_LEVELS
            self.by_plevel_den[field] = [0] * self.PLAYER_LEVELS

    def serialize(self):
        return {'by_day_num': self.by_day_num,
                'by_day_den': self.by_day_den,
                'by_level_num': self.by_level_num,
                'by_level_den': self.by_level_den,
                'by_plevel_num': self.by_plevel_num,
                'by_plevel_den': self.by_plevel_den}
    def reduce(self, datalist):
        for data in datalist:
            for field in self.LEVEL_FIELDS:
                add_list(self.by_day_num[field], data['by_day_num'][field])
                add_list(self.by_day_den[field], data['by_day_den'][field])
                add_list(self.by_level_num[field], data['by_level_num'][field])
                add_list(self.by_level_den[field], data['by_level_den'][field])
                add_list(self.by_plevel_num[field], data['by_plevel_num'][field])
                add_list(self.by_plevel_den[field], data['by_plevel_den'][field])


    def add(self, user):
        creat = user.get('account_creation_time',-1)
        if creat <= 0: return

        creat += self.offset


        plevel_series = user.get('player_level_at_time', None)
        if plevel_series:
            # dict mapping level -> time when level was achieved
            plevel_inverse = dict([(v,int(st)) for st,v in plevel_series.iteritems()])
            plevel_inverse[0] = plevel_inverse[1] = 0

        sessions = user.get('sessions', None)
        if not sessions or len(sessions) < 1: return
        last_login_age = (sessions[-1][0] - user['account_creation_time'])

        for field in self.LEVEL_FIELDS:
            user_level = user.get(field,0)

            # get snapshot of % accounts >= each upgrade level
            for level in xrange(self.LEVELS):
                self.by_level_den[field][level] += 1
                if user_level >= level:
                    self.by_level_num[field][level] += 1

            # get level by account age
            series_name = field+'_at_time'
            if series_name not in user:
                continue
            series = user[series_name]

            # create sorted version of time samples in the series for fast searching
            # { "time2": value, "time1": value } => [ time1, time2, ... ]
            sorted_times = sorted([int(st) for st,v in series.iteritems()])
            for day in xrange(self.DAYS):
                sample_age = day*self.interval
                if time_now < creat + sample_age:
                    break # in the future
                if sample_age > last_login_age + 24*60*60:
                    # user churned off, don't count
                    break
                self.by_day_den[field][day] += 1
                # see where the level was at that sample time
                where = bisect.bisect(sorted_times, sample_age) - 1
                if where < 0:
                    value = 0
                else:
                    value = series[str(sorted_times[where])]
                self.by_day_num[field][day] += value

            if plevel_series:
                for plevel in xrange(self.PLAYER_LEVELS):
                    if plevel not in plevel_inverse:
                        break
                    self.by_plevel_den[field][plevel] += 1
                    # find age at which player reached this level
                    age = plevel_inverse[plevel]
                    # see where the upgrade level was at this time
                    where = bisect.bisect(sorted_times, age) - 1
                    if where < 0:
                        value = 0
                    else:
                        value = series[str(sorted_times[where])]
                    self.by_plevel_num[field][plevel] += value

    def finalize(self):
        pass

class UserSpendCurve (UserAccumulator):
    HURDLES = [0.01, 10]

    # choices for time_axis
    ACCT_AGE = 0
    TIME_IN_GAME = 1

    def __init__(self, tmin, tmax, interval, offset, time_axis = ACCT_AGE):
        UserAccumulator.__init__(self, tmin, tmax, interval, offset=offset)
        self.time_axis = time_axis
        self.BUCKETS = {self.ACCT_AGE: 1000,
                        self.TIME_IN_GAME: 500}[time_axis]
        self.ret = [0] * self.BUCKETS
        self.pret = [0] * self.BUCKETS
        self.num = dict([(currency, dict([(name, [0.0]*self.BUCKETS) for name in SPEND_CATEGORIES])) for currency in SPEND_CURRENCIES])
        self.hurdle = dict([(str(amount), [0]*self.BUCKETS) for amount in self.HURDLES])
        self.den = [0] * self.BUCKETS
        self.den_primary = [0] * self.BUCKETS

    def serialize(self):
        return {'ret': self.ret, 'pret': self.pret, 'num': self.num, 'hurdle': self.hurdle,
                'den': self.den, 'den_primary': self.den_primary, 'time_axis': self.time_axis}
    def reduce(self, datalist):
        for data in datalist:
            assert data['time_axis'] == self.time_axis
            for currency in SPEND_CURRENCIES:
                for cat in SPEND_CATEGORIES:
                    add_list(self.num[currency][cat], data['num'][currency][cat])
            add_list(self.ret, data['ret'])
            add_list(self.pret, data['pret'])
            for amount in self.HURDLES:
                add_list(self.hurdle[str(amount)], data['hurdle'][str(amount)])
            add_list(self.den, data['den'])
            add_list(self.den_primary, data['den_primary'])

    # convert account age in seconds to our X axis value
    def acct_age_to_x_axis(self, user, age):
        if self.time_axis == self.ACCT_AGE:
            return int(math.floor(age/self.interval))
        elif self.time_axis == self.TIME_IN_GAME:
            creat = user['account_creation_time']
            abs_time = age + creat
            cum = 0
            sec_in_game = -1
            for s in user['sessions']: # XXX slow
                if abs_time >= s[0] and abs_time < s[1]:
                    sec_in_game = cum + abs_time - s[0]
                    assert sec_in_game >= 0
                    break
                if s[0] > 0 and s[1] > 0:
                    cum += s[1]-s[0]

            if sec_in_game < 0:
                sec_in_game = cum

            return sec_in_game/(3600) # hard-code to hours

    def add(self, user):
        sessions = user.get('sessions', None)
        if not sessions: return
        primary = (not user.get('acquisition_secondary',False))
        if user.get('account_creation_time', -1) <= 0: return
        if user['account_creation_time'] > time_now: return

        age = min(time_now,self.tmax) - (user['account_creation_time'] + self.offset)
        nbuckets = self.acct_age_to_x_axis(user, age) # int(math.floor(age/self.interval))
        if nbuckets < 1:
            return
        # fill all buckets UP TO AND INCLUDING "nbuckets"
        for i in xrange(min(nbuckets+1, self.BUCKETS)):
            self.den[i] += 1
            if primary:
                self.den_primary[i] += 1
        last_spend = -1
        last_login = -1

        cumulative = 0.0

        for currency in SPEND_CURRENCIES:
            spend_times = sorted(map(int, user.get(currency+'_spent_at_time',{}).iterkeys()))
            for spend_time in spend_times:
                ssec = str(spend_time)
                amount = user[currency+'_spent_at_time'][ssec]
                age_at_purchase = int(ssec)
                time_at_purchase = age_at_purchase + (user['account_creation_time'] + self.offset)
                if time_at_purchase > time_now:
                    # ignore the future
                    continue

                day = self.acct_age_to_x_axis(user, age_at_purchase)

                last_spend = max(last_spend, day)
                if day < self.BUCKETS and day < nbuckets+1:
                    for cat in SPEND_CATEGORIES:
                        for history_category in [currency + x for x in SPEND_CATEGORY_MAP[cat]]:
                            if history_category in user and ssec in user[history_category]:
                                self.num[currency][cat][day] += float(user[history_category][ssec])

                    if currency == 'money' and amount > 0:
                        new_cum = cumulative + amount
                        for hurdle_amount in self.HURDLES:
                            if cumulative < hurdle_amount and new_cum >= hurdle_amount:
                                # hurdle crossed, set all following days to 1
                                for d in xrange(day, min(nbuckets+1, self.BUCKETS)):
                                    self.hurdle[str(hurdle_amount)][d] += 1
                        cumulative = new_cum


        if 0 and len(sessions) > 1: # XXX this is slow, don't bother computing it for now
            for session in sessions:
                login_time = session[0] + self.offset
                if login_time > time_now:
                    # ignore the future
                    break
                last_login = self.acct_age_to_x_axis(user, login_time - (user['account_creation_time']+self.offset)) # offset math might be wrong

        if last_login >= 0:
            for day in xrange(min(last_login+1, nbuckets+1, self.BUCKETS)):
                self.ret[day] += 1
        if last_spend >= 0:
            for day in xrange(min(last_spend+1, nbuckets+1, self.BUCKETS)):
                self.pret[day] += 1

    def finalize(self):
        self.avg_receipts = dict([(currency, dict([(name, [0.0]*self.BUCKETS) for name in SPEND_CATEGORIES])) for currency in SPEND_CURRENCIES])
        self.avg_receipts_primary = [0.0]*self.BUCKETS
        self.avg_cum_receipts = dict([(currency, dict([(name, [0.0]*self.BUCKETS) for name in SPEND_CATEGORIES])) for currency in SPEND_CURRENCIES])
        self.avg_cum_receipts_primary = [0.0]*self.BUCKETS
        self.avg_retention = [0.0]*self.BUCKETS
        self.avg_pretention = [0.0]*self.BUCKETS
        cum_counter = dict([(currency, dict([(name, 0.0) for name in SPEND_CATEGORIES])) for currency in SPEND_CURRENCIES])
        cum_counter_primary = 0.0
        for i in xrange(self.BUCKETS):
            if self.den[i] > 0:
                for currency in SPEND_CURRENCIES:
                    for cat in SPEND_CATEGORIES:
                        self.avg_receipts[currency][cat][i] = float(self.num[currency][cat][i])/self.den[i]
                if self.den_primary[i] > 0:
                    self.avg_receipts_primary[i] = float(self.num['money']['ALL'][i])/self.den_primary[i]
                self.avg_retention[i] = float(self.ret[i])/self.den[i]
                self.avg_pretention[i] = float(self.pret[i])/self.den[i]

            for currency in SPEND_CURRENCIES:
                for cat in SPEND_CATEGORIES:
                    cum_counter[currency][cat] += self.avg_receipts[currency][cat][i]
                    self.avg_cum_receipts[currency][cat][i] = cum_counter[currency][cat]

            cum_counter_primary += self.avg_receipts_primary[i]
            self.avg_cum_receipts_primary[i] = cum_counter_primary

class UserRetention (UserAccumulator):
    INTERVALS = [
#        (0,1,1),  # first-day return within 24hrs
        (1,2,2),  # 1-day retention for accounts age=2
#        (2,3,3),  # 2-day retention for accounts age=3
        (7,10,10), # 7-day retention for accounts age=10
        (30,33,33), # 30-day retention for accounts age=33
        ]
    VISITS = [1,3,7,60] # check # visits within first 1,3,7,60 days
    # MUST BE A SUPERSET OF UserReceipts.INTERVALS!

    def __init__(self, tmin, tmax, interval, offset):
        UserAccumulator.__init__(self, tmin, tmax, interval, offset=offset)

        # dict INTERVAL -> cur_t -> value
        self.retained = dict([(i, dict([[t,0] for t in self.sample_ts])) for i in UserRetention.INTERVALS])
        self.total = dict([(i, dict([[t,0] for t in self.sample_ts])) for i in UserRetention.INTERVALS])

        self.visits_num = dict([(i, dict([[t,0] for t in self.sample_ts])) for i in UserRetention.VISITS])
        self.visits_den = dict([(i, dict([[t,0] for t in self.sample_ts])) for i in UserRetention.VISITS])
        self.alive = dict([(i, dict([[t,0] for t in self.sample_ts])) for i in UserRetention.VISITS])

    def serialize(self):
        return {'retained': stringify_keys(dict([(i, stringify_keys(self.retained[i])) for i in UserRetention.INTERVALS])),
                'total': stringify_keys(dict([(i, stringify_keys(self.total[i])) for i in UserRetention.INTERVALS])),
                'visits_num': stringify_keys(dict([(i, stringify_keys(self.visits_num[i])) for i in UserRetention.VISITS])),
                'visits_den': stringify_keys(dict([(i, stringify_keys(self.visits_den[i])) for i in UserRetention.VISITS])),
                'alive': stringify_keys(dict([(i, stringify_keys(self.visits_den[i])) for i in UserRetention.VISITS]))}

    def reduce(self, datalist):
        for data in datalist:
            for key, val in self.retained.iteritems(): add_dict(val, unstringify_keys(evalify_keys(data['retained'])[key]))
            for key, val in self.total.iteritems(): add_dict(val, unstringify_keys(evalify_keys(data['total'])[key]))
            for key, val in self.visits_num.iteritems(): add_dict(val, unstringify_keys(unstringify_keys(data['visits_num'])[key]))
            for key, val in self.visits_den.iteritems(): add_dict(val, unstringify_keys(unstringify_keys(data['visits_den'])[key]))
            for key, val in self.alive.iteritems(): add_dict(val, unstringify_keys(unstringify_keys(data['alive'])[key]))

    def add(self, user):
        sessions = user.get('sessions', None)
        if not sessions: return
        t_begin = sessions[0][0] + self.offset
        logins = [s[0]+self.offset for s in sessions]
        for i in self.INTERVALS:
            interval, start, end = i
            for cur_t in self.sample_ts:
                age_days = (cur_t - t_begin)/self.interval
                if age_days >= start and age_days <= end:
                    self.total[i][cur_t] += 1
                    i_end = bisect.bisect(logins, cur_t)-1
                    if i_end > 0 and i_end < len(logins) and (logins[i_end]-t_begin)/self.interval >= interval:
                        self.retained[i][cur_t] += 1

        # NOTE: 'alive' is used as the denominator for spend_Xd calcs
        for cur_t in self.sample_ts:
            age_days = (cur_t-t_begin)/self.interval
            for mark in self.VISITS:
                if age_days >= 0 and age_days < mark:
                    self.alive[mark][cur_t] += 1

        ## for cur_t in self.sample_ts:
        ##     age_days = (cur_t - sessions[0][0])/self.interval

        ##     # compute retention %
        ##     for i in UserRetention.INTERVALS:
        ##         interval, start, end = i
        ##         if age_days >= start and age_days <= end:
        ##             self.total[i][cur_t] += 1
        ##             for s in sessions[1:]:
        ##                 if s[0] > cur_t:
        ##                     break
        ##                 s_days = (s[0]-sessions[0][0])/self.interval
        ##                 if s_days >= interval:
        ##                     # NOTE: this skips days when the user didn't log in. Can be fixed by inverting the loop.
        ##                     self.retained[i][cur_t] += 1
        ##                     break
        ##     # compute # visits
        ##     for mark in UserRetention.VISITS:
        ##         # arbitrarily look at accounts created in the 1-day window leading to current data point
        ##         if age_days >= mark and age_days < (mark+1):
        ##             self.visits_den[mark][cur_t] += 1
        ##             for s in sessions:
        ##                 if s[0] > cur_t:
        ##                     break
        ##                 s_days = (s[0]-sessions[0][0])/self.interval
        ##                 if s_days < mark:
        ##                     self.visits_num[mark][cur_t] += 1
        ##                 else:
        ##                     break


    def finalize(self):
        self.trailing = dict([(i, dict([[t,0] for t in self.sample_ts])) for i in UserRetention.INTERVALS])
        for i in UserRetention.INTERVALS:
            for cur_t in self.sample_ts:
                if self.total[i][cur_t] > 0:
                    self.trailing[i][cur_t] = float(self.retained[i][cur_t])/float(self.total[i][cur_t])
                else:
                    self.trailing[i][cur_t] = 0

# convert a Python dictionary of {"t": sample} to a SpinWebUI chart data source object
def make_data_series(samples, y_format, N_samples = None, SD_samples = None, x_format = 'date', name='yyy'):
    return SpinWebUI.DataSeries(samples, x_format, y_format, N_samples = N_samples, SD_samples = SD_samples, name = name)

# same as above, but average across a trailing window
def make_averaged_series(samples, y_format, N_samples = None, SD_samples = None, denom_samples = None, x_format = 'date', name='yyy', window = 7):
    if window <= 1:
        if denom_samples:
            return make_quotient_series(samples, denom_samples, y_format, x_format = x_format, name = name)
        else:
            return make_data_series(samples, y_format, N_samples = N_samples, SD_samples = SD_samples, x_format = x_format, name = name)
    avg = {}
    sample_ts = sorted(samples.keys())
    for t in xrange(len(sample_ts)):
        den = 0
        total = 0
        for i in xrange(-window+1, 1): # range(-window/2,window/2+1):
            if (t+i) >= 0 and (t+i) < len(sample_ts):
                den += 1
                if denom_samples:
                    d = denom_samples[sample_ts[t+i]]
                    if d == 0:
                        value = 0
                    else:
                        value = samples[sample_ts[t+i]]/float(d)
                else:
                    value = samples[sample_ts[t+i]]
                total += value
        if den > 0:
            avg[sample_ts[t]] = total/den
        else:
            avg[sample_ts[t]] = 0
    return SpinWebUI.DataSeries(avg, x_format, y_format, N_samples = denom_samples if denom_samples else N_samples, name = name)

# same as above, but create a series that is a quotient of two other kinds of data
# (e.g. Daily Revenue / Daily Active Users = ARPDAU)
def make_quotient_series(num, denom, y_format, x_format = 'date', name='yyy'):
    samples = {}
    N_samples = {}
    for key in denom.iterkeys():
        if denom[key] == 0:
            continue
        samples[key] = num.get(key,0)/float(denom[key])
        N_samples[key] = denom[key]
    return SpinWebUI.DataSeries(samples, x_format, y_format, N_samples = N_samples, name = name)

# MAIN REQUEST METHODS


def do_upload_ad_csv(data):
    print 'Content-Type: text/html' # required by Ext.js, not text/javascript!
    print 'Pragma: no-cache'
    print 'Cache-Control: no-cache'
    print ''
    retmsg = {}
    try:
        converter = FacebookAdScraper.CSVToJSON(cStringIO.StringIO(data))
        atom = AtomicFileWrite.AtomicFileWrite(ad_data_path(), 'w')
        for dataline in converter.produce():
            SpinJSON.dump(dataline, atom.fd)
            atom.fd.write('\n')
        atom.complete()
        if USE_S3_UPCACHE:
            SpinS3.S3(S3_KEYFILE).put_file(SpinConfig.upcache_s3_location(game_id)[0], os.path.basename(ad_data_path()), ad_data_path())
        retmsg['success'] = True
    except:
        retmsg['success'] = False
        retmsg['error'] = traceback.format_exc() # urllib.quote(traceback.format_exc(), '')

    print SpinJSON.dumps(retmsg)

def do_ui(args):
    page = SpinWebUI.Page()

    campaign_list = ['ALL']

    page.add(SpinWebUI.JQueryUI(args=args,
                                campaign_list=campaign_list,
                                gamedata=gamedata
                                ))

    print '<!DOCTYPE html><html><head><meta http-equiv="X-UA-Compatible" content="IE=edge"><title>%s Analytics</title>' % gamedata['strings']['game_name'].upper()

    page.write_head(sys.stdout)

    print '</head><body>'

    page.write_body(sys.stdout)

    print '</body></html>'

def do_csv(qlist, csv_format, zip = True, sample_interval = 'day'):
    if 0: # Debugging
        print 'Content-Type: text/plain'
        print 'Content-Disposition: attachment; filename=%s.csv' % csv_format
        print 'Pragma: no-cache'
        print 'Cache-Control: no-cache'
        print ''
        print 'QUERY WAS '+repr(qlist)
        sys.stdout.flush()
        return

    # os.nice(20) # lower CPU priority
    userdb = stream_userdb()

    output_filename = csv_format
    if csv_format == 'time_series':
        output_filename += '_%s' % sample_interval
    output_filename += '.csv'

    print 'Content-Type: text/csv'
    if zip:
        print 'Content-Encoding: gzip'
    print 'Content-Disposition: attachment; filename=%s' % output_filename
    print 'Pragma: no-cache'
    print 'Cache-Control: no-cache'
    print ''
    sys.stdout.flush()

    if zip:
        fd = FastGzipFile.Writer(sys.stdout)
    else:
        fd = sys.stdout

    if csv_format == "time_series":
        writer = SpinUpcache.TimeSeriesCSVWriter(fd, gamedata)
    else:
        writer = SpinUpcache.CSVWriter(fd, gamedata)

    for user in userdb:
        matched = False
        for query in qlist:
            if query.match(user):
                matched = True
                break
        if matched:
            writer.write_user(user, time_now)

    fd.flush()
    sys.stdout.flush()

# probability distribution functions for Funnel significance testing
# X move to library. From http://elem.com/~btilly/effective-ab-testing/g-test-calculator.html
def uprob(x):
    p = 0.0
    absx = abs(x)
    if absx < 1.9:
        p = math.pow((1 +absx * (.049867347 + absx * (.0211410061 + absx * (.0032776263 + absx * (.0000380036 + absx * (.0000488906 + absx * .000005383)))))), -16)/2;
    elif absx <= 100:
        i = 18
        while i >= 1:
            p = i / (absx+p)
            i -= 1
            p = math.exp(-0.5*absx*absx) / math.sqrt(2*math.pi) / (absx+p)
    if x < 0:
        p = 1-p
    return p

def tprob(n,x):
    w = math.atan2(x/math.sqrt(n), 1.0)
    z = math.pow(math.cos(w), 2.0)
    y = 1
    i = n-2
    while i >= 2:
        y = 1.0 + float(i-1)/i * z * y
        i -= 2
    if (n%2) == 0:
        a = math.sin(w)/2
        b = 0.5
    else:
        if n == 1:
            a = 0
        else:
            a = math.sin(w)*math.cos(w)/math.pi
        b = 0.5 + w/math.pi
    return max(0, 1-b-a*y)

def chisqrprob(n, x):
    if x <= 0:
        return 1
    elif n > 100:
        return uprob((math.pow(x/n, 1.0/3.0) - (1 - 2.0/9.0/n))/math.sqrt(2.0/9.0/n))
    elif x > 400:
        return 0
    else:
        if (n%2) != 0:
            p = 2 * uprob(math.sqrt(x))
            a = math.sqrt(2.0/math.pi) * math.exp(-x/2) / math.sqrt(x)
            i1 = 1
        else:
            p = math.exp(-x/2)
            a = p
            i1 = 2
        for i in xrange(i1, n-1, 2):
            a *= x/i
            p += a
        return p

def g_test_with_yates(A_yes, A_no, B_yes, B_no):
    data = [[A_yes, A_no], [B_yes,B_no]]
    row_totals = [0]*len(data)
    column_totals = [0]*len(data[0])
    total = 0
    for i in xrange(len(data)):
        for j in xrange(len(data[0])):
            entry = data[i][j]
            row_totals[i] += entry
            column_totals[j] += entry
            total += entry
    if total < 1:
        return 999
    g_test = 0.0
    for i in xrange(len(data)):
        for j in xrange(len(data[0])):
            expected = float(row_totals[i]*column_totals[j])/float(total)
            seen = data[i][j]
            # yates correction
            if expected + 0.5 < seen:
                seen -= 0.5
            elif expected - 0.5 > seen:
                seen += 0.5
            else:
                seen = expected
            g_test += 2*seen*math.log(seen/expected)
    return g_test

def contingency_chisq_test(a, c, b, d):
    return (math.pow(a*d-b*c,2.0) * (a+b+c+d))/((a+b)*(c+d)*(b+d)*(a+c))

# Regression/Exponential Model LTV coefficients
REGEXP_LTV_COEFF = {'tr': {'intercept_reg': -0.08978, 'intercept_exp': -11.82,
                           'country_tier': {'1':{'exp': 0},
                                            '2':{'exp': 0.2244, 'reg': 0.07066},
                                            '3':{'exp': -1.000},
                                            '4':{'exp': -1.194, 'reg': 0.1935}},
                           'age_reg': 0.009533, 'age_reg_power2': 0, 'age_exp': 0.2329, 'age_exp_power2': -0.003106,
                           'age_exp_power3': 0.00001371, 'gendermale_exp': -1.320, 'gendermale_reg': 0.7999, 'browsersafari_reg': 0.1920, 'browserexplorer_reg': 0,
                           'townhall_exp': 2.128, 'townhall_reg': 0.1328, 'sessiontime_exp': 0.0001287, 'sessiontime_reg': 0.000008190,
                           'numofsessions_exp': 0, 'numofsessions_reg': -0.02648},
                    'mf2': {'intercept_reg': -0.0715722, 'intercept_exp': -11.50,
                           'country_tier': {'1':{'exp': 0},
                                            '2':{'exp': 0.09786},
                                            '3':{'exp': -1.143},
                                            '4':{'exp': -1.049, 'reg': 0.3038443}},
                            'age_reg': 0.0327486, 'age_reg_power2': -0.0002204, 'age_exp': 0.1060, 'age_exp_power2': -0.0006676,
                            'age_exp_power3': 0, 'gendermale_exp': 0, 'gendermale_reg': 0, 'browsersafari_reg': 0.2716917, 'browserexplorer_reg': 0,
                            'townhall_exp': 2.150, 'townhall_reg': 0.2293780, 'sessiontime_exp': 0.0001587, 'sessiontime_reg': 0,
                            'numofsessions_exp': -0.09588, 'numofsessions_reg': -0.0342553}
                    }

REGEXP_LTV_COEFF_NO_AGE = {'tr': {'intercept_reg': 0.3065, 'intercept_exp': -7.685,
                                  'country_tier': {'1':{'exp': 0},
                                                   '2':{'exp': 0.3071, 'reg': 0.08618},
                                                   '3':{'exp': -0.9393},
                                                   '4':{'exp': -1.595}},
                                  'age_reg': 0, 'age_reg_power2': 0, 'age_exp': 0, 'age_exp_power2': 0, 'age_exp_power3': 0,
                                  'gendermale_exp': 0, 'gendermale_reg': 0.8810, 'browsersafari_reg': 0.195, 'browserexplorer_reg': 0,
                                                                  'townhall_exp': 2.098, 'townhall_reg': 0.1265, 'sessiontime_exp': 0.0001328, 'sessiontime_reg': 0.000009329,
                                                                  'numofsessions_exp': 0, 'numofsessions_reg': -0.02932},
                           'mf2': {'intercept_reg': 0.99094, 'intercept_exp': -8.029,
                                   'country_tier': {'1':{'exp': 0},
                                                    '2':{'exp': 0.1673},
                                                    '3':{'exp': -1.057},
                                                    '4':{'exp': -1.5, 'reg': 0.23}},
                                   'age_reg': 0, 'age_reg_power2': 0, 'age_exp': 0, 'age_exp_power2': 0,'age_exp_power3': 0,
                                   'gendermale_exp': 0, 'gendermale_reg': 0, 'browsersafari_reg': 0.29094, 'browserexplorer_reg': 0.07978,
                                                                   'townhall_exp': 2.118, 'townhall_reg': 0.21913, 'sessiontime_exp': 0.0001613, 'sessiontime_reg': 0,
                                   'numofsessions_exp': -0.09858, 'numofsessions_reg': -0.0389}
                           }

def regexp_model_ltv_estimate(user):
    # make sure accounts have a reasonable creation time
    if time_now - user.get('account_creation_time',time_now) < 1: return None

    # need at least 3 hours of data
    if time_now - user['account_creation_time'] < 3*3600: return None

    # get coefficients for this game
    if game_id not in REGEXP_LTV_COEFF: return None # no data for this game
    coeff = REGEXP_LTV_COEFF[game_id]

    # AGE (years)
    years_old = -1
    if 'birthday' in user:
        try:
            years_old = SpinUpcache.birthday_to_years_old(user['birthday'], user['account_creation_time'])
        except:
            years_old = -1
    if years_old < 0: # unknown
        coeff = REGEXP_LTV_COEFF_NO_AGE[game_id] # switch to coefficients with no age

    regression = coeff['intercept_reg']
    exponential = coeff['intercept_exp']

    regression  += coeff['age_reg'] * years_old + coeff['age_reg_power2'] * math.pow(years_old,2)
    exponential += coeff['age_exp'] * years_old + coeff['age_exp_power2'] * math.pow(years_old,2) + coeff['age_exp_power3'] * math.pow(years_old,3)

    # COUNTRY TIER
    if ('country_tier' not in user) or (user['country_tier'] not in ('1','2','3','4')): return None
    exponential += coeff['country_tier'][user['country_tier']]['exp']
    regression  += coeff['country_tier'][user['country_tier']].get('reg',0)

    # GENDER
    if user.get('gender','male') != 'female': # assume male unless we specifically know otherwise
        exponential += coeff['gendermale_exp']
        regression += coeff['gendermale_reg']

    # BROWSER NAME
    if user.get('browser_name','Chrome') == 'Safari':
        regression += coeff['browsersafari_reg']
    if user.get('browser_name','Chrome') == 'Explorer':
        regression += coeff['browserexplorer_reg']

    # MAX CC LEVEL WITHIN FIRST 3 HOURS
    townhall_within_3h = 1
    for stime, level in user.get(gamedata['townhall']+'_level_at_time', {}).iteritems():
        t = long(stime)
        if t < 3*60*60:
            townhall_within_3h = max(townhall_within_3h, level)

    exponential += coeff['townhall_exp'] * townhall_within_3h
    regression  += coeff['townhall_reg'] * townhall_within_3h

    # TIME (seconds) SPENT IN GAME AND NUMBER OF SESSIONS WITHIN FIRST 3 HOURS
    time_spent = 0.0
    num_of_sessions = 0
    for start, end in user.get('sessions',[]):
        if start > 0 and end > 0:
            if (start - user.get('account_creation_time',time_now)) >= 3*60*60: break
            time_spent += (end - start)
            num_of_sessions += 1

    exponential += coeff['sessiontime_exp'] * time_spent
    regression  += coeff['sessiontime_reg'] * time_spent
    exponential += coeff['numofsessions_exp'] * num_of_sessions
    regression  += coeff['numofsessions_reg'] * num_of_sessions

    # ESTIMATE OF 90-DAY RECEIPTS (IN US DOLLARS)
    ltv = math.pow(math.pow(10.0,regression) * (math.exp(exponential) / (1.0 + math.exp(exponential)))/1.35,2)

    # ADJUST FOR KNOWN ONLINE SPENDERS
    if SkynetLTV.is_online_spender(user): ltv * 7.5

    # CROSS-TARGET or RETARGET CAMPAIGN
    camp = user.get('acquisition_campaign','unknown')
    if camp.startswith('7121'): return None # reacquisition
    elif camp.startswith('7122'): ltv * 2.5 # cross-target

    return ltv

def skynet_ltv_estimate_available(user, use_post_install_data = None):
    return SkynetLTV.ltv_estimate_available(game_id, gamedata, user, time_now, use_post_install_data = use_post_install_data)

def skynet_ltv_estimate(user, use_post_install_data = None):
    return SkynetLTV.ltv_estimate(game_id, gamedata, user, time_now, use_post_install_data = use_post_install_data)

# some data tables for setting up the funnel stages for each game

EXTENDED_TUTORIAL_QUESTS = {
    'mf': ['gather_resources',
           'build_7_robots',
           'attack_an_outpost',
           'upgrade_energy_level_2',
           'build_robotics_lab',
           'unlock_blaster_droids',
           'blaster_attack',
           'upgrade_central_computer_level_2',
           'activate_an_item'],
    'mf2': ['gather_resources',
           'build_7_robots',
           'attack_an_outpost',
           'upgrade_energy_level_2',
           'build_drone_lab',
           'unlock_avengers',
           'avenger_attack',
           'upgrade_central_computer_level_2',
           'activate_an_item'],
    'tr': ['gather_resources',
           'build_7_robots',
           'attack_an_outpost',
           'upgrade_energy_level_2',
           'build_academy',
           'unlock_machine_gunners',
           'blaster_attack',
           'upgrade_toc_level_2',
           'activate_an_item'],
    'bfm': ['gather_resources',
           'build_7_robots',
           'attack_an_outpost',
           'upgrade_energy_level_2',
           'build_rover_lab',
           'unlock_chaingunners',
           'blaster_attack',
           'upgrade_central_computer_level_2',
           'activate_an_item'],
    'sg': []
    }

TUTORIAL_AI = {
    'mf': [{'ui_name': 'Medusa (new)', 'key': 'ai_medusa2_progress', 'level_to_key': [0,3,4,5,6,7,8,9,10]}],
    'mf2':[{'ui_name': 'Wilder (tutorial08)', 'key': 'ai_tutorial08_progress', 'level_to_key': [0,3,4,5,6,7,8,9,10]}],
    'tr': [{'ui_name': 'Red Pole', 'key': 'ai_redpole_progress', 'level_to_key': [0,3,4,5,6,7,8,9,10]},
           {'ui_name': 'Mr. Skilling', 'key': 'ai_mrskilling_progress', 'num_levels':25},
           ],
    'bfm': [{'ui_name': 'Murdock (tutorial08)', 'key': 'ai_tutorial08_progress', 'level_to_key': [0,1,2,3,4,5,6,7,8]},
            {'ui_name': 'Crimson Armada (tutorial25)', 'key': 'ai_tutorial25_progress', 'num_levels': 25},
            ],
    'sg': [{'ui_name': 'Rall (tutorial25)', 'key': 'ai_tutorial25_progress', 'num_levels':25}],
    }

TECH_BUILDINGS = {
    'mf': ['robotics_lab', 'research_center'],
    'mf2': ['drone_lab', 'transport_lab', 'gunship_lab'],
    'tr': ['academy', 'maintenance_bay', 'flight_center'],
    'bfm': ['rover_lab', 'transport_lab', 'starcraft_lab'],
    'sg': []
    }

UNITS_BY_CATEGORY = dict([(cat, sorted([k for k in gamedata['units'].iterkeys() if \
                                        (gamedata['units'][k]['manufacture_category'] == cat and gamedata['units'][k].get('show_in_analytics',True))],
                                       key = lambda name: gamedata['units'][name]['max_hp'][0])) \
                          for cat in gamedata['strings']['manufacture_categories']])
ALL_UNITS = sum([UNITS_BY_CATEGORY[cat] for cat in gamedata['strings']['manufacture_categories']], [])

# AI events that follow the Normal/Heroic/Epic pattern
EVENT_STAGES = {
    'mf': [{'ui_name': 'Abyss', 'key': 'abyss', 'check_levels': range(0,8+1)},
           {'ui_name': 'Dark Moon', 'key': 'dark_moon', 'check_levels': range(0,8+1)},
           {'ui_name': 'Gale', 'key': 'gale', 'check_levels': range(0,8+1)},
           {'ui_name': 'Wasteland', 'key': 'wasteland'},
           {'ui_name': 'Phantom Attack', 'key': 'phantom_attack'},
           {'ui_name': 'Horde', 'key': 'horde'},
           {'ui_name': 'Zero', 'key': 'zero'},
           {'ui_name': 'Meltdown', 'key': 'meltdown'},
           {'ui_name': 'Prisoner', 'key': 'prisoner',  'difficulties': ['normal'], 'check_levels': range(0,-1) }, # range(1,24+1)},
           {'ui_name': 'Kingpin', 'key': 'kingpin',  'difficulties': ['normal'], 'check_levels': range(0,-1) }, # range(1,24+1)},
           {'ui_name': 'Mutiny', 'key': 'mutiny',  'difficulties': ['normal'], 'check_levels': range(0,-1) }, # range(1,60+1)}
           {'ui_name': 'Chunk', 'key': 'chunk',  'difficulties': ['normal'], 'check_levels': range(1,50+1)}
           ],
    'mf2': [{'ui_name': 'Karl (tutorial25)', 'key': 'tutorial25', 'difficulties': ['normal'], 'check_levels': range(1,25+1)}],
    'tr': [{'ui_name': 'Hamilton', 'key': 'hamilton', 'difficulties': ['normal'], 'check_levels': range(0,-1)}],
    'bfm': [],
    'sg': [],
    }
EVENT_DIFFICULTIES = {
    'normal': {'key': '', 'ui_name': 'Normal'},
    'heroic': {'key': '_heroic', 'ui_name': 'Heroic'},
    'epic': {'key': '_epic', 'ui_name': 'Epic'}
    }

# custom per-game stages
CUSTOM_STAGES = {
    'tr': [
    {'name': 'E130A Completed Alpha Task Force', 'func': lambda user: user.get('achievement:leader_set_alpha_L1_complete',0) >= 1 },
    {'name': 'E130B Completed Bravo Task Force', 'func': lambda user: user.get('achievement:leader_set_bravo_L1_complete',0) >= 1 },
    {'name': 'E130C Completed Charlie Task Force', 'func': lambda user: user.get('achievement:leader_set_charlie_L1_complete',0) >= 1 },
    {'name': 'E130D Completed Delta Task Force', 'func': lambda user: user.get('achievement:leader_set_delta_L1_complete',0) >= 1 },
    {'name': 'E130E Completed Echo Task Force', 'func': lambda user: user.get('achievement:leader_set_echo_L1_complete',0) >= 1 },
    {'name': 'E130F Completed Foxtrot Task Force', 'func': lambda user: user.get('achievement:leader_set_foxtrot_L1_complete',0) >= 1 },
    {'name': 'E130G Completed Golf Task Force', 'func': lambda user: user.get('achievement:leader_set_golf_L1_complete',0) >= 1 },
    {'name': 'E131A Entered Thunder Dome region', 'func': lambda user: user.get('thunder_dome_entered',0) >= 1 },
    {'name': 'E132A Built Weapons Factory', 'func': lambda user: user.get('weapon_factory_level',0) >= 1 },
    {'name': 'E132B Built Weapons Lab', 'func': lambda user: user.get('weapon_lab_level',0) >= 1 },
    {'name': 'E132C Built 1x Minefield', 'func': lambda user: user.get('minefield_level',0) >= 1 },
    {'name': 'E132D Crafted 1x Anti-Infantry Mine', 'func': lambda user: user.get('achievement:anti_infantry_minecraft_1',0) >= 1 },
    {'name': 'E132E Crafted 100x Anti-Infantry Mine', 'func': lambda user: user.get('achievement:anti_infantry_minecraft_100',0) >= 1 },
    {'name': 'E132F Crafted 500x Anti-Infantry Mine', 'func': lambda user: user.get('achievement:anti_infantry_minecraft_500',0) >= 1 },
    {'name': 'E132G Unlocked Anti-Armor Mines', 'mandatory_field': 'tech', 'func': lambda user: user['tech'].get('anti_transport_mines',0) > 0 },
    {'name': 'E132H Crafted 1x Anti-Armor Mine', 'func': lambda user: user.get('achievement:anti_tank_minecraft_1',0) >= 1 },
    {'name': 'E132I Crafted 100x Anti-Armor Mine', 'func': lambda user: user.get('achievement:anti_tank_minecraft_100',0) >= 1 },
    {'name': 'E132J Crafted 500x Anti-Armor Mine', 'func': lambda user: user.get('achievement:anti_tank_minecraft_500',0) >= 1 },
    {'name': 'E132K Unlocked Anti-Air Mines', 'mandatory_field': 'tech', 'func': lambda user: user['tech'].get('anti_air_mines',0) > 0 },
    {'name': 'E132L Crafted 1x Anti-Air Mine', 'func': lambda user: user.get('achievement:anti_air_minecraft_1',0) >= 1 },
    {'name': 'E132M Crafted 100x Anti-Air Mine', 'func': lambda user: user.get('achievement:anti_air_minecraft_100',0) >= 1 },
    {'name': 'E132N Crafted 500x Anti-Air Mine', 'func': lambda user: user.get('achievement:anti_air_minecraft_500',0) >= 1 },
    {'name': 'E136G Completed FASCAM Shield Set', 'func': lambda user: user.get('achievement:aoefire_shield_infantry_complete',0) >= 1 },
    ],
    'bfm': [],
    'sg': [
        {'name': 'E02 Maker House L2+', 'func': lambda user: user.get('extra_foreman_level',1) >= 2 },
        {'name': 'E03 Maker House L3+', 'func': lambda user: user.get('extra_foreman_level',1) >= 3 },
        {'name': 'E04 Maker House L4+', 'func': lambda user: user.get('extra_foreman_level',1) >= 4 },
        {'name': 'E05 Maker House L5+', 'func': lambda user: user.get('extra_foreman_level',1) >= 5 },
        {'name': 'E10 Built 2+ Barracks', 'func': lambda user: user.get('barracks_num',1) >= 2 },
        {'name': 'E11 Upgraded Barracks L2+', 'func': lambda user: user.get('barracks_level',1) >= 2 },
        {'name': 'E12 Upgraded Barracks L3+', 'func': lambda user: user.get('barracks_level',1) >= 3 },
        {'name': 'E13B Trained 20+ Burglars', 'func': lambda user: user.get('unit:thief:manufactured',0) >= 20 },
        {'name': 'E13C Trained 5+ Hulks', 'func': lambda user: user.get('unit:orc:manufactured',0) >= 5 },
        {'name': 'E13D Trained 20+ Archers', 'func': lambda user: user.get('unit:archer:manufactured',0) >= 20 },
        {'name': 'E13E Trained 10+ Knights', 'func': lambda user: user.get('unit:paladin:manufactured',0) >= 10 },
    ],
    'mf': [],
    'mf2': [],
}

FUNNEL_BASIC = [

    # These first stages are fixed to match the ad network KPIs
    {'name': 'A00 Account Created', 'func': lambda user: 1 },
    {'name': 'A01 Tutorial Complete', 'func': lambda user: user.get('completed_tutorial',False), 'show_p':True },
    {'name': 'A02 Central Computer L2 within 1 Day of acct creation', 'mandatory_age': 24*60*60, 'func': lambda user: SpinUpcache.player_history_within(user, gamedata['townhall']+'_level', 2, 1), 'show_p': True },
    {'name': 'A04A Returned between 24-48 hrs after acct creation', 'mandatory_age': 48*60*60, 'func': lambda user: SpinUpcache.visits_within(user, 2, after=1) >= 1, 'show_p':True },
    {'name': 'A04B Returned between 168-192 hrs after acct creation', 'mandatory_age': 192*60*60, 'func': lambda user: SpinUpcache.visits_within(user, 8, after=7) >= 1, 'show_p':True },
    {'name': 'A04C Returned between 672-696 hrs after acct creation', 'mandatory_age': 696*60*60, 'func': lambda user: SpinUpcache.visits_within(user, 29, after=28) >= 1, 'show_p':True },

#    {'name': 'A04C Retained at least One Day', 'mandatory_age': 2*24*60*60,
#     'func':         lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >= 24*60*60, 'show_p': True },

    {'name': 'A05 %CONV% Spent 5hr in game within 10 Days of acct creation', 'mandatory_age': 10*24*60*60,
     'func': lambda user: SpinUpcache.playtime_within(user, 10) >= 5*60*60, 'show_p': True },
    {'name': 'A06 Central Computer L3 within 10 Days of acct creation', 'mandatory_age': 10*24*60*60, 'func': lambda user: SpinUpcache.player_history_within(user, gamedata['townhall']+'_level', 3, 10), 'show_p': True},

    {'name': 'A07B Made A Payment within 3 Days of acct creation', 'mandatory_age': 3*24*60*60, 'func': lambda user: num_purchases_within(user,3) >= 1, 'show_p':True },
    {'name': 'A07C Made A Payment within 7 Days of acct creation', 'mandatory_age': 7*24*60*60, 'func': lambda user: num_purchases_within(user,7) >= 1, 'show_p':True },
    {'name': 'A07D Made A Payment within 30 Days of acct creation', 'mandatory_age': 30*24*60*60, 'func': lambda user: num_purchases_within(user,30) >= 1, 'show_p':True },
    {'name': 'A09 Made >=2 Payments within 14 Days of acct creation', 'mandatory_age': 14*24*60*60, 'func': lambda user: num_purchases_within(user,14) >= 2, 'show_p':True },

    {'name': 'A10 Mean 1-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 1*24*60*60, 'func': lambda user: money_spent_within(user,1) },
    {'name': 'A11 Mean 3-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 3*24*60*60, 'func': lambda user: money_spent_within(user,3) },
    {'name': 'A12 Mean 7-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 7*24*60*60, 'func': lambda user: money_spent_within(user,7) },
    {'name': 'A13 Mean 14-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 14*24*60*60, 'func': lambda user: money_spent_within(user,14) },
    {'name': 'A14 Mean 30-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 30*24*60*60, 'func': lambda user: money_spent_within(user,30) },
    {'name': 'A15 Mean 45-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 45*24*60*60, 'func': lambda user: money_spent_within(user,45) },
    {'name': 'A16 Mean 60-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 60*24*60*60, 'func': lambda user: money_spent_within(user,60) },
    {'name': 'A17 Mean 90-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 90*24*60*60, 'func': lambda user: money_spent_within(user,90) },
    {'name': 'A18 Mean 180-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 180*24*60*60, 'func': lambda user: money_spent_within(user,180) },
    {'name': 'A19 Mean 300-Day Receipts/User', 'aggregate': 'mean', 'mandatory_age': 300*24*60*60, 'func': lambda user: money_spent_within(user,300) },

#    {'name': 'Z97 Mean Receipts/Account Day', 'aggregate': 'mean_and_variance', 'show_p': True,
#     'func': lambda user: user.get('money_spent',0) / (float(time_now-user['account_creation_time'])/(24*60*60)) },
    {'name': 'A50 Skynet Demographic Estimated 90-Day Receipts/User', 'aggregate': 'mean',
     'mandatory_func': lambda user: skynet_ltv_estimate_available(user),
     'func': lambda user: skynet_ltv_estimate(user) },
    {'name': 'A51 Skynet Demographic+2h Estimated 90-Day Receipts/User', 'aggregate': 'mean',
     'mandatory_func': lambda user: skynet_ltv_estimate_available(user, use_post_install_data = 0.01),
     'func': lambda user: skynet_ltv_estimate(user, use_post_install_data = 0.01) },
    {'name': 'A52 Skynet Demographic+1d Estimated 90-Day Receipts/User', 'aggregate': 'mean',
     'mandatory_func': lambda user: skynet_ltv_estimate_available(user, use_post_install_data = 3),
     'func': lambda user: skynet_ltv_estimate(user, use_post_install_data = 1) },
    {'name': 'A52B Reg/Exp Test Model Demographic+3h Estimated 90-Day Receipts/User', 'aggregate': 'mean',
     'mandatory_func': lambda user: regexp_model_ltv_estimate(user) is not None,
     'func': lambda user: regexp_model_ltv_estimate(user) },
    {'name': 'A53 Skynet Demographic+10d Estimated 90-Day Receipts/User', 'aggregate': 'mean',
     'mandatory_func': lambda user: skynet_ltv_estimate_available(user, use_post_install_data = 240),
     'func': lambda user: skynet_ltv_estimate(user, use_post_install_data = 10) },
    {'name': 'A54 Actual 90-Day Total Receipts', 'aggregate': 'sum', 'mandatory_age': 90*24*60*60, 'func': lambda user: money_spent_within(user,90) },

    {'name': 'A98 Mean Receipts/User', 'aggregate': 'mean', 'func': lambda user: user.get('money_spent',0), },
    {'name': 'A99 Total Receipts', 'aggregate': 'sum', 'func': lambda user: user.get('money_spent',0) },
    ]

def get_tutorial_steps(gamedata):
    if gamedata['starting_conditions'].get('tutorial_state') == "COMPLETE": return [] # no rails tutorial in this game
    ret = []
    cur = "START"
    while True:
        ret.append(cur)
        if cur == 'COMPLETE':
            break
        cur = gamedata['tutorial'][cur]['next']
    return ret

def get_tutorial_stages(gamedata):
    steps = get_tutorial_steps(gamedata)
    ret = []
    for i in xrange(len(steps)):
        data = gamedata['tutorial'][steps[i]]
        if 'ui_description' in data:
            s = data['ui_description']
            if type(s) is list: # cond chain
                s = s[0][1]
            descr = ' "'+s[:32]+'..."'
        else:
            descr = ''
        ret.append({'name': 'B00%s%s %%CONV%% Rails Tutorial: %s%s' % (chr(ord('A')+i//26), chr(ord('A')+i%26), steps[i], descr),
                    'mandatory_func': lambda user: user.get('account_creation_time',0) >= 1395996178,
                    'func': lambda user, _steps=steps, _i=i: _steps.index(user.get('tutorial_state','START')) >= _i,
                    'convert_from': lambda user, _steps=steps, _i=i: _steps.index(user.get('tutorial_state','START')) >= _i-1, 'show_p': True })
    return ret

FUNNEL_ADVANCED = get_tutorial_stages(gamedata) + [

    # chain of extended tutorial missions
    {'name': 'B01 Tutorial Complete', 'func': lambda user: user.get('completed_tutorial',False), 'show_p':True },
    ] + \
    [{'name': 'B%02d %%CONV%% Quest: %s' % (i+1, gamedata['quests'][EXTENDED_TUTORIAL_QUESTS[game_id][i]]['ui_name']), 'convert_from': lambda user, i=i: user.get(('quest:%s:completed' % EXTENDED_TUTORIAL_QUESTS[game_id][i-1]) if (i>0) else 'completed_tutorial',0), 'show_p': True,
      'func': lambda user, i=i: user.get('quest:%s:completed' % EXTENDED_TUTORIAL_QUESTS[game_id][i],0) > 0 } for i in xrange(len(EXTENDED_TUTORIAL_QUESTS[game_id]))] + \
    [

    {'name': 'B99 Tutorial -> Quest: Central Computer L2', 'convert_from': lambda user: user.get('completed_tutorial',False),
     'func': lambda user: user.get('quest:upgrade_'+gamedata['townhall']+'_level_2:completed',0) > 0, 'show_p':True },

    # townhall levels
    {'name': 'C02 Central Computer L2',
     'func': lambda user: user.get(gamedata['townhall']+'_level',0) >= 2, 'show_p': True },
    {'name': 'C03 %CONV% Central Computer L3', 'convert_from': lambda user: user.get(gamedata['townhall']+'_level',0) >= 2,
     'func': lambda user: user.get(gamedata['townhall']+'_level',0) >= 3, 'show_p': True },
    {'name': 'C04 %CONV% Central Computer L4', 'convert_from': lambda user: user.get(gamedata['townhall']+'_level',0) >= 3,
     'func': lambda user: user.get(gamedata['townhall']+'_level',0) >= 4, 'show_p': True },
    {'name': 'C05 %CONV% Central Computer L5', 'convert_from': lambda user: user.get(gamedata['townhall']+'_level',0) >= 4,
     'func': lambda user: user.get(gamedata['townhall']+'_level',0) >= 5, 'show_p': True },
    {'name': 'C06 %CONV% Central Computer L6', 'convert_from': lambda user: user.get(gamedata['townhall']+'_level',0) >= 5,
     'func': lambda user: user.get(gamedata['townhall']+'_level',0) >= 6, 'show_p': True },
    {'name': 'C07 %CONV% Central Computer L7', 'convert_from': lambda user: user.get(gamedata['townhall']+'_level',0) >= 6,
     'func': lambda user: user.get(gamedata['townhall']+'_level',0) >= 7, 'show_p': True },

    # storage/harvester upgrades on the way to CC L3
    #{'name': 'D10 Upgraded Storage L2', 'func': lambda user: user.get('storages_max_level',0) >= 2 },
    {'name': 'D11 Built 3+ Harvesters', 'func': lambda user: user.get('harvesters_built',0) >= 3 },
    {'name': 'D12 Built 3+ Storages', 'func': lambda user: user.get('storages_built',0) >= 3 },
    {'name': 'D13 Built 4+ Harvesters', 'func': lambda user: user.get('harvesters_built',0) >= 4 },
    {'name': 'D14 Built 4+ Storages', 'func': lambda user: user.get('storages_built',0) >= 4 },
    {'name': 'D15 Upgraded a Harvester L2', 'func': lambda user: user.get('harvesters_max_level',0) >= 2 },
    {'name': 'D16 Upgraded a Storage L2', 'func': lambda user: user.get('storages_max_level',0) >= 2 },
    {'name': 'D17 Upgraded a Harvester L3', 'func': lambda user: user.get('harvesters_max_level',0) >= 3 },
    {'name': 'D18 Upgraded a Storage L3', 'func': lambda user: user.get('storages_max_level',0) >= 3 },

#    {'name': 'D20 CC2 %CONV% Built 4 Storages', 'convert_from': lambda user: user.get(gamedata['townhall']+'_level',0) >= 2,
#     'func': lambda user: user.get('storages_built',0) >= 4 },
#    {'name': 'D21 %CONV% Storage L3', 'convert_from': lambda user: user.get('storages_built',0) >= 4,
#     'func': lambda user: user.get('storages_max_level',0) >= 3 },
#    {'name': 'D22 %CONV% Storage L4', 'convert_from': lambda user: user.get('storages_max_level',0) >= 3,
#     'func': lambda user: user.get('storages_max_level',0) >= 4 },
#    {'name': 'D23 %CONV% Central Computer L3', 'convert_from': lambda user: user.get('storages_max_level',0) >= 4,
#     'func': lambda user: user.get(gamedata['townhall']+'_level',0) >= 3 },

    {'name': 'D23A Collected 1+ iron_deposit', 'func': lambda user: user.get('iron_deposits_collected',0) >= 1, 'show_p': True },
    {'name': 'D23B Collected 10+ iron_deposits', 'func': lambda user: user.get('iron_deposits_collected',0) >= 10, 'show_p': True },

    # looting
    {'name': 'D24A Harvested 1 Iron/Water', 'func': lambda user: user.get('resources_harvested',0) >= 1, 'show_p': True },
    {'name': 'D24B Harvested 50k Iron/Water', 'func': lambda user: user.get('resources_harvested',0) >= 50000, 'show_p': True },
    {'name': 'D24C Harvested 500k Iron/Water', 'func': lambda user: user.get('resources_harvested',0) >= 500000, 'show_p': True },
    {'name': 'D25A Looted 5k Iron/Water', 'func': lambda user: user.get('resources_looted',0) >= 5000, 'show_p': True },
    {'name': 'D25A Looted 50k Iron/Water', 'func': lambda user: user.get('resources_looted',0) >= 50000, 'show_p': True },
    {'name': 'D25A Looted 500k Iron/Water', 'func': lambda user: user.get('resources_looted',0) >= 500000, 'show_p': True },
    {'name': 'D25B Looted 500k Iron/Water in PvE', 'func': lambda user: user.get('resources_looted_from_ai',0) >= 500000, 'show_p': True },
    {'name': 'D25C Looted 500k Iron/Water in PvP', 'func': lambda user: user.get('resources_looted_from_human',0) >= 500000, 'show_p': True },
    {'name': 'D26 Lost 100k Iron/Water in PvP', 'func': lambda user: user.get('resources_stolen_by_human',0) >= 100000, 'show_p': True },

    # alliance activity
    {'name': 'F01 Joined an Alliance', 'func': lambda user: user.get('alliances_joined',0) >= 1, 'show_p': True },
    {'name': 'F02 Donated Units', 'func': lambda user: user.get('units_donated',0) >= 1, 'show_p': True },
    {'name': 'F03 Received Donated Units', 'func': lambda user: user.get('donated_units_received',0) >= 1, 'show_p': True },
    {'name': 'F04 Received a Birthday Gift', 'func': lambda user: user.get('birthday_gifts_received',0) >= 1, 'show_p': True },

    # unit unlocks
    ] + [{'name': 'RA%02d %%CONV%% Built %s' % (i+1, gamedata['buildings'][TECH_BUILDINGS[game_id][i]]['ui_name']), 'show_p': True,
          'func': lambda user, i=i: user.get(TECH_BUILDINGS[game_id][i]+'_level',0) > 0,
          'convert_from':  lambda user, i=i: (user.get(TECH_BUILDINGS[game_id][i-1]+'_level',0) > 0 if i>0 else True)} \
         for i in xrange(len(TECH_BUILDINGS[game_id]))
    ] + [{'name': 'RB%02d %%CONV%% Unlocked %s' % (i+1, gamedata['units'][ALL_UNITS[i]]['ui_name']), 'mandatory_field': 'tech', 'show_p': True,
          'convert_from': lambda user, i=i: (user['tech'].get(ALL_UNITS[i-1]+'_production',0)) if i>0 else True,
          'func': lambda user, i=i: user['tech'].get(ALL_UNITS[i]+'_production',0) > 0 } \
         for i in xrange(2,len(ALL_UNITS))
    ] + [


    # feature use
    {'name': 'F00 Used Feature: Multi-select', 'func': lambda user: user.get('feature_used:drag_select',False) },
    {'name': 'F01 Used Feature: Attack-Move', 'func': lambda user: user.get('feature_used:unit_attack_command',False) },
    {'name': 'F02 Used Feature: Battle History', 'func': lambda user: user.get('feature_used:battle_history',False) },
#    {'name': 'F03 Used Feature: Battle Log', 'func': lambda user: user.get('feature_used:battle_log',False) },
    {'name': 'F04 Used Feature: Leader Board', 'func': lambda user: user.get('feature_used:leaderboard',False) },
#    {'name': 'F05 Used Feature: Kbd Shortcuts List', 'func': lambda user: user.get('feature_used:keyboard_shortcuts_list',False) },
#    {'name': 'F06 Used Feature: Shift-Select', 'func': lambda user: user.get('feature_used:shift_select',False) },
#    {'name': 'F07 Used Feature: Settings Menu', 'func': lambda user: user.get('feature_used:settings_dialog',False) },
    {'name': 'F08A Used Feature: Skip Tutorial', 'func': lambda user: user.get('feature_used:skip_tutorial',False) },
    {'name': 'F08B Used Feature: Resume Tutorial', 'func': lambda user: user.get('feature_used:resume_tutorial',False) },
    {'name': 'F20 Disabled Sound Effects', 'func': lambda user: get_preference(user, 'sound_volume', 1) == 0 },
    {'name': 'F21 Disabled Music', 'func': lambda user: get_preference(user, 'music_volume', 1) == 0 },
    {'name': 'F22 Enabled "Manual Unit Control" preference', 'func': lambda user: get_preference(user, 'auto_unit_control', 1) == 0 },
    {'name': 'F23 Enabled "Show health on all units" preference', 'func': lambda user: get_preference(user, 'always_show_unit_health', 0) == 1 },
    {'name': 'F24 Enabled "Shoot Barriers" preference', 'func': lambda user: get_preference(user, 'target_barriers', 0) == 1 },
    {'name': 'F25 Disabled "Show Idle Buildings" preference', 'func': lambda user: get_preference(user, 'show_idle_buildings', 1) == 0 },
    {'name': 'F26 Disabled "FB Notifications" preference', 'func': lambda user: get_preference(user, 'enable_fb_notifications', 1) == 0 },
    {'name': 'F30A Used True HTML5 Full Screen', 'func': lambda user: user.get('feature_used:truefullscreen',False) },
    {'name': 'F30B Used True HTML5 Full Screen during tutorial', 'func': lambda user: user.get('feature_used:truefullscreen_during_tutorial',False) },
    {'name': 'F31 Used Scrolling', 'func': lambda user: user.get('feature_used:scrolling',False) },
    {'name': 'F32 Used Playfield Zoom', 'func': lambda user: user.get('feature_used:playfield_zoom',False) },

    {'name': 'F33A Looked at own achievements', 'func': lambda user: user.get('feature_used:own_achievements',False),
     'mandatory_func': lambda user: user.get('account_creation_time',0) >= 1395122699 },
    {'name': 'F33B Looked at another player\'s achievements', 'func': lambda user: user.get('feature_used:other_achievements',False),
     'mandatory_func': lambda user: user.get('account_creation_time',0) >= 1395122699 },

    {'name': 'F33C Looked at own statistics', 'func': lambda user: user.get('feature_used:own_statistics',False) },
    {'name': 'F33D Looked at another player\'s statistics', 'func': lambda user: user.get('feature_used:other_statistics',False) },

    {'name': 'F35 Saw Region Map Scroll Help', 'func': lambda user: user.get('feature_used:region_map_scroll_help',False) },
    {'name': 'F36 Scrolled Region Map', 'func': lambda user: user.get('feature_used:region_map_scrolled',False),
     'mandatory_func': lambda user: user.get('account_creation_time',0) >= 1395468178 },
    {'name': 'F37 Saw Hive Finder', 'func': lambda user: user.get('feature_used:hive_finder_seen',False) },
    {'name': 'F38 Used Hive Finder', 'func': lambda user: user.get('feature_used:hive_finder_used',False) },
    {'name': 'F39 Saw Attacker Finder', 'func': lambda user: user.get('feature_used:attacker_finder_seen',False) },
    {'name': 'F40 Used Attacker Finder', 'func': lambda user: user.get('feature_used:attacker_finder_used',False) },
    {'name': 'F41 Saw Strongpoint Finder', 'func': lambda user: user.get('feature_used:strongpoint_finder_seen',False) },
    {'name': 'F42 Used Strongpoint Finder', 'func': lambda user: user.get('feature_used:strongpoint_finder_used',False) },

    {'name': 'G01 Browser Supports WebGL', 'func': lambda user: user.get('browser_supports_webgl',False) },
    {'name': 'G02 Browser Supports WebSockets', 'func': lambda user: user.get('browser_supports_websocket',False) },
    {'name': 'G03 Browser Supports HTML5 AudioContext', 'func': lambda user: user.get('browser_supports_audio_context',False) },

    {'name': 'G10 Using a direct gameserver connection',
     'mandatory_func': lambda user: ('last_sprobe_result' in user) and ('connection' in user['last_sprobe_result']['tests']),
     'func': lambda user: user['last_sprobe_result']['tests']['connection'].get('method','unknown').startswith('direct') },
    {'name': 'G10A Direct SSL connection works',
     'mandatory_func': lambda user: ('last_sprobe_result' in user) and ('direct_ssl' in user['last_sprobe_result']['tests']),
     'func': lambda user: user['last_sprobe_result']['tests']['direct_ssl'].get('result',None)=='ok' },
    {'name': 'G10B Direct SSL connection NOT working: Timeout',
     'mandatory_func': lambda user: ('last_sprobe_result' in user) and ('direct_ssl' in user['last_sprobe_result']['tests']),
     'func': lambda user: user['last_sprobe_result']['tests']['direct_ssl'].get('error',None)=='timeout' },
    {'name': 'G10C Direct SSL connection NOT working: Firewall or browser issue',
     'mandatory_func': lambda user: ('last_sprobe_result' in user) and ('direct_ssl' in user['last_sprobe_result']['tests']),
     'func': lambda user: user['last_sprobe_result']['tests']['direct_ssl'].get('error',None) not in ('timeout',None) },
    {'name': 'G10D Direct SSL connection has bad ping (>1000ms)',
     'mandatory_func': lambda user: ('last_sprobe_result' in user) and ('direct_ssl' in user['last_sprobe_result']['tests']) and ('ping' in user['last_sprobe_result']['tests']['direct_ssl']),
     'func': lambda user: user['last_sprobe_result']['tests']['direct_ssl']['ping'] >= 1.0 },
    {'name': 'G10E Direct SSL connection has REALLY bad ping (>5000ms)',
     'mandatory_func': lambda user: ('last_sprobe_result' in user) and ('direct_ssl' in user['last_sprobe_result']['tests']) and ('ping' in user['last_sprobe_result']['tests']['direct_ssl']),
     'func': lambda user: user['last_sprobe_result']['tests']['direct_ssl']['ping'] >= 5.0 },

    {'name': 'G11 Direct WebSocket SSL connection works',
     'mandatory_func': lambda user: ('last_sprobe_result' in user) and ('direct_wss' in user['last_sprobe_result']['tests']) and (user['last_sprobe_result']['time'] >= 1387568140),
     'func': lambda user: user['last_sprobe_result']['tests']['direct_wss'].get('result',None)=='ok' },

    {'name': 'G99 Has bad frame rate (<20 FPS)',
     'mandatory_func': lambda user: ('last_sprobe_result' in user) and ('graphics' in user['last_sprobe_result']['tests']) and ('framerate' in user['last_sprobe_result']['tests']['graphics']),
     'func': lambda user: user['last_sprobe_result']['tests']['graphics']['framerate'] < 20.0 },


    # warehouse upgrades
    {'name': 'Q16A2 %CONV% Warehouse L2', 'convert_from': lambda user: user.get('warehouse_level',0) >= 1,
     'func': lambda user: user.get('warehouse_level',0) >= 2 },
    {'name': 'Q16A3 %CONV% Warehouse L3', 'convert_from': lambda user: user.get('warehouse_level',0) >= 2,
     'func': lambda user: user.get('warehouse_level',0) >= 3 },
    {'name': 'Q16A4 %CONV% Warehouse L4', 'convert_from': lambda user: user.get('warehouse_level',0) >= 3,
     'func': lambda user: user.get('warehouse_level',0) >= 4 },
    {'name': 'Q16A5 %CONV% Warehouse L5', 'convert_from': lambda user: user.get('warehouse_level',0) >= 4,
     'func': lambda user: user.get('warehouse_level',0) >= 5 },
    {'name': 'Q16A6 %CONV% Warehouse L6', 'convert_from': lambda user: user.get('warehouse_level',0) >= 5,
     'func': lambda user: user.get('warehouse_level',0) >= 6 },
    {'name': 'Q16A7 %CONV% Warehouse L7', 'convert_from': lambda user: user.get('warehouse_level',0) >= 6,
     'func': lambda user: user.get('warehouse_level',0) >= 7 },
    {'name': 'Q16A8 %CONV% Warehouse L8', 'convert_from': lambda user: user.get('warehouse_level',0) >= 7,
     'func': lambda user: user.get('warehouse_level',0) >= 8 },

    {'name': 'Q16D Looted An Item', 'func': lambda user: user.get('items_looted',0) >= 1 },
    {'name': 'Q16E Activated 2+ Items', 'func': lambda user: user.get('items_activated',0) >= 2 },

    # expeditions/store items
    {'name': 'Q17A0 Launched a FREE Expedition', 'func': lambda user: user.get('free_random_items',0) >= 1 },
    {'name': 'Q17A1 Launched a Paid Expedition', 'func': lambda user: user.get('random_items_purchased',0) >= 1 },
    {'name': 'Q17A2 Launched 10+ Paid Expeditions', 'func': lambda user: user.get('random_items_purchased',0) >= 10 },
    {'name': 'Q17A3 Spent 1,000+ Alloy on Paid Expeditions', 'func': lambda user: sum(user.get('gamebucks_spent_on_random_items_at_time',{}).itervalues(),0) >= 1000 },
    {'name': 'Q17B1 Purchased A Specific Item', 'func': lambda user: user.get('items_purchased',0) >= 1 },
    {'name': 'Q17B2 Purchased 10+ Specific Items', 'func': lambda user: user.get('items_purchased',0) >= 10 },
    {'name': 'Q17B3 Spent 1,000+ Alloy on Specific Items', 'func': lambda user: sum(user.get('gamebucks_spent_on_items_at_time',{}).itervalues(),0) >= 1000 },

    {'name': 'Q20A Built A Transmitter', 'func': lambda user: user.get('transmitter_level',0) >= 1 },
    {'name': 'Q20B %CONV% Transmitter L2', 'convert_from': lambda user: user.get('transmitter_level',0) >= 1,
     'func': lambda user: user.get('transmitter_level',0) >= 2 },

    {'name': 'Q21A Built A Squad Bay', 'func': lambda user: user.get('squad_bay_level',0) >= 1 },
    {'name': 'Q21B %CONV% Squad Bay L2', 'convert_from': lambda user: user.get('squad_bay_level',0) >= 1,
     'func': lambda user: user.get('squad_bay_level',0) >= 2 },

    {'name': 'Q22A Destroyed 1+ Hive', 'func': lambda user: user.get('hives_destroyed',0) >= 1 },
    {'name': 'Q22B Destroyed 5+ Hives', 'func': lambda user: user.get('hives_destroyed',0) >= 5 },
    {'name': 'Q22C Destroyed 10+ Hives', 'func': lambda user: user.get('hives_destroyed',0) >= 10 },

    {'name': 'Q23A Built A Logistics Dispatch', 'func': lambda user: user.get('fishing_factory_level',0) >= 1 },
    {'name': 'Q23B Collected 1+ Dispatch', 'func': lambda user: user.get('fish_completed',0) >= 1 },
    {'name': 'Q23B Collected 2+ Dispatches', 'func': lambda user: user.get('fish_completed',0) >= 2 },
    {'name': 'Q23B Collected 5+ Dispatches', 'func': lambda user: user.get('fish_completed',0) >= 5 },

    # tutorial AI progress
    ] + [{'name': 'E%02d Conquered %s L%d' % (level, AI['ui_name'], level), 'show_p': True,
          'func': lambda user, level=level, AI=AI: user.get(AI['key'],0) >= (AI['level_to_key'][level] if 'level_to_key' in AI else level),
          'convert_from': lambda user, level=level, AI=AI: (user.get(AI['key'],0) >= (AI['level_to_key'][level-1] if 'level_to_key' in AI else (level-1))) if level > 1 else True} \
         for AI in TUTORIAL_AI[game_id] for level in xrange(1,AI.get('num_levels',8)+1)
    ] + \
    CUSTOM_STAGES[game_id] + [

    # Immortal AI progress

    ] + [item for sublist in \

         [[{'name': 'Exx Started %s %s x1' % (ev['ui_name'], EVENT_DIFFICULTIES[diff]['ui_name']),
            'func': lambda user, ev=ev, diff=diff: user.get('ai_%s%s_times_started' % (ev['key'], EVENT_DIFFICULTIES[diff]['key']),0) >= 1 },
           {'name': 'Exx %%CONV%% Completed %s %s x1' % (ev['ui_name'], EVENT_DIFFICULTIES[diff]['ui_name']),
            'func': lambda user, ev=ev, diff=diff: user.get('ai_%s%s_times_completed' % (ev['key'], EVENT_DIFFICULTIES[diff]['key']),0) >= 1,
            'convert_from': lambda user, ev=ev, diff=diff: user.get('ai_%s%s_times_started' % (ev['key'], EVENT_DIFFICULTIES[diff]['key']),0) >= 1 },
           {'name': 'Exx Started %s %s x2' % (ev['ui_name'], EVENT_DIFFICULTIES[diff]['ui_name']),
            'func': lambda user, ev=ev, diff=diff: user.get('ai_%s%s_times_started' % (ev['key'], EVENT_DIFFICULTIES[diff]['key']),0) >= 2 },
           {'name': 'Exx %%CONV%% Completed %s %s x2' % (ev['ui_name'], EVENT_DIFFICULTIES[diff]['ui_name']),
            'func': lambda user, ev=ev, diff=diff: user.get('ai_%s%s_times_completed' % (ev['key'], EVENT_DIFFICULTIES[diff]['key']),0) >= 2,
            'convert_from': lambda user, ev=ev, diff=diff: user.get('ai_%s%s_times_started' % (ev['key'], EVENT_DIFFICULTIES[diff]['key']),0) >= 1 }
           ] + ([
           {'name': 'Exx %%CONV%% %s %s %s L%d' % (mode, ev['ui_name'], EVENT_DIFFICULTIES[diff]['ui_name'], level),
            'convert_from':  lambda user, ev=ev, diff=diff, level=level, mode=mode: user.get('ai_%s%s_%s' % (ev['key'], EVENT_DIFFICULTIES[diff]['key'], 'attempted' if mode=='Won' else 'progress'),0) >= (level if mode=='Won' else level-1),
            'func': lambda user, ev=ev, diff=diff, level=level, mode=mode: user.get('ai_%s%s_%s' % (ev['key'], EVENT_DIFFICULTIES[diff]['key'], 'progress' if mode=='Won' else 'attempted'),0) >= level }
           for level in ev['check_levels'] for mode in ('Attempted','Won')
           ] if ev.get('attempts',False) else [
           {'name': 'Exx %%CONV%% Won %s %s L%d' % (ev['ui_name'], EVENT_DIFFICULTIES[diff]['ui_name'], level),
            'convert_from':  lambda user, ev=ev, diff=diff, level=level: user.get('ai_%s%s_progress' % (ev['key'], EVENT_DIFFICULTIES[diff]['key']),0) >= level-1,
            'func': lambda user, ev=ev, diff=diff, level=level: user.get('ai_%s%s_progress' % (ev['key'], EVENT_DIFFICULTIES[diff]['key']),0) >= level }
           for level in ev.get('check_levels',(3,5,7,8))])

           for ev in EVENT_STAGES[game_id] for diff in ev.get('difficulties', ('normal','heroic','epic'))]
         for item in sublist] + [

    # attack activity

    {'name': 'K00 Launched 2 Attacks', 'func': lambda user: user.get('attacks_launched',0) >= 3, 'show_p': True }, # not counting tutorial
    {'name': 'K01 %CONV% Launched 3 Attacks', 'convert_from': lambda user: user.get('attacks_launched',0) >= 3,
     'func': lambda user: user.get('attacks_launched',0) >= 4, 'show_p': True }, # not counting tutorial
    {'name': 'K05 %CONV% Launched 5 Attacks', 'convert_from': lambda user: user.get('attacks_launched',0) >= 4,
     'func': lambda user: user.get('attacks_launched',0) >= 6, 'show_p': True }, # not counting tutorial
    {'name': 'K10 %CONV% Launched 10 Attacks', 'convert_from': lambda user: user.get('attacks_launched',0) >= 6,
     'func': lambda user: user.get('attacks_launched',0) >= 11, 'show_p': True }, # not counting tutorial
    {'name': 'K10 %CONV% Launched 25 Attacks', 'convert_from': lambda user: user.get('attacks_launched',0) >= 11,
     'func': lambda user: user.get('attacks_launched',0) >= 26, 'show_p': True }, # not counting tutorial
    {'name': 'K10 %CONV% Launched 50 Attacks', 'convert_from': lambda user: user.get('attacks_launched',0) >= 26,
     'func': lambda user: user.get('attacks_launched',0) >= 51, 'show_p': True }, # not counting tutorial
    {'name': 'K20 Suffered One Daily Attack', 'func': lambda user: user.get('daily_attacks_suffered',0) >= 1 },

    {'name': 'P01 Launched one PvP Attack', 'func': lambda user: user.get('attacks_launched_vs_human',0) > 0, 'show_p': True },
    {'name': 'P02 Launched >=10 PvP Attacks', 'func': lambda user: user.get('attacks_launched_vs_human',0) >= 10, 'show_p': True },
    {'name': 'P03 Suffered one PvP Attack', 'func': lambda user: user.get('attacks_suffered',0) > 0 },

    {'name': 'P10 Conquered 1+ Ladder PvP AI', 'func': lambda user: user.get('ai_ladder_conquests',0) >= 1, 'show_p': True },
    {'name': 'P10 Conquered 5+ Ladder PvP AIs', 'func': lambda user: user.get('ai_ladder_conquests',0) >= 5, 'show_p': True },
    {'name': 'P10 Conquered 10+ Ladder PvP AIs', 'func': lambda user: user.get('ai_ladder_conquests',0) >= 10, 'show_p': True },

    # retention

    {'name': 'R05 Retained 12 Hours', 'mandatory_age': 1*24*60*60,
     'func': lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >= 12*60*60, 'show_p': True },
    {'name': 'R10 %CONV% Retained One Day', 'mandatory_age': 2*24*60*60,
     'convert_from': lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >= 12*60*60,
     'func':         lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >= 24*60*60, 'show_p': True },
    {'name': 'R20 %CONV% Retained Two Days', 'mandatory_age': 3*24*60*60,
     'convert_from': lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >= 24*60*60,
     'func':         lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >= 48*60*60, 'show_p': True },
    {'name': 'R70 %CONV% Retained One Week', 'mandatory_age': 8*24*60*60,
     'convert_from': lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >= 48*60*60,
     'func':         lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >= 7*24*60*60, 'show_p': True },
    {'name': 'R73 %CONV% Retained 30 Days', 'mandatory_age': 35*24*60*60,
     'convert_from': lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >=  7*24*60*60,
     'func':         lambda user: user.get('last_login_time',0) - user.get('account_creation_time',0) >= 30*24*60*60, 'show_p': True },

    # time in game

    {'name': 'S00 Spent 5min in game', 'func': lambda user: user.get('time_in_game',0) >= 5*60, 'show_p': True },
    {'name': 'S01 %CONV% Spent 15min in game', 'convert_from': lambda user: user.get('time_in_game',0) >= 5*60,
     'func': lambda user: user.get('time_in_game',0) >= 15*60, 'show_p': True },
    {'name': 'S02 %CONV% Spent 30min in game', 'convert_from': lambda user: user.get('time_in_game',0) >= 15*60,
     'func': lambda user: user.get('time_in_game',0) >= 30*60, 'show_p': True },
    {'name': 'S03 %CONV% Spent 1hr in game', 'convert_from': lambda user: user.get('time_in_game',0) >= 30*60,
     'func': lambda user: user.get('time_in_game',0) >= 60*60, 'show_p': True },
    {'name': 'S04 %CONV% Spent 2hr in game', 'convert_from': lambda user: user.get('time_in_game',0) >= 60*60,
     'func': lambda user: user.get('time_in_game',0) >= 2*60*60, 'show_p': True },
    {'name': 'S05 %CONV% Spent 5hr in game', 'convert_from': lambda user: user.get('time_in_game',0) >= 2*60*60,
     'func': lambda user: user.get('time_in_game',0) >= 5*60*60, 'show_p': True },
    {'name': 'S10 %CONV% Spent 10hr in game', 'convert_from': lambda user: user.get('time_in_game',0) >= 5*60*60,
     'func': lambda user: user.get('time_in_game',0) >= 10*60*60, 'show_p': True },

    {'name': 'S99 Mean Total Hours in Game', 'aggregate': 'mean', 'func': lambda user: user.get('time_in_game',0)/3600.0 },

    # visits

    {'name': 'V02 Visited 2 Times', 'func': lambda user: len(user.get('sessions',[])) >= 2, 'show_p': True },
    {'name': 'V03 %CONV% Visited 3 Times', 'convert_from': lambda user: len(user.get('sessions',[])) >= 2,
     'func': lambda user: len(user.get('sessions',[])) >= 3, 'show_p': True },
    {'name': 'V05 %CONV% Visited 5 Times', 'convert_from': lambda user: len(user.get('sessions',[])) >= 3,
     'func': lambda user: len(user.get('sessions',[])) >= 5, 'show_p': True },
    {'name': 'V07 %CONV% Visited 7 Times', 'convert_from': lambda user: len(user.get('sessions',[])) >= 5,
     'func': lambda user: len(user.get('sessions',[])) >= 7, 'show_p': True },
    {'name': 'V50 %CONV% Visited 50 Times', 'convert_from': lambda user: len(user.get('sessions',[])) >= 7,
     'func': lambda user: len(user.get('sessions',[])) >= 50, 'show_p': True },

    {'name': 'V99 Visits 50:7 Ratio', 'mandatory_func': lambda user: len(user.get('sessions',[])) >= 7, 'func': lambda user: len(user.get('sessions',[])) >= 50 },
#    {'name': '800 Saw Payer Promo Offer (in-game)', 'func': lambda user: user.get('payer_promo_offered',0) > 0 },
    {'name': 'X01A Accepted Payer Promo Offer', 'func': lambda user: user.get('promo_gamebucks_earned',0) > 0 },
#    {'name': 'X02 Payer Promo Conversion Rate', 'mandatory_func': lambda user: user.get('payer_promo_offered',0) > 0, 'func': lambda user: user.get('promo_gamebucks_earned',0) > 0 },
    {'name': 'X01B Redeemed a Facebook Gift Card', 'func': lambda user: user.get('fb_gift_cards_redeemed',0) > 0 },

    # Facebook fan page Likes
    ] + [{'name': 'X02 Likes FB Fan Page: %s' % (' '.join([(x[0].upper()+x[1:]) if x!='of' else x for x in name.split('_')])),
          'mandatory_func': lambda user: user.get('frame_platform', 'fb') == 'fb' and user.get('has_facebook_likes',0) >= SpinConfig.FACEBOOK_GAME_FAN_PAGES_VERSION,
          'func': lambda user, _name=name: user.get('likes_'+_name,False)} for name in sorted(SpinConfig.FACEBOOK_GAME_FAN_PAGES.keys())] + [

    {'name': 'X04C Quest: Like App Page',
     'func': lambda user: user.get('quest:like_app_page:completed',0) > 0 or user.get('quest:like_mars_frontier:completed',0), 'show_p': True },

    # purchase activity
    {'name': 'X51 Made First Purchase at CC L1', 'mandatory_func': lambda user: ('money_spent_at_time' in user) and user.get('account_creation_time',-1) >= BUILDING_HISTORY_TIME,
     'func': lambda user: cc_level_when_first_purchase_made(user) == 1 },
    {'name': 'X52 Made First Purchase at CC L2', 'mandatory_func': lambda user: ('money_spent_at_time' in user) and user.get('account_creation_time',-1) >= BUILDING_HISTORY_TIME,
     'func': lambda user: cc_level_when_first_purchase_made(user) == 2 },
    {'name': 'X53 Made First Purchase at CC L3', 'mandatory_func': lambda user: ('money_spent_at_time' in user) and user.get('account_creation_time',-1) >= BUILDING_HISTORY_TIME,
     'func': lambda user: cc_level_when_first_purchase_made(user) == 3 },
    {'name': 'X54 Made First Purchase at CC L4', 'mandatory_func': lambda user: ('money_spent_at_time' in user) and user.get('account_creation_time',-1) >= BUILDING_HISTORY_TIME,
     'func': lambda user: cc_level_when_first_purchase_made(user) == 4 },
    {'name': 'X55 Made First Purchase at CC L5', 'mandatory_func': lambda user: ('money_spent_at_time' in user) and user.get('account_creation_time',-1) >= BUILDING_HISTORY_TIME,
     'func': lambda user: cc_level_when_first_purchase_made(user) == 5 },
    {'name': 'X56 Made First Purchase at CC L6', 'mandatory_func': lambda user: ('money_spent_at_time' in user) and user.get('account_creation_time',-1) >= BUILDING_HISTORY_TIME,
     'func': lambda user: cc_level_when_first_purchase_made(user) == 6 },

    {'name': 'X60 Spent Alloy/$ On Base or Unit Repair', 'func': lambda user: user.get('base_repairs_purchased',0) > 0 or user.get('unit_repair_speedups_purchased',0) > 0, 'show_p': True },

    {'name': 'X70 Sent an Alloy Gift', 'func': lambda user: user.get('gift_orders_sent',0) > 0 },
    {'name': 'X71 Received an Alloy Gift', 'func': lambda user: user.get('gift_orders_received',0) > 0 },

    {'name': 'Z00 Made A Payment', 'func': lambda user: user.get('money_spent',0) > 0, 'show_p': True },
    {'name': 'Z01 %CONV% Made 2 Payments', 'convert_from': lambda user: user.get('money_spent',0) > 0,
     'func': lambda user: user.get('num_purchases',0) > 1, 'show_p': True },
    {'name': 'Z02 %CONV% Receipts >$10', 'convert_from': lambda user: user.get('money_spent',0) > 0,
     'func': lambda user: user.get('money_spent',0) > 10.0, 'show_p': True },
    {'name': 'Z03 %CONV% Receipts >$25', 'convert_from': lambda user: user.get('money_spent',0) > 10.0,
     'func': lambda user: user.get('money_spent',0) > 25.0, 'show_p': True },
    {'name': 'Z04 %CONV% Receipts >$50', 'convert_from': lambda user: user.get('money_spent',0) > 25.0,
     'func': lambda user: user.get('money_spent',0) > 50.0, 'show_p': True },
    {'name': 'Z05 %CONV% Receipts >$100','convert_from': lambda user: user.get('money_spent',0) > 50.0,
     'func': lambda user: user.get('money_spent',0) > 100.0, 'show_p': True },

    ]

# make an index for the funnel stages (name -> (index, stage))
def make_funnel_index(funnel):
    by_name = {}
    for i in xrange(len(funnel)):
        assert funnel[i]['name'] not in by_name
        by_name[funnel[i]['name']] = (i, funnel[i])
    return by_name

def get_preference(user, name, default_value):
    pref = user.get('player_preferences',None)
    if type(pref) is dict:
        return pref.get(name, default_value)
    return default_value

def attacked_within(user, times, days):
    if 'attacks_launched_at_time' not in user: return False
    count = 0
    for sage, n in user['attacks_launched_at_time'].iteritems():
        age = int(sage)
        if days < 0 or (age < days*24*60*60): count += n
    return count >= times
def money_spent_and_num_purchases_within(user, days):
    if 'money_spent_at_time' not in user: return 0, 0
    count = 0
    total = 0
    for sage, amount in user['money_spent_at_time'].iteritems():
        age = int(sage)
        if days < 0 or (age < days*24*60*60):
            count += 1
            total += amount
    return total, count
def money_spent_within(user, days): return money_spent_and_num_purchases_within(user, days)[0]
def num_purchases_within(user, days): return money_spent_and_num_purchases_within(user, days)[1]

def cc_level_when_first_purchase_made(user):
    if 'money_spent_at_time' not in user: return -1
    first_purchase_age = min(map(int, user['money_spent_at_time'].iterkeys()))

    # note: when buying CC upgrades, the new CC level is set before the instant of purchase
    # so to be accurate here, bring the age backward in time a bit
    first_purchase_age -= 15
    return cc_level_at_age(user, first_purchase_age)

def cc_level_at_age(user, age):
    return SpinUpcache.building_level_at_age(user, gamedata['townhall'], age)

class UserGraphAccumulators(object):
    # bundle of accumulators for all active queries

    class QData:
        # bundle of accumulators for each particular query
        def __init__(self, query, time_range, interval_seconds, do_extrapolate, compute_spend_curve, compute_progression, strict_kfactor_calc,
                     reduce_data = None):
            self.query = query
            self.a_uniques = UserUniques(time_range[0], time_range[1], interval_seconds, query.offset, do_extrapolate)
            self.a_receipts = UserReceipts(time_range[0], time_range[1], interval_seconds, query.offset, do_extrapolate)
            self.a_attacks = UserAttacks(time_range[0], time_range[1], interval_seconds, query.offset)
            self.a_activity = UserActivity(time_range[0], time_range[1], interval_seconds, query.offset)
            self.a_retention = UserRetention(time_range[0], time_range[1], interval_seconds, query.offset) if interval_seconds == 24*60*60 else None
            self.a_spend_curve = UserSpendCurve(time_range[0], time_range[1], interval_seconds, query.offset, time_axis = UserSpendCurve.ACCT_AGE) if (interval_seconds == 24*60*60 and compute_spend_curve) else None
            self.a_time_curve = UserSpendCurve(time_range[0], time_range[1], interval_seconds, query.offset, time_axis = UserSpendCurve.TIME_IN_GAME) if (interval_seconds == 24*60*60 and compute_spend_curve) else None
            self.a_progress_curve = UserProgressCurve(time_range[0], time_range[1], interval_seconds, query.offset) if (interval_seconds == 24*60*60 and compute_progression) else None
            self.a_counter = UserCounter(time_range[0], time_range[1], interval_seconds, query.offset, strict_kfactor_calc = strict_kfactor_calc) if interval_seconds == 24*60*60 else None
            self.a_ads = None
            if reduce_data:
                self.reduce(reduce_data)

        def serialize(self):
            ret = {'query': self.query.serialize()}
            if self.a_uniques: ret['uniques'] = self.a_uniques.serialize()
            if self.a_receipts: ret['receipts'] = self.a_receipts.serialize()
            if self.a_attacks: ret['attacks'] = self.a_attacks.serialize()
            if self.a_activity: ret['activity'] = self.a_activity.serialize()
            if self.a_retention: ret['retention'] = self.a_retention.serialize()
            if self.a_spend_curve: ret['spend_curve'] = self.a_spend_curve.serialize()
            if self.a_time_curve: ret['time_curve'] = self.a_time_curve.serialize()
            if self.a_progress_curve: ret['progress_curve'] = self.a_progress_curve.serialize()
            if self.a_counter: ret['counter'] = self.a_counter.serialize()
            if self.a_ads: ret['ads'] = self.a_ads.serialize()
            return ret

        def reduce(self, reduce_data):
            if self.a_uniques: self.a_uniques.reduce([data['uniques'] for data in reduce_data if 'uniques' in data])
            if self.a_receipts: self.a_receipts.reduce([data['receipts'] for data in reduce_data if 'receipts' in data])
            if self.a_attacks: self.a_attacks.reduce([data['attacks'] for data in reduce_data if 'attacks' in data])
            if self.a_activity: self.a_activity.reduce([data['activity'] for data in reduce_data if 'activity' in data])
            if self.a_retention: self.a_retention.reduce([data['retention'] for data in reduce_data if 'retention' in data])
            if self.a_spend_curve: self.a_spend_curve.reduce([data['spend_curve'] for data in reduce_data if 'spend_curve' in data])
            if self.a_time_curve: self.a_time_curve.reduce([data['time_curve'] for data in reduce_data if 'time_curve' in data])
            if self.a_progress_curve: self.a_progress_curve.reduce([data['progress_curve'] for data in reduce_data if 'progress_curve' in data])
            if self.a_counter: self.a_counter.reduce([data['counter'] for data in reduce_data if 'counter' in data])

        def add_user(self, user):
            if self.query.match(user):
                if self.a_uniques: self.a_uniques.add(user)
                if self.a_retention: self.a_retention.add(user)
                if self.a_receipts: self.a_receipts.add(user)
                if self.a_attacks: self.a_attacks.add(user)
                if self.a_activity: self.a_activity.add(user)
                if self.a_spend_curve: self.a_spend_curve.add(user)
                if self.a_time_curve: self.a_time_curve.add(user)
                if self.a_progress_curve: self.a_progress_curve.add(user)
                if self.a_counter: self.a_counter.add(user)
        def finalize(self):
            if self.a_receipts: self.a_receipts.finalize()
            if self.a_attacks: self.a_attacks.finalize()
            if self.a_activity: self.a_activity.finalize()
            if self.a_retention: self.a_retention.finalize()
            if self.a_spend_curve: self.a_spend_curve.finalize()
            if self.a_time_curve: self.a_time_curve.finalize()
            if self.a_progress_curve: self.a_progress_curve.finalize()
            if self.a_counter:
                self.a_counter.finalize()
                # use this result to get cohort size
                self.csize = self.a_counter.result
                self.csize_primary = self.a_counter.k_den
                self.kfactor = self.a_counter.k_result
        def init_ad_data(self, time_range, interval_seconds):
            self.a_ads = AdAccumulator(time_range[0], time_range[1], interval_seconds, self.query.offset)
        def add_ad_datum(self, datum):
            if self.query.match_ads(datum):
                self.a_ads.add(datum)
        def finalize_ad_data(self):
            self.a_ads.finalize()

    def __init__(self, qlist, fork_base, fork_on, time_range, interval_seconds, do_extrapolate, compute_spend_curve, compute_progression, strict_kfactor_calc):
        self.fork_base = fork_base
        self.fork_on = fork_on
        self.time_range = time_range
        self.interval_seconds = interval_seconds
        self.do_extrapolate = do_extrapolate
        self.compute_spend_curve = compute_spend_curve
        self.compute_progression = compute_progression
        self.strict_kfactor_calc = strict_kfactor_calc
        self.forks = {}
        self.accum = [self.QData(query,
                                 self.time_range,
                                 self.interval_seconds,
                                 self.do_extrapolate,
                                 self.compute_spend_curve,
                                 self.compute_progression,
                                 self.strict_kfactor_calc) for query in qlist]

    def serialize(self):
        return [data.serialize() for data in self.accum]

    def reduce(self, serial_data):
        # merge slave-duplicated and forked queries
        data_by_query = {}
        for ser in serial_data:
            query = Query.deserialize(ser['query'])
            key = query.name # hash(query)
            if key not in data_by_query:
                data_by_query[key] = []
            data_by_query[key].append(ser)

        assert len(self.accum) == 0


        data_by_query_keys = sorted(data_by_query.keys(), lambda a, b: cmp(data_by_query[a][0]['query']['sort_key'], data_by_query[b][0]['query']['sort_key']))

        self.accum = [self.QData(Query.deserialize(data_by_query[k][0]['query']),
                                 self.time_range,
                                 self.interval_seconds,
                                 self.do_extrapolate,
                                 self.compute_spend_curve,
                                 self.compute_progression,
                                 self.strict_kfactor_calc,
                                 reduce_data = data_by_query[k]
                                 ) for k in data_by_query_keys]


    def add_user(self, user):
        if self.fork_base:
            # detect new query "fork" (i.e. a value for user[fork_on] that we haven't seen yet)
            if self.fork_base.match(user):
                do_fork = True

                if self.fork_on.startswith('acquisition_'):
                    if user.get('acquisition_secondary',False):
                        # when comparing acquisition campaigns/ads, don't include a campaign just because a secondary user appeared
                        # sometime during the sample interval. Require a primary acquisition.
                        do_fork = False
                    else:
                        # for acquisition comparisons, include accounts with missing data as MISSING
                        user_val = user.get(self.fork_on, 'MISSING')
                        if not user_val:
                            user_val = 'MISSING'

                        # de-obfuscate Facebook UI element clicks
                        if self.fork_on == 'acquisition_campaign':
                            user_val = SpinUpcache.remap_facebook_campaigns(user_val)
                            # if numeric, restrict to first 4 digits
                            if user_val[0:4].isdigit():
                                user_val = user_val[0:4]

                else:
                    # for all other comparisons, ignore users who do not have the fork_on metadata
                    user_val = user.get(self.fork_on, None)
                    if not user_val:
                        do_fork = False

                if do_fork and (user_val not in self.forks):
                    # create a new copy of the query
                    new_params = copy.deepcopy(self.fork_base.q)
                    new_params[self.fork_on] = [user_val]

                    # quotes in query names can screw up the JSON format
                    query_name = user_val.replace('"','').replace(' ','_')

                    newq = Query(new_params, query_name, offset = self.fork_base.offset)
                    self.forks[user_val] = newq
                    #self.qlist.append(newq)
                    self.accum.append(self.QData(newq, self.time_range, self.interval_seconds, self.do_extrapolate, self.compute_spend_curve, self.compute_progression, self.strict_kfactor_calc))

        for qdata in self.accum:
            qdata.add_user(user)

    def finalize(self):
        for qdata in self.accum: qdata.finalize()
    def init_ad_data(self, *args):
        for qdata in self.accum: qdata.init_ad_data(*args)
    def add_ad_datum(self, datum):
        for qdata in self.accum: qdata.add_ad_datum(datum)
    def finalize_ad_data(self):
        for qdata in self.accum: qdata.finalize_ad_data()


class UserFunnel(object):

    def blank_stage_cohort(self, cohort_name, aggregate):
        if aggregate == 'binary':
            # accumulate binary yes/no answers
            return {'name': cohort_name, 'N': 0, 'yes': 0,  'pay_corr':{'tp':0,'tn':0,'fp':0,'fn':0} }
        elif aggregate == 'mean_and_variance':
            # accumulate a list of values, one per user
            return {'name': cohort_name, 'N': 0, 'value': 0.0, 'each_value': [] }
        elif aggregate in ('sum', 'mean'):
            # accumulate a scalar sum or mean value
            return {'name': cohort_name, 'N': 0, 'value': 0.0 }
        else:
            raise Exception('unknown funnel stage aggregation mode '+aggregate)
    def blank_stage(self, fun):
        return {'stage': fun['name'].replace('%CONV%', '&nbsp;&nbsp;->' if self.conversion_rates else ''), 'original_name': fun['name'],
                'cohorts': [self.blank_stage_cohort(query.name, fun.get('aggregate','binary')) for query in self.qlist]}


    def __init__(self, qlist, funnel = None, use_stages = 'ALL', conversion_rates = True):
        self.qlist = qlist
        self.use_stages = use_stages
        self.conversion_rates = conversion_rates
        if use_stages == 'skynet':
            self.stage_data = FUNNEL_BASIC
        else:
            self.stage_data = FUNNEL_BASIC + FUNNEL_ADVANCED
        self.stage_data_by_name = make_funnel_index(self.stage_data)
        self.funnel = funnel if funnel else dict([(fun['name'], self.blank_stage(fun)) for fun in self.stage_data])

    def serialize(self):
        return {'funnel':self.funnel, 'use_stages': self.use_stages, 'conversion_rates': self.conversion_rates}
    @classmethod
    def deserialize(cls, qlist, data):
        return cls(qlist, funnel = data['funnel'], use_stages = data['use_stages'], conversion_rates = data['conversion_rates'])

    def add_user(self, user):
        creat = user.get('account_creation_time',-1)
        if creat <= 0: return

        for q in xrange(len(self.qlist)):
            query = self.qlist[q]
            if query.match(user):
                money_spent = user.get('money_spent',0)
                for name, data in self.funnel.iteritems():
                    fun = self.stage_data_by_name[name][1]
                    if 'mandatory_field' in fun and (fun['mandatory_field'] not in user):
                        continue
                    if 'mandatory_age' in fun and (time_now - creat < fun['mandatory_age']):
                        continue
                    if 'mandatory_func' in fun and not fun['mandatory_func'](user):
                        continue
                    if self.conversion_rates and ('convert_from' in fun) and (not fun['convert_from'](user)):
                        continue
                    cohort = data['cohorts'][q]
                    cohort['N'] += 1
                    aggregate = fun.get('aggregate', 'binary')
                    val = fun['func'](user)

                    if aggregate == 'binary':
                        is_yes = bool(val)
                        if is_yes:
                            cohort['yes'] += 1

                        # correlation with is_paying_user
                        corr = cohort['pay_corr']
                        if is_yes and money_spent > 0:
                            corr['tp'] += 1 # true positive
                        elif (not is_yes) and money_spent > 0:
                            corr['fn'] += 1 # false negative
                        elif is_yes and money_spent <= 0:
                            corr['fp'] += 1 # false positive
                        elif (not is_yes) and money_spent <= 0:
                            corr['tn'] += 1 # true negative
                    else:
                        cohort['value'] += val
                        if aggregate == 'mean_and_variance':
                            cohort['each_value'].append(val)

    @classmethod
    def reduce(cls, qlist, slist):
        dst = cls(qlist, funnel = None, use_stages = slist[0].use_stages, conversion_rates = slist[0].conversion_rates)
        for src in slist:
            for name in dst.funnel.iterkeys():
                if name not in src.funnel: continue # skip mismatched stages
                s = src.funnel[name]
                d = dst.funnel[name]
                assert len(s['cohorts']) == len(d['cohorts'])
                for j in xrange(len(d['cohorts'])):
                    s2 = s['cohorts'][j]
                    d2 = d['cohorts'][j]
                    assert s2['name'] == d2['name']
                    d2['N'] += s2['N']
                    if 'value' in d2:
                        d2['value'] += s2['value']
                    if 'each_value' in d2:
                        d2['each_value'] += s2['each_value']
                    if 'yes' in d2:
                        d2['yes'] += s2['yes']
                        for kind in ('tp','tn','fp','fn'):
                            d2['pay_corr'][kind] += s2['pay_corr'][kind]

        # perform aggregations
        for name, d in dst.funnel.iteritems():
            fun = dst.stage_data_by_name[name][1]
            agg = fun.get('aggregate',None)
            if agg in ('mean', 'mean_and_variance'):
                for cohort in d['cohorts']:
                    N = cohort['N']
                    if N > 0:
                        cohort['value'] /= float(N)
                    if agg == 'mean_and_variance':
                        mean = cohort['value']
                        assert N == len(cohort['each_value'])
                        cohort['value_var'] = sum(map(lambda x: math.pow(x-mean,2.0), cohort['each_value']))/float(N)
                        del cohort['each_value']
        return dst


def do_funnel_slave_func(input, info, seg):
    qlist = [Query.deserialize(s) for s in input['qlist']]

    master = get_userdb(info = info)
    slave = UserFunnel(qlist, use_stages = input['use_stages'], conversion_rates = bool(input['conversion_rates']))
    # os.nice(10) # lower CPU priority

    for user in master.iter_segment(seg):
        slave.add_user(user)
    return slave.serialize()

def do_funnel_slave(): Slave.do_slave(do_funnel_slave_func)


def do_funnel(qlist, significance_test, use_stages, conversion_rates):
    master = get_userdb()

    retmsg = {'success': True,
              'queries': [[query.name, query.q] for query in qlist],
              'compute_time': pretty_print_date(time_now),
              'upcache_time': pretty_print_date(master.info['update_time']),
              'conversion_rates': conversion_rates,
              'funnel': []}
    timers = {'start': time_now}


    slaves = Slave()
    input = {'qlist': [q.serialize() for q in qlist], 'use_stages': use_stages, 'conversion_rates': conversion_rates}

    slaves.start_slaves('--funnel-slave', input, master, do_funnel_slave_func)
    u_funnel = UserFunnel.reduce(qlist, [UserFunnel.deserialize(qlist, x) for x in slaves.get_results()])
    slaves = None

    # compute post-reduction statistics
    for name, stage in u_funnel.funnel.iteritems():
        i, fun = u_funnel.stage_data_by_name[name]
        aggregate = fun.get('aggregate', 'binary')

        if aggregate == 'binary':
            # compute Matthews Correlation Coefficient with each stage on is_paying_user
            # http://en.wikipedia.org/wiki/Matthews_correlation_coefficient
            for cohort in stage['cohorts']:
                if cohort['N'] > 0:
                    corr = cohort['pay_corr']
                    tp = corr['tp']; tn = corr['tn']; fp = corr['fp']; fn = corr['fn']
                    denom = (tp+fp)*(tp+fn)*(tn+fp)*(tn+fn)
                    if denom > 0:
                        mcc = ((tp*tn) - (fp*fn)) / math.sqrt(denom)
                        cohort['mcc_with_paying'] = mcc
                        cohort['mcc_with_paying_p'] = chisqrprob(1, cohort['N']*mcc*mcc)

        if len(qlist) == 2:
            # perform significance tests when comparing 2 cohorts
            #if (not fun.get('show_p',False)): continue
            A = stage['cohorts'][0]
            B = stage['cohorts'][1]

            if aggregate == 'binary':
                # G-tests on yes/no funnel stages
                if A['yes'] < 10 or B['yes'] < 10 or A['N'] < 10 or B['N'] < 10 or (A['N']-A['yes'])<10 or (B['N']-B['yes'])<10:
                    stage['p'] = 999
                else:
                    if significance_test == "g_test":
                        g_test_all = g_test_with_yates(A['yes'], A['N']-A['yes'], B['yes'], B['N']-B['yes'])
                    elif significance_test == "contingency_chisq":
                        g_test_all = contingency_chisq_test(A['yes'], A['N']-A['yes'], B['yes'], B['N']-B['yes'])

                    if g_test_all == 999:
                        stage['p'] = 999
                    else:
                        stage['p'] = chisqrprob(2-1, g_test_all)

            elif aggregate == 'mean_and_variance':
                # difference-of-means test
                if A['N'] > 10 and B['N'] > 10:
                    A_var = A['value_var']
                    B_var = B['value_bar']
                    pooled_var = (A_var*(A['N']+1) + B_var*(B['N']-1))/(A['N']+B['N']-2)
                    delta_sd = math.sqrt(pooled_var)*math.sqrt(1/float(A['N']) + 1/float(B['N']))
                    if delta_sd > 0:
                        t_stat = abs((A['value']-B['value'])/delta_sd)
                        n_dof = A['N']+B['N']-2

                        # p is double the tprob() because this is a two-tailed test
                        stage['p'] = 2.0*tprob(n_dof, t_stat)

    # for queries that only return users acquired via Skynet ads, add CPI info from the skynet adstats MongoDB database
    if use_stages == 'ALL' and all(q.is_skynet_query() for q in qlist):
        retmsg['using_skynet'] = True
        retmsg['skynet_queries'] = []

        # connect to MongoDB
        import pymongo
        dbconfig = SpinConfig.get_mongodb_config('skynet_remote' if 'skynet_remote' in SpinConfig.config['mongodb_servers'] else 'skynet_readonly')
        skynet_con = pymongo.MongoClient(*dbconfig['connect_args'], **dbconfig['connect_kwargs'])
        skynet_db = skynet_con[dbconfig['dbname']]

        # grab the funnel stages for receipts
        i_user = u_funnel.stage_data_by_name['A98 Mean Receipts/User'][0]
        stage_rec_user = u_funnel.funnel['A98 Mean Receipts/User']

        i_total = u_funnel.stage_data_by_name['A99 Total Receipts'][0]
        # stage_rec_total = u_funnel.funnel['A99 Total Receipts']

        # create new funnel stages for CPI and total cost
        fun_user = {'name': 'A98B Skynet Ad Cost/User (CPI)', 'aggregate': 'mean'}
        fun_total = {'name': 'A99B Total Skynet Ad Cost', 'aggregate': 'sum'}
        stage_cost_user = u_funnel.blank_stage(fun_user)
        stage_cost_total = u_funnel.blank_stage(fun_total)

        # for each aggregation group in the query
        for i in xrange(len(qlist)):
            # get list of included skynet parameters
            def make_list(x): return x if type(x) is list else [x]

            # collect all constraints to be ANDed together
            stgt_sources = [make_list(qlist[i].q[FIELD]) for FIELD in ('acquisition_ad_skynet', 'acquisition_ad_skynet2') if qlist[i].q.get(FIELD, None)]
            constrained = len(stgt_sources) > 0
            stgt_sources.append(['a'+game_id]) # require game_id match

            # return list of ORs (of all AND combinations threaded through stgt_sources)
            # ['atr']
            # ['krts','krtsi']
            # ['qb201']
            # should become
            # {'$or': ['atr_krts_qb201', 'atr_krtsi_qb201']}

            stgt_list = []
            for source in stgt_sources:
                if len(stgt_list) == 0:
                    stgt_list = source
                else:
                    stgt_list = [item+'_'+s for item in stgt_list for s in source]

            param_qs = {'$or': [SkynetLib.adgroup_dtgt_filter_query(SkynetLib.stgt_to_dtgt(stgt)) for stgt in stgt_list]}

            if not constrained:
                # when doing an unparameterized skynet query, require
                # 'k' (keyword present) or 'A' (lookalike audience) to
                # avoid seeing retention/xptarget spend in CPI.
                for i in xrange(len(param_qs['$or'])):
                    item = param_qs['$or'][i]
                    must_have_k = {'dtgt.k':{'$exists':True}}
                    must_have_k.update(item)
                    must_be_lookalike = {'dtgt.A':{'$regex':'^lap10'}}
                    must_be_lookalike.update(item)
                    param_qs['$or'][i] = {'$or':[must_have_k, must_be_lookalike]}

            # add up all spend within the time window
            time_range = qlist[i].q.get('account_creation_time', [-1,-1])
            time_qs = {}
            if time_range[0] > 0:
                time_qs['start_time'] = {'$gte': time_range[0]}
            if time_range[1] > 0:
                time_qs['end_time'] = {'$lt': time_range[1]}
            if time_qs:
                qs = {'$and':[time_qs, param_qs]}
            else:
                qs = param_qs
            #open('/tmp/zzz','a').write('%s\n' % (repr(qs)))

            retmsg['skynet_queries'].append(qs)

            agg_result = skynet_db.fb_adstats_hourly.aggregate([
                {'$match': qs},
                {'$group':{'_id':'ALL', 'spent':{'$sum':'$spent'}}}
                ])['result']

            if agg_result and len(agg_result) == 1:
                total_spent = agg_result[0]['spent']/100.0 # cents -> dollars
            else:
                total_spent = 0.0

            # get the "N" value for this measurement
            user_count = stage_rec_user['cohorts'][i]['N']
            stage_cost_user['cohorts'][i]['N'] = user_count
            if user_count > 0:
                stage_cost_user['cohorts'][i]['value'] = total_spent/user_count
            stage_cost_total['cohorts'][i]['N'] = user_count
            stage_cost_total['cohorts'][i]['value'] = total_spent

        # insert the new funnel stages
        u_funnel.funnel[fun_user['name']] = stage_cost_user
        u_funnel.funnel[fun_total['name']] = stage_cost_total

        # to sort these properly into the funnel output, splice them in right next to the receipts stages
        u_funnel.stage_data_by_name[fun_user['name']] = (i_user-0.5, fun_user)
        u_funnel.stage_data_by_name[fun_total['name']] = (i_total-0.5, fun_total)

    # turn the funnel back into a list for final output
    # note: use original_name instead of stage because of the %CONV% replacement
    funnel_list = list(sorted(u_funnel.funnel.values(), key = lambda x: u_funnel.stage_data_by_name[x['original_name']][0]))
    retmsg['funnel'] = funnel_list

    timers['done'] = time.time()
    time_info = 'Total time: %.3fs' % \
                (timers['done']-timers['start'])
    retmsg['time_info'] = time_info

    sys.stderr.write(time_info)
    sys.stderr.write('\n')
    return retmsg

def do_units(qlist, N_min, sample_interval):
    print 'Content-Type: text/javascript'
    print ''
    retmsg = {'success': True,
              'queries': [[query.name, query.q] for query in qlist],
              'compute_time': pretty_print_date(time_now),
              'units': []}
    timers = {'start': time_now}

    # os.nice(20) # lower CPU priority

    userdb = stream_userdb()
    timers['read_upcache'] = time.time()

    def get_weight(unit_name):
        return gamedata['units'][unit_name]['max_hp'][0]

    unit_names = sorted(gamedata['units'].keys())
    total_weight = float(sum([get_weight(u) for u in unit_names]))

    retmsg['units'] = [ {'query': query.name,
                         'units': [{'name': name,
                                    'manufactured': 0, 'manufactured_weighted': 0,
                                    'killed': 0, 'killed_weighted': 0,
                                    'lost': 0, 'lost_weighted': 0} for name in unit_names] } \
                        for query in qlist]

    for user in userdb:
        creat = user.get('account_creation_time',-1)
        if creat <= 0: continue

        for q in xrange(len(qlist)):
            query = qlist[q]
            if query.match(user):
                data = retmsg['units'][q]['units']
                for n in xrange(len(unit_names)):
                    name = unit_names[n]
                    dat = data[n]
                    weight = float(get_weight(name)) / total_weight
                    dat['manufactured'] += user.get('unit:'+name+':manufactured')
                    dat['manufactured_weighted'] += weight * user.get('unit:'+name+':manufactured')
                    dat['killed'] += user.get('unit:'+name+':killed')
                    dat['killed_weighted'] += weight * user.get('unit:'+name+':killed')
                    dat['lost'] += user.get('unit:'+name+':lost')
                    dat['lost_weighted'] += weight * user.get('unit:'+name+':lost')

    timers['done'] = time.time()
    time_info = 'Total time: %.3fs (read_upcache %.3fs compute %.3fs)' % \
                (timers['done']-timers['start'],
                 timers['read_upcache']-timers['start'],
                 timers['done']-timers['read_upcache'])
    retmsg['time_info'] = time_info

    sys.stderr.write(time_info)
    sys.stderr.write('\n')
    SpinJSON.dump(retmsg, sys.stdout)

def do_graph_slave_func(input, info, seg):
    qlist = [Query.deserialize(s) for s in input['qlist']]

    master = get_userdb(info = info)
    slave = UserGraphAccumulators(qlist, Query.deserialize(input['fork_base']) if input['fork_base'] else None,
                                  input['fork_on'], input['time_range'], input['interval_seconds'],
                                  input['do_extrapolate'], input['compute_spend_curve'],
                                  input['compute_progression'], input['strict_kfactor_calc'])
    # os.nice(20) # lower CPU priority
    for user in master.iter_segment(seg):
        slave.add_user(user)
    return slave.serialize()

def do_graph_slave(): Slave.do_slave(do_graph_slave_func)

def do_graph(qlist, bounds, N_min, sample_interval, utc_offset = 0, interval_window = -1, fork_base = None, fork_on = None, overlay_mode = None, do_extrapolate = True, compute_progression = True, compute_spend_curve = True, compute_ads = True):

    retmsg = {'success': True,
              'queries': [],
              'utc_offset': utc_offset,
              'compute_time': pretty_print_date(time_now) + ('' if utc_offset == 0 else ' DISPLAYED AS UTC%+d' % (utc_offset/3600)),
              'graphs': []}

    timers = {'start': time_now, 'userdb': time_now, 'init_query': time_now,
              'map_userdb': time_now, 'reduce_userdb': time_now,
              'traverse_final': time_now}

    sys.stderr.write('opening userdb...')
    userdb = get_userdb()
    retmsg['upcache_time'] = pretty_print_date(userdb.info['update_time'])
    sys.stderr.write('done\n')
    timers['userdb'] = time.time()

    time_range = [SpinConfig.game_launch_date(), time_now]
    if bounds[0] > 0:
        time_range[0] = min(time_range[0], bounds[0])

    INTERVALS = { 'week': {'seconds': 7*24*60*60, 'name': 'Week', 'name_adj': 'Weekly', 'letter': 'W', 'window':7 },
                  'day': {'seconds': 24*60*60, 'name': 'Day', 'name_adj': 'Daily', 'letter': 'D', 'window':7 },
                  'qday': {'seconds': 6*60*60, 'name': 'QuarterDay', 'name_adj': '6-Hourly', 'letter': 'Q', 'window':7 },
                  'hour': {'seconds': 1*60*60, 'name': 'Hour', 'name_adj': 'Hourly', 'letter': 'H', 'window': 12 },
                  'minute': {'seconds':60, 'name': 'Minute', 'name_adj':'Minutely', 'letter': 'Min', 'window': 30 },
                  }
    interval_seconds = INTERVALS[sample_interval]['seconds']
    interval_ui_name = INTERVALS[sample_interval]['name']
    interval_ui_name_adj = INTERVALS[sample_interval]['name_adj']
    interval_letter = INTERVALS[sample_interval]['letter']
    if interval_window < 1: interval_window = INTERVALS[sample_interval]['window']

    if 1 or interval_seconds >= 24*60*60:
        # quantize START (but not end) of time range to days IN THE GUI TIME ZONE
        time_range[0] = int(SpinConfig.cal_to_unix(SpinConfig.unix_to_cal(time_range[0])) - utc_offset)

    strict_kfactor_calc = False

    # detect campaign-based queries, and turn on strict K-factor calc if so
    for query in qlist:
        if fork_on and fork_on.startswith('acquisition_'):
            strict_kfactor_calc = True
            break
        for key in query.q.iterkeys():
            if key.startswith('acquisition_'):
                strict_kfactor_calc = True
                break
        if strict_kfactor_calc:
            break

    # set up input block for slave processes
    input = { 'qlist': [q.serialize() for q in qlist],
              'fork_base': fork_base.serialize() if fork_base else None,
              'fork_on': fork_on,
              'time_range': time_range,
              'interval_seconds': interval_seconds,
              'do_extrapolate': do_extrapolate,
              'compute_spend_curve': compute_spend_curve,
              'compute_progression': compute_progression,
              'strict_kfactor_calc': strict_kfactor_calc
              }

    # this accumulator will hold the master results reduced from all slaves
    accum = UserGraphAccumulators([], fork_base, fork_on, time_range, interval_seconds, do_extrapolate, compute_spend_curve, compute_progression, strict_kfactor_calc)

    slaves = Slave()
    slaves.start_slaves('--graph-slave', input, userdb, do_graph_slave_func)

    timers['init_query'] = time.time()

    COMPARE_OLD = False
    if COMPARE_OLD:
        old_accum = UserGraphAccumulators(qlist, fork_base, fork_on, time_range, interval_seconds, do_extrapolate, compute_spend_curve, compute_progression, strict_kfactor_calc)
        for user in stream_userdb():
            old_accum.add_user(user)
        old_accum.finalize()

    slave_results = sum(slaves.get_results(), [])
    timers['map_userdb'] = time.time()

    accum.reduce(slave_results)
    accum.finalize()

    if COMPARE_OLD:
        accum = old_accum

    retmsg['queries'] = [[data.query.name, data.query.q] for data in accum.accum]

    timers['reduce_userdb'] = time.time()

    # get ad spend data, if applicable
    if compute_ads and \
       sample_interval == 'day' and \
       (len(qlist) == 1 or \
        overlay_mode in ['acquisition_campaign']) and \
       has_ad_data():

        accum.init_ad_data(time_range, interval_seconds)
        ad_data = stream_ad_data()
        for datum in ad_data:
            accum.add_ad_datum(datum)
        accum.finalize_ad_data()

    timers['traverse_ads'] = time.time()

    # use first query dataset to test for existence of particular accumulators
    example = accum.accum[0]

    retmsg['graphs'].append(SpinWebUI.Chart('%sAU' % interval_letter,
                                            [make_data_series(data.a_uniques.au, 'number', N_samples=data.a_uniques.au, name=data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
    if example.a_uniques.concurrent:
        retmsg['graphs'].append(SpinWebUI.Chart('Peak Concurrent Users By %s' % interval_ui_name,
                                                [make_data_series(data.a_uniques.concurrent, 'number', N_samples=data.a_uniques.concurrent, name=data.query.name) for data in accum.accum],
                                                extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
    retmsg['graphs'].append(SpinWebUI.Chart('Minutes Spent In Game Per %sAU' % interval_letter,
                                            [make_quotient_series(dict([(kv[0],kv[1]/60.0) for kv in data.a_uniques.tig.iteritems()]), data.a_uniques.au, 'number', name=data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
#    retmsg['graphs'].append(SpinWebUI.Chart('Paying users as fraction of %sAU' % interval_letter,
#                                            [make_quotient_series(data.a_uniques.paying_users, data.a_uniques.au, 'percent', name=data.query.name) for data in accum.accum],
#                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
    retmsg['graphs'].append(SpinWebUI.Chart('%sAU (%d-%s Trailing Average)' % (interval_letter, interval_window, interval_ui_name),
                                            [make_averaged_series(data.a_uniques.au, 'number', N_samples=data.a_uniques.au, window=interval_window, name=data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    retmsg['graphs'].append(SpinWebUI.Chart('%s New Users Acquired' % (interval_ui_name_adj),
                                            [make_data_series(data.a_uniques.new_users, 'number', N_samples=data.a_uniques.new_users, name=data.query.name) for data in accum.accum],
                                             extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    retmsg['graphs'].append(SpinWebUI.Chart('%s Tutorial Completion Rate' % (interval_ui_name_adj),
                                            [make_quotient_series(data.a_uniques.tutorial_completions, data.a_uniques.new_users, 'percent', name=data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    if example.a_counter:
        retmsg['graphs'].append(SpinWebUI.Chart('Total User Count',
                                                [make_data_series(data.csize, 'number', N_samples=data.csize, name=data.query.name) for data in accum.accum],
                                                bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    retmsg['graphs'].append(SpinWebUI.Chart('%s Receipts' % (interval_ui_name_adj),
                                            [make_data_series(data.a_receipts.period_receipts['money']["ALL"], 'big_money',
                                                              N_samples = data.a_receipts.period_purchases,
                                                              name = data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
    retmsg['graphs'].append(SpinWebUI.Chart('%s Receipts (%d-%s Trailing Average)' % (interval_ui_name_adj, interval_window, interval_ui_name),
                                            [make_averaged_series(data.a_receipts.period_receipts['money']["ALL"], 'big_money',
                                                                  window = interval_window,
                                                                  N_samples = data.a_receipts.period_purchases,
                                                                  name = data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    for data in accum.accum:
        # put these on a separate panel if there is more than 1 query
        panel = 'breakdown' if len(accum.accum) > 1 else 'graph'

        # categorized money receipts
        if False and len(data.a_receipts.period_receipts['money']) > 1:
            retmsg['graphs'].append(SpinWebUI.Chart('%s Receipts By Category (excluding purchases of %s): %s' % (interval_ui_name_adj, CURRENCY_UI_NAMES()['gamebucks'], data.query.name),
                                                    [make_data_series(data.a_receipts.period_receipts['money'][cat], 'big_money',
                                                                      N_samples = data.a_receipts.period_purchases,
                                                                      name = cat) for cat in UserReceipts.CATEGORIES if (not cat.startswith('ALL'))],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, panel=panel, utc_offset=utc_offset).get_json())

            retmsg['graphs'].append(SpinWebUI.Chart('%s Receipts By Category (excluding purchases of %s): %s (%d-%s Trailing Average)' % (interval_ui_name_adj, CURRENCY_UI_NAMES()['gamebucks'], data.query.name, interval_window, interval_ui_name),
                                                    [make_averaged_series(data.a_receipts.period_receipts['money'][cat], 'big_money',
                                                                          window = interval_window,
                                                                          N_samples = data.a_receipts.period_purchases,
                                                                          name = cat) for cat in UserReceipts.CATEGORIES if (not cat.startswith('ALL'))],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, panel=panel, utc_offset=utc_offset).get_json())

        # categorized gamebucks receipts
        if 'gamebucks' in data.a_receipts.period_receipts:
            retmsg['graphs'].append(SpinWebUI.Chart('%s %s Expenditures By Category: %s' % (interval_ui_name_adj, CURRENCY_UI_NAMES()['gamebucks'], data.query.name),
                                                    [make_data_series(data.a_receipts.period_receipts['gamebucks'][cat], 'number',
                                                                      name = cat) for cat in UserReceipts.CATEGORIES if (not cat.startswith('ALL'))],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, panel=panel, utc_offset=utc_offset).get_json())

            retmsg['graphs'].append(SpinWebUI.Chart('%s %s Expenditures By Category: %s (%d-%s Trailing Average)' % (interval_ui_name_adj, CURRENCY_UI_NAMES()['gamebucks'], data.query.name, interval_window, interval_ui_name),
                                                    [make_averaged_series(data.a_receipts.period_receipts['gamebucks'][cat], 'number',
                                                                          window = interval_window,
                                                                          name = cat) for cat in UserReceipts.CATEGORIES if (not cat.startswith('ALL'))],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, panel=panel, utc_offset=utc_offset).get_json())

    if example.a_counter:
        retmsg['graphs'].append(SpinWebUI.Chart('Total Receipts',
                                                [make_data_series(data.a_receipts.cum_receipts, 'big_money', N_samples=data.csize, name = data.query.name) for data in accum.accum],
                                                extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    if example.a_ads:
        ad_series = [make_data_series(data.a_ads.period_spend, 'big_money', name=data.query.name) for data in accum.accum if data.a_ads.has_data]
        if len(ad_series) > 0:
            retmsg['graphs'].append(SpinWebUI.Chart('%s Ad Spend' % interval_ui_name_adj,
                                                    ad_series,
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
            retmsg['graphs'].append(SpinWebUI.Chart('%s Gross Profit' % interval_ui_name_adj,
                                                    [make_data_series(dict([(t, data.a_receipts.period_receipts['money']["ALL"][t]-data.a_ads.period_spend[t]) for t in data.a_ads.period_spend.iterkeys()]),
                                                                      'big_money', name=data.query.name) for data in accum.accum if data.a_ads.has_data],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
            retmsg['graphs'].append(SpinWebUI.Chart('%s Gross Profit (%d-%s Trailing Average)' % (interval_ui_name_adj, interval_window,  interval_ui_name),
                                                    [make_averaged_series(dict([(t, data.a_receipts.period_receipts['money']["ALL"][t]-data.a_ads.period_spend[t]) for t in data.a_ads.period_spend.iterkeys()]),
                                                                          'big_money', window = interval_window, name=data.query.name) for data in accum.accum if data.a_ads.has_data],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
            retmsg['graphs'].append(SpinWebUI.Chart('Total Ad Spend',
                                                    [make_data_series(data.a_ads.cum_spend, 'big_money', name=data.query.name) for data in accum.accum if data.a_ads.has_data],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
            retmsg['graphs'].append(SpinWebUI.Chart('Total Gross Profit',
                                                    [make_data_series(dict([(t, data.a_receipts.cum_receipts[t]-data.a_ads.cum_spend[t]) for t in data.a_ads.cum_spend.iterkeys()]),
                                                                      'big_money', name=data.query.name) for data in accum.accum if data.a_ads.has_data],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
            if example.a_counter:
                retmsg['graphs'].append(SpinWebUI.Chart('Effective CPI (includes referred viral installs)',
                                                        [make_quotient_series(data.a_ads.cum_spend, data.csize, 'little_money', name=data.query.name) for data in accum.accum if data.a_ads.has_data],
                                                        extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
                if example.a_receipts:
                    retmsg['graphs'].append(SpinWebUI.Chart('Gross Margin/User',
                                                            [make_quotient_series(dict([(t, data.a_receipts.cum_receipts[t]-data.a_ads.cum_spend[t]) for t in data.a_ads.cum_spend.iterkeys()]), data.csize, 'little_money', name=data.query.name) for data in accum.accum if data.a_ads.has_data],
                                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())


    if example.a_counter:
        retmsg['graphs'].append(SpinWebUI.Chart('Total Receipts/User',
                                                [make_quotient_series(data.a_receipts.cum_receipts, data.csize, 'little_money', name=data.query.name) for data in accum.accum],
                                                extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

        retmsg['graphs'].append(SpinWebUI.Chart('Total Receipts/Primary User',
                                                [make_quotient_series(data.a_receipts.cum_receipts, data.csize_primary, 'little_money', name=data.query.name) for data in accum.accum],
                                                extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    if example.a_retention:
        if 0:
            for i in UserRetention.INTERVALS:
                interval, start, end = i
                retmsg['graphs'].append(SpinWebUI.Chart('%d-%s Retention (by %s %d)' % (interval, interval_ui_name, interval_ui_name, end),
                                                        [make_data_series(data.a_retention.trailing[i], 'percent',
                                                                          N_samples = data.a_retention.total[i], name=data.query.name) for data in accum.accum], bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())


    for mark in UserRetention.VISITS:
        pass
#         retmsg['graphs'].append(SpinWebUI.Chart('Average # of Visits Within First %d %s%s of Account Creation' % (mark, interval_ui_name, 's' if mark != 1 else ''),
#                                                [make_quotient_series(query.retention.visits_num[mark],
#                                                                      query.retention.visits_den[mark],
#                                                                      'number',
#                                                                      name=data.query.name) for data in accum.accum], bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
#         retmsg['graphs'].append(SpinWebUI.Chart('Average # of Visits Within First %d %s%s of Account Creation' % (mark, interval_ui_name, 's' if mark != 1 else ''),
#                                                [make_quotient_series(data.a_retention.visits_num[mark],
#                                                                      data.a_retention.visits_den[mark],
#                                                                      'number',
#                                                                      name=data.query.name) for data in accum.accum], bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())



    retmsg['graphs'].append(SpinWebUI.Chart('Average Purchase Size',
                                            [make_data_series(data.a_receipts.avg_size, 'little_money',
                                                              N_samples = data.a_receipts.period_purchases,
                                                              name = data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    retmsg['graphs'].append(SpinWebUI.Chart('ARP%sAU All Users' % interval_letter,
                                            [make_quotient_series(data.a_receipts.period_receipts['money']["ALL"],
                                                                  data.a_uniques.au, 'little_money', name=data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    retmsg['graphs'].append(SpinWebUI.Chart('ARP%sAU All Users (%d-%s Trailing Average)' % (interval_letter, interval_window, interval_ui_name),
                                            [make_averaged_series(data.a_receipts.period_receipts['money']["ALL"],
                                                                  'little_money',
                                                                  denom_samples = data.a_uniques.au,
                                                                  window = interval_window,
                                                                  name=data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    retmsg['graphs'].append(SpinWebUI.Chart('ARP%sAU CCL%d+ Users (%d-%s Trailing Average)' % (interval_letter, UserActivity.MIN_CC, interval_window, interval_ui_name),
                                            [make_averaged_series(data.a_receipts.period_receipts['money']["ALL_MIN_CC"],
                                                                  'little_money',
                                                                  denom_samples = dict(((t, sum((data.a_uniques.au_by_cc_level[level-1].get(t,0) for level in xrange(UserActivity.MIN_CC,max_cc_level()+1)),0)) for t in data.a_receipts.period_receipts['money']['ALL_MIN_CC'])),
                                                                  window = interval_window,
                                                                  name=data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    retmsg['graphs'].append(SpinWebUI.Chart('ARPP%sAU Paying Users' % interval_letter,
                                            [make_quotient_series(data.a_receipts.period_receipts['money']["ALL"],
                                                                  data.a_uniques.paying_users, 'little_money', name=data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    retmsg['graphs'].append(SpinWebUI.Chart('ARPP%sAU Paying Users (%d-%s Trailing Average)' % (interval_letter, interval_window, interval_ui_name),
                                            [make_averaged_series(data.a_receipts.period_receipts['money']["ALL"],
                                                                  'little_money',
                                                                  window = interval_window,
                                                                  denom_samples = data.a_uniques.paying_users,
                                                                  name=data.query.name) for data in accum.accum],
                                            extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    if example.a_retention:
        for i in UserReceipts.INTERVALS:
            retmsg['graphs'].append(SpinWebUI.Chart('%d-%s Receipts/User (INCLUDES ALL ACCOUNTS < %d %s%s OLD,\nWILL DROP WITH INFLUX OF NEW USERS)' % (i, interval_ui_name,
                                                                                                              i, interval_ui_name, 's' if i != 1 else ''),
                                                    [make_quotient_series(data.a_receipts.by_age_num[i],
                                                                          data.a_retention.alive[i],
                                                                          'little_money',
                                                                          name=data.query.name) for data in accum.accum],
                                                    bounds = bounds, N_min = N_min, utc_offset=utc_offset).get_json())

    if example.a_attacks:
        retmsg['graphs'].append(SpinWebUI.Chart('PvE Attacks Made/%sAU (%d-%s Trailing Average)' % (interval_letter, interval_window, interval_ui_name),
                                                [make_averaged_series(dict([(t, data.a_attacks.period_attacks['attacks_launched'][t] - data.a_attacks.period_attacks['attacks_launched_vs_human'][t]) for t in data.a_attacks.period_attacks['attacks_launched'].iterkeys()]),
                                                                      'number', denom_samples = data.a_uniques.au, window = interval_window,
                                                                      name=data.query.name) for data in accum.accum],
                                                bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
        retmsg['graphs'].append(SpinWebUI.Chart('PvP Attacks Made/%sAU (at opponent\'s base/quarry/squad) (%d-%s Trailing Average)' % (interval_letter, interval_window, interval_ui_name),
                                                [make_averaged_series(data.a_attacks.period_attacks['attacks_launched_vs_human'],
                                                                      'number', denom_samples = data.a_uniques.au, window = interval_window,
                                                                      name=data.query.name) for data in accum.accum],
                                                bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
        retmsg['graphs'].append(SpinWebUI.Chart('Revenge PvP Attacks Made/%sAU (at opponent\'s base/quarry/squad) (%d-%s Trailing Average)' % (interval_letter, interval_window, interval_ui_name),
                                                [make_averaged_series(data.a_attacks.period_attacks['revenge_attacks_launched_vs_human'],
                                                                      'number', denom_samples = data.a_uniques.au, window = interval_window,
                                                                      name=data.query.name) for data in accum.accum],
                                                bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
        retmsg['graphs'].append(SpinWebUI.Chart('PvP Attacks Suffered/%sAU (at own base) (%d-%s Trailing Average)' % (interval_letter, interval_window, interval_ui_name),
                                                [make_averaged_series(data.a_attacks.period_attacks['attacks_suffered'],
                                                                      'number', denom_samples = data.a_uniques.au, window = interval_window,
                                                                      name=data.query.name) for data in accum.accum],
                                                bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    if example.a_activity and len(accum.accum) == 1 and len(example.a_activity.seen_states)>0:
#        retmsg['graphs'].append(SpinWebUI.Chart('APPROX Min. Spent on Activity by CCL%d+ Users per %sAU' % (UserActivity.MIN_CC, interval_letter),
#                                                [make_quotient_series(dict(((t, data.a_activity.activity_by_time[t].get(state,0)/60.0) for t in data.a_activity.activity_by_time)),
#                                                                      #data.a_uniques.au,
#                                                                      dict(((t, sum((data.a_uniques.au_by_cc_level[level-1].get(t,0) for level in xrange(UserActivity.MIN_CC, max_cc_level()+1)),0)) for t in data.a_activity.activity_by_time)),
#                                                                      'number',
#                                                                      name = '%s' % (state)
#                                                                      ) for state in data.a_activity.get_states() for data in accum.accum],
#                                                extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
        retmsg['graphs'].append(SpinWebUI.Chart('APPROX Min. Spent on Activity by CCL%d+ Users per %sAU (%d-%s Trailing Average)' % (UserActivity.MIN_CC, interval_letter, interval_window, interval_ui_name),
                                                [make_averaged_series(dict(((t, data.a_activity.activity_by_time[t].get(state,0)/60.0) for t in data.a_activity.activity_by_time)),
                                                                      'number',
                                                                      #denom_samples = data.a_uniques.au,
                                                                      denom_samples = dict(((t, sum((data.a_uniques.au_by_cc_level[level-1].get(t,0) for level in xrange(UserActivity.MIN_CC,max_cc_level()+1)),0)) for t in data.a_activity.activity_by_time)),
                                                                      window = interval_window,
                                                                      name = '%s' % (state)
                                                                      ) for state in data.a_activity.get_states() for data in accum.accum],
                                                extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
        retmsg['graphs'].append(SpinWebUI.Chart('Gamebucks Spent During Activity by CCL%d+ VIPs per %sAU (%d-%s Trailing Average)' % (UserActivity.MIN_CC, interval_letter, interval_window, interval_ui_name),
                                                    [make_averaged_series(dict(((t, data.a_activity.activity_gamebucks_by_time[t].get(state,0)) for t in data.a_activity.activity_gamebucks_by_time)),
                                                                          'number',
                                                                          #denom_samples = data.a_uniques.au,
                                                                          denom_samples = dict(((t, sum((data.a_uniques.au_by_cc_level[level-1].get(t,0) for level in xrange(UserActivity.MIN_CC,max_cc_level()+1)),0)) for t in data.a_activity.activity_gamebucks_by_time)),
                                                                          window = interval_window,
                                                                          name = '%s' % (state.replace(' ','_').replace('.','_'))
                                                                          ) for state in data.a_activity.get_states() for data in accum.accum],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
        # intensity: gamebucks per day per DAU
        retmsg['graphs'].append(SpinWebUI.Chart('Rate of Gamebucks Spend During Activity by CCL%d+ VIPs per %sAU (%d-%s Trailing Average)' % (UserActivity.MIN_CC, interval_letter, interval_window, interval_ui_name),
                                                    [make_averaged_series(dict(((t, data.a_activity.activity_gamebucks_by_time[t].get(state,0)/(data.a_activity.activity_by_time[t].get(state,0)/86400.0)) for t in data.a_activity.activity_by_time if data.a_activity.activity_by_time[t].get(state,0)>0)),
                                                                          'number',
                                                                          denom_samples = dict(((t, sum((data.a_uniques.au_by_cc_level[level-1].get(t,0) for level in xrange(UserActivity.MIN_CC,max_cc_level()+1)),0)) for t in data.a_activity.activity_by_time if data.a_activity.activity_by_time[t].get(state,0)>0)),
                                                                          window = interval_window,
                                                                          name = '%s' % (state.replace(' ','_').replace('.','_'))
                                                                          ) for state in data.a_activity.get_states() for data in accum.accum],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

        if len(example.a_activity.seen_ais)>0:
            retmsg['graphs'].append(SpinWebUI.Chart('AI Fight Time by CCL%d+ Users per %sAU' % (UserActivity.MIN_CC, interval_letter),
                                                    [make_quotient_series(dict(((t, data.a_activity.ais_by_time[t].get(state,0)/60.0) for t in data.a_activity.ais_by_time)),
                                                                          #data.a_uniques.au,
                                                                          dict(((t, sum((data.a_uniques.au_by_cc_level[level-1].get(t,0) for level in xrange(UserActivity.MIN_CC,max_cc_level()+1)),0)) for t in data.a_activity.activity_by_time)),
                                                                          'number',
                                                                          name = '%s' % (state.replace(' ','_').replace('.','_'))
                                                                          ) for state in data.a_activity.get_ais() for data in accum.accum],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
            retmsg['graphs'].append(SpinWebUI.Chart('AI Fight Time by CCL%d+ Users per %sAU (%d-%s Trailing Average)' % (UserActivity.MIN_CC, interval_letter, interval_window, interval_ui_name),
                                                    [make_averaged_series(dict(((t, data.a_activity.ais_by_time[t].get(state,0)/60.0) for t in data.a_activity.ais_by_time)),
                                                                          'number',
                                                                          #denom_samples = data.a_uniques.au,
                                                                          denom_samples = dict(((t, sum((data.a_uniques.au_by_cc_level[level-1].get(t,0) for level in xrange(UserActivity.MIN_CC,max_cc_level()+1)),0)) for t in data.a_activity.activity_by_time)),
                                                                          window = interval_window,
                                                                          name = '%s' % (state.replace(' ','_').replace('.','_'))
                                                                          ) for state in data.a_activity.get_ais() for data in accum.accum],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
            retmsg['graphs'].append(SpinWebUI.Chart('AI Gamebucks Spent by CCL%d+ VIPs per %sAU (%d-%s Trailing Average)' % (UserActivity.MIN_CC, interval_letter, interval_window, interval_ui_name),
                                                    [make_averaged_series(dict(((t, data.a_activity.ai_gamebucks_by_time[t].get(state,0)) for t in data.a_activity.ai_gamebucks_by_time)),
                                                                          'number',
                                                                          #denom_samples = data.a_uniques.au,
                                                                          denom_samples = dict(((t, sum((data.a_uniques.au_by_cc_level[level-1].get(t,0) for level in xrange(UserActivity.MIN_CC,max_cc_level()+1)),0)) for t in data.a_activity.activity_by_time)),
                                                                          window = interval_window,
                                                                          name = '%s' % (state.replace(' ','_').replace('.','_'))
                                                                          ) for state in data.a_activity.get_ais() for data in accum.accum],
                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())
#            retmsg['graphs'].append(SpinWebUI.Chart('AI Enemy Receipts per %sAU (%d-%s Trailing Average)' % (interval_letter, interval_window, interval_ui_name),
#                                                    [make_averaged_series(dict(((t, data.a_activity.ai_money_by_time[t].get(state,0)) for t in data.a_activity.ai_money_by_time)),
#                                                                          'little_money',
#                                                                          #denom_samples = data.a_uniques.au, window = interval_window,
#                                                                          denom_samples = dict(((t, sum((data.a_uniques.au_by_cc_level[level-1].get(t,0) for level in xrange(3,max_cc_level()+1)),0)) for t in data.a_activity.activity_by_time)),
#                                                                          name = '%s' % (state.replace(' ','_').replace('.','_'))
#                                                                          ) for state in data.a_activity.get_ais() for data in accum.accum],
#                                                    extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    if example.a_uniques and len(accum.accum) == 1:
        retmsg['graphs'].append(SpinWebUI.Chart('%sAU by Central Computer Level on that %s' % (interval_letter, interval_ui_name),
                                                [make_data_series(data.a_uniques.au_by_cc_level[level-1], 'number',
                                                                  name = 'CC%d - %s' % (level, data.query.name)
                                                                  ) for level in xrange(1,max_cc_level()+1) for data in accum.accum],
                                                extrap='time' if do_extrapolate else 'none', bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    if example.a_progress_curve:
        retmsg['graphs'].append(SpinWebUI.Chart('Average player level by account age (%ss) (retained players only)' % interval_ui_name,
                                                [make_quotient_series(dict([(i,data.a_progress_curve.by_day_num['player_level'][i]) for i in xrange(UserProgressCurve.DAYS)]),
                                                                      dict([(i,data.a_progress_curve.by_day_den['player_level'][i]) for i in xrange(UserProgressCurve.DAYS)]),
                                                                      'number',
                                                                      x_format = 'number',
                                                                      name = data.query.name) for data in accum.accum],
                                                N_min=N_min, panel='progress', utc_offset=utc_offset).get_json())
        retmsg['graphs'].append(SpinWebUI.Chart('Average CC level by account age (%ss) (retained players only)' % interval_ui_name,
                                                [make_quotient_series(dict([(i,data.a_progress_curve.by_day_num[gamedata['townhall']+'_level'][i]) for i in xrange(UserProgressCurve.DAYS)]),
                                                                     dict([(i,data.a_progress_curve.by_day_den[gamedata['townhall']+'_level'][i]) for i in xrange(UserProgressCurve.DAYS)]),
                                                                  'number',
                                                                  x_format = 'number',
                                                                  name = data.query.name) for data in accum.accum],
                                                N_min=N_min, panel='progress', utc_offset=utc_offset).get_json())
        for kind in gamedata['strings']['manufacture_categories']:
            retmsg['graphs'].append(SpinWebUI.Chart('Average # '+kind+' unlocked by account age (%ss) (retained players only)' % interval_ui_name,
                                                    [make_quotient_series(dict([(i,data.a_progress_curve.by_day_num[kind+'_unlocked'][i]) for i in xrange(UserProgressCurve.DAYS)]),
                                                                          dict([(i,data.a_progress_curve.by_day_den[kind+'_unlocked'][i]) for i in xrange(UserProgressCurve.DAYS)]),
                                                                          'number',
                                                                          x_format = 'number',
                                                                          name = data.query.name) for data in accum.accum],
                                                    N_min=N_min, panel='progress', utc_offset=utc_offset).get_json())


        retmsg['graphs'].append(SpinWebUI.Chart('Average CC level by player level',
                                                [make_quotient_series(dict([(i,data.a_progress_curve.by_plevel_num[gamedata['townhall']+'_level'][i]) for i in xrange(UserProgressCurve.PLAYER_LEVELS)]),
                                                                     dict([(i,data.a_progress_curve.by_plevel_den[gamedata['townhall']+'_level'][i]) for i in xrange(UserProgressCurve.PLAYER_LEVELS)]),
                                                                  'number',
                                                                  x_format = 'number',
                                                                  name = data.query.name) for data in accum.accum],
                                                N_min=N_min, panel='progress', utc_offset=utc_offset).get_json())

        for kind in gamedata['strings']['manufacture_categories']:
            retmsg['graphs'].append(SpinWebUI.Chart('Average # '+kind+' unlocked by player level',
                                                    [make_quotient_series(dict([(i,data.a_progress_curve.by_plevel_num[kind+'_unlocked'][i]) for i in xrange(UserProgressCurve.PLAYER_LEVELS)]),
                                                                          dict([(i,data.a_progress_curve.by_plevel_den[kind+'_unlocked'][i]) for i in xrange(UserProgressCurve.PLAYER_LEVELS)]),
                                                                          'number',
                                                                          x_format = 'number',
                                                                          name = data.query.name) for data in accum.accum],
                                                    N_min=N_min, panel='progress', utc_offset=utc_offset).get_json())

        retmsg['graphs'].append(SpinWebUI.Chart('% of players with CC level',
                                                [make_quotient_series(dict([(i,data.a_progress_curve.by_level_num[gamedata['townhall']+'_level'][i]) for i in xrange(2,UserProgressCurve.LEVELS)]),
                                                                     dict([(i,data.a_progress_curve.by_level_den[gamedata['townhall']+'_level'][i]) for i in xrange(2,UserProgressCurve.LEVELS)]),
                                                                  'percent',
                                                                  x_format = 'number',
                                                                  name = data.query.name) for data in accum.accum],
                                                N_min=N_min, panel='progress', utc_offset=utc_offset).get_json())

        for kind in gamedata['strings']['manufacture_categories']:
            retmsg['graphs'].append(SpinWebUI.Chart('% of players who have unlocked N ' + kind,
                                                    [make_quotient_series(dict([(i,data.a_progress_curve.by_level_num[kind+'_unlocked'][i]) for i in xrange(1,UserProgressCurve.LEVELS)]),
                                                                          dict([(i,data.a_progress_curve.by_level_den[kind+'_unlocked'][i]) for i in xrange(1,UserProgressCurve.LEVELS)]),
                                                                          'percent',
                                                                  x_format = 'number',
                                                                          name = data.query.name) for data in accum.accum],
                                                    N_min=N_min, panel='progress', utc_offset=utc_offset).get_json())

    if example.a_counter:
        retmsg['graphs'].append(SpinWebUI.Chart('K-Factor ' + ('(secondary/primary)' if strict_kfactor_calc else '(nonpaid/paid)'),
                                                [make_data_series(data.kfactor, 'percent',
                                                                  N_samples = data.csize, name=data.query.name) for data in accum.accum], bounds=bounds, N_min=N_min, utc_offset=utc_offset).get_json())

    if example.a_spend_curve:
        retmsg['graphs'].append(SpinWebUI.Chart('Average Period Receipts/User by Account Age (%ss)' % interval_ui_name,
                                                [make_quotient_series(dict([(i, data.a_spend_curve.num['money']['ALL'][i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                      dict([(i, data.a_spend_curve.den[i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                      'little_money',
                                                                      x_format = 'number',
                                                                      name = data.query.name) for data in accum.accum], N_min=N_min, utc_offset=utc_offset).get_json())

        if 0:
            for currency in SPEND_CURRENCIES:
                for data in accum.accum:
                    retmsg['graphs'].append(SpinWebUI.Chart('Average Period %s Receipts/User by Account Age By Category: %s (%ss)' % (CURRENCY_UI_NAMES()[currency], data.query.name, interval_ui_name),
                                                            [make_quotient_series(dict([(i, data.a_spend_curve.num[currency][cat][i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                                  dict([(i, data.a_spend_curve.den[i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                                  'little_money' if currency == 'money' else 'number',
                                                                                  x_format = 'number',
                                                                                  name = cat) for cat in SPEND_CATEGORIES if (not cat.startswith('ALL'))], N_min=N_min, panel='breakdown', utc_offset=utc_offset).get_json())
        retmsg['graphs'].append(SpinWebUI.Chart('Cumulative Receipts/User by Account Age (%ss) TAIL INACCURATE - LOW N' % interval_ui_name,
                                                [make_data_series(dict([(i, data.a_spend_curve.avg_cum_receipts['money']['ALL'][i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                  'little_money',
                                                                  x_format = 'number',
                                                                  N_samples = dict([(i, data.a_spend_curve.den[i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                  name = data.query.name) for data in accum.accum], N_min=N_min, utc_offset=utc_offset).get_json())

        retmsg['graphs'].append(SpinWebUI.Chart('Cumulative Receipts/User by Time In Game (Hours) TAIL INACCURATE - LOW N',
                                                [make_data_series(dict([(i, data.a_time_curve.avg_cum_receipts['money']['ALL'][i]) for i in xrange(data.a_time_curve.BUCKETS)]),
                                                                  'little_money',
                                                                  x_format = 'number',
                                                                  N_samples = dict([(i, data.a_time_curve.den[i]) for i in xrange(data.a_time_curve.BUCKETS)]),
                                                                  name = data.query.name) for data in accum.accum], N_min=N_min, utc_offset=utc_offset).get_json())

        if 1:
            for currency in SPEND_CURRENCIES:
                for data in accum.accum:
                    retmsg['graphs'].append(SpinWebUI.Chart('Cumulative %s Receipts/User by Account Age By Category: %s (%ss)' % (CURRENCY_UI_NAMES()[currency], data.query.name, interval_ui_name),
                                                [make_data_series(dict([(i, data.a_spend_curve.avg_cum_receipts[currency][cat][i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                  'little_money' if currency == 'money' else 'number',
                                                                  x_format = 'number',
                                                                  N_samples = dict([(i, data.a_spend_curve.den[i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                  name = cat) for cat in SPEND_CATEGORIES if (not cat.startswith('ALL'))], N_min=N_min, panel='breakdown', utc_offset=utc_offset).get_json())

        retmsg['graphs'].append(SpinWebUI.Chart('Cumulative Receipts/Primary User by Account Age (%ss) TAIL INACCURATE - LOW N' % interval_ui_name,
                                         [make_data_series(dict([(i, data.a_spend_curve.avg_cum_receipts_primary[i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                           'little_money',
                                                           x_format = 'number',
                                                           N_samples = dict([(i, data.a_spend_curve.den_primary[i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                           name = data.query.name) for data in accum.accum], N_min=N_min, utc_offset=utc_offset).get_json())

        for hurdle_amount in UserSpendCurve.HURDLES:
            samt = str(hurdle_amount)
            retmsg['graphs'].append(SpinWebUI.Chart('Fraction Of Users Whose Receipts >= $%s by Account Age (%ss) TAIL INACCURATE - LOW N' % (samt, interval_ui_name),
                                                    [make_quotient_series(dict([(i, data.a_spend_curve.hurdle[samt][i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                          dict([(i, data.a_spend_curve.den[i]) for i in xrange(data.a_spend_curve.BUCKETS)]),
                                                                          'percent',
                                                                          x_format = 'number',
                                                                          name = data.query.name) for data in accum.accum], N_min=N_min, utc_offset=utc_offset).get_json())
            retmsg['graphs'].append(SpinWebUI.Chart('Fraction Of Users Whose Receipts >= $%s by Time In Game (Hours) TAIL INACCURATE - LOW N' % (samt),
                                                    [make_quotient_series(dict([(i, data.a_time_curve.hurdle[samt][i]) for i in xrange(data.a_time_curve.BUCKETS)]),
                                                                          dict([(i, data.a_time_curve.den[i]) for i in xrange(data.a_time_curve.BUCKETS)]),
                                                                          'percent',
                                                                          x_format = 'number',
                                                                          name = data.query.name) for data in accum.accum], N_min=N_min, utc_offset=utc_offset).get_json())



        if 0:
            # NOTE: don't draw last data point, because it underestimates retention, since it requires the user to have logged in within <24 hours
            # of the last sample time
            retmsg['graphs'].append(SpinWebUI.Chart('Retention by Account Age (%ss) TAIL INACCURATE - LOW N' % interval_ui_name,
                                                    [make_data_series(dict([(i,
                                                                             data.a_spend_curve.avg_retention[i]) for i in xrange(data.a_spend_curve.BUCKETS-1)]),
                                                                      'percent',
                                                                      x_format = 'number',
                                                                      N_samples = dict([(i,
                                                                                         data.a_spend_curve.den[i]) for i in xrange(data.a_spend_curve.BUCKETS-1)]),
                                                                      name = data.query.name) for data in accum.accum], N_min=N_min, utc_offset=utc_offset).get_json())

        retmsg['graphs'].append(SpinWebUI.Chart('Paying Retention by Account Age (%ss) TAIL INACCURATE - LOW N' % interval_ui_name,
                                          [make_data_series(dict([(i,
                                                                   data.a_spend_curve.avg_pretention[i]) for i in xrange(data.a_spend_curve.BUCKETS-1)]),
                                                                 'percent',
                                                          x_format = 'number',
                                                          N_samples = dict([(i,
                                                                             data.a_spend_curve.den[i]) for i in xrange(data.a_spend_curve.BUCKETS-1)]),
                                                          name = data.query.name) for data in accum.accum], N_min=N_min, utc_offset=utc_offset).get_json())


    timers['done'] = time.time()
    time_info = 'Total time: %.3fs (open %.3fs qinit %.3fs map %.3fs reduce %.3fs trav_ads %.3fs graphgen %.3fs)' % \
                (timers['done']-timers['start'],
                 timers['userdb']-timers['start'],
                 timers['init_query']-timers['userdb'],
                 timers['map_userdb']-timers['init_query'],
                 timers['reduce_userdb']-timers['map_userdb'],
                 timers['traverse_ads']-timers['reduce_userdb'],
                 timers['done']-timers['traverse_ads'])
    retmsg['time_info'] = time_info
    return retmsg

if __name__ == "__main__":
    # command line args that trigger special map/reduce slave modes
    if '--funnel-slave' in sys.argv:
        do_funnel_slave()
        sys.exit(0)
    elif '--graph-slave' in sys.argv:
        do_graph_slave()
        sys.exit(0)

    args = cgi.parse() or {}

    if SpinGoogleAuth.cgi_is_local():
        auth_info = {'ok':1,'spin_token':{'spin_user':'local','google_access_token':'local'},'raw_token':'local'}
    else:
        auth_info = SpinGoogleAuth.cgi_do_auth(args, 'ANALYTICS2', time_now)

    output_mode = args.get('output_mode', ['ui'])[0]
    if output_mode == 'ui':
        print 'Content-Type: text/html'
        print 'Pragma: no-cache'
        print 'Cache-Control: no-cache'
        print ''
        if auth_info['ok']:
            do_ui(args)
        elif 'redirect' in auth_info:
            print auth_info['redirect']
        else:
            print auth_info['error']
        sys.exit(0)
    else:
        if not auth_info['ok']:
             print 'Content-Type: text/javascript'
             print ''
             print SpinJSON.dumps({'success':True, 'error':'Authentication error: '+auth_info['error']}, newline=True)
             sys.exit(0)

    csv_format = "userdb"
    significance_test = "g_test"
    conversion_rates = True
    use_funnel_stages = 'ALL'
    allow_zip = True
    overlay_mode = None
    overlay_abtest = None
    sample_interval = "day"
    interval_window = -1
    do_extrapolate = False
    compute_progression = False
    compute_spend_curve = False
    compute_ads = False
    show_fbcredits = True
    show_gamebucks = True
    utc_offset = 0 # difference from UTC to GUI timezone, in seconds
    N_min = 1

    # parse args into userdb query
    query = {}
    manual_qlist = None

    # date-based bounds must be parsed manually since they are sent in MM/DD/YYYY form
    date_bounds = { 'account': {'min': '', 'max': ''},
                    'graph': {'min': '', 'max': ''} }

    bounds = { 'account': {'min':-1, 'max':-1}, # determined later by conversion from date_bounds
               'graph': {'min':-1, 'max':-1}, # determined later by conversion from date_bounds
               'player_level': {'min':-1, 'max':-1},
               'money_spent': {'min':-1, 'max':-1},
               }

    # parse manual query filter
    try:
        if 'manual' in args:
            manual_str = args['manual'][-1]
            del args['manual']
            manual_obj = SpinJSON.loads(manual_str)
            if isinstance(manual_obj, dict):
                for key, val in manual_obj.iteritems():
                    if isinstance(val, list):
                        query[key] = query.get(key,[])+val
                    else:
                        query[key] = val
            elif isinstance(manual_obj, list):
                manual_qlist = []
                for entry in manual_obj:
                    q = {}
                    for key, val in entry.iteritems():
                        if isinstance(val, list):
                            q[key] = q.get(key,[])+val
                        else:
                            q[key] = val
                    manual_qlist.append(q)
    except:
        pass

    for key, valist in args.iteritems():
        if key == "output_mode":
            output_mode = valist[-1]
        elif key == "csv_format":
            csv_format = valist[-1]
        elif key == "significance_test":
            significance_test = valist[-1]
        elif key == "conversion_rates":
            conversion_rates = bool(int(valist[-1]))
        elif key == "funnel_stages":
            assert valist[-1] in ('ALL', 'skynet')
            use_funnel_stages = valist[-1]
        elif key == "allow_zip":
            allow_zip = bool(int(valist[-1]))
        elif key == "sample_interval":
            sample_interval = valist[-1]
        elif key == "interval_window":
            interval_window = int(valist[-1])
        elif key.startswith('account_creation') or key.startswith('graph_time'):
            which = key.split('_')[-1]
            date_bounds[key.split('_')[0]][which] = valist[0]
        elif key.startswith('player_level') or key.startswith('money_spent'):
            if valist[0]:
                member = string.join(key.split('_')[:-1], '_')
                which = key.split('_')[-1]
                bounds[member][which] = float(valist[0])
        elif valist == ['ALL']:
            pass # ignore
        elif key == "country_tier" and valist == ['1','2','3','4']:
            pass # equivalent to ALL
        elif key == "price_region" and valist == ['A','B','C','D']:
            pass # equivalent to ALL
        elif key == "country":
            query[key] = map(lambda x: x.lower(), valist[0].split(','))
        elif key in ("acquisition_campaign","acquisition_ad_skynet","acquisition_ad_skynet2"):
            query[key] = valist[0].split(',')

            if ('ad_skynet' in key):
                # unfortunately we have confusion here due to Skynet targetings that have internal commas, like
                # "atr_ql243b_Alap10-20140510us,ca,gb,au,nz,dk,nl,no,se_something_something"
                # handle these as a special case so we do not split on the internal commas!
                new_query = []
                for i in xrange(len(query[key])):
                    e = query[key][i]
                    if len(new_query) > 0 and new_query[-1].split('_')[-1][0] == 'A' and len(query[key][i].split('_')[0]) == 2:
                        # append to last field instead of starting a new one
                        new_query[-1] += ','+e
                    else:
                        new_query.append(e)
                #open('/tmp/zzz3','a').write('%s OLD %s NEW %s\n' % (key, repr(query[key]), repr(new_query)))
                query[key] = new_query

        elif key == "age_group" and set(valist) == set(['MISSING']+SpinConfig.AGE_GROUPS.keys()):
            pass # equivalent to ALL
        elif key == "home_region" and set(valist) == set(['MISSING']+gamedata['regions'].keys()):
            pass # equivalent to ALL
        elif key == "N_min":
            N_min = max(int(valist[0]), 0)
        elif key == "join_week":
            # convert to int
            query[key] = map(int, valist)
        elif key == "user_id":
            query[key] = int(valist[0])
        elif key == "overlay_mode":
            overlay_mode = valist[0]
        elif key == "overlay_abtest":
            overlay_abtest = valist[0]
        elif key == "do_extrapolate":
            do_extrapolate = (valist[0] == 'on')
        elif key == "compute_progression":
            compute_progression = (valist[0] == 'on')
        elif key == "compute_spend_curve":
            compute_spend_curve = (valist[0] == 'on')
        elif key == "compute_ads":
            compute_ads = (valist[0] == 'on')
        elif key == "show_fbcredits":
            show_fbcredits = (valist[0] == 'on')
        elif key == "show_gamebucks":
            show_gamebucks = (valist[0] == 'on')
        elif key == "utc_offset":
            utc_offset = int(valist[0])
        elif key == "alter_now":
            m,d,y = map(int, valist[0].split('/'))
            time_now = SpinConfig.cal_to_unix((y,m,d)) - utc_offset
        elif key.startswith("client_"):
            # ignore client-side-only parameters
            continue
        elif key == "debug_local" and (valist[0] == 'on'):
            # run single-threaded on local host, for debugging
#            USE_S3_UPCACHE = 0
            Slave.remote = False
            Slave.PROCS_PER_HOST = 0
        elif key == "game_id":
            assert game_id == valist[0]
        elif valist[0] == "ANY":
            continue
        else:
            query[key] = valist

    if (not show_fbcredits) or (not show_gamebucks):
        query['abtest_value:currency'] = []
        if show_fbcredits: query['abtest_value:currency'] += ['fbcredits', 'MISSING']
        if show_gamebucks: query['abtest_value:currency'] += ['gamebucks']

    # parse date_bounds MM/DD/YYYY bounds into UNIX timestamp
    for KEY in ('account','graph'):
        for WHICH in ('min','max'):
            if date_bounds[KEY][WHICH]:
                if '/' in date_bounds[KEY][WHICH]:
                    m,d,y = map(int, date_bounds[KEY][WHICH].split('/'))
                    unix = SpinConfig.cal_to_unix((y,m,d)) - utc_offset
                else:
                    unix = int(date_bounds[KEY][WHICH])
                bounds[KEY][WHICH] = unix

    # add account creation time bounds to query
    if bounds['account']['min'] > 0 or bounds['account']['max'] > 0:
        query['account_creation_time'] = [bounds['account']['min'], bounds['account']['max']]

        # clamp graph bounds to account creation time
        bounds['graph']['min'] = max(bounds['graph']['min'], bounds['account']['min'])

    # add non-time-based numeric bounds to query
    def add_bounds_to_query(query, key):
        if bounds[key]['min'] > 0 or bounds[key]['max'] > 0:
            query[key] = [bounds[key]['min'], bounds[key]['max']]
    add_bounds_to_query(query, 'player_level')
    add_bounds_to_query(query, 'money_spent')

    sys.stderr.write('args %s\nquery %s\n' % (repr(args), repr(query)))
    open('/tmp/zzz','w').write('QS %s\nargs %s\nquery %s\n' % (os.environ['QUERY_STRING'], repr(args), repr(query)))

    # for generating query list on the fly (e.g. from ad campaigns
    # seen), use fork_base for the other parameters, and fork it on the fork_on key
    fork_on = None
    fork_base = None

    # list of queries to overlay
    qlist = []

    if manual_qlist:
        for i in xrange(len(manual_qlist)):
            q2 = query.copy()
            for key, val in manual_qlist[i].iteritems():
                q2[key] = val
            qlist.append(Query(q2, str(i)))
    elif overlay_abtest and overlay_abtest != 'none':
        # note: overlay_abtest takes precedence over overlay_mode
        group_names = sorted(gamedata['abtests'][overlay_abtest]['groups'].keys())
        for group_name in group_names:
            data = gamedata['abtests'][overlay_abtest]['groups'][group_name]
            query[overlay_abtest] = group_name
            qlist.append(Query(query, group_name))
    elif overlay_mode == 'active_abtests':
        for test_name, data in gamedata['abtests'].iteritems():
            if not data['active']: continue
            for group_name, group_data in data['groups'].iteritems():
                query[test_name] = group_name
                cohort_name = '%s:%s' % (test_name, group_name)
                qlist.append(Query(query, cohort_name))
    elif overlay_mode == 'country_tier':
        for tier in ('1','2','3','4'):
            query['country_tier'] = tier
            qlist.append(Query(query, 'Tier '+tier))
    elif overlay_mode == 'price_region':
        for tier in set(SpinConfig.price_region_map.itervalues()):
            query['price_region'] = tier
            qlist.append(Query(query, 'Region '+tier))
    elif overlay_mode == 'acquisition_paid_or_free':
        query['acquisition_campaign'] = ['!MISSING','!facebook_free','!game_viral']
        qlist.append(Query(query, 'Paid'))
        query['acquisition_campaign'] = ['facebook_free']
        qlist.append(Query(query, 'Free (Facebook)'))
        query['acquisition_campaign'] = ['game_viral']
        qlist.append(Query(query, 'Free (Game Viral)'))

    elif overlay_mode in ('acquisition_campaign', 'acquisition_ad_image', 'acquisition_ad_title', 'acquisition_ad_text', 'acquisition_ad_target', 'acquisition_ad_skynet'):
        if overlay_mode in query and type(query[overlay_mode]) is list:
            for value in query[overlay_mode]:
                query2 = query.copy()
                query2[overlay_mode] = [value]
                qlist.append(Query(query2, value))
        else:
            fork_on = overlay_mode
            fork_base = Query(query, 'base')
    elif overlay_mode == 'country':
        if 'country' in query:
            country_list = query['country']
            for c in country_list:
                query['country'] = c
                qlist.append(Query(query, c))

#            fork_on = 'country'
#            fork_base = Query(query, 'base')
        else:
            # do not allow big exploding queries
            pass

    elif overlay_mode == 'join_week':
        # figure out the bounds
        starting_week = 8 if SpinConfig.game() == 'mf' else 0 # exclude first 8 weeks of MF data
        weeks_since_launch = int((time.time() - SpinConfig.game_launch_date(game_id))/(60*60*24*7))
        ending_week = weeks_since_launch
        if ('account_creation_time' in query):
            if query['account_creation_time'][0] > 0:
                # start at a later week if possible
                starting_week = max(starting_week, int((query['account_creation_time'][0]-SpinConfig.game_launch_date())/(60*60*24*7)))
            if query['account_creation_time'][1] > 0:
                ending_week = min(ending_week, int((query['account_creation_time'][1]-SpinConfig.game_launch_date())/(60*60*24*7)))

        weeklist = range(starting_week, ending_week+1)
        for week in weeklist:
            query['join_week'] = week
            y, m, d = SpinConfig.unix_to_cal(SpinConfig.game_launch_date()+week*(60*60*24*7))
            qlist.append(Query(query, 'Week %d (%d/%d/%d)' % (week, m, d, y)))

    elif overlay_mode == 'join_day':
        if ('account_creation_time' not in query) or query['account_creation_time'][0] <= 0 or query['account_creation_time'][1] <= 0:
            pass # require these so that we don't send a ridiculously big query
        else:
            start_time = query['account_creation_time'][0]
            end_time = query['account_creation_time'][1]
            for t in xrange(start_time, end_time, 24*60*60):
                y, m, d = SpinConfig.unix_to_cal(t)
                query['account_creation_time'] = [t, t+24*60*60]
                qlist.append(Query(query, '%d/%d/%d' % (m,d,y)))

    elif overlay_mode == 'join_month':
        starting_time = SpinConfig.game_launch_date()
        ending_time = time_now
        if ('account_creation_time' in query):
            if query['account_creation_time'][0] > 0:
                # start at a later month if possible
                starting_time = max(starting_time, query['account_creation_time'][0])
            if query['account_creation_time'][1] > 0:
                # end at an earlier month if possible
                ending_time = min(ending_time, query['account_creation_time'][1])

        starting_year, starting_month, unused = SpinConfig.unix_to_cal(starting_time)
        ending_year, ending_month, unused = SpinConfig.unix_to_cal(ending_time)

        for year in xrange(starting_year, ending_year+1):
            if year == starting_year:
                first_month = starting_month
            else:
                first_month = 1
            if year == ending_year:
                last_month = ending_month
            else:
                last_month = 12
            for month in xrange(first_month, last_month+1):
                end_month = month+1
                end_year = year
                if end_month > 12:
                    end_month = 1
                    end_year = year+1
                query['account_creation_time'] = [SpinConfig.cal_to_unix((year,month,1)), SpinConfig.cal_to_unix((end_year,end_month,1))]
                qlist.append(Query(query, '%04d-%02d-%s ' % (year, month, SpinWebUI.MONTH_NAMES[month-1])))
    elif overlay_mode == 'years_old':
        BANDS = [[13,18,'13-17'],
                 [18,25,'18-24'],
                 [25,35,'25-34'],
                 [35,45,'35-44'],
                 [45,55,'45-54'],
                 [55,65,'55-64']]
        for band in BANDS:
            query['years_old'] = band[0:2]
            qlist.append(Query(query, band[2]))
    elif overlay_mode == 'age_group': # old age group derived from ad URL query
        for group in sorted(SpinConfig.AGE_GROUPS.keys(), key = lambda x: int(SpinConfig.AGE_GROUPS[x].split('-')[0])):
            query['age_group'] = group
            qlist.append(Query(query, 'Age '+SpinConfig.AGE_GROUPS[group]))
    elif overlay_mode == 'spend_level':
        BANDS = [[-1,0.01,'a 0'], #'$0'],
                 [0.01,10.0,'b 1-10'], #   '$0.01-$9.99'],
                 [10.0,100.0,'c 10-100'], # '$10.00-$99.99'],
                 [100.0,-1, 'd 100+']] # '$100.00+']]
        for band in BANDS:
            query['money_spent'] = band[0:2]
            qlist.append(Query(query, band[2]))
    elif overlay_mode == 'logged_in_times':
        BANDS = [[-1, 2, 'Visited 1'],
                 [2, 8, 'Visited 2-7'],
                 [8, 50, 'Visited 8-50'],
                 [50,200,'Visited 50-200'],
                 [200, -1, 'Visited 200+']]
        BANDS = [[-1, 2, 'Visited 1'],
                 [2, 8, 'Visited 2-7'],
                 [8, 50, 'Visited 8-50'],
                 [50,125,'Visited 50-125'],
                 [125,200,'Visited 125-200'],
                 [200,400,'Visited 200-400'],
                 [400, -1, 'Visited 400+']]

        for i in xrange(len(BANDS)):
            band = BANDS[i]
            query['logged_in_times'] = band[0:2]
            qlist.append(Query(query, band[2], sort_key = i))
    elif overlay_mode == 'currency':
        for ui_name, names in [['Alloys', ['gamebucks']], ['FBCredits', ['fbcredits','MISSING']]]:
            query['abtest_value:currency'] = names
            qlist.append(Query(query, ui_name))
    elif overlay_mode == 'frame_platform':
        for ui_name, names in [['Armor Games', ['ag']], ['Kongregate', ['kg']], ['Facebook', ['fb','MISSING']]]:
            query['frame_platform'] = names
            qlist.append(Query(query, ui_name))
    elif overlay_mode == 'browser_name':
        for name, ui_name in [['Chrome', 'Chrome'], ['Explorer', 'IE'], ['Firefox', 'Firefox'], ['Safari', 'Safari'], ['Opera', 'Opera']]:
            query['browser_name'] = name
            qlist.append(Query(query, ui_name))
    elif overlay_mode == 'home_region':
        for name, data in gamedata['regions'].iteritems():
            if data.get('developer_only',False): continue
            query['home_region'] = name
            title = name+' ('+data['ui_name']+')'
            if 'notes' in data:
                title += '- '+data['notes']
            qlist.append(Query(query, title))
    elif overlay_mode == gamedata['townhall']+'_level':
        BANDS = range(1,len(gamedata['buildings'][gamedata['townhall']]['build_time'])+1)
        for band in BANDS:
            query[gamedata['townhall']+'_level'] = band
            qlist.append(Query(query, 'CC Level %d' % band))
    elif overlay_mode == 'player_level':
        BANDS = [[1,5], [5,10], [10,15], [15,20], [20,25], [25,30], [30,35]]
        for band in BANDS:
            query['player_level'] = band
            qlist.append(Query(query, 'Levels %d-%d' % (band[0], band[1]-1)))
    elif overlay_mode and overlay_mode.endswith('_ago'):
        qlist.append(Query(query, 'Now'))
        if overlay_mode == 'week_ago':
            offset = 7*24*60*60
            name = 'Week'
        elif overlay_mode == 'month_ago':
            offset = 30*24*60*60
            name = 'Month'
        if 'account_creation_time' in query:
            # shift cohort by time offset
            if query['account_creation_time'][0] > 0:
                query['account_creation_time'][0] -= offset
            if query['account_creation_time'][1] > 0:
                query['account_creation_time'][1] -= offset
            else:
                # with end = current, shift back one week
                query['account_creation_time'][1] = time_now - offset
        else:
            query['account_creation_time'] = [-1, time_now - offset]
        qlist.append(Query(query, 'Previous ' + name, offset=offset))
    else:
        qlist.append(Query(query, 'Users'))

    if output_mode.startswith("graph"):
        print 'Content-Type: text/javascript'
        print 'Pragma: no-cache'
        print 'Cache-Control: no-cache'
        print ''
        sys.stdout.flush()
        try:
            retmsg = do_graph(qlist, [bounds['graph']['min'], bounds['graph']['max']], N_min, sample_interval,
                              utc_offset = utc_offset, interval_window = interval_window,
                              fork_on = fork_on, fork_base = fork_base, overlay_mode = overlay_mode, do_extrapolate = do_extrapolate,
                              compute_progression = compute_progression, compute_spend_curve = compute_spend_curve, compute_ads = compute_ads)
        except:
            # "success" being true is for the benefit of Ext.js -  it requires a "success" field - our SpinWebUI.py JS code looks for the 'error' field below
            retmsg = {'success': True, 'error': traceback.format_exc() }
        print SpinJSON.dumps(retmsg, newline = True)
    elif output_mode == "funnel":
        print 'Content-Type: text/javascript'
        print 'Pragma: no-cache'
        print 'Cache-Control: no-cache'
        print ''
        sys.stdout.flush()
        try:
            retmsg = do_funnel(qlist, significance_test, use_funnel_stages, conversion_rates)
        except:
            retmsg = {'success': True, 'error': traceback.format_exc() }
        print SpinJSON.dumps(retmsg, newline = True)
    elif output_mode == "units":
        do_units(qlist, N_min, sample_interval)
    elif output_mode == "csv":
        do_csv(qlist, csv_format, zip = allow_zip, sample_interval = sample_interval)
    else:
        raise Exception('unknown output_mode')

    sys.exit(0)
