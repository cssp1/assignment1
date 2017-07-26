#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# logging module

import SpinJSON
import time, re, copy
import gzip

# convert unix time to date string like "20120224"
def time_to_date_string(t):
    st = time.gmtime(t)
    return '%04d%02d%02d' % (st.tm_year, st.tm_mon, st.tm_mday)

# turn struct_time into a human-readable string
def pretty_time(st):
    return '%04d/%02d/%02d %02d:%02d:%02d' % (st.tm_year, st.tm_mon, st.tm_mday,
                                              st.tm_hour, st.tm_min, st.tm_sec)

# LogFile is an implementation detail of the *Log classes below
class LogFile(object):
    def __init__(self):
        self.cur_fd = None
    def set_ymd(self, ymd):
        pass

# log to single flat file
class SimpleLogFile(LogFile):
    def __init__(self, filename, buffer = 1):
        LogFile.__init__(self)
        self.cur_fd = open(filename, 'a', buffer)
    def close(self):
        self.cur_fd.close()

# log to single gzipped file
class GzipLogFile(LogFile):
    def __init__(self, filename):
        LogFile.__init__(self)
        self.cur_fd = gzip.GzipFile(filename = filename, fileobj = open(filename, 'w'))
    def close(self):
        self.cur_fd.close()

# log to a set of flat files, one per day of data
class DailyLogFile(LogFile):
    def __init__(self, prefix, suffix, bufsize = 1):
        LogFile.__init__(self)
        self.prefix = prefix
        self.suffix = suffix
        self.bufsize = bufsize
        self.cur_ymd = (0,0,0)
    def set_ymd(self, ymd):
        if ymd != self.cur_ymd:
            # switch to a different file
            self.cur_ymd = ymd
            if self.cur_fd:
                self.cur_fd.close()
            self.cur_fd = open(self.prefix + '%04d%02d%02d' % ymd + self.suffix, 'a', self.bufsize)

# base class for logs
class Log(object):
    def close(self): pass
    def event(self, t, arg): raise Exception('not implemented')

# black-hole empty log
class NullLog(Log):
    def event(self, t, arg): pass

# multiplex several logs
class MultiLog(Log):
    def __init__(self, children):
        Log.__init__(self)
        self.children = children
    def close(self):
        for child in self.children:
            child.close()
    def event(self, t, arg):
        for child in self.children:
            child.event(t, arg)

# print raw strings with time stamps as log messages
class RawLog(Log):
    def __init__(self, target):
        Log.__init__(self)
        self.target = target
    def close(self): self.target.close()
    def event(self, t, msg):
        st = time.gmtime(t)
        self.target.set_ymd((st.tm_year, st.tm_mon, st.tm_mday))
        time_string = '%10d ' % t + pretty_time(st)
        for line in msg.split('\n'):
            self.target.cur_fd.write(time_string + ' ' + line + '\n')

# print JSON dictionaries as log messages
class JSONLog(Log):
    def __init__(self, target):
        Log.__init__(self)
        self.target = target

    def close(self): self.target.close()

    # usage:
    # event(server_time, {'code': 1234, 'key1': "val1", ... })
    def event(self, t, keyval):
        assert isinstance(keyval, dict)
        assert len(keyval) > 0

        st = time.gmtime(t)

        # UNIX UTC epoch seconds
        time_string = '%10d' % t

        # human-readable version of above
        # (optional, turned off now to save space/time)
        if 0:
            pretty_time_string = pretty_time(st)
        else:
            pretty_time_string = None

        self.target.set_ymd((st.tm_year, st.tm_mon, st.tm_mday))

        # bring special keywords to the front for easy viewing
        if 'event_name' in keyval:
            event_name = keyval['event_name']
            del keyval['event_name']
        else:
            event_name = None

        if 'user_id' in keyval:
            user_id = keyval['user_id']
            del keyval['user_id']
        else:
            user_id = None

        # JSON-encoded log data
        str = SpinJSON.dumps(keyval, pretty = False, double_precision = 5)

        # add back deleted fields
        if event_name is not None:
            keyval['event_name'] = event_name
        if user_id is not None:
            keyval['user_id'] = user_id

        # manually strip apart the JSON string and add 'time' at the very beginning,
        # to make the files easy to sort

        # strip off the {}
        str = str[1:-1]

        out = '{"time":'+time_string
        if pretty_time_string:
            out +=',"ptime":"'+pretty_time_string+'"'
        if user_id is not None:
            out += ',"user_id":'+repr(user_id)
        if event_name is not None:
            out += ',"event_name":"'+event_name+'"'
        if str:
            out += ','+str
        out += '}\n'
        self.target.cur_fd.write(out)

def SimpleJSONLog(filename, buffer = 1):
    return JSONLog(SimpleLogFile(filename, buffer = buffer))

