#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# CGI script for customer support and server management

import os, sys, subprocess, traceback, time, re, copy
import cgi, cgitb
import urllib, urllib2
import SpinFacebook
import SpinNoSQL
import SpinNoSQLLog
import SpinConfig
import SpinJSON
import SpinGoogleAuth
import SpinLog
import FastGzipFile
import pymongo # 3.0+ OK

time_now = int(time.time())

# generic parameters for flot time graphs
time_axis_params = {'mode':'time', 'timeformat': '%b %d %H:00', 'minTickSize': [1, "hour"]}


def print_html_headers():
    print 'Content-Type: text/html'
    print 'Pragma: no-cache, no-store'
    print 'Cache-Control: no-cache, no-store'
    print ''

def print_json(data, attachment_name = None, gzip_encode = False):
    print 'Content-Type: text/javascript'
    if attachment_name:
        print 'Content-Disposition: attachment; filename=%s' % attachment_name
    if gzip_encode:
        print 'Content-Encoding: gzip'
    print 'Pragma: no-cache, no-store'
    print 'Cache-Control: no-cache, no-store'
    print ''
    sys.stdout.flush()
    if gzip_encode:
        fd = FastGzipFile.Writer(sys.stdout)
    else:
        fd = sys.stdout
    if attachment_name:
        if 'error' in data:
            fd.write('ERROR: '+data['error']+'\n')
        else:
            SpinJSON.dump(data['result'], fd, pretty = True)
    else:
        SpinJSON.dump(data, fd, pretty = False)
    fd.flush()
    sys.stdout.flush()

boost_item_expr = None

def item_is_giveable(gamedata, spec):
    global boost_item_expr
    if not boost_item_expr:
        boost_item_expr = re.compile('boost_(%s)_([0-9]+)' % '|'.join(gamedata['resources'].keys()))
    if spec['name'] in ('instant_repair', 'token', 'friendstone', 'flask'): return True
    if spec['name'].startswith('home_base_relocator'): return True
    if spec['name'].startswith('title_'): return True
    if spec['name'].endswith('_blueprint'): return True
    if 'time_warp' in spec['name']: return True
    match = boost_item_expr.search(spec['name'])
    if match:
        sqty = match.groups()[1]
        if sqty[0] == '1' and int(sqty) >= 10000: return True

    if 'use' in spec:
        if type(spec['use']) is dict:
            use = [spec['use']]
        else: use = spec['use']
        for entry in use:
            spellname = entry.get('spellname','')
            if spellname.startswith('BUY_PROTECTION') or spellname.startswith('TACTICAL_'):
                return True
    return False

def do_gui(spin_token_data, spin_token_raw, spin_token_cookie_name, my_endpoint, nosql_client):
    log_bookmark = nosql_client.log_bookmark_get(spin_token_data['spin_user'], 'ALL')
    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

    ssl_available = SpinConfig.config.get('ssl_crt_file','') and os.path.exists(SpinConfig.config['ssl_crt_file'])
    replacements = {
        '$GAME_NAME$': gamedata['strings']['game_name'].upper(),
        '$GAME_LOGO_URL$': (gamedata['virals']['common_image_path']+gamedata['virals']['default_image']).replace('http:','https:'),
        '$SPIN_TOKEN$': spin_token_raw,
        '$SPIN_TOKEN_DATA$': SpinJSON.dumps(spin_token_data),
        '$SPIN_TOKEN_COOKIE_NAME$': spin_token_cookie_name,
        '$SPIN_TOKEN_DOMAIN$': SpinConfig.config['spin_token_domain'],
        '$GOOGLE_ACCESS_TOKEN$': spin_token_data['google_access_token'],
        '$SPIN_USERNAME$': spin_token_data['spin_user'],
        '$SPIN_URL$': my_endpoint,
        '$SPIN_GAME_ID$': SpinConfig.game(),
        '$SPIN_LOG_BOOKMARK$': str(log_bookmark or -1),
        '$GAMEBUCKS_NAME$': gamedata['store']['gamebucks_ui_name'],
        '$GAMEBUCKS_ITEM$': 'alloy' if SpinConfig.game() == 'mf' else 'gamebucks',
        '$SPIN_GIVEABLE_ITEMS$': SpinJSON.dumps(sorted([{'name':name, 'ui_name':data['ui_name']} for name, data in gamedata['items'].iteritems() if item_is_giveable(gamedata, data)], key = lambda x: x['ui_name'])),
        '$SPIN_REGIONS$': SpinJSON.dumps(get_regions(gamedata)),
        '$SPIN_AI_BASE_IDS$': SpinJSON.dumps(sorted([int(strid) for strid in gamedata['ai_bases_client']['bases'].iterkeys()])),
        '$SPIN_SSL_AVAILABLE$': 'true' if ssl_available else 'false',
        '$SPIN_WSS_AVAILABLE$': 'true' if ssl_available else 'false',
        '$SPIN_PUBLIC_S3_BUCKET$': SpinConfig.config['public_s3_bucket'],
        }
    expr = re.compile('|'.join([key.replace('$','\$') for key in replacements]))
    template = open('cgipcheck.html').read()
    return expr.sub(lambda match: replacements[match.group(0)], template)

