# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# utilities for gameserver for handling player notification state

# state is all in player.history
# notification2:xxx:last_time -  UNIX timestamp of last transmission
# notification2:xxx:sent      -  number of notifications sent
# notification2:xxx:clicked   -  number of notifications responded to
# notification2:xxx:unacked   -  number of notifications sent that player hasn't responded to yet

import time

# different notification settings for different "classes" of users
USER_NEW = 'n' # townhall < 2
USER_ENGAGED = 'm' # townhall 2
USER_HARDCORE = 'e' # townhall >= 3

# policy: according to Facebook best practices
max_per_day = { USER_NEW: 1,
                USER_ENGAGED: 3,
                USER_HARDCORE: 5 }

STREAM_RETENTION = 'RETENTION'
STREAM_PROGRESSION = 'PROGRESSION'
STREAM_URGENT = 'URGENT' # got attacked etc - send once per logout
STREAM_ALWAYS = 'ALWAYS' # always send, even repeatedly per logout

# when no timezone is known, assume center-of-gravity in mid US
DEFAULT_TIMEZONE = -5

# XXXXXX move this into fb_notifications.json
def ref_to_stream(ref):
    return {None: STREAM_URGENT,
            'you_got_attacked': STREAM_URGENT,
            'incoming_raid': STREAM_URGENT,
            'raid_complete': STREAM_URGENT,

            'you_sent_gift_order': STREAM_ALWAYS,
            'you_got_gift_order': STREAM_ALWAYS,
            'your_gift_order_was_received': STREAM_ALWAYS,
            'alliance_promoted': STREAM_ALWAYS,
            'alliance_demoted': STREAM_ALWAYS,
            'bh_invite_accepted_sender': STREAM_ALWAYS,
            'bh_invite_accepted_target': STREAM_ALWAYS,
            'bh_invite_completed_sender': STREAM_ALWAYS,
            'bh_invite_completed_target': STREAM_ALWAYS,
            'bh_invite_daily_gift': STREAM_URGENT,

            '168h': STREAM_RETENTION,
            'retain_168h': STREAM_RETENTION,
            'retain_167h': STREAM_RETENTION,
            '24h': STREAM_RETENTION,
            'retain_47h': STREAM_RETENTION,
            'retain_23h': STREAM_RETENTION,

            'login_incentive_expiring': STREAM_URGENT, # ???
            'fishing_complete': STREAM_PROGRESSION, # ???

            }.get(ref, STREAM_PROGRESSION)

def get_user_class(history, townhall_name):
    townhall_level = history.get('%s_level' % townhall_name,1)
    if townhall_level < 2:
        return USER_NEW
    elif townhall_level == 2:
        return USER_ENGAGED
    else:
        return USER_HARDCORE

def local_date(local_time_now):
    local_st = time.gmtime(local_time_now)
    return '%04d%02d%02d' % (local_st.tm_year, local_st.tm_mon, local_st.tm_mday)

def can_send(time_now, timezone, stream, ref, history, cooldowns, user_class):
    if 'sessions' not in history: return False, 'no sessions data'
    last_logout_time = history['sessions'][-1][1]
    local_time_now = time_now + timezone * 3600

    if user_class is USER_NEW and stream not in (STREAM_RETENTION, STREAM_ALWAYS):
        return False, 'cannot send notification streams other than RETENTION and ALWAYS to TH<2 users'

    # not sure about this restriction
#    if user_class is USER_ENGAGED and stream is STREAM_PROGRESSION:
#        return False, 'cannot send progression stream until TH 3+'

    # don't send notifications within 1 hour of playing, except urgent ones
    if stream not in (STREAM_URGENT, STREAM_ALWAYS):
        if last_logout_time <= 0:
            return False, 'player is logged in'
        if last_logout_time >= time_now - 3600:
            return False, 'player was logged in less than 1 hour ago'

    # retention messages
    if stream is STREAM_RETENTION:
        # don't send if any notification on any stream was sent in the last 8 hours
        if history.get('notification2:GLOBAL:last_time',-1) >= time_now - 8*3600:
            return False, 'another notification was sent less than 8 hours ago'

        # don't send between midnight to 7am local time
        if time.gmtime(local_time_now).tm_hour < 7:
            return False, 'no retention notifications midnight-7am'

        if user_class is not USER_HARDCORE and last_logout_time < time_now - 5*86400:
            return False, 'non-hardcore users should not get retention notifications after more than 2 days of inactivity'

    # non-retention messages
    else:

        if stream is not STREAM_ALWAYS:
            # don't send more than once per stream since logout (except ALWAYS)
            if history.get('notification2:%s:last_time' % stream,-1) >= last_logout_time:
                return False, 'a notification on this stream was already sent since last logout'

            # check against daily limit
            cdname = 'notification2_%s' % local_date(local_time_now)
            if cdname in cooldowns:
                stack = cooldowns[cdname].get('stack', 1)
                if stack >= max_per_day[user_class]:
                    return False, 'max %d notification(s) per day for user class %s' % \
                           (max_per_day[user_class], user_class)

        # auto-mute - check for too many unacked notifications with this ref
        if ref:
            max_unacked = {STREAM_URGENT: 5, STREAM_ALWAYS: 5}.get(stream, 3)
            if history.get('notification2:%s:unacked' % ref, 0) >= max_unacked:
                return False, 'player has ignored too many notifications with ref "%s" (auto-muted)' % ref

    return True, None

def _record_send_history(time_now, param, history):
    if param is None: return
    history['notification2:%s:last_time' % param] = time_now
    for key in ('notification2:%s:unacked' % param,
                'notification2:%s:sent' % param):
        history[key] = history.get(key,0) + 1

def record_send(time_now, timezone, stream, ref, history, cooldowns):
    # track global number of notifications sent by (local) day
    local_time_now = time_now + timezone * 3600
    cdname = 'notification2_%s' % local_date(local_time_now)

    if cdname in cooldowns:
        cooldowns[cdname]['stack'] = cooldowns[cdname].get('stack',1) + 1
    else:
        cooldowns[cdname] = {'start': time_now,
                             # end of local day
                             'end': time_now + 86400 - (local_time_now % 86400)}

    for s in (stream, ref, 'GLOBAL'):
        _record_send_history(time_now, s, history)

def _record_ack_history(time_now, param, history):
    if param is None: return
    key = 'notification2:%s:unacked' % param
    if key in history:
        del history[key]
    key = 'notification2:%s:clicked' % param
    history[key] = history.get(key,0) + 1

def ack(time_now, stream, ref, history):
    for s in (stream, ref, 'GLOBAL'):
        _record_ack_history(time_now, s, history)