def DailyJSONLog(prefix, suffix):
    return JSONLog(DailyLogFile(prefix, suffix))

def DailyRawLog(prefix, suffix, buffer = False):
    return RawLog(DailyLogFile(prefix, suffix, bufsize = -1 if buffer else 1))

class JSONLogFilter(Log):
    def __init__(self, child, allow = None, deny = None, require_func = None):
        Log.__init__(self)
        self.child = child
        self.allow = set(allow) if allow is not None else None
        self.deny = set(deny) if deny is not None else None
        self.require_func = require_func
    def event(self, t, props):
        name = props.get('event_name',None)
        if self.allow is not None:
            if not name: return
            if name not in self.allow: return
        if self.deny is not None:
            if name in self.deny: return
        if self.require_func and (not self.require_func(props)): return
        self.child.event(t, props)

def MetricsLogFilter(child):
    return JSONLogFilter(child,
                         # *maybe* allow stuff like authenticated_visit here, if performance impact is not bad
                         allow = [#'0115_logged_in', # obsolete - use sessions table
                                  '0113_account_deauthorized',
                                  '0140_tutorial_oneway_ticket',
                                  '0140_tutorial_start',
                                  '0141_tutorial_start_client',
                                  '0145_deploy_one_unit',
                                  '0150_finish_battle',
                                  '0155_reward_finish_battle',
                                  '0159_reward_collection',
                                  '0160_accept_barracks_mission',
                                  '0170_click_barracks_on_menu',
                                  '0180_reward_barracks_mission',
                                  '0190_one_unit_queued',
                                  '0200_full_army_queued',
                                  '0210_reward_full_army_mission',
                                  '0220_click_attack_menu',
                                  '0230_base_attack_started',
                                  '0240_win_base_attack',
                                  '0244_reward_base_attack',
                                  '0246_proceed_incoming_message',
                                  '0250_click_allandra_console',
                                  '0260_click_warehouse',
                                  '0270_activate_mana_icon',
                                  '0280_reward_activate_item_mission',
                                  '0399_tutorial_complete',

                                  '0691_idle_check',
                                  '0692_idle_check_success',
                                  '0693_idle_check_fail',
                                  '0694_idle_check_timeout',

                                  '0700_login_abuse_detected',

                                  '0800_abtest_joined',

                                  '1500_server_restart',
                                  # '3832_battle_replay_uploaded', # temporary - causes bloat, but useful for looking at replay size
                                  '3833_battle_replay_downloaded',
                                  '3870_loot_given',
                                  '4701_change_region_success',
                                  '4702_region_close_notified',
                                  #'5120_buy_item', # obsolete - use gamebucks log

                                  # these can be turned on temporarily for analytics
                                  '3350_no_miss_hack',
                                  #'4010_quest_complete',
                                  #'4011_quest_complete_again',
                                  '4120_send_gift_completed',
                                  '4056_strategy_guide_opened',

                                  # note: used by FS only, for quarry tracking
                                  '4030_upgrade_building',

                                  '4461_promo_warehouse_upgrade',
                                  #'5130_item_activated',
                                  #'5131_item_trashed',
                                  #'5140_mail_attachment_collected'
                                  '5141_dp_cancel_aura_acquired',
                                  '5142_dp_cancel_aura_ended',

                                  '5149_turret_heads_migrated',

                                  '5200_insufficient_resources_dialog',
                                  '5201_insufficient_resources_go_to_store',
                                  '5202_insufficient_resources_topup_dialog',
                                  '5203_insufficient_resources_topup_buy_now',
                                  '6000_retention_incentive_sent',
                                  '6001_retention_incentive_claimed',

                                  '7150_friendstone_generated',
                                  '7151_friendstone_opened_send_ui',
                                  '7153_friendstone_sent',
                                  '7154_friendstone_received',
                                  '7155_friendstones_redeemed',

                                  '7530_cross_promo_banner_seen',
                                  '7531_cross_promo_banner_clicked',
                                  ],
                         deny = ['0970_client_exception'] # these get sent to the log_client_exceptions log instead
                         )

def AcquisitionsLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['0110_created_new_account',
                                  '0111_account_lapsed', # note: written by ETL scripts, not server code, but included here for reference
                                  '0112_account_reacquired',
                                  '0113_account_deauthorized',
                                  ])
def InventoryLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['5125_item_obtained',
                                  '5130_item_activated',
                                  '5131_item_trashed',
                                  '5132_item_expired',
                                  '5140_mail_attachment_collected'
                                  ])
def LadderPvPLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['3300_ladder_search',
                                  '3301_ladder_search_success',
                                  '3302_ladder_search_fail',
                                  '3303_ladder_spy',
                                  '3304_ladder_skip',
                                  '3305_ladder_attack_start',
                                  '3306_ladder_attack_end',
                                  '3307_ladder_peek',
                                  ])
def DamageProtectionLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['3880_protection_from_new_account',
                                  '3881_protection_from_ladder_battle',
                                  '3882_protection_from_nonladder_battle',
                                  '3883_protection_from_spell',
                                  '3884_protection_removed',
                                  '3885_i_got_attacked',
                                  '3886_protection_removed_manually'
                                  ])
def QuestsLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['4010_quest_complete',
                                  '4011_quest_complete_again'
                                  ])
def LotteryLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['1630_lottery_scan_free',
                                  '1631_lottery_scan_paid',
                                  '1632_lottery_no_space_help',
                                  '1633_lottery_dialog_open',
                                  ])
def AchievementsLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['4055_achievement_claimed',
                                  ])
def AlliancesLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['4600_alliance_created',
                                  '4601_alliance_settings_updated',
                                  '4602_alliance_num_members_updated',
                                  '4630_alliance_disbanded'
                                  ])
def AllianceMembersLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['4605_alliance_member_invite_sent',
                                  '4610_alliance_member_joined',
                                  '4620_alliance_member_left',
                                  '4625_alliance_member_kicked',
                                  '4626_alliance_member_promoted',
                                  '4640_alliance_member_join_request_sent',
                                  '4650_alliance_member_join_request_accepted',
                                  '4660_alliance_member_join_request_rejected'
                                  ])
def UnitDonationLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['4150_units_donated'
                                  ])
def DamageAttributionLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['3871_damage_attribution'
                                  ])

def FishingLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['5150_fish_start',
                                  '5151_fish_speedup',
                                  '5152_fish_cancel',
                                  '5153_fish_collect',
                                  '5154_fish_open_dialog'
                                  ])
def LoginSourcesFilter(child): # for tracking acquisition/reacquisition sources
    return JSONLogFilter(child,
                         allow = ['0020_page_view',
                                  '0115_logged_in'])
def LoginFlowFilter(child): # for tracking churn during game load process
    return JSONLogFilter(child,
                         allow = ['0100_authenticated_visit',
                                  '0105_client_start',
                                  '0115_logged_in',
                                  '0120_client_ingame',
                                  '0125_first_action',
                                  '0940_unsupported_browser'])
def FBPermissionsLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['0030_request_permission',
                                  '0031_request_permission_prompt',
                                  '0032_request_permission_prompt_success',
                                  '0033_request_permission_prompt_fail',
                                  '0034_request_permission_prompt_unnecessary',
                                  '0110_created_new_account'])
def FBNotificationsLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['7130_fb_notification_sent',
                                  '7131_fb_notification_hit',

                                  '6400_web_push_sub_prompt',
                                  '6401_web_push_sub_prompt_ok',
                                  '6402_web_push_sub_prompt_fail',
                                  '6410_web_push_sub_created',
                                  ])
def FBRequestsLogFilter(child):
    return JSONLogFilter(child,
                         allow = [
                                  '4100_send_gifts_popup_shown',
                                  '4101_send_gifts_ingame_prompt',
                                  '4102_send_gifts_ingame_fb_prompt',
                                  '4103_send_gifts_fb_prompt',
                                  '4104_send_gifts_fb_success',
                                  '4105_send_gifts_fb_fail',
                                  '4106_send_gifts_hit_acquisition',
                                  '4107_send_gifts_hit_redundant',

                                  '4120_send_gift_completed',

                                  '7101_invite_friends_ingame_prompt',
                                  '7102_invite_friends_ingame_fb_prompt',
                                  '7102_invite_friends_ingame_bh_link_copied',
                                  '7103_invite_friends_fb_prompt',
                                  '7104_invite_friends_fb_success',
                                  '7105_invite_friends_fb_fail',
                                  '7106_invite_friends_hit_acquisition',
                                  '7107_invite_friends_hit_redundant',
                                  '7121_mentorship_init',
                                  '7122_mentorship_complete',
                                  '7123_mentorship_count_update',
                                  ])
def FBSharingLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['7270_feed_post_attempted',
                                  '7271_feed_post_completed',
                                  '7272_photo_upload_attempted',
                                  '7273_photo_upload_completed',
                                  '7274_photo_upload_failed',
                                  '7275_screenshot_failed',
                                  ])
def FBOpenGraphLogFilter(child):
    return JSONLogFilter(child,
                         allow = ['7140_fb_open_graph_action_published',
                                  '7141_fb_open_graph_acquisition',
                                  '7142_fb_open_graph_redundant_hit'
                                  ])