# return list of regions, adding missing "name" field if necessary
def get_regions(gamedata):
    ret = []
    for key, val in gamedata['regions'].iteritems():
        # skip obsolete regions - these tend to have auto_join off plus a "requires" predicate
        if not (val.get('auto_join',1) or ('requires' not in val) or val['requires']['predicate'] == 'AURA_INACTIVE'): continue
        val = copy.copy(val)
        val['name'] = key
        ret.append(val)
    ret.sort(key = lambda x: x['ui_name'])
    return ret

def check_role(spin_token_data, want_role):
    if (want_role not in spin_token_data['roles']):
        raise Exception('user %s does not have role %s' % (spin_token_data['spin_user'], want_role))

def run_shell_command(argv, ignore_stderr = False):
     p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
     out, err = p.communicate()
     if err and (not ignore_stderr):
         raise Exception(err)
     if p.returncode != 0:
         raise Exception(err or out)
     return out

def do_action(path, method, args, spin_token_data, nosql_client):
    try:
        do_log = False

        assert len(path) >= 1
        if path[0] == 'player':
            # player methods
            if (method not in ('lookup', 'get_raw_player')):
                do_log = True # log all write activity

            # require special role for writes, except for chat, aura, and alt actions
            if (method not in ('lookup','get_raw_player','chat_gag','chat_ungag','chat_block','chat_unblock','apply_aura','remove_aura','ignore_alt','unignore_alt')):
                check_role(spin_token_data, 'PCHECK-WRITE')
                if method in ('ban','unban'):
                    check_role(spin_token_data, 'PCHECK-BAN')

            control_args = args.copy()
            if 'spin_token' in control_args: # do not pass credentials along
                del control_args['spin_token']
            control_args['spin_user'] = spin_token_data['spin_user']

            if method == 'lookup':
                result = {'result':do_lookup(control_args)}
            elif method in ('give_item','send_message','chat_gag','chat_ungag','chat_block','chat_unblock','apply_aura','remove_aura','get_raw_player','ban','unban',
                            'make_developer','unmake_developer','clear_alias','chat_official','chat_unofficial','clear_lockout','clear_cooldown','change_region','ignore_alt','unignore_alt','demote_alliance_leader','kick_alliance_member'):
                result = do_CONTROLAPI(control_args)
            else:
                raise Exception('unknown player method '+method)

        elif path[0] == 'payment':
            check_role(spin_token_data, 'PCHECK-WRITE')
            fb_path = args['payment_id']
            fb_args = {}
            if method == 'lookup':
                fb_method = 'GET'
            elif method == 'refund':
                check_role(spin_token_data, 'ADMIN')
                do_log = True
                fb_method = 'POST'
                fb_path += '/refunds'
                fb_args['currency'] = args['currency']
                fb_args['amount'] = args['amount']
                fb_args['reason'] = 'CUSTOMER_SERVICE'
            elif method == 'resolve_dispute':
                check_role(spin_token_data, 'ADMIN')
                do_log = True
                fb_method = 'POST'
                fb_path += '/dispute'
                assert args['reason'] in ('GRANTED_REPLACEMENT_ITEM', 'DENIED_REFUND', 'BANNED_USER')
                fb_args['reason'] = args['reason']
            else:
                raise Exception('unknown payment method '+method)

            fb_args['access_token'] = SpinConfig.config['facebook_app_access_token']
            fb_args['fields'] = SpinFacebook.PAYMENT_FIELDS
            request = urllib2.Request(SpinFacebook.versioned_graph_endpoint('payment', fb_path)+'?'+urllib.urlencode(fb_args))
            request.get_method = lambda: fb_method
            result = {'result': urllib2.urlopen(request).read().strip()}

        elif path[0] == 'server':
            # server methods
            check_role(spin_token_data, 'ADMIN')

            if method == 'get_status':
                result = {'result': nosql_client.server_status_query()}
            elif method == 'get_latency':
                result = {'result':get_server_latency(nosql_client)}

            elif method == 'setup_ai_base':
                result = do_CONTROLAPI({'method':args['method'], 'idnum':args['idnum']})

            elif method in ('reconfig','change_state','maint_kick','panic_kick','shutdown'):
                server_name = args['server']
                row = nosql_client.server_status_query_one({'_id':server_name}, {'hostname':1, 'game_http_port':1, 'external_http_port':1, 'type':1})
                if not row:
                    raise Exception('server %s not found' % server_name)
                control_args = args.copy()
                for FIELD in ('server', 'spin_token'):
                    if FIELD in control_args: del control_args[FIELD]
                # tell proxyserver to handle it instead of forwarding
                if row['type'] == 'proxyserver':
                    control_args['server'] = 'proxyserver'
                result = do_CONTROLAPI(control_args, host = row['hostname'], port = row.get('game_http_port',None) or row.get('external_http_port',None))

            elif method == 'start':
                server_name = args['server']
                if nosql_client.server_status_query_one({'_id':server_name}):
                    raise Exception('server %s already exists' % server_name)
                conf = SpinJSON.loads(args['config'])
                p = subprocess.Popen(['./server.py', '--skip', '--config', SpinJSON.dumps(conf), server_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                out, err = p.communicate()
                if err:
                    raise Exception(err)
                if p.returncode != 0:
                    raise Exception(out)
                result = {'result': 'ok'}

            else:
                raise Exception('unknown server method '+method)

        elif path[0] == 'gamedata':
            check_role(spin_token_data, 'ADMIN')
            if method == 'make':
                out = run_shell_command(['./make-gamedata.sh', '-u'])
                gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
                result = {'result': {'gamedata_build':gamedata['gamedata_build_info']['date']}}
            elif method == 'download_art':
                result = {'result': run_shell_command(['./download-art.sh', '-q']).strip() or 'Artpack downloaded OK'}
            else:
                raise Exception('unknown gamedata method '+method)

        elif path[0] == 'gameclient':
            check_role(spin_token_data, 'ADMIN')
            if method == 'compile':
                result = {'result': run_shell_command(['./make-compiled-client.sh'], ignore_stderr = True).strip() or 'Client compiled OK'}
            else:
                raise Exception('unknown gameclient method '+method)

        elif path[0] == 'scm':
            check_role(spin_token_data, 'ADMIN')
            do_log = True

            if method == 'up':
                res_list = [run_shell_command(['../scmtool.sh', 'force-revert']) or 'Revert OK',
                            run_shell_command(['../scmtool.sh', 'up'], ignore_stderr = True) or 'Update OK',
                            run_shell_command(['../scmtool.sh', 'site-patch']) or 'Site-patch OK']
                result = {'result': '\n'.join(res_list) }
            else:
                raise Exception('unknown scm method '+method)

        elif path[0] == 'chat':
            # non-player-specific chat methods
            if method == 'get':
                qs = {'time': {'$gte':int(args['start_time'])},
                      'sender.user_id': int(args['user_id'])
                      }
                if 'end_time' in args:
                    qs['time']['$lt'] = int(args['end_time'])

                result = {'result': list(nosql_client.chat_buffer_table().find(qs, {'_id':0,'channel':1,'sender':1,'text':1,'time':1}).sort([('time',-1)]).limit(1000))}
            else:
                raise Exception('unknown '+path[0]+' method '+method)

        elif path[0] == 'logs':
            # log retrieval methods
            check_role(spin_token_data, 'ADMIN')

            log_name = args['log_name']
            assert log_name in ('log_exceptions', 'log_client_exceptions', 'log_metrics', 'log_credits')

            # require SKYNET role for finanical info
            if log_name in ('log_credits'):
                check_role(spin_token_data, 'SKYNET')

            code = int(args['code']) if 'code' in args else None

            if 'bookmark' in args:
                nosql_client.log_bookmark_set(spin_token_data['spin_user'], 'ALL', int(args['bookmark']))

            if method == 'get_by_time':
                result = {'result': list(nosql_client.log_retrieve(log_name, code=code, time_range = [int(args['start_time']),int(args.get('end_time','-1'))], inclusive = True))}
            elif method == 'get_more':
                if 'end_time' in args:
                    time_range = [-1, int(args['end_time'])]
                else:
                    time_range = [-1,-1]
                result = {'result': list(nosql_client.log_retrieve(log_name, code=code, id_range = [args['start_id'], None], time_range = time_range, inclusive = False))}
            elif method == 'get_credits':
                sample_list = []
                today_start = 86400*(time_now//86400)
                for start_time in (today_start - 86400, today_start):
                    end_time = start_time + 86400
                    total = 0.0
                    for code, sign in ((1000,1), (1310,-1)):
                        agg = [{'$match':{'code':code,'time':{'$gte':start_time,'$lt':end_time},'summary.developer':{'$exists':False}}},
                               {'$group':{'_id':1,'total':{'$sum':'$Billing Amount'}}}]
                        agg_result = nosql_client.log_buffer_table('log_credits').aggregate(agg)
                        for result in agg_result:
                            total += sign * result['total']
                    y,m,d = SpinConfig.unix_to_cal(start_time)
                    sample = {'start_time': start_time, 'end_time': end_time, 'date': '%d/%d' % (m,d), 'net': total}
                    if end_time > time_now:
                        sample['proj'] = total * (end_time - start_time) / (time_now - start_time)
                    sample_list.append(sample)
                result = {'result': sample_list}
            else:
                raise Exception('unknown log method '+method)

        elif path[0] == 'skynet':
            # skynet methods
            check_role(spin_token_data, 'SKYNET')

            import SkynetLib

            # special-case skynet_remote for local use
            dbconfig = SpinConfig.get_mongodb_config('skynet_remote' if 'skynet_remote' in SpinConfig.config['mongodb_servers'] else 'skynet_readonly')

            skynet_con = pymongo.MongoClient(*dbconfig['connect_args'], **dbconfig['connect_kwargs'])
            skynet_db = skynet_con[dbconfig['dbname']]

            if method == 'graph':
                ui_info = None
                adgroup_dtgt_qs = SkynetLib.adgroup_dtgt_filter_query(SkynetLib.stgt_to_dtgt(args['query']))
                adgroup_list = [{'_id':str(row['_id']), 'name':row.get('adgroup_name','BAD')} for row in \
                                skynet_db.fb_adstats_hourly.aggregate([
                    {'$match': adgroup_dtgt_qs},
                    {'$group':{'_id':'$adgroup_id', 'adgroup_name':{'$last':'$adgroup_name'}}}
                    ]) \
                                if (not SkynetLib.adgroup_name_is_bad(row.get('adgroup_name','BAD'))) and \
                                   (SkynetLib.decode_adgroup_name(SkynetLib.standin_spin_params, row['adgroup_name'])[1] is not None)]
                adgroup_dict = dict((x['_id'], x) for x in adgroup_list)

                # add some extra properties to each adgroup
                for entry in adgroup_list:
                    stgt, tgt = SkynetLib.decode_adgroup_name(SkynetLib.standin_spin_params, entry['name'])
                    entry['tgt'] = tgt
                    coeff, install_rate, unused_info = SkynetLib.bid_coeff(SkynetLib.standin_spin_params, tgt, 1.0, use_bid_shade = False,
                                                                           use_install_rate = tgt['bid_type'] in ('CPC', 'oCPM_CLICK', 'oCPM_INSTALL'))
                    entry['est_ltv'] = coeff # this is the 90-day est LTV associated with the bid_type event

                # figure out what bid types we're dealing with
                bid_types = list(set(SkynetLib.decode_adgroup_name(SkynetLib.standin_spin_params, x['name'])[1]['bid_type'] for x in adgroup_list))
                game_ids = list(set(SkynetLib.decode_adgroup_name(SkynetLib.standin_spin_params, x['name'])[1].get('game','tr') for x in adgroup_list))

                # query time series
                time_interval = max(int(args.get('time_interval','3600')), 3600)
                time_range = [time_now-10*86400,time_now] # XXXXXX
                time_range[0] = max(time_range[0], 1389337632) # started recording valid context data from this time onward

                start_time = (time_range[0]//time_interval)*time_interval
                end_time = (time_range[1]//time_interval)*time_interval

                adstat_qs = {'adgroup_id':{'$in':[x['_id'] for x in adgroup_list]},
                             'start_time':{'$gte':start_time},
                             'end_time':{'$lte':end_time},
                             'impressions':{'$gt':0}}

                if 0:
                    click_weighted_value_available = False
                    agg = [{'$match': adstat_qs},
                           {'$project':{'start_time':1,'spent':1,'clicks':1,'impressions':1,'bid':1}},
                           {'$group':{'_id':'$start_time' if time_interval == 3600 else { '$subtract' :['$start_time', {'$mod':['$start_time', time_interval]}] },
                                      'spent':{'$sum':'$spent'},
                                      'impressions':{'$sum':'$impressions'},
                                      'clicks':{'$sum':'$clicks'},
                                      'avg_bid':{'$avg':'$bid'},
                                      'click_weighted_bid':{'$sum':{'$multiply':['$bid','$clicks']}},
                                      'imp_weighted_bid':{'$sum':{'$multiply':['$bid','$impressions']}},
                                      'samples':{'$sum':1}}}]
                    agg_ret = skynet_db.fb_adstats_hourly.aggregate(agg)
                else:
                    click_weighted_value_available = True
                    by_time = {}
                    for row in skynet_db.fb_adstats_hourly.find(adstat_qs, {'start_time':1,'adgroup_id':1,'spent':1,'clicks':1,'impressions':1,'bid':1}):
                        ts = (row['start_time']//time_interval)*time_interval
                        if ts not in by_time: by_time[ts] = []
                        # get value-add
                        row['value_add'] = adgroup_dict[row['adgroup_id']]['est_ltv']
                        by_time[ts].append(row)
                    agg_ret = []
                    for ts, samples in by_time.iteritems():
                        agg_ret.append({'_id':ts,
                                        'spent':sum((x['spent'] for x in samples),0),
                                        'impressions':sum((x['impressions'] for x in samples),0),
                                        'clicks':sum((x['clicks'] for x in samples),0),
                                        'avg_bid':sum((x['bid'] for x in samples),0)/len(samples),
                                        'click_weighted_bid':sum((x['bid']*x['clicks'] for x in samples),0),
                                        'imp_weighted_bid':sum((x['bid']*x['impressions'] for x in samples),0),
                                        'click_weighted_value':sum((x['value_add']*x['clicks'] for x in samples),0),
                                        'samples':len(samples)})


                if agg_ret:
                    agg_ret.sort(key = lambda x: x['_id']) # sort by start_time
                    ret = [{'ui_name': "Impressions",
                            'plot_params': {'yaxis': {'min': 0, 'panRange':[0,None]}, 'xaxis': time_axis_params},
                            'series': [{'label':'impressions', 'points':{'show':True}, 'lines':{'show':True},
                                        'data': [(1000*datum['_id'], datum['impressions']) for datum in agg_ret]},
                                       ]},
                            {'ui_name': "Clicks",
                            'plot_params': {'yaxis': {'min': 0, 'panRange':[0,None]}, 'xaxis': time_axis_params},
                            'series': [{'label':'clicks', 'points':{'show':True}, 'lines':{'show':True},
                                        'data': [(1000*datum['_id'], datum['clicks']) for datum in agg_ret]},
                                       ]},
                           {'ui_name': "CTR%",
                            'plot_params': {'yaxis': {'min': 0, 'panRange':[0,None]}, 'xaxis': time_axis_params},
                            'series': [{'label':'CTR%', 'points':{'show':True}, 'lines':{'show':True},
                                        'data': [(1000*datum['_id'], 100.0*datum['clicks']/max(datum['impressions'],0.01)) for datum in agg_ret]}]}]

                    if len(bid_types) == 1:
                        # graph bid performance
                        bid_type = bid_types[0]
                        if bid_type == 'CPC':
                            series =  [{'label':'click_weighted_bid', 'points':{'show':True}, 'lines':{'show':True}, 'color':'rgb(0,0,255)',
                                        'data': [(1000*datum['_id'], (0.01*datum['click_weighted_bid']/max(1.0*datum['clicks'],0.01))) for datum in agg_ret]},
                                       {'label':'imp_weighted_bid', 'points':{'show':True}, 'lines':{'show':True}, 'color':'rgb(200,200,200)',
                                        'data': [(1000*datum['_id'], (0.01*datum['imp_weighted_bid']/max(1.0*datum['impressions'],0.01))) for datum in agg_ret]},
#                                       {'label':'avg_bid', 'points':{'show':True}, 'lines':{'show':True},
#                                        'data': [(1000*datum['_id'], 0.01*datum['avg_bid']) for datum in agg_ret]},
                                       {'label':'CPC', 'points':{'show':True}, 'lines':{'show':True}, 'color':'rgb(255,0,0)',
                                        'data': [(1000*datum['_id'], (0.01*datum['spent']/max(1.0*datum['clicks'],0.01))) for datum in agg_ret]}]

                            if click_weighted_value_available:
                                series.insert(0,{'label':'LTV/Click', 'points':{'show':True}, 'lines':{'show':True}, 'color':'rgb(0,255,0)',
                                                 'data': [(1000*datum['_id'], (datum['click_weighted_value']/max(1.0*datum['clicks'],0.01))) for datum in agg_ret]})

                            ret.append({'ui_name': "Bid Performance (%s)" % bid_type,
                                        'plot_params': {'yaxis': {'min': 0, 'panRange':[0,None]}, 'xaxis': time_axis_params},
                                        'series':series})

                        elif bid_type.startswith('oCPM_'):

                            if bid_type == 'oCPM_INSTALL':
                                kpi = 'acquisition_event'
                            else:
                                kpi = bid_type[len('oCPM_'):][(0 if game_ids[0]=='tr' else len(game_ids[0]+'_')):]

                            gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
                            if kpi in gamedata['adnetworks']['fb_conversion_pixels']['events']:
                                # pull acquisition events from production server log
                                if len(game_ids) != 1:
                                    ui_info = 'Multiple game_ids, cannot query conversions'
                                elif game_ids[0] not in SpinConfig.config['mongodb_servers']:
                                    ui_info = 'config.json has no mongodb_servers entry for game_id %s, cannot query conversions' % game_ids[0]

                                else:
                                    remote_nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_ids[0]), identity = 'pcheck_skynet')
                                    event_qs = {'time':{'$gte':start_time, '$lte': end_time}, 'kpi':kpi}
                                    event_qs.update(adgroup_dtgt_qs)

                                    if 0:
                                        weighted_value_available = False
                                        remote_agg =  [{'$match':event_qs},
                                                       {'$project':{'time':1}},
                                                       {'$group': {'_id': { '$subtract' :['$time', {'$mod':['$time', time_interval]}] }, # group by hour
                                                                   'count':{'$sum': 1}}}]

                                        events = dict((x['_id'], {'count':x['count']}) for x in remote_nosql_client.log_buffer_table('log_fb_conversion_pixels').aggregate(remote_agg))
                                    else:
                                        weighted_value_available = True
                                        events_by_time = {}
                                        for row in remote_nosql_client.log_buffer_table('log_fb_conversion_pixels').find(event_qs, {'time':1,'context':1}):
                                            ts = time_interval*(row['time']//time_interval)
                                            tgt = SkynetLib.decode_params(SkynetLib.standin_spin_params, row['context'])
                                            row['tgt'] = tgt
                                            coeff, install_rate, unused_info = SkynetLib.bid_coeff(SkynetLib.standin_spin_params, tgt, 1.0, use_bid_shade = False,
                                                                                                   use_install_rate = tgt['bid_type'] in ('CPC', 'oCPM_CLICK', 'oCPM_INSTALL'))
                                            row['est_ltv'] = coeff # this is the 90-day est LTV associated with the bid_type event
                                            if ts not in events_by_time: events_by_time[ts] = []
                                            events_by_time[ts].append(row)
                                        events = {}
                                        for ts, rows in events_by_time.iteritems():
                                            events[ts] = {'count':len(rows),
                                                          'weighted_value':sum((row['est_ltv'] for row in rows), 0)
                                                          }

                                    if len(events) < 1:
                                        ui_info = 'No conversion events found'
                                    else:
                                        series = [
                                            #{'label':'avg_bid', 'points':{'show':True}, 'lines':{'show':True},
                                            # 'data': [(1000*datum['_id'], 0.01*datum['avg_bid']) for datum in agg_ret]},
                                            #{'label':'imp_weighted_bid', 'points':{'show':True}, 'lines':{'show':True}, 'color':'rgb(200,200,200)',
                                            # 'data': [(1000*datum['_id'], (0.01*datum['imp_weighted_bid']/max(1.0*datum['impressions'],0.01))) for datum in agg_ret]},
                                            {'label':'click_weighted_bid', 'points':{'show':True}, 'lines':{'show':True}, 'color':'rgb(0,0,255)',
                                             'data': [(1000*datum['_id'], (0.01*datum['click_weighted_bid']/max(1.0*datum['clicks'],0.01))) for datum in agg_ret]},

                                            {'label':'Cost/event', 'points':{'show':True}, 'lines':{'show':True}, 'color':'rgb(255,0,0)',
                                             'data': [(1000*datum['_id'], 0.01*datum['spent']/events.get(datum['_id'],{}).get('count',0)) for datum in agg_ret if \
                                                      events.get(datum['_id'],{}).get('count',0)>0]}]
                                        if weighted_value_available:
                                            series.append({'label':'LTV/event', 'points':{'show':True}, 'lines':{'show':True}, 'color':'rgb(0,255,0)',
                                                           'data': [(1000*datum['_id'], events.get(datum['_id'],{}).get('weighted_value',0)/events.get(datum['_id'],{}).get('count',0)) for datum in agg_ret if \
                                                                     events.get(datum['_id'],{}).get('count',0)>0]})

                                        ret.append({'ui_name': "Bid Performance (%s: %s)" % (game_ids[0], bid_type),
                                                    'plot_params': {'yaxis': {'min': 0, 'panRange':[0,None]}, 'xaxis': time_axis_params},
                                                    'series': series})

                            else:
                                ui_info = 'Unhandled oCPM bid KPI "%s", cannot graph bid performance' % kpi
                        else:
                            ui_info = 'Unhandled bid type "%s", cannot graph bid performance' % bid_type
                    else:
                        ui_info = 'Multiple bid types (%s), cannot graph bid performance.' % repr(bid_types)
                else:
                    ui_info = 'No adstats found'
                    ret = []

                result = {'result': {'graphs': ret,
                                     'query': args['query'],
                                     'bid_types': list(bid_types),
                                     'adgroup_dtgt_qs': adgroup_dtgt_qs,
                                     'adgroup_list_len': len(adgroup_list),
                                     'ui_info': ui_info
                                     }}
            else:
                raise Exception('unknown skynet method '+method)

        else:
            raise Exception('unknown path '+repr(path))

        # do some logging here
        if do_log and ('result' in result):
            log_args = args.copy()
            for FIELD in ('spin_token', 'secret'):
                if FIELD in log_args: del log_args[FIELD]

            pcheck_log = SpinLog.MultiLog([SpinLog.DailyJSONLog(SpinConfig.config.get('log_dir', 'logs')+'/','-pcheck.json'),
                                           SpinNoSQLLog.NoSQLJSONLog(nosql_client, 'log_pcheck')])

            pcheck_log.event(time_now, {'spin_user': spin_token_data['spin_user'], 'path':path, 'method':method, 'args':log_args, 'result':result['result']})

        return result

    except:
        return {"error":traceback.format_exc()}

def do_CONTROLAPI(args, host = None, port = None):
    url = 'http://%s:%d/CONTROLAPI' % (host or SpinConfig.config['proxyserver'].get('external_listen_host','localhost'),
                                       port or SpinConfig.config['proxyserver']['external_http_port'])
    args['secret'] = SpinConfig.config['proxy_api_secret']
    response = urllib2.urlopen(url+'?'+urllib.urlencode(args)).read().strip()
    return SpinJSON.loads(response)

def do_lookup(args):
    if 'user_id' in args:
        user_id = int(args['user_id'])
        cmd_args = [str(user_id)]
    elif 'facebook_id' in args:
        cmd_args = ['--facebook-id', args['facebook_id']]
    else:
        raise Exception('must pass user_id or facebook_id')
    p = subprocess.Popen(['./check_player.py'] + cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if err:
        raise Exception(err)
    if p.returncode != 0:
        raise Exception(out)
    return out

def get_server_latency_series(server_name, rows):
    return {'label':server_name,
            'lines':{'show':False}, 'points':{'show':True, 'shadowSize':0, 'radius':1},
            #'threshold': { 'above': 1000.0, 'below': 1e-9, 'color': 'rgb(200,20,30)' },
            #'tooltips': ['%s %0.1fms' % (server_name, 1000.0*datum['latency']) for datum in rows],
            'data': [(1000*datum['time'], 1000.0*datum['latency']) for datum in rows]}

def get_client_perf_series(nosql_client, name, source_key, qs, rescale = 1):
    return {'label': name,
            'lines':{'show':True},'points':{'show':True},
            'data': [(1000*row['_id'], rescale * row['average']) for row in \
                     nosql_client.client_perf_table().aggregate([{'$match':qs},
                                                                 {'$project':{'time':1,'rate':source_key}},
                                                                 {'$group':{'_id': { '$subtract' :['$time', {'$mod':['$time', 3600]}] },
                                                                            'average': {'$avg': '$rate'}}},
                                                                 {'$sort':{'_id':1}}
                                                                 ])]}

def get_server_latency(nosql_client):
    time_range = [time_now - 1*86400, time_now]
    IGNORE_BELOW = 0.50
    rows = list(nosql_client.server_latency_table().find({'$or':[{'time':{'$gte':time_range[0],'$lt':time_range[1]},
                                                                   'latency':{'$lte':0}},
                                                                  {'time':{'$gte':time_range[0],'$lt':time_range[1]},
                                                                   'latency':{'$gte':IGNORE_BELOW}}],
                                                          }, {'time':1,'latency':1,'ident':1}).sort([('time',-1)]).limit(2000))
    server_names = set(x['ident'] for x in rows)
    latency_series = [get_server_latency_series(server_name, filter(lambda datum: datum['ident']==server_name, rows)) for server_name in server_names]
    return {'graphs':[{'ui_name': 'Server Latency',
                       'plot_params': {'yaxis': {'min':0, 'max':5000.0, 'panRange':[0,None]}, 'xaxis': time_axis_params, 'legend':{'show':False} },
                       'series': latency_series},
                      {'ui_name': 'Client Framerates',
                       'plot_params': {'yaxis': {'min':0, 'max':40.0, 'panRange':[0,None]}, 'xaxis': time_axis_params, 'legend':{'position':'nw'} },
                       'series': [get_client_perf_series(nosql_client, 'avg_framerate', '$graphics.framerate', {'time':{'$gte':time_range[0],'$lt':time_range[1]}}),
                                  #get_client_perf_series(nosql_client, 'avg_framerate_us', '$graphics.framerate', {'country':'us', 'time':{'$gte':time_range[0],'$lt':time_range[1]}}),
                                  ]
                       },
                      {'ui_name': 'Client Pings',
                       'plot_params': {'yaxis': {'min':0, 'max':2000.0, 'panRange':[0,None]}, 'xaxis': time_axis_params, 'legend':{'position':'nw'} },
                       'series': [get_client_perf_series(nosql_client, 'avg_ping', '$direct_ssl.ping', {'time':{'$gte':time_range[0],'$lt':time_range[1]}}, rescale=1000),
                                  get_client_perf_series(nosql_client, 'avg_ping_us', '$direct_ssl.ping', {'country':'us', 'time':{'$gte':time_range[0],'$lt':time_range[1]}}, rescale=1000),
                                  #get_client_perf_series(nosql_client, 'avg_ping_aunz', '$direct_ssl.ping', {'country':{'$in':['au','nz']}, 'time':{'$gte':time_range[0],'$lt':time_range[1]}}, rescale=1000),
                                  ]
                       },
                      ]}

if __name__ == "__main__":
    if (not SpinConfig.config.get('secure_mode',False)):
        cgitb.enable()

    args = cgi.parse() or {}
    method = args.get('method',['gui'])[-1]
    full_path = (os.getenv('REQUEST_URI') or 'PCHECK').split('?')[0].split('/')
    sub_path = full_path[full_path.index('PCHECK')+1:]

    if SpinGoogleAuth.cgi_is_local():
        auth_info = {'ok':1,'spin_token':{'spin_user':'local','google_access_token':'local','roles':['PCHECK','PCHECK-WRITE','PCHECK-BAN','ADMIN','SKYNET']},'raw_token':'local'}
    else:
        auth_info = SpinGoogleAuth.cgi_do_auth(args, 'PCHECK', time_now)

    if auth_info['ok']:
        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), identity = 'pcheck')
        nosql_client.set_time(time_now)

    if method == 'gui':
        print_html_headers()
        if auth_info['ok']:
            print do_gui(auth_info['spin_token'], auth_info['raw_token'],
                         SpinGoogleAuth.spin_token_cookie_name(),
                         SpinGoogleAuth.cgi_get_my_endpoint(),
                         nosql_client)
        elif 'redirect' in auth_info:
            print auth_info['redirect']
        else:
            print auth_info['error']
    else:
        if auth_info['ok']:
            print_json(do_action(sub_path, method, dict(((k,v[0]) for k,v in args.iteritems())), auth_info['spin_token'], nosql_client),
                       attachment_name = args.get('attachment_name',[None])[-1], gzip_encode = bool(int(args.get('gzip_encode',[0])[-1])))
        else:
            time.sleep(1)
            print_json({'error': auth_info['error']})
