#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# CGI script for customer support and server management

import os, sys, subprocess, traceback, time, re, copy
import cgi, cgitb, socket
import urllib, urllib2
import SpinFacebook
import SpinNoSQL
import SpinNoSQLLog
import SpinConfig
import SpinJSON
import SpinGoogleAuth
import SpinLog
import FastGzipFile

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
        '$GOOGLE_TRANSLATE_ENABLED$': 'true' if SpinConfig.config.get('google_translate_api_key') else 'false',
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
        # skip obsolete regions
        if not (val.get('open_join',1)): continue
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

CHAT_ABUSE_MEMORY_DURATION = 365*86400

def chat_abuse_clear(control_args):
    check_stacks_args = control_args.copy()
    check_stacks_args.update({'method': 'cooldown_active', 'name': 'chat_abuse_violation'})
    active_stacks = max(do_CONTROLAPI_checked(check_stacks_args), 0)

    if active_stacks > 0:
        new_stacks = max(0, active_stacks - 1)
        clear_cd_args = control_args.copy()
        clear_cd_args.update({'method':'clear_cooldown', 'name': 'chat_abuse_violation'})
        assert do_CONTROLAPI_checked(clear_cd_args) == 'ok'
        if new_stacks > 0:
            add_stack_args = control_args.copy()
            add_stack_args.update({'method': 'trigger_cooldown', 'name': 'chat_abuse_violation', 'add_stack': new_stacks, 'duration': CHAT_ABUSE_MEMORY_DURATION})
            assert do_CONTROLAPI_checked(add_stack_args) == 'ok'
    else:
        new_stacks = 0

    ungag_args = control_args.copy()
    ungag_args.update({'method': 'chat_ungag'})
    assert do_CONTROLAPI_checked(ungag_args) == 'ok'
    return "Player was unmuted and reduced to %d chat offense(s)." % new_stacks

def bbcode_quote(s):
    r = ''
    for c in s:
        if c in ('\\', '[', ']'):
            r += '\\'+c
        else:
            r += c
    return r

def chat_abuse_violate(control_args, ui_context, channel_name, message_id):
    ui_reason = 'The player said: "%s"' % ui_context
    spin_user = control_args['spin_user']

    # query current repeat-offender stacks and gag status
    check_args = control_args.copy()
    check_args.update({'method': 'player_batch', 'batch': SpinJSON.dumps([{'method': 'cooldown_active', 'args': {'name': 'chat_abuse_violation'}},
                                                                          {'method': 'aura_active', 'args': {'aura_name': 'chat_gagged'}}])})
    check_result = do_CONTROLAPI_checked(check_args)
    active_stacks = max(check_result[0], 0)
    is_gagged_now = bool(check_result[1])

    # for policy see https://sites.google.com/a/spinpunch.com/support/about-zendesk/chat-moderation-process
    # active_stacks 0 -> message and 24h mute
    # active_stacks 1 -> message and 48h mute
    # active_stacks 2 -> message and 72h mute
    # active_stacks 3 -> no message, permanent mute, also mute alts.
    ui_policy_link = '[color=#ffff00][u][url=https://spinpunch.zendesk.com/entries/88917453-What-is-the-Chat-Abuse-policy-]chat abuse policy[/url][/u][/color]'
    ui_player_context = '[color=#ff0000]'+bbcode_quote(ui_context)+'[/color]'
    ui_actions = []
    message_body = None
    alt_message_body = None
    add_stack = False
    temporary_mute_duration = -1
    permanent_mute = False
    permanent_mute_alts = False

    if message_id and channel_name:
        censor_args = {'method': 'censor_chat_message', 'channel': channel_name, 'target_user_id': control_args['user_id'], 'message_id': message_id}
        assert do_CONTROLAPI_checked(censor_args) == 'ok'
        ui_actions.append("Hid this chat message from other players")

    if is_gagged_now:
        ui_actions.append("Player is currently muted, perhaps because of a recent violation. No action taken against the player.")

    elif active_stacks == 0:
        message_body = "Hello! You were recently reported for violating our %s. A support agent reviewed this report and confirmed your message was offensive:\n\n%s\n\nThis message is to serve as a warning, and a notification that you are receiving a temporary mute from in-game chat. Any future offenses may result in a longer temporary or permanent mute from chat. Thanks in advance for your understanding." % (ui_policy_link, ui_player_context)
        add_stack = True
        temporary_mute_duration = 24*3600
    elif active_stacks == 1:
        message_body = "You were recently reported again for violating our %s. A support agent reviewed this report and confirmed your message was offensive:\n\n%s\n\nThis message is to serve as a 2nd warning, and a notification that you are receiving a temporary mute from in-game chat. Any future offenses may result in a longer temporary or permanent mute from chat. Thanks in advance for your understanding." % (ui_policy_link, ui_player_context)
        add_stack = True
        temporary_mute_duration = 48*3600
    elif active_stacks == 2:
        message_body = "You were recently reported again for violating our %s. A support agent reviewed this report and confirmed your message was offensive:\n\n%s\n\nThis message is to serve as a 3rd warning, and a notification that you are receiving a temporary mute from in-game chat. Any future offenses will result in a permanent chat mute without further warning. Thanks in advance for your understanding." % (ui_policy_link, ui_player_context)
        add_stack = True
        temporary_mute_duration = 72*3600
    elif active_stacks >= 3:
        if active_stacks == 3:
            alt_message_body = "Hello! This message is to inform you that your account has been muted from in-game chat due to offensive chat violations on a related game account (ID: %d). If you feel this ban may have been made in error, please submit a ticket to our Customer Support team. Thanks in advance for your understanding." % int(control_args['user_id'])
        add_stack = (active_stacks < 4)
        permanent_mute = True
        permanent_mute_alts = True

    batch = []
    if add_stack:
        batch.append({'method': 'trigger_cooldown', 'args':{'name': 'chat_abuse_violation', 'add_stack': 1, 'duration': CHAT_ABUSE_MEMORY_DURATION, 'spin_user': spin_user}})
        ui_actions.append("Offense count increased to %d" % (active_stacks + 1))
    if message_body:
        batch.append({'method': 'send_message', 'args':{'message_subject': 'Chat Warning', 'message_body': message_body, 'ui_reason': ui_reason, 'spin_user': spin_user}})
        ui_actions.append("Sent warning message")
    if temporary_mute_duration > 0:
        batch.append({'method': 'chat_gag', 'args':{'duration': temporary_mute_duration, 'spin_user': spin_user}})
        ui_actions.append("Muted player for %d hours" % (temporary_mute_duration / 3600))
    if permanent_mute:
        batch.append({'method': 'chat_gag', 'args':{'ui_reason': ui_reason, 'spin_user': spin_user}})
        ui_actions.append("Muted player permanently")

    if batch:
        batch_args = control_args.copy()
        batch_args.update({'method': 'player_batch', 'batch': SpinJSON.dumps(batch)})
        assert do_CONTROLAPI_checked(batch_args) == ['ok',]*len(batch)

    if permanent_mute_alts or alt_message_body:
        pass # XXXXXX no handling for alts yet

    return "Player had %d offense(s) before this. Took actions:\n\n- %s" % (active_stacks, "\n- ".join(ui_actions))