def ClientTroubleLogFilter(child):
    return JSONLogFilter(child, allow = ['0620_client_died_from_client_lag',

                                         # These two are redundant with server-side 0955_lagged_out event
                                         #'0621_client_died_from_downstream_lag',
                                         #'0622_client_died_from_upstream_lag',

                                         '0623_client_reconnected',

                                         '0624_client_retrans_buffer_overflow',
                                         '0625_client_recv_buffer_overflow',

                                         '0630_client_died_from_ajax_xmit_failure',
                                         '0631_direct_ajax_failure_falling_back_to_proxy',
                                         '0635_client_died_from_ajax_xmit_timeout',
                                         '0639_client_died_from_ajax_unknown_failure',
                                         '0640_client_died_from_ajax_recv_failure',
                                         '0641_client_died_from_ws_connect_timeout',
                                         '0642_client_died_from_ws_xmit_failure',
                                         '0643_client_died_from_ws_shutdown',
                                         '0645_direct_ws_failure_falling_back_to_proxy',
                                         '0649_client_died_from_ws_unknown_failure',
                                         '0650_client_died_from_facebook_api_error',
                                         '0651_client_died_from_kongregate_api_error',
                                         '0652_client_died_from_armorgames_api_error',
                                         '0660_asset_load_fail',
                                         '0670_client_died_from_version_mismatch',
                                         '0671_client_died_from_proxy_signature_fail',
                                         '0672_client_died_from_backend_race_condition',
                                         '0673_client_cannot_log_in_under_attack',
                                         '0674_client_died_from_simultaneous_login_attempt',
                                         '0955_lagged_out'
                                         ])

# filter out uninteresting client and server exceptions so they do not bloat logs

client_exception_filter = 'Context2D|NS_ERROR_FAILURE|setVol|ut of memory|ot enough st|createSo|measureText|lagerplads| ikke |kke nok minne|peicher|insuffisante|insuficiente|insufficiente|ukladacieho|opslagruimte|finns inte till|suficiente|tamamlamak|Slut p.+ minne|Memoria esaurita|etersiz bellek|Pro dokon|Object expected|Objeto esperado|Previsto oggetto|Objet attendu|esperaba un objeto|Onvoldoende geheugen|esgotada|Nesne bekleniyor|NS_ERROR_UNEXPECTED|0x805e0006|a presentation error|GetDeviceRemovedReason|concluir a opera|mpossibile completare|suorittamiseen|magazynie brak miejsca|ould not complete the operation due to err|HTMLMediaElement.currentTime is not a finite|number of hardware contexts reached maximum|init not called with valid version|api\.dropbox\.com'

class ClientExceptionLogFilter(Log):
    my_re = re.compile(client_exception_filter)
    def __init__(self, child, brief = False):
        Log.__init__(self)
        self.child = child
        self.brief = brief
    def event(self, t, props):
        if props.get('event_name', None) != '0970_client_exception': return

        # check for known harmless exceptions
        if self.my_re.search(props.get('method','')) or self.my_re.search(props.get('location','')): return

        if self.brief: # abbreviate "method" text
            MAXLEN = 64
            if ('method' in props) and len(props['method']) > 64:
                props = copy.deepcopy(props)
                props['method'] = props['method'][0:MAXLEN]+'...'

        self.child.event(t, props)

server_exception_filter = 'ladder spy|suitable|VISIT_LADD|revenge batt|attack START|attack END|prevented banned|failed to fetch|fixing invalid obj_id|daily tip|excused'

class ServerExceptionLogFilter(Log):
    my_re = re.compile(server_exception_filter)
    def __init__(self, child):
        Log.__init__(self)
        self.child = child
    def event(self, t, text):
        if self.my_re.search(text): return
        self.child.event(t, text)

proxyserver_exception_filter = 'ignoreme'

class ProxyserverExceptionLogFilter(Log):
    my_re = re.compile(proxyserver_exception_filter)
    def __init__(self, child):
        Log.__init__(self)
        self.child = child
    def event(self, t, text):
        if self.my_re.search(text): return
        self.child.event(t, text)

# TEST CODE

if __name__ == '__main__':
    test = DailyJSONLog('/tmp/', '-spinlogtest.json')
    test.event(int(time.time()), {'foo':'bar', 'bap':'baz'})
    test.event(int(time.time())+2, {'foo':'bar2'})
    test.event(int(time.time())+3, {'user_id':1234})
    test.event(int(time.time())+3, {'user_id':1234,'event_name':'foo'})
    test.event(int(time.time())+3, {'user_id':1234,'event_name':'foo','code':432})
    test.event(int(time.time())+3, {'event_name':'foo','code':432})
    test.event(int(time.time())+3, {'event_name':'a'})
    #test.event(int(time.time())+24*60*60, {'foo':'bar3'})

    test2 = DailyRawLog('/tmp/', '-spinrawtest.txt')
    test2.event(int(time.time()), 'asdfdas')
    test3 = SimpleJSONLog('/tmp/spinfoo.json')
    test3.event(int(time.time())+4, {'user_id': 4321, 'event_name': 'bar', 'code': 333, 'prop':'foo'})