def filter_chat_report_list(reports):
    # clean up a list of chat reports and return only the ones still eligible for enforcement
    # in addition to filtering reports that are already resolved, we also need to avoid "double jeopardy"
    # (report -> violate -> report again -> violate again) by ignoring any reports that refer to things
    # said before a player's latest violation
    latest_violations = {}
    for report in reports:
        if report.get('resolved', False) and report.get('resolution', None) == 'violate' and ('resolution_time' in report):
            latest_violations[report['target_id']] = max(latest_violations.get(report['target_id'],-1), report['resolution_time'])

    return filter(lambda x:
                  (not x.get('resolved')) and # unresolved
                  (x['time'] > latest_violations.get(x['target_id'],-1)), # no later violation
                  reports)

def do_action(path, method, args, spin_token_data, nosql_client):
    try:
        do_log = False

        assert len(path) >= 1
        if path[0] == 'player':
            # player methods
            if (method not in ('lookup', 'get_raw_player')):
                do_log = True # log all write activity

            # require special role for writes, except for chat, aura, and alt actions
            if (method not in ('lookup','get_raw_player','chat_gag','chat_ungag','chat_block','chat_unblock','chat_abuse_violate','chat_abuse_clear','apply_aura','remove_aura','ignore_alt','unignore_alt')):
                check_role(spin_token_data, 'PCHECK-WRITE')
                if method in ('ban','unban'):
                    check_role(spin_token_data, 'PCHECK-BAN')

            control_args = args.copy()
            if 'spin_token' in control_args: # do not pass credentials along
                del control_args['spin_token']
            control_args['spin_user'] = spin_token_data['spin_user']

            if method == 'lookup':
                result = {'result':do_lookup(control_args)}
            # chat abuse handling doesn't map 1-to-1 with CONTROLAPI calls, so handle them specially
            elif method == 'chat_abuse_violate':
                result = {'result':chat_abuse_violate(control_args, control_args['ui_player_reason'], None, None)}
            elif method == 'chat_abuse_clear':
                result = {'result':chat_abuse_clear(control_args)}
            elif method in ('give_item','send_message','chat_gag','chat_ungag','chat_block','chat_unblock','apply_aura','remove_aura','get_raw_player','ban','unban',
                            'make_developer','unmake_developer','clear_alias','chat_official','chat_unofficial','clear_lockout','clear_cooldown','check_idle','change_region','ignore_alt','unignore_alt','demote_alliance_leader','kick_alliance_member'):
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
                row = nosql_client.server_status_query_one({'_id':server_name}, {'hostname':1, 'game_http_port':1, 'game_ssl_port': 1,
                                                                                 'external_http_port':1, 'external_ssl_port': 1, 'type':1})
                if not row:
                    raise Exception('server %s not found' % server_name)
                control_args = args.copy()
                for FIELD in ('server', 'spin_token'):
                    if FIELD in control_args: del control_args[FIELD]
                # tell proxyserver to handle it instead of forwarding
                if row['type'] == 'proxyserver':
                    control_args['server'] = 'proxyserver'
                result = do_CONTROLAPI(control_args, host = row['hostname'],
                                       http_port = row.get('game_http_port',None) or row.get('external_http_port',None),
                                       ssl_port = row.get('game_ssl_port',None) or row.get('external_ssl_port',None)
                                       )

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
            elif method == 'get_reports':
                report_list = list(nosql_client.chat_reports_get(args['start_time'], args['end_time']))
                if args.get('filter') == 'unresolved':
                    report_list = filter_chat_report_list(report_list)
                result = {'result': report_list }
            elif method == 'resolve_report':
                assert args['action'] in ('ignore', 'violate')
                do_log = True
                if args['action'] == 'ignore':
                    result = {'result': nosql_client.chat_report_resolve(args['id'], 'ignore', time_now)}
                elif args['action'] == 'violate':
                    if not nosql_client.chat_report_resolve(args['id'], 'violate', time_now): # start here to avoid race condition
                        result = {'result': 'This report has already been resolved, perhaps by another PCHECK user.'}
                    # query for the report so we can get the context and time
                    target_report = nosql_client.chat_report_get_one(args['id'])
                    if nosql_client.chat_report_is_obsolete(target_report):
                        result = {'result': 'This report is obsolete. The player has already been punished for a more recent report.'}
                    else:
                        control_args = args.copy()
                        control_args['user_id'] = args['user_id'] # trusting the client - but they have the power to violate anyone anyway.
                        if 'spin_token' in control_args: # do not pass credentials along
                            del control_args['spin_token']
                        control_args['spin_user'] = spin_token_data['spin_user']
                        violate_result = chat_abuse_violate(control_args, target_report['context'], target_report['channel'], target_report.get('message_id',None))
                        result = {'result': violate_result}
            elif method == 'translate':
                # use Google Translate API conventions
                from_language = args.get('from_language', None)
                to_language = args.get('to_language', 'en')
                text = args['text']
                result = {'result': do_google_translate(from_language, to_language, text)}
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

def do_google_translate(from_language, to_language, text):
    args = {'target': to_language, 'q': text}
    if from_language:
        args['source'] = from_language
    args['key'] = SpinConfig.config['google_translate_api_key']
    url = 'https://www.googleapis.com/language/translate/v2?' + urllib.urlencode(args)
    try:
        request = urllib2.urlopen(url)
        response_text = request.read()
    except urllib2.HTTPError as e:
        raise Exception('Google Translate API error:\n%s' % e.read())
    response = SpinJSON.loads(response_text.strip())
    translation = response['data']['translations'][0]
    ret = {'translation': translation['translatedText']}
    if 'detectedSourceLanguage' in translation:
        ret['source_language'] = translation['detectedSourceLanguage']
    return ret

def do_CONTROLAPI(args, host = None, http_port = None, ssl_port = None):
    host = host or SpinConfig.config['proxyserver'].get('external_listen_host','localhost')
    proto = 'http' if host in ('localhost', socket.gethostname()) else 'https'
    url = '%s://%s:%d/CONTROLAPI' % (proto, host,
                                     (ssl_port or SpinConfig.config['proxyserver']['external_ssl_port']) if proto == 'https' else \
                                     (http_port or SpinConfig.config['proxyserver']['external_http_port'])
                                     )
    args['secret'] = SpinConfig.config['proxy_api_secret']
    response = urllib2.urlopen(url+'?'+urllib.urlencode(args)).read().strip()
    return SpinJSON.loads(response)

# this version assumes the CustomerSupport return value conventions
def do_CONTROLAPI_checked(args):
    ret = do_CONTROLAPI(args)
    if 'error' in ret:
        raise Exception('CONTROLAPI method failed: ' + (ret['error'] if isinstance(ret['error'], basestring) else repr(ret['error'])))
    else:
        return ret['result']

def do_lookup(args):
    cmd_args = ['--live']
    if 'user_id' in args:
        user_id = int(args['user_id'])
        cmd_args += [str(user_id)]
    elif 'facebook_id' in args:
        cmd_args += ['--facebook-id', args['facebook_id']]
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

#                      {'ui_name': 'Client Pings',
#                       'plot_params': {'yaxis': {'min':0, 'max':2000.0, 'panRange':[0,None]}, 'xaxis': time_axis_params, 'legend':{'position':'nw'} },
#                       'series': [get_client_perf_series(nosql_client, 'avg_ping', '$direct_ssl.ping', {'time':{'$gte':time_range[0],'$lt':time_range[1]}}, rescale=1000),
#                                  get_client_perf_series(nosql_client, 'avg_ping_us', '$direct_ssl.ping', {'country':'us', 'time':{'$gte':time_range[0],'$lt':time_range[1]}}, rescale=1000),
                                  #get_client_perf_series(nosql_client, 'avg_ping_aunz', '$direct_ssl.ping', {'country':{'$in':['au','nz']}, 'time':{'$gte':time_range[0],'$lt':time_range[1]}}, rescale=1000),
#                                  ]
#                       },

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
