#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# SpinUpcache.py
# library for creating upcache from userdb/playerdb and manipulating upcache entries
# does NOT have anything to do with live production data storage
# this is just for analytics

import csv
import sys, time, string, traceback, getopt
import bisect
import SpinConfig
import SpinJSON
import SpinS3
import LootTable

# return index number of segment to which this user_id belongs
def get_segment_for_user(user_id, num_segments):
    return (user_id % num_segments)

def segment_name(seg, num_segments):
    if num_segments == 1: return ''
    return '-seg%dof%d' % (seg, num_segments-1)

# recipt dollar amount that makes you a whale
WHALE_LINE = 7.0

# retention/spend/visit breakpoints, in days
DAY_MARKS = [0,1,2,3,5,7,14,21,30,45,60,90,120]
RETENTION_FIELDS = ["retained_%dd" % days for days in DAY_MARKS]
SPEND_FIELDS = ["spend_%dd" % days for days in DAY_MARKS]
VISITS_FIELDS = ["visits_%dd" % days for days in DAY_MARKS]

CLIENT_FIELDS = ["client:"+x for x in ["purchase_ui_opens","purchase_ui_opens_preftd"]]
FEATURE_USE_FIELDS = ["feature_used:"+x for x in ["drag_select",
                                                  "scrolling",
                                                  "double_click_select",
                                                  "shift_select",
                                                  "battle_history",
                                                  "battle_log",
                                                  "leaderboard",
                                                  "keyboard_shortcuts_list",
                                                  "fullscreen_dialog",
                                                  "truefullscreen",
                                                  "truefullscreen_during_tutorial",
                                                  "unit_attack_command",
                                                  "unit_patrol_command",
                                                  "settings_dialog",
                                                  "skip_tutorial",
                                                  "resume_tutorial",
                                                  "playfield_zoom",
                                                  "playfield_speed",
                                                  "own_achievements",
                                                  "other_achievements",
                                                  "own_statistics",
                                                  "other_statistics",
                                                  "region_map_scrolled",
                                                  "region_map_scroll_help",
                                                  "region_map_scroll_help_closed",
                                                  "hive_finder_seen", "hive_finder_used",
                                                  "quarry_finder_seen", "quarry_finder_used",
                                                  "strongpoint_finder_seen", "strongpoint_finder_used",
                                                  "attacker_finder_seen", "attacker_finder_used",
                                                  ]]

def get_all_abtests(gamedata):
    return gamedata['abtests'].keys()
def get_active_abtests(gamedata):
    return [k for k, v in gamedata['abtests'].iteritems() if v['active']]
def get_browser_cap_fields(gamedata):
    return ['browser_supports_'+cap for cap in gamedata['browser_caps']]
def get_quest_fields(gamedata):
    ret = ['quest:'+q['name']+':completed' for q in gamedata['quests'].itervalues()]
    # oops, removed this quest from quests.json - Probably not a good idea.
    ret += ['quest:unlock_repair_droid:completed']
    return ret

def get_unit_fields(gamedata):
    return sum([ ['unit:'+name+':'+field for name in gamedata['units'].iterkeys()] \
                 for field in ('manufactured', 'killed', 'lost') ], [])

def get_item_fields(gamedata):
    return ['item:'+str(name)+':'+field for name in gamedata['items'].iterkeys() for field in ('activated','purchased','crafted','trashed')]

def get_viral_fields(gamedata):
    return ['client:virals_sent'] + ['client:viral:'+name+':sent' for name, val in gamedata['virals'].iteritems() if (type(val) is dict and 'image' in val)]

def get_fb_notification_fields(gamedata):
    return ['fb_notifications_sent'] + ['fb_notification:'+spec['ref']+':'+action for spec in gamedata['fb_notifications']['notifications'].itervalues() for action in ('sent','clicked')]

def get_lab_names(gamedata):
    return [name for name, data in gamedata['buildings'].iteritems() if ('research_categories' in data)]

def get_building_names(gamedata):
    return gamedata['buildings'].keys()

def get_tech_names(gamedata):
    return gamedata['tech'].keys()

def is_shooter(spec):
    for spellname in spec.get('spells',[]):
        if 'SHOOT' in spellname: return True
    return False
def get_turret_names(gamedata):
    return [name for name, data in gamedata['buildings'].iteritems() if is_shooter(data)]


# return list of all fields that should go in userdb CSV output
def get_csv_fields(gamedata):
    ALL_ABTESTS = get_all_abtests(gamedata)
    BROWSER_CAP_FIELDS = get_browser_cap_fields(gamedata)
    FIELDS = ["user_id", "account_creation_time", "acquisition_campaign", "acquisition_secondary", "acquisition_type", "acquisition_game_version", "age_group",

          "acquisition_ad_image", "acquisition_ad_title", "acquisition_ad_text", "acquisition_ad_target", "acquisition_ad_skynet", "skynet_retargets",
          "adotomi_context", "dauup_context",
          "last_login_time", "logged_in_times", "last_purchase_time",
          "facebook_id", "country", "country_tier", "currency", "facebook_permissions_str",
          "gender", "locale", "birth_year", "birthday", "facebook_name", "email", "link",
          "tutorial_state", "player_level", "gamebucks_cur_balance", "completed_quests", "lock_state",
          'payer_promo_offered', 'promo_gamebucks_earned', 'payer_promo_gamebucks_earned', 'fb_gift_cards_redeemed',
          "money_spent", "money_refunded", "gamebucks_refunded", "largest_purchase", "time_in_game"] + \
          [resname for resname in gamedata['resources']] + \
          ["harvested_"+resname+"_total" for resname in gamedata['resources']] + \
          [name+'_level' for name in get_building_names(gamedata)] + \
          + ["attacks_launched", "attacks_victory", "attacks_launched_vs_ai", "attacks_launched_vs_ai:1007",
          "attacks_suffered", "ai_attacks_suffered", "daily_attacks_suffered", "revenge_attacks_suffered",
          "random_items_purchased", "items_purchased", "free_random_items",
          "gift_orders_sent", "gift_orders_received", "gamebucks_received_from_gift_orders",
          "gift_orders_refunded", "gift_orders_received_then_refunded", "gamebucks_refunded_from_received_gift_orders",
          "items_activated", "items_looted", "inventory_slots_total", "inventory_slots_used",
          "home_region", "quarries_conquered", "hives_destroyed", "hive_kill_points", "hitlist_victories",
          "attacks_launched_vs_human", "revenge_attacks_launched_vs_human",

          "alliances_joined", "units_donated", "donated_units_received", "alliance_gift_items_sent",
          "thunder_dome_entered",
          "iron_deposits_collected",
          "chat_messages_sent",

          "ai_sirenum_progress", "ai_erebus_progress", "ai_erebus4_progress", "ai_vostok_progress", "ai_vostok2_progress", "ai_hellas_progress", "ai_medusa_progress", "ai_medusa2_progress", "ai_kirat_progress", "ai_kirat2_progress", "ai_phantom_progress", "ai_phantom2_progress", "ai_radiation_progress", "ai_ice_progress", "ai_arsenal_progress", "ai_blaster_attack_progress",
          "ai_nu_blizzard_progress", "ai_learning_storm_progress", "ai_gala_narcs_progress",

          "ai_dark_moon_progress", "ai_dark_moon_heroic_progress", "ai_dark_moon_epic_progress",
          "ai_dark_moon_heroic_speedrun",
          "ai_dark_moon_times_started", "ai_dark_moon_heroic_times_started", "ai_dark_moon_epic_times_started",
          "ai_dark_moon_times_completed", "ai_dark_moon_heroic_times_completed", "ai_dark_moon_epic_times_completed",

          "ai_abyss_progress", "ai_abyss_heroic_progress", "ai_abyss_epic_progress",
          "ai_abyss_heroic_speedrun",
          "ai_abyss_times_started", "ai_abyss_heroic_times_started", "ai_abyss_epic_times_started",
          "ai_abyss_times_completed", "ai_abyss_heroic_times_completed", "ai_abyss_epic_times_completed",

          "ai_gale_progress", "ai_gale_heroic_progress", "ai_gale_epic_progress",
          "ai_gale_heroic_speedrun",
          "ai_gale_times_started", "ai_gale_heroic_times_started", "ai_gale_epic_times_started",
          "ai_gale_times_completed", "ai_gale_heroic_times_completed", "ai_gale_epic_times_completed",

          "T158_resurrect_test_exposed",

          "ai_wasteland_progress", "ai_wasteland_heroic_progress", "ai_wasteland_epic_progress",
          "ai_wasteland_heroic_speedrun",
          "ai_wasteland_times_started", "ai_wasteland_heroic_times_started", "ai_wasteland_epic_times_started",
          "ai_wasteland_times_completed", "ai_wasteland_heroic_times_completed", "ai_wasteland_epic_times_completed",

          "ai_phantom_attack_progress", "ai_phantom_attack_heroic_progress", "ai_phantom_attack_epic_progress",
          "ai_phantom_attack_heroic_speedrun",
          "ai_phantom_attack_times_started", "ai_phantom_attack_heroic_times_started", "ai_phantom_attack_epic_times_started",
          "ai_phantom_attack_times_completed", "ai_phantom_attack_heroic_times_completed", "ai_phantom_attack_epic_times_completed",

          "ai_horde_progress", "ai_horde_heroic_progress", "ai_horde_epic_progress",
          "ai_horde_heroic_speedrun",
          "ai_horde_times_started", "ai_horde_heroic_times_started", "ai_horde_epic_times_started",
          "ai_horde_times_completed", "ai_horde_heroic_times_completed", "ai_horde_epic_times_completed",

          "ai_zero_progress", "ai_zero_heroic_progress", "ai_zero_epic_progress",
          "ai_zero_heroic_speedrun",
          "ai_zero_times_started", "ai_zero_heroic_times_started", "ai_zero_epic_times_started",
          "ai_zero_times_completed", "ai_zero_heroic_times_completed", "ai_zero_epic_times_completed",

          "ai_meltdown_progress", "ai_meltdown_heroic_progress", "ai_meltdown_epic_progress",
          "ai_meltdown_heroic_speedrun",
          "ai_meltdown_times_started", "ai_meltdown_heroic_times_started", "ai_meltdown_epic_times_started",
          "ai_meltdown_times_completed", "ai_meltdown_heroic_times_completed", "ai_meltdown_epic_times_completed",

          "ai_crash_conquests", "ai_crash_progress",
          "ai_crash_heroic_L2_conquests", "ai_crash_heroic_L3_conquests", "ai_crash_heroic_L5_conquests",
          "ai_crash_heroic_L7_conquests", "ai_crash_heroic_L8_conquests",
          "ai_crash_epic_L2_conquests", "ai_crash_epic_L3_conquests", "ai_crash_epic_L5_conquests",
          "ai_crash_epic_L7_conquests", "ai_crash_epic_L8_conquests",
          "ai_crash_533_conquests", "ai_crash_534_conquests", "ai_crash_535_conquests", "ai_crash_536_conquests", "ai_crash_537_conquests",
          "ai_crash_538_conquests", "ai_crash_539_conquests", "ai_crash_540_conquests", "ai_crash_541_conquests", "ai_crash_542_conquests",
          "ai_crash_543_conquests", "ai_crash_544_conquests", "ai_crash_545_conquests", "ai_crash_546_conquests", "ai_crash_547_conquests",
          "ai_crash_548_conquests",

          "ai_prisoner_progress",
          "ai_prisoner_conquests",
          "ai_prisoner_low_conquests",
          "ai_prisoner_549_conquests","ai_prisoner_550_conquests","ai_prisoner_551_conquests","ai_prisoner_552_conquests",
          "ai_prisoner_553_conquests","ai_prisoner_554_conquests","ai_prisoner_555_conquests","ai_prisoner_556_conquests",
          "ai_prisoner_557_conquests","ai_prisoner_558_conquests",

          "ai_kingpin_progress",
          "ai_kingpin_conquests",
          "ai_kingpin_low_conquests",
          "ai_kingpin_394_conquests","ai_kingpin_395_conquests","ai_kingpin_396_conquests","ai_kingpin_397_conquests",
          "ai_kingpin_398_conquests","ai_kingpin_399_conquests","ai_kingpin_400_conquests","ai_kingpin_401_conquests",

          "ai_mutiny_progress",
          "ai_mutiny_conquests",
          "ai_mutiny_low_conquests",
          "ai_mutiny_692_conquests","ai_mutiny_693_conquests","ai_mutiny_694_conquests","ai_mutiny_695_conquests",
          "ai_mutiny_696_conquests","ai_mutiny_697_conquests","ai_mutiny_698_conquests","ai_mutiny_699_conquests",

          "ai_chunk_progress",
          "ai_chunk_conquests",
          "ai_chunk_low_conquests",
          "ai_chunk_584_conquests","ai_chunk_585_conquests","ai_chunk_586_conquests","ai_chunk_587_conquests",
          "ai_chunk_588_conquests","ai_chunk_589_conquests","ai_chunk_590_conquests","ai_chunk_591_conquests",

                             "ai_ladder_conquests",
                             "ai_ladder_conquests_342", "ai_ladder_conquests_343", "ai_ladder_conquests_344", "ai_ladder_conquests_345",
                             "ai_ladder_conquests_346", "ai_ladder_conquests_347", "ai_ladder_conquests_348", "ai_ladder_conquests_349",
                             "ai_ladder_conquests_350", "ai_ladder_conquests_351", "ai_ladder_conquests_352", "ai_ladder_conquests_353",
                             "ai_ladder_conquests_354", "ai_ladder_conquests_355", "ai_ladder_conquests_356", "ai_ladder_conquests_357",
                             "ai_ladder_conquests_358", "ai_ladder_conquests_359", "ai_ladder_conquests_360",
                             "ai_ladder_conquests_albor", "ai_ladder_conquests_arabia", "ai_ladder_conquests_kalamity", "ai_ladder_conquests_kirat",
                             "ai_ladder_conquests_phobos", "ai_ladder_conquests_prisoner", "ai_ladder_conquests_subareion", "ai_ladder_conquests_tharsis",
                             "ai_ladder_conquests_vell",

             # TR events
             "ai_mrskilling_progress", "ai_redpole_progress", "ai_redpole1_conquests",
             "ai_ambush_progress","ai_ambush_times_started","ai_ambush_times_completed","ai_ambush_conquests",
             "ai_ambush2_progress","ai_ambush2_times_started","ai_ambush2_times_completed","ai_ambush2_conquests",
             "ai_ambush3_attempted","ai_ambush3_progress","ai_ambush3_times_started","ai_ambush2_times_completed","ai_ambush3_conquests",
             "ai_ambush4_attempted","ai_ambush4_progress","ai_ambush4_times_started","ai_ambush4_times_completed","ai_ambush4_conquests",
             "ai_ambush5_attempted","ai_ambush5_progress","ai_ambush5_times_started","ai_ambush5_times_completed","ai_ambush5_conquests",
             "ai_hamilton_progress", "ai_hamilton_times_started", "ai_hamilton_times_completed",
             "ai_hamilton2_progress", "ai_hamilton2_times_started", "ai_hamilton2_times_completed",
             "ai_hamilton3_progress", "ai_hamilton3_times_started", "ai_hamilton3_times_completed",
             "ai_hamilton4_attempted", "ai_hamilton4_progress", "ai_hamilton4_times_started", "ai_hamilton4_times_completed",
             "ai_hamilton5_attempted", "ai_hamilton5_progress", "ai_hamilton5_times_started", "ai_hamilton5_times_completed",
             "ai_hamilton6_attempted", "ai_hamilton6_progress", "ai_hamilton6_times_started", "ai_hamilton6_times_completed",
             "ai_pirate_progress","ai_pirate_times_started","ai_pirate_times_completed",
             "ai_pirate2_progress","ai_pirate2_times_started","ai_pirate2_times_completed",
             "ai_pirate3_progress","ai_pirate3_times_started","ai_pirate3_times_completed",
             "ai_pirate4_attempted","ai_pirate4_progress","ai_pirate4_times_started","ai_pirate4_times_completed",
             "ai_pirate5_attempted","ai_pirate5_progress","ai_pirate5_times_started","ai_pirate5_times_completed",
             "ai_pirate6_attempted","ai_pirate6_progress","ai_pirate6_times_started","ai_pirate6_times_completed",
             "ai_pirate7_attempted","ai_pirate7_progress","ai_pirate7_times_started","ai_pirate7_times_completed",
             "ai_xerxes_progress","ai_xerxes_times_started","ai_xerxes_times_completed",
             "ai_xerxes2_progress","ai_xerxes2_times_started","ai_xerxes2_times_completed",
             "ai_xerxes3_progress","ai_xerxes3_times_started","ai_xerxes3_times_completed",
             "ai_xerxes4_attempted","ai_xerxes4_progress","ai_xerxes4_times_started","ai_xerxes4_times_completed",
             "ai_xerxes5_attempted","ai_xerxes5_progress","ai_xerxes5_times_started","ai_xerxes5_times_completed",
             "ai_xerxes6_attempted","ai_xerxes6_progress","ai_xerxes6_times_started","ai_xerxes6_times_completed",
             "ai_giancarlo_progress","ai_giancarlo_times_started","ai_giancarlo_times_completed",
             "ai_giancarlo2_progress","ai_giancarlo2_times_started","ai_giancarlo2_times_completed",
             "ai_giancarlo3_progress","ai_giancarlo3_times_started","ai_giancarlo3_times_completed",
             "ai_giancarlo4_attempted","ai_giancarlo4_progress","ai_giancarlo4_times_started","ai_giancarlo4_times_completed",
             "ai_giancarlo5_attempted","ai_giancarlo5_progress","ai_giancarlo5_times_started","ai_giancarlo5_times_completed",
             "ai_giancarlo6_attempted","ai_giancarlo6_progress","ai_giancarlo6_times_started","ai_giancarlo6_times_completed",
             "ai_giancarlo7_attempted","ai_giancarlo7_progress","ai_giancarlo7_times_started","ai_giancarlo7_times_completed",
             "ai_maximilien_progress","ai_maximilien_times_started","ai_maximilien_times_completed",
             "ai_maximilien2_attempted","ai_maximilien2_progress","ai_maximilien2_times_started","ai_maximilien2_times_completed",
             "ai_maximilien3_attempted","ai_maximilien3_progress","ai_maximilien3_times_started","ai_maximilien3_times_completed",
             "ai_maximilien4_attempted","ai_maximilien4_progress","ai_maximilien4_times_started","ai_maximilien4_times_completed",
             "ai_maximilien5_attempted","ai_maximilien5_progress","ai_maximilien5_times_started","ai_maximilien5_times_completed",
             "ai_kim_progress","ai_kim_times_started","ai_kim_times_completed",
             "ai_kim2_progress","ai_kim2_times_started","ai_kim2_times_completed",
             "ai_kim3_attempted", "ai_kim3_progress","ai_kim3_times_started","ai_kim3_times_completed",
             "ai_kim4_attempted", "ai_kim4_progress","ai_kim4_times_started","ai_kim4_times_completed",
             "ai_kim5_attempted", "ai_kim5_progress","ai_kim5_times_started","ai_kim5_times_completed",
             "ai_kim6_attempted", "ai_kim6_progress","ai_kim6_times_started","ai_kim6_times_completed",
             "ai_segvec_progress","ai_segvec_times_started","ai_segvec_times_completed",
             "ai_segvec2_progress","ai_segvec2_times_started","ai_segvec2_times_completed",
             "ai_segvec3_attempted","ai_segvec3_progress","ai_segvec3_times_started","ai_segvec3_times_completed",
             "ai_segvec4_attempted","ai_segvec4_progress","ai_segvec4_times_started","ai_segvec4_times_completed",
             "ai_segvec5_attempted","ai_segvec5_progress","ai_segvec5_times_started","ai_segvec5_times_completed",
             "ai_segvec6_attempted","ai_segvec6_progress","ai_segvec6_times_started","ai_segvec6_times_completed",
             "ai_cyclops_progress","ai_cyclops_times_started","ai_cyclops_times_completed","ai_cyclops_conquests",
             "ai_cyclops2_attempted","ai_cyclops2_progress","ai_cyclops2_times_started","ai_cyclops2_times_completed","ai_cyclops2_conquests",
             "ai_cyclops3_attempted","ai_cyclops3_progress","ai_cyclops3_times_started","ai_cyclops3_times_completed","ai_cyclops3_conquests",
             "ai_cyclops4_attempted","ai_cyclops4_progress","ai_cyclops4_times_started","ai_cyclops4_times_completed","ai_cyclops4_conquests",
             "ai_cyclops5_attempted","ai_cyclops5_progress","ai_cyclops5_times_started","ai_cyclops5_times_completed","ai_cyclops5_conquests",
             "ai_queen_progress","ai_queen_times_started","ai_queen_times_completed","ai_queen_conquests",
             "ai_queen2_attempted", "ai_queen2_progress","ai_queen2_times_started","ai_queen2_times_completed","ai_queen2_conquests",
             "ai_queen3_attempted", "ai_queen3_progress","ai_queen3_times_started","ai_queen3_times_completed","ai_queen3_conquests",
             "ai_queen4_attempted", "ai_queen4_progress","ai_queen4_times_started","ai_queen4_times_completed","ai_queen4_conquests",
             "ai_warlord1_progress","ai_warlord1_times_started","ai_warlord1_times_completed","ai_warlord1_conquests",
             "ai_warlord2_attempted","ai_warlord2_progress","ai_warlord2_times_started","ai_warlord2_times_completed","ai_warlord2_conquests",
             "ai_warlord3_attempted","ai_warlord3_progress","ai_warlord3_times_started","ai_warlord3_times_completed","ai_warlord3_conquests",
             "ai_warlord4_attempted","ai_warlord4_progress","ai_warlord4_times_started","ai_warlord4_times_completed","ai_warlord4_conquests",
             "ai_fugitive1_attempted", "ai_fugitive1_progress","ai_fugitive1_times_started","ai_fugitive1_times_completed","ai_fugitive1_conquests",
             "ai_fugitive2_attempted", "ai_fugitive2_progress","ai_fugitive2_times_started","ai_fugitive2_times_completed","ai_fugitive2_conquests",
             "ai_fugitive3_attempted", "ai_fugitive3_progress","ai_fugitive3_times_started","ai_fugitive3_times_completed","ai_fugitive3_conquests",
             "ai_fugitive4_attempted", "ai_fugitive4_progress","ai_fugitive4_times_started","ai_fugitive4_times_completed","ai_fugitive4_conquests",
             "ai_piper_progress","ai_piper_times_started","ai_piper_times_completed","ai_piper_conquests",
             "ai_piper1_progress","ai_piper1_times_started","ai_piper1_times_completed","ai_piper1_conquests",
             "ai_piper2_attempted","ai_piper2_progress","ai_piper2_times_started","ai_piper2_times_completed","ai_piper2_conquests",
             "ai_piper3_attempted","ai_piper3_progress","ai_piper3_times_started","ai_piper3_times_completed","ai_piper3_conquests",
             "ai_piper4_attempted","ai_piper4_progress","ai_piper4_times_started","ai_piper4_times_completed","ai_piper4_conquests",
             "ai_rogue_attempted","ai_rogue_progress","ai_rogue_times_started","ai_rogue_times_completed","ai_rogue_conquests",
             "ai_rogue1_attempted","ai_rogue1_progress","ai_rogue1_times_started","ai_rogue1_times_completed","ai_rogue1_conquests",
             "ai_rogue2_attempted","ai_rogue2_progress","ai_rogue2_times_started","ai_rogue2_times_completed","ai_rogue2_conquests",
             "ai_rogue3_attempted","ai_rogue3_progress","ai_rogue3_times_started","ai_rogue3_times_completed","ai_rogue3_conquests",
             "ai_rogue4_attempted","ai_rogue4_progress","ai_rogue4_times_started","ai_rogue4_times_completed","ai_rogue4_conquests",
             "ai_murderous_attempted","ai_murderous_progress","ai_murderous_times_started","ai_murderous_times_completed","ai_murderous_conquests",
             "ai_murderous1_attempted","ai_murderous1_progress","ai_murderous1_times_started","ai_murderous1_times_completed","ai_murderous1_conquests",
             "ai_murderous2_attempted","ai_murderous2_progress","ai_murderous2_times_started","ai_murderous2_times_completed","ai_murderous2_conquests",
             "ai_murderous3_attempted","ai_murderous3_progress","ai_murderous3_times_started","ai_murderous3_times_completed","ai_murderous3_conquests",
             "ai_fanatic_attempted","ai_fanatic_progress","ai_fanatic_times_started","ai_fanatic_times_completed","ai_fanatic_conquests",
             "ai_fanatic1_attempted","ai_fanatic1_progress","ai_fanatic1_times_started","ai_fanatic1_times_completed","ai_fanatic1_conquests",
             "ai_fanatic2_attempted","ai_fanatic2_progress","ai_fanatic2_times_started","ai_fanatic2_times_completed","ai_fanatic2_conquests",
             "ai_berkman_conquests", "ai_berkman1_conquests", "ai_berkman2_conquests", "ai_berkman3_conquests",
             "ai_mandel_conquests", "ai_mandel1_conquests", "ai_mandel2_conquests", "ai_mandel3_conquests",
             "ai_gashi_conquests", "ai_gashi1_conquests", "ai_gashi2_conquests",
             "ai_nomad_attempted","ai_nomad_progress","ai_nomad_times_started","ai_nomad_times_completed","ai_nomad_conquests",
             "ai_nomad1_attempted","ai_nomad1_progress","ai_nomad1_times_started","ai_nomad1_times_completed","ai_nomad1_conquests",
             "ai_nomad2_attempted","ai_nomad2_progress","ai_nomad2_times_started","ai_nomad2_times_completed","ai_nomad2_conquests",

             # MF2
             "ai_tutorial02A_progress", "ai_tutorial02B_progress", "ai_tutorial08_progress", "ai_tutorial25_progress",
             "ai_guardian_progress","ai_guardian_times_started","ai_guardian_times_completed","ai_guardian_conquests",
             "ai_guardian1_progress","ai_guardian1_times_started","ai_guardian1_times_completed","ai_guardian1_conquests",
             "ai_guardian2_progress","ai_guardian2_times_started","ai_guardian2_times_completed","ai_guardian2_conquests",
             "ai_guardian3_progress","ai_guardian3_times_started","ai_guardian3_times_completed","ai_guardian3_conquests",
             "ai_harvest_progress","ai_harvest_times_started","ai_harvest_times_completed","ai_harvest_conquests",
             "ai_harvest1_progress","ai_harvest1_times_started","ai_harvest1_times_completed","ai_harvest1_conquests",
             "ai_harvest2_attempted","ai_harvest2_progress","ai_harvest2_times_started","ai_harvest2_times_completed","ai_harvest2_conquests",
             "ai_tonca_conquests","ai_tonca1_conquests","ai_tonca2_conquests","ai_tonca3_conquests",
             "ai_khronic_conquests","ai_khronic1_conquests","ai_khronic2_conquests","ai_khronic3_conquests","ai_khronic4_conquests",
             "ai_wilder_conquests","ai_wilder1_conquests","ai_wilder2_conquests","ai_wilder3_conquests","ai_wilder4_conquests",
             "ai_devil_progress","ai_devil_times_started","ai_devil_times_completed","ai_devil_conquests",
             "ai_devil1_progress","ai_devil1_times_started","ai_devil1_times_completed","ai_devil1_conquests",
             "ai_devil2_attempted","ai_devil2_progress","ai_devil2_times_started","ai_devil2_times_completed","ai_devil2_conquests",
             "ai_turncoat_progress","ai_turncoat_times_started","ai_turncoat_times_completed","ai_turncoat_conquests",
             "ai_turncoat1_attempted","ai_turncoat1_progress","ai_turncoat1_times_started","ai_turncoat1_times_completed","ai_turncoat1_conquests",
             "ai_turncoat2_attempted","ai_turncoat2_progress","ai_turncoat2_times_started","ai_turncoat2_times_completed","ai_turncoat2_conquests",
             "ai_collection_progress","ai_collection_times_started","ai_collection_times_completed","ai_collection_conquests",
             "ai_collection1_attempted","ai_collection1_progress","ai_collection1_times_started","ai_collection1_times_completed","ai_collection1_conquests",
             "ai_collection2_attempted","ai_collection2_progress","ai_collection2_times_started","ai_collection2_times_completed","ai_collection2_conquests",
             "ai_prophecy_progress","ai_prophecy_times_started","ai_prophecy_times_completed","ai_prophecy_conquests",
             "ai_prophecy1_attempted","ai_prophecy1_progress","ai_prophecy1_times_started","ai_prophecy1_times_completed","ai_prophecy1_conquests",
             "ai_prophecy2_attempted","ai_prophecy2_progress","ai_prophecy2_times_started","ai_prophecy2_times_completed","ai_prophecy2_conquests",
             "ai_extinction_progress","ai_extinction_times_started","ai_extinction_times_completed","ai_extinction_conquests",
             "ai_extinction1_attempted","ai_extinction1_progress","ai_extinction1_times_started","ai_extinction1_times_completed","ai_extinction1_conquests",
             "ai_defense_waa_progress","ai_defense_waa_times_started","ai_defense_waa_times_completed","ai_defense_waa_conquests",
             "ai_defense_waa1_attempted","ai_defense_waa1_progress","ai_defense_waa1_times_started","ai_defense_waa1_times_completed","ai_defense_waa1_conquests",
             "ai_defense_waa2_attempted","ai_defense_waa2_progress","ai_defense_waa2_times_started","ai_defense_waa2_times_completed","ai_defense_waa2_conquests",
             "ai_monstrous_progress","ai_monstrous_times_started","ai_monstrous_times_completed","ai_monstrous_conquests",
             "ai_monstrous1_attempted","ai_monstrous1_progress","ai_monstrous1_times_started","ai_monstrous1_times_completed","ai_monstrous1_conquests",
             "ai_defense_wab_progress","ai_defense_wab_times_started","ai_defense_wab_times_completed","ai_defense_wab_conquests",
             "ai_defense_wab1_attempted","ai_defense_wab1_progress","ai_defense_wab1_times_started","ai_defense_wab1_times_completed","ai_defense_wab1_conquests",
             "ai_devious_progress","ai_devious_times_started","ai_devious_times_completed","ai_devious_conquests",
             "ai_devious1_attempted","ai_devious1_progress","ai_devious1_times_started","ai_devious1_times_completed","ai_devious1_conquests",
             "ai_defense_wad_progress","ai_defense_wad_times_started","ai_defense_wad_times_completed","ai_defense_wad_conquests",
             "ai_defense_wad1_attempted","ai_defense_wad1_progress","ai_defense_wad1_times_started","ai_defense_wad1_times_completed","ai_defense_wad1_conquests",
             "ai_herald_progress","ai_herald_times_started","ai_herald_times_completed","ai_herald_conquests",
             "ai_herald1_attempted","ai_herald1_progress","ai_herald1_times_started","ai_herald1_times_completed","ai_herald1_conquests",
             "ai_defense_waf_progress","ai_defense_waf_times_started","ai_defense_waf_times_completed","ai_defense_waf_conquests",
             "ai_defense_waf1_attempted","ai_defense_waf1_progress","ai_defense_waf1_times_started","ai_defense_waf1_times_completed","ai_defense_waf1_conquests",
             "ai_ruckus_progress","ai_ruckus_times_started","ai_ruckus_times_completed","ai_ruckus_conquests",
             "ai_ruckus1_attempted","ai_ruckus1_progress","ai_ruckus1_times_started","ai_ruckus1_times_completed","ai_ruckus1_conquests",
             "ai_tyrant_progress","ai_tyrant_times_started","ai_tyrant_times_completed","ai_tyrant_conquests",
             "ai_tyrant1_attempted","ai_tyrant1_progress","ai_tyrant1_times_started","ai_tyrant1_times_completed","ai_tyrant1_conquests",
             "ai_skar_conquests","ai_skar1_conquests",
             # add new event player history keys here
             # YOU MUST ALSO ADD THEM BELOW AS WELL! SEARCH FOR "ai_ambush_progress"!

          "units_manufactured",
          'resources_looted_from_ai', 'resources_looted_from_human', 'resources_stolen_by_human',
          "fb_gamer_status", "fb_credit_balance", "days_since_joined", "days_since_last_login", "join_week",
          "is_paying_user", "is_whale", "time_of_first_purchase", "paid_within_24hrs",
          "completed_tutorial", "browser_name", "browser_version", "browser_os", "browser_hardware",
          "canvas_width", "canvas_height",
          "browser_supports_canvas", "browser_supports_webgl", "browser_supports_websocket",
          "browser_supports_audio_element", "browser_supports_audio_ogg",
          "browser_supports_audio_wav", "browser_supports_audio_mp3", "browser_supports_audio_aac", "browser_supports_audio_context",
          "friends_in_game", "initial_friends_in_game", "friends_at_least_10", ] + \
          ['likes_'+x for x in SpinConfig.FACEBOOK_GAME_FAN_PAGES.iterkeys()] + \
          ["account_creation_wday", "account_creation_hour", "acquired_on_weekend", "timezone", "chat_gagged", "history_version", "last_fb_notification_time",
          ] + RETENTION_FIELDS + SPEND_FIELDS + VISITS_FIELDS + BROWSER_CAP_FIELDS + FEATURE_USE_FIELDS + get_quest_fields(gamedata) + get_unit_fields(gamedata) + get_item_fields(gamedata) + get_viral_fields(gamedata) + get_fb_notification_fields(gamedata) + ALL_ABTESTS
    FIELDS += TimeSeriesCSVWriter.TIME_CURRENT_FIELDS
    return FIELDS

# fields that should be stripped out of userdb before inserting into upcache (because they are large and irrelevant to metrics)
# note that we do need to *read* the facebook_profile and facebook_likes to compute and store a few values before getting rid of them
HOG_FIELDS = ["last_login_ip", "fb_hit_time", "facebook_profile", "facebook_friends", "facebook_likes", "facebook_currency", "facebook_permissions", "acquisition_data", "preferences", "facebook_first_name", "facebook_friends_map", "browser_caps", "oauth_token", "fb_oauth_token", "kg_auth_token", "kg_friend_ids", "kg_avatar_url", "purchase_ui_log"]

# fields that should be stripped out of upcache before writing CSV
# in addition to these, any time-series field ending with "_at_time" is also stripped
CSV_IGNORE_FIELDS = ["money_spent_by_day", "logins_by_day", "upcache_time", "tech", "history", "sessions", "player_preferences", "skynet_retargets",
                     "money_purchase_history", "gamebucks_purchase_history", "purchase_ui_log"]

# rename A/B test groups for some early tests to be more readable
ABTEST_RENAME_HACK = {
    "T004_first_purchase_one_muffin": { "0": "control", "1": "discount" },
    "T001_harvester_cap": { "0": "control", "1": "doubled" },
    "T007_enable_gunship_motd": { "0": "control", "1": "no_gunship_message" }
    }

FACEBOOK_CAMPAIGN_MAP = {
    # Most of these UI elements only show up if you have already
    # installed the app. If your acquisition_campaign equals one of
    # these values, then it means we missed your original first
    # acquisition source. So, treat that as a missing value, rather
    # than incorrectly reporting the UI element as a "campaign".
    'ad': 'MISSING',
    'aggregation': 'MISSING',
    'bookmark': 'MISSING',
    'bookmark_apps': 'MISSING',
    'bookmark_favorites': 'MISSING',
    'bookmark_seeall': 'MISSING',
    'canvasbookmark': 'MISSING',
    'canvas_bookmark': 'MISSING',
    'canvasbookmarkapps': 'MISSING',
    'canvasbookmark_more': 'MISSING',
    'dashboard_bookmark': 'MISSING',
    'sidebar': 'MISSING',
    'sidebar_bookmark': 'MISSING',
    'dialog': 'MISSING',
    'dialog_permission': 'MISSING',
    'myapps': 'MISSING',
    'reminders': 'MISSING',

    # Facebook-sourced free acquisition
    'bookmark_favoritestry': 'facebook_free',
    'dashboard_toplist': 'facebook_free',
    'ego': 'facebook_free',
    'home': 'facebook_free',
    'hovercard': 'facebook_free',
    'other_multiline': 'facebook_free',
    'sidebar_recommended': 'facebook_free',
    'rightcolumn': 'facebook_free',

    # pull these out separately because they are their own huge sources of traffic
    'canvasbookmark_featured': 'facebook_free',
    'canvasbookmark_recommended': 'facebook_free',
    'canvas_recommended': 'facebook_free',
    'canvas_showcase': 'facebook_free',
    'canvas_featured': 'facebook_free',

    'appcenter': 'facebook_free',
    'appcenter_curated': 'facebook_free',
    'appcenter_related': 'facebook_free',
    'appcenter_featured': 'facebook_free',
    'appcenter_getting_started': 'facebook_free',
    'appcenter_search': 'facebook_free',
    'appcenter_search_typeahead': 'facebook_free',
    'appcenter_toplist': 'facebook_free',

    # game-sourced viral acquisition
    'achievement_brag': 'game_viral',
    'appcenter_request': 'game_viral',
    'facebook_app_request': 'game_viral',
    'facebook_friend_invite': 'game_viral',
    'facebook_message': 'game_viral',
    'fbpage': 'game_viral', # not sure on this one
    'fbpage_button': 'game_viral', # not sure on this one
    'fbpage_gameinfo': 'game_viral', # not sure on this one
    'feed': 'game_viral',
    'feed_achievement': 'game_viral',
    'feed_aggregated': 'game_viral',
    'feed_highscore': 'game_viral',
    'feed_leaderboard_brag': 'game_viral',
    'feed_level_up': 'game_viral',
    'feed_opengraph': 'game_viral',
    'feed_passing': 'game_viral',
    'feed_playing': 'game_viral',
    'feed_thanks': 'game_viral',
    'notification': 'game_viral',
    'request': 'game_viral',
    'reminders': 'game_viral', # this is a reminder *about* a request
    'search': 'game_viral',
    'timeline': 'game_viral',
    'timeline_collection': 'game_viral',
    'timeline_og': 'game_viral',
    'timeline_passing': 'game_viral',
    'timeline_playing': 'game_viral',
    'timeline_highscore': 'game_viral',
    }

# rename acquisition_campaigns values that come from clicks on various Facebook UI elements (?ref=YYY) to be more readable
# also implemented in SQL in analytics_views.sql - please keep in sync!
def remap_facebook_campaigns(x):
    if x.startswith('viral_') or x.startswith('open_graph_'): return 'game_viral'
    if x.endswith('/'): x = x[:-1]
    if '.com' in x: x = x[:x.index('.com')+len('.com')] # get rid of junk on the end of .com URL
    if x.startswith('canvasbookmark_feat'): x = 'canvasbookmark_featured' # some browsers added junk at the end
    return FACEBOOK_CAMPAIGN_MAP.get(x, x)


# purchase classifier
# works based on the "description" field from purchase_history and also the credits log

PURCHASE_CATEGORY_MAP = {'MAKE_DROIDS': 'manufacturing', # dummy entry for production speedups
                         'BUY_GAMEBUCKS': 'gamebucks', # dummy entry, parsed as a special case
                         'BUY_PROTECTION': 'protection', # dummy entry, parsed as a special case
                         'SPEEDUP_FOR_MONEY': 'speedup',
                         'RESEARCH_FOR_MONEY': 'research',
                         'UPGRADE_FOR_MONEY': 'building_upgrade',
                         'BOOST_IRON_10PCT': 'resource_boost', 'BOOST_IRON_25PCT': 'resource_boost', 'BOOST_IRON_50PCT': 'resource_boost', 'BOOST_IRON_100PCT': 'resource_boost',
                         'BOOST_WATER_10PCT': 'resource_boost', 'BOOST_WATER_25PCT': 'resource_boost', 'BOOST_WATER_50PCT': 'resource_boost', 'BOOST_WATER_100PCT': 'resource_boost',
                         'REPAIR_ALL_FOR_MONEY': 'repair',
                         'UNIT_REPAIR_SPEEDUP_FOR_MONEY': 'repair',
                         'UPGRADE_BARRIERS_LEVEL2': 'barriers', 'UPGRADE_BARRIERS_LEVEL3': 'barriers', 'UPGRADE_BARRIERS_LEVEL4': 'barriers',
                         'GROW_BASE_PERIMETER1': 'grow_base',
                         'CHANGE_REGION_INSTANTLY': 'change_region',
                         'BUY_LOTTERY_TICKET': 'lottery',
                         'FREE_RANDOM_ITEM': 'free_items',
                         'FREE_RANDOM_DAILY_ITEM': 'free_items',
                         'BUY_RANDOM_ITEM': 'random_items',
                         'BUY_RANDOM_MISSILE': 'random_items',
                         'BUY_RANDOM_EXTENDED_ITEM': 'random_items',
                         'BUY_RANDOM_MISSILE_ITEM': 'random_items',
                         'BUY_RANDOM_GIFT_ITEM': 'random_items',
                         'BUY_RANDOM_GIFT_ITEM_SALE': 'random_items',
                         'BUY_RANDOM_PREMIUM_ITEM': 'random_items',
                         'BUY_ITEM': 'specific_items',
                         'FB_PROMO_GAMEBUCKS': 'Facebook In-App Currency Promotions',
                         'FB_GAMEBUCKS_PAYMENT': 'Facebook In-App Currency Promotions'
                       }

def classify_purchase(gamedata, descr):
    fields = descr.split(',')
    level = None
    cat = fields[0]

    # determine major category
    if cat.startswith('BUY_GAMEBUCKS'):
        catname = 'gamebucks'
    elif cat.startswith('BUY_PROTECTION'):
        catname = 'protection'
    elif cat == 'SPEEDUP_FOR_MONEY':
        # recategorize under what it was speeding up
        action = fields[2]
        if action == 'upgrade':
            catname = 'building_upgrade'
            descr = 'UPGRADE_FOR_MONEY,%s,%s' % (fields[1], fields[3])
            fields = descr.split(',') # reparse
        elif action == 'construct':
            catname = 'building_upgrade'
            descr = 'UPGRADE_FOR_MONEY,%s,level1' % (fields[1])
            fields = descr.split(',') # reparse
        elif action == 'research':
            #   SPEEDUP_FOR_MONEY,drone_lab,research,avenger_production,level2
            # ->RESEARCH_FOR_MONEY,avenger_production,drone_lab,level2
            catname = 'research'
            descr = 'RESEARCH_FOR_MONEY,%s,%s' % (fields[3],fields[1])
            if len(fields) >= 5:
                descr += ',%s' % (fields[4])
            fields = descr.split(',') # reparse

        elif action == 'repair':
            catname = 'repair'
        elif action == 'manufacture':
            catname = 'manufacturing'
        elif action == 'craft':
            catname = 'crafting'
            #   SPEEDUP_FOR_MONEY,weapon_factory,craft,[u'craft,make_mine_anti_tracker_L2', u'craft,make_mine_anti_tracker_L2'],28.0min
            # ->['CRAFT_FOR_MONEY','weapon_factory', "[u'craft,make_mine_anti_tracker_L2', u'craft,make_mine_anti_tracker_L2']"]
            if fields[-1].endswith('min'):
                fields = ['CRAFT_FOR_MONEY', fields[1], ','.join(fields[3:-1])]
            else:
                assert fields[-1].endswith(']')
                fields = ['CRAFT_FOR_MONEY', fields[1], ','.join(fields[3:])]
    elif cat == 'BUY_ITEM':
        spellarg_str = descr[len("BUY_ITEM,"):]
        if ("':" in spellarg_str): # old Python repr()
            spellarg = eval(spellarg_str)
        else:
            spellarg = SpinJSON.loads(spellarg_str)
        skudata = spellarg['skudata']
        if 'expedition' in skudata['item']:
            catname = 'random_items'
        else:
            catname = PURCHASE_CATEGORY_MAP.get(cat, None) # 'specific_items'
    else:
        catname = PURCHASE_CATEGORY_MAP.get(cat, None)

    if catname is None:
        return 'UNCATEGORIZED:'+cat, descr, level

    # determine subcategory
    if catname == 'barriers':
        subcat = 'level_'+cat[-1]
        level = int(cat[-1])
    elif catname == 'gamebucks':
        subcat = cat
    elif catname == 'research':
        # reparse RESEARCH_FOR_MONEY,techname,labname,levelNN
        fields = descr.split(',')
        spec_name = fields[1]
        if len(fields) >= 4 and fields[3].startswith('level'):
            level = int(fields[3][5:]) # "levelNN"

        spec = gamedata['tech'][spec_name]
        if spec.has_key('associated_unit'):
            sn = spec['associated_unit'] # inconsistent - for legacy compatibility
        elif spec.has_key('affects_unit') or spec.has_key('affects_manufacture_category'):
            sn = 'all_mods'
        else:
            sn = spec_name
        #unit = string.join(fields[1].split('_')[:-1], '_')
        subcat = sn

    elif catname == 'building_upgrade':
        spec_name = fields[1]
        if fields[2].startswith('level'):
            level = int(fields[2][5:]) # "levelNN"
        if 0 and spec_name == gamedata['townhall']: # was inconsistent - for legacy compatibility
            subcat = ('%s_L%d' % (spec_name, level))
        else:
            subcat = spec_name

    elif catname == 'speedup':
        fields[1] = '%-18s' % fields[1]
        fields[2] = '%-12s' % fields[2]
        subcat = string.join(fields[1:-1], ' ')

    elif catname == 'repair':
        if cat == 'UNIT_REPAIR_SPEEDUP_FOR_MONEY':
            subcat = 'units_only'
            #subcat = fields[2]
        else:
            if len(fields) >= 4 and fields[1][0] == 'q':
                subcat = 'quarry'
            else:
                subcat = 'base_and_units'

    elif catname == 'crafting':
        # e.g.: fields[3:] = "[u'craft", "make_mine_anti_tank_L1']"
        subcat = eval(fields[2])[0].split(',')[1]

    elif catname == 'manufacturing':
        subcat = fields[3]

    elif catname == 'protection':
        subcat = catname
        level = gamedata['spells'][fields[0]]['duration']
    elif catname in ('free_items', 'random_items', 'specific_items'):
        subcat = descr.split(',')[0]

    elif catname == 'change_region':
        subcat = fields[0]

    elif catname == 'resource_boost':
        subcat = fields[0]

    else:
        subcat = string.join(descr.split(',')[1:],',')

    return catname, subcat, level

# given an upcache etnry, crawl through purchase history looking for
# the Nth purchase.
# If the purchase was buying alloys,
# then look for the following use of alloys and return that instead
def find_nth_purchase(user, n):

    if ('money_purchase_history' not in user) or len(user['money_purchase_history']) < n:
        return None # no purchases
    purchase = user['money_purchase_history'][n-1]
    descr = purchase['description']
    fields = descr.split(',')
    if (not fields[0].startswith('BUY_GAMEBUCKS')):
        # easy case - it was a direct FB Credits purchase
        return purchase

    # alloy purchase - need to locate the first use of alloys immediately following this purchase
    age = purchase['age']
    if ('gamebucks_purchase_history' not in user):
        return None
    for entry in user['gamebucks_purchase_history']:
        if entry['age'] >= age:
            return entry
    return None

def find_first_purchase(user): return find_nth_purchase(user, 1)

# utility function to parse player history time series to check for current building level as of a certain age
def building_level_at_age(user, specname, age):
    if specname+'_level_at_time' not in user: return 1
    upgrade_times = sorted([int(st) for st,v in user[specname+'_level_at_time'].iteritems()])
    where = bisect.bisect(upgrade_times, age) - 1
    if where < 0:
        return 1
    else:
        return user[specname+'_level_at_time'][str(upgrade_times[where])]
def receipts_at_age(user, age):
    if 'money_spent_at_time' not in user: return 0
    payment_times = sorted([[int(st), v] for st,v in user['money_spent_at_time'].iteritems()])
    cum = 0
    for entry in payment_times:
        this_payment = entry[1]
        entry[1] += cum
        cum += this_payment
    where = bisect.bisect([e[0] for e in payment_times], age) - 1
    if where < 0:
        return 0
    else:
        return payment_times[where][1]

# count number of visits and seconds of playtime within a certain day interval since account creation
def visits_and_playtime_within(user, days, after=-1):
    if ('sessions' not in user) or ('account_creation_time' not in user): return 0, 0
    creat = user['account_creation_time']
    sessions = user['sessions']
    visits = 0; playtime = 0
    for s in sessions:
        age = s[0] - creat
        if (age < days*24*60*60):
            if (age >= after*24*60*60):
                visits += 1
                if s[1] > 0:
                    playtime += s[1]-s[0]
        else:
            break
    return visits, playtime
def visits_within(user, days, after=-1): return visits_and_playtime_within(user, days, after=after)[0]
def playtime_within(user, days): return visits_and_playtime_within(user, days)[1]

def player_history_within(user, key, val, days, hours = 0):
    for sage, v in user.get(key+'_at_time', {}).iteritems():
        if v < val: continue
        age = int(sage)
        if days < 0 or (age < (days*24*60*60 + hours*60*60)):
            return True
    return False

# convert birthday (in "m/d/y" format) to number of years old at time "creat"
def birthday_to_years_old(birthday, creat):
    m, d, y = map(int, birthday.split('/'))
    birth_time = SpinConfig.cal_to_unix((y,m,d))
    return int((creat - birth_time)/(365*24*60*60)) # no leap years, yeah...

# utility functions to parse AI base JSON to see whether it always yields tokens as loot
def cons_has_tokens(gamedata, cons):
    if 'subconsequents' in cons:
        for entry in cons['subconsequents']:
            if cons_has_tokens(gamedata, entry):
                return True
    elif cons['consequent'] == 'GIVE_LOOT':
        loot = LootTable.get_loot(gamedata['loot_tables'], cons['loot'], cond_resolver = lambda x: True)
        for item in loot:
            if item['spec'].startswith('token'):
                return True
    return False
def ai_base_has_tokens(gamedata, base):
    if 'completion' not in base: return False
    return cons_has_tokens(gamedata, base['completion'])

# utility functions to parse AI base JSON to obtain start/end time and repeat interval

def pred_start_end_times(gamedata, pred): # return array of (start_time, end_time) if present in the predicate, else None
    if pred['predicate'] == 'OR':
        # return the union of all the times
        time_list = []
        for entry in pred['subpredicates']:
            sub_list = pred_start_end_times(gamedata, entry)
            if sub_list:
                time_list += sub_list
        return time_list
    elif 'subpredicates' in pred:
        for entry in pred['subpredicates']:
            temp = pred_start_end_times(gamedata, entry)
            if temp is not None:
                return temp
    elif pred['predicate'] == 'ABSOLUTE_TIME':
        return [[pred['range'][0], pred['range'][1]]]
    return None

def cons_cooldown(gamedata, cons): # return cooldown trigger interval if present in the consequent, else None
    if 'subconsequents' in cons:
        for entry in cons['subconsequents']:
            temp = cons_cooldown(gamedata, entry)
            if temp is not None: return temp
    elif cons['consequent'] == 'COOLDOWN_TRIGGER':
        return cons['period']
    return None

def ai_base_timings(gamedata, base): # return list of [start_time, end_time, repeat_interval] for this base
    start_end_times = None
    if 'activation' in base:
        start_end_times = pred_start_end_times(gamedata, base['activation'])
    if (start_end_times is None) and ('show_if' in base):
        start_end_times = pred_start_end_times(gamedata, base['show_if'])

    if start_end_times is None: # unrestricted
        start_end_times = [[-1,-1]]

    # append the repeat intervals to each start_end_times entry
    if 'completion' in base:
        repeat_interval = cons_cooldown(gamedata, base['completion'])
    else:
        repeat_interval = None

    for entry in start_end_times:
        entry.append(repeat_interval)

    return start_end_times

# utility function to parse AI hive JSON to obtain list of start/end times
def hive_timings(gamedata, template):
    start_end_times = []
    for entry in gamedata['hives']['spawn']:
        if entry['template'] == template:
            if not entry.get('active',True): continue
            if 'spawn_times' in entry:
                start_end_times += [[x[0],x[1]] for x in entry['spawn_times']]
            elif 'start_time' in entry:
                start_end_times.append([entry['start_time'], entry['end_time']])
            else:
                start_end_times.append([-1,-1]) # unrestricted
    return start_end_times

# utility functions to classify the type of an AI base, hive, or quarry for analytics purposes

def classify_ai_base(gamedata, ai_id):
    if str(ai_id) in gamedata['ai_bases']['bases']:
        base = gamedata['ai_bases']['bases'][str(ai_id)]

        # detect dummy hive owner bases
        if (base.get('kind',None) != 'ai_attack') and \
           ('buildings' in base) and \
           len(base['buildings']) == 1 and \
           ('activation' in base) and \
           base['activation']['predicate'] == 'ALWAYS_FALSE':
            return 'pve_dummy'

        if ai_base_has_tokens(gamedata, base):
            return 'pve_event_progression'
        elif base.get('ui_category', None) == 'hitlist':
            return 'hitlist'
        elif 'ui_instance_cooldown' in base:
            return 'pve_immortal_progression'
        else:
            return 'pve_tutorial_progression'
    return 'pve_unknown'

def classify_hive(gamedata, template):
    if (template in gamedata['hives_client']['templates']) and \
       gamedata['hives_client']['templates'][template].get('ui_tokens',None):
        return 'pve_event_hive'
    else:
        return 'pve_immortal_hive'

def classify_quarry(gamedata, template):
    if template and (template in gamedata['quarries_client']['templates']) and \
       gamedata['quarries_client']['templates'][template].get('turf_points',None):
        return 'pvp_quarry_strongpoint'
    else:
        return 'pvp_quarry_nonstrongpoint'

# player history "activity" sample classifier
# returns a simplified version of the player history "activity" sample
# as a dictionary, or None if the sample is totally uninteresting
def classify_activity(gamedata, data):
    assert ('ai_bases' in gamedata) and ('loot_tables' in gamedata) # ensure some server-side stuff we need is loaded
    state = data['state']
    if state in ('idle', 'harvest'): return None

    if state in ('pve_defense','pve_list'):
        if state == 'pve_defense':
            ai_id = data['attacker_id']
        else:
            ai_id = data['defender_id']

        state = classify_ai_base(gamedata, ai_id)

    elif state == 'pve_map':
        state = classify_hive(gamedata, data.get('template',None))
    elif state == 'pvquarry':
        state = classify_quarry(gamedata, data.get('template',None))
    elif state == 'pvp_map':
        state = 'pvp_map'
    elif state == 'pvp_list':
        state = 'pvp_ladder'
    elif state in ('consume', 'invest'):
        state = 'invest_or_consume'
    else:
        pass # leave "state" alone

    ret = {'state': state}

    if state.startswith('pve'):
        if 'tag' in data:
            ret['ai_tag'] = data['tag']
        if 'ui_name' in data:
            ret['ai_ui_name'] = data['ui_name']

    return ret

# encapsulate all the voodoo necessary to produce userdb.csv from upcache
class CSVWriter (object):
    def __init__(self, fd, gamedata):
        self.CSV_FIELDS = get_csv_fields(gamedata)
        self.CSV_FIELD_SET = set(self.CSV_FIELDS)
        self.writer = csv.DictWriter(fd, self.CSV_FIELDS, dialect='excel')
        # write header row
        self.writer.writerow(dict((fn,fn) for fn in self.CSV_FIELDS))

    def write_user(self, obj, time_now):
        csv_obj = {}
        for key in obj.iterkeys():
            val = obj[key]
            if key.startswith("T00"):
                if key in ABTEST_RENAME_HACK:
                    val = ABTEST_RENAME_HACK[key][val]
            key = conform_column_name(key)
            if key in CSV_IGNORE_FIELDS or key.endswith('_on_day') or key.endswith('_at_time'):
                continue
            if key not in self.CSV_FIELD_SET:
                # this will cause writerow() to throw an exception,
                # just note the name of the key so we can add it to CSV_FIELDS
                sys.stderr.write('UNKNOWN USERDB KEY %s\n' % key)
                continue
            if isinstance(val, str) or isinstance(val, unicode):
                val = sanitize_text_for_csv(val)
            csv_obj[key] = val

        # output CSV row
        self.writer.writerow(csv_obj)

# time series fields from player.history: *_at_time
class SeriesField(object):
    def __init__(self, name, method = '+', minver = 2):
        self.name = name
        self.method = method
        self.minver = minver
        self.series_name = name + '_at_time'

# for money_spent_on_* fields, also accumulate *_purchased
def make_series_field(name):
    ret = [SeriesField(name)]
    if name.startswith('money_spent_on_'):
        spend_kind = name[len('money_spent_on_'):]
        ret.append(SeriesField(spend_kind+'_purchased'))
    return ret

class TimeSeriesCSVWriter(object):

    # XXX handle money_spent and logins from old version if new history is not available
    # time-series fields in upcache that correspond to the sampled outputs
    # read from the *_at_time sample arrays
    # NOTE! upcache must be regenerated if anything is added here!

    SOURCE_FIELDS = sum(map(make_series_field,
                            [
                             "logged_in_times",
                             "time_in_game",
                             "num_purchases",
                             "money_spent",
                             "gamebucks_balance",
                             "gamebucks_spent",
                             "units_manufactured",
                             "money_spent_on_speedups",
                             "money_spent_on_building_upgrades",
                             "money_spent_on_techs",
                             "money_spent_on_base_repairs",
                             "money_spent_on_unit_repair_speedups",
                             #"money_spent_on_barrier_upgrades",
                             "money_spent_on_resource_boosts",
                             "money_spent_on_building_upgrade_speedups",
                             "money_spent_on_produce_speedups",
                             "money_spent_on_research_speedups",
                             "money_spent_on_repair_speedups",
                             "money_spent_on_tech_unlocks",
                             "money_spent_on_random_items",
                             "player_level",
                             "quests_completed",
                             "resources_harvested",
                             "resources_looted",
                             "resources_looted_from_ai",
                             "resources_looted_from_human",
                             "resources_stolen",
                             "attacks_launched",
                             "attacks_launched_vs_ai",
                             "attacks_launched_vs_human",
                             "units_lost",
                             "units_killed",
                             "units_lost_in_attacks",
                             "units_killed_in_attacks",
                             "units_lost_in_defenses",
                             "units_killed_in_defenses",
                             "buildings_killed",
                             "buildings_lost",
                             "turrets_killed",
                             "turrets_lost",
                             "storages_killed",
                             "storages_lost",
                             "harvesters_killed",
                             "harvesters_lost"]), [])

    SOURCE_FIELDS += map(lambda x: SeriesField(x, method = 'max'),
                        ["units_unlocked",
                         "friends_in_game",
                         #"central_ computer_level"
                         # XXX "robotics _lab_level", "research _center_level", "energy _plant_level"
                         ])
    SOURCE_FIELDS +=  map(lambda x: SeriesField(x, minver = 3),
                          ["energy_plants_built", "energy_plants_max_level",
                           "turrets_built", "turrets_max_level",
                           "storages_built", "storages_max_level",
                           "harvesters_built", "harvesters_max_level"
                           ])

    TIME_SERIES_FIELDS = [field.series_name for field in SOURCE_FIELDS] # array containing past states indexed by time since acct creation
    TIME_CURRENT_FIELDS = [field.name for field in SOURCE_FIELDS] # atomic values of current state

    DAY=24*60*60

    # mandatory sample times
    TIME_MARKS = [1, 2, 3, 6, 12, 24, 2*24, 3*24, 5*24, 7*24, 10*24]

#    TIME_RES=60
#    TIME_RES_NAME = 'minutes_old'
#    TIME_MARKS = [5,10,15,20,25,30,45,60,90,120,180,240, 24*60, 2*24*60, 3*24*60, 5*24*60, 7*24*60, 10*24*60]




    def __init__(self, fd, gamedata, sample_interval = 'hour'):
        self.gamedata = gamedata

        # resolution of time samples, in seconds
        self.TIME_RES = {'hour':60*60, 'minute':60, 'day':24*60*60, 'week':7*24*60*60, 'month':30*24*60*60}[sample_interval]
        self.TIME_RES_NAME = sample_interval+'s_old'

        self.ALL_FIELDS = ["user_id", self.TIME_RES_NAME, 'history_version'] + self.TIME_CURRENT_FIELDS

        self.writer = csv.DictWriter(fd, self.ALL_FIELDS, dialect='excel')
        self.writer.writerow(dict((fn,fn) for fn in self.ALL_FIELDS))

    def write_user(self, obj, time_now):
        if 'user_id' not in obj: return
        creat = obj.get('account_creation_time',-1)
        if creat <= 0: return
        user_ver = obj.get('history_version',0)

        age = int(time_now - creat)
        #age = 11*self.DAY

        if user_ver < 2:
            # resolution is limited to days because we only have old money_spent_by_day and logins_by_day fields for old users
            age_days = age/self.DAY
            cum = {'user_id': obj['user_id'], 'history_version':user_ver,
                   self.TIME_RES_NAME: 0, 'money_spent': 0.0, 'logged_in_times': 0}
            for day in xrange(min(age_days+1, (self.TIME_MARKS[-1])/(self.DAY/self.TIME_RES)+1)):
                mark = day*(self.DAY/self.TIME_RES)
                if mark in self.TIME_MARKS:
                    cum[self.TIME_RES_NAME] = mark
                    self.writer.writerow(cum)
                if 'money_spent_by_day' in obj:
                    cum['money_spent'] += obj['money_spent_by_day'].get(str(day), 0)
                if 'logins_by_day' in obj:
                    cum['logged_in_times'] += obj['logins_by_day'].get(str(day), 0)
            return

        # only include fields where the user history_version is recent enough
        user_fields = filter(lambda field: user_ver >= field.minver, self.SOURCE_FIELDS)

        cum = dict([(field.name, 0) for field in user_fields])
        cum['user_id'] = obj['user_id']
        cum['history_version'] = user_ver
        cum[self.TIME_RES_NAME] = 0

        # open player file to get time series from player.history
        import SpinUserDB
        try:
            player = SpinJSON.loads(SpinUserDB.driver.sync_download_player(obj['user_id']))
        except:
            sys.stderr.write('player file missing for user_id %d, skipping\n' % obj['user_id'])
            return

        history = player.get('history',None)
        if not history:
            return

        # create sorted version of object series for fast accumulation
        # { "time2": value, "time1": value } => [ ("time1", value), ("time2", value), ... ]
        def make_sorted(d):
            return sorted([(int(st), v) for st, v in d.iteritems()], key = lambda tv: tv[0])
        sorted_series = dict([(field.series_name, make_sorted(history[field.series_name])) for field in user_fields if field.series_name in history])
        last_index = dict([(field.series_name, 0) for field in user_fields])

        for mark in self.TIME_MARKS:
            if (age/self.TIME_RES < mark):
                break

            cum[self.TIME_RES_NAME] = mark

            # accumulate events at t < age_limit
            age_limit = self.TIME_RES*(mark+1)

            for field in user_fields:
                if field.series_name in sorted_series:
                    series = sorted_series[field.series_name]
                    i = last_index[field.series_name]
                    while i < len(series):
                        t, val = series[i]
                        if t < age_limit:
                            if field.method == "+":
                                cum[field.name] += val
                            elif field.method == "max":
                                cum[field.name] = max(cum[field.name], val)
                        else:
                            break
                        i += 1
                    last_index[field.series_name] = i

            self.writer.writerow(cum)

# set key names to lower case and replace spaces and dashes with underscore for clean CSV output
def conform_column_name(name):
    # fix up the old Kissmetrics-compatible field names
    if name.startswith('Billing'):
        name = name.lower()
        name = name.replace(' ', '_')
        name = name.replace('-', '_')
    # correct misspelling
    if name == "referrer":
        name = "referer"
    return name

# get rid of any non-ASCII characters so that CSV output is 7-bit clean
def sanitize_text_for_csv(text):
    ret = ''
    for i in range(len(text)):
        o = ord(text[i])
        if (o >= 0) and (o < 128):
            ret += text[i]
        else:
            ret += 'X'
    return ret

# return updated upcache entry for one user with userdb file 'filename'
# 'entry' is the old upcache entry (may be None if missing)
# read source data from userdb/playerdb if the old upcache entry is out of date

def update_upcache_entry(user_id, driver, entry, time_now, gamedata, user_mtime = -1):
    obj = None
    need_playerdb_info = True

    try:
        if entry:
            # we have a cache entry, let's see if it is fresh enough to use
            if user_mtime < 0:
                # no known last modified time, have to ping the DB to get it
                user_mtime = driver.sync_get_player_mtime(user_id)
            if user_mtime < entry['upcache_time']:
                # cache is valid!
                obj = entry
                # don't need to search playerdb since the cache is up to date
                need_playerdb_info = False

        # cache miss, load userdb file
        if not obj:
            buf = None
            try:
                buf = driver.sync_download_user(user_id)
                obj = SpinJSON.loads(buf)
            # this can be simplified later once we figure out where the bad data is coming from
            except IOError: raise # missing user, abort immediately
            except SpinS3.S3404Exception: raise # missing user, abort immediately
            except:
                debug = open('/tmp/upcache-fail-user-%d.json' % user_id, 'w')
                debug.write(traceback.format_exc())
                if buf: debug.write(buf)
                debug.close()
                raise

    except IOError:
        # missing userdb file (disk)
        obj = None
    except SpinS3.S3404Exception:
        # missing userdb file (S3)
        obj = None

    if obj is None:
        # create empty entry
        obj = {'user_id': user_id, 'EMPTY': 1, 'upcache_time': time_now}
    else:
        # clean out old bloated fields
        for FIELD in ('money_purchase_history', 'gamebucks_purchase_history'):
            if FIELD in obj:
                del obj[FIELD]

    if obj.has_key('user_id'):
        assert obj['user_id'] == user_id
    else:
        obj['user_id'] = user_id

    # only bump upcache_time if current entry was not up to date
    if need_playerdb_info:
        obj['upcache_time'] = time_now

    if 'EMPTY' in obj: return obj

    # update fields

    if obj.has_key('country'):
        if SpinConfig.country_tier_map.has_key(obj['country']):
            obj['country_tier'] = str(SpinConfig.country_tier_map[obj['country']])
        else:
            # assign unrecognized or missing countries to tier 4
            obj['country_tier'] = str(4)

    if obj.has_key('facebook_profile') and type(obj['facebook_profile']) == dict:
        # update demographic info from Facebook profile
        profile = obj['facebook_profile']
        if profile.has_key('gender'):
            obj['gender'] = profile['gender']
        if profile.has_key('locale'):
            obj['locale'] = profile['locale']
        if profile.has_key('email'):
            obj['email'] = profile['email']
        if profile.has_key('link'):
            obj['link'] = profile['link']
        if profile.has_key('timezone'):
            obj['timezone'] = int(profile['timezone'])
        if profile.has_key('birthday'):
            obj['birthday'] = profile['birthday']
        try:
            obj['birth_year'] = int(profile['birthday'].split('/')[2])
        except:
            pass

    # revise facebook likes only if out of date - otherwise leave them alone
    # note: passes through upcache where "obj" is the existing cache entry will never have a 'facebook_likes' field!
    if (not obj.get('has_facebook_likes',None)) or obj['has_facebook_likes'] < SpinConfig.FACEBOOK_GAME_FAN_PAGES_VERSION:
        if 'has_facebook_likes' in obj: del obj['has_facebook_likes'] # version number for the likes_ data
        if 'facebook_likes' in obj and len(obj['facebook_likes']) > 0:
            obj['has_facebook_likes'] = SpinConfig.FACEBOOK_GAME_FAN_PAGES_VERSION
            REVERSE_TBL = dict((id, name) for name, id in SpinConfig.FACEBOOK_GAME_FAN_PAGES.iteritems())

            for like in ('likes_'+x for x in SpinConfig.FACEBOOK_GAME_FAN_PAGES.iterkeys()):
                if like in obj: del obj[like]

            for data in obj['facebook_likes']:
                if ('id' in data) and str(data['id']) in REVERSE_TBL:
                    obj['likes_'+REVERSE_TBL[str(data['id'])]] = 1

    if 'facebook_currency' in obj:
        fbcur = obj['facebook_currency']
        if 'user_currency' in fbcur:
            obj['currency'] = fbcur['user_currency']

    if 'facebook_permissions' in obj and type(obj['facebook_permissions']) is list:
        obj['facebook_permissions_str'] = string.join(obj['facebook_permissions'], ',')

    # priority: (ad click | friend invite) > everything else
    def get_acquisition_type(obj):
        for d in obj['acquisition_data']:
            if d['type'] in ('ad_click', 'facebook_friend_invite'):
                return d['type']
        if len(obj['acquisition_data']) > 0:
            return obj['acquisition_data'][0]['type']
        return None

    if 'acquisition_data' in obj:
        atype = get_acquisition_type(obj)
        if atype:
            obj['acquisition_type'] = atype

    if 'browser_caps' in obj:
        for cap in gamedata['browser_caps']:
            if cap in obj['browser_caps']:
                obj['browser_supports_'+cap] = obj['browser_caps'][cap]

    if ('last_sprobe_result' in obj) and ('graphics' in obj['last_sprobe_result']['tests']) and ('framerate' in obj['last_sprobe_result']['tests']['graphics']):
        obj['last_framerate'] = float(obj['last_sprobe_result']['tests']['graphics']['framerate'])

    # deleted keys that should not be cached or output to CSV
    for field in HOG_FIELDS:
        if field in obj:
            del obj[field]

    # gather additional info from the user's corresponding playerdb file
    if need_playerdb_info:
        try:
            fd_buf = driver.sync_download_player(user_id)
        except:
            # usually a 404
            fd_buf = None

        if fd_buf:
            try:
                data = SpinJSON.loads(fd_buf)
            except:
                debug = open('/tmp/upcache-fail-player-%d.json' % user_id, 'w')
                debug.write(fd_buf)
                debug.close()
                raise

            # OVERRIDE userdb preferences field with playerdb preferences field
            if 'player_preferences' in data:
                obj['player_preferences'] = data['player_preferences']

            if 'last_fb_notification_time' in data:
                obj['last_fb_notification_time'] = data['last_fb_notification_time']

            obj['tutorial_state'] = data.get('tutorial_state', 'START')
            resources = data['resources']
            obj['player_level'] = resources.get('player_level', 1)
            for resname in gamedata['resources']:
                obj[resname] = resources.get(resname, 0)
            obj['player_xp'] = resources.get('xp', 0)
            obj['gamebucks_cur_balance'] = resources.get('gamebucks', 0)
            obj['lock_state'] = data.get('lock_state', 0)

            # note: override userdb facebook_permissions with playerdb facebook_permissions
            if 'facebook_permissions' in data and type(data['facebook_permissions']) is list:
                obj['facebook_permissions_str'] = string.join(data['facebook_permissions'], ',')

            completed_quests = data.get('completed_quests', {})

            # migrate legacy playerdb files where completed_quests is a list rather than a dictionary
            if type(completed_quests) is list:
                completed_quests = dict([(qname, {'count':1}) for qname in completed_quests])

            obj['completed_quests'] = len(completed_quests)

            for qname, qdat in completed_quests.iteritems():
                if qname in gamedata['quests']:
                    obj['quest:'+qname+':completed'] = qdat.get('count',1)

            for aname, adat in data.get('achievements',{}).iteritems():
                if aname in gamedata['achievements']:
                    obj['achievement:'+aname] = adat.get('time',1)

            if 'home_region' in data:
                obj['home_region'] = data['home_region']

            if data.has_key('history'):
                history = data['history']

                # store parts of player.history in upcache
                # used for time-series metrics
                for name in TimeSeriesCSVWriter.TIME_CURRENT_FIELDS: # TIME_SERIES_FIELDS to get entire array
                    if name in history:
                        obj[name] = history[name]

                for name in ['harvested_'+resname+'_total' for resname in gamedata['resources']] + \
                            ['peak_'+resname for resname in gamedata['resources']] + ['peak_gamebucks',] + \
                            [catname+'_unlocked' for catname in gamedata['strings']['manufacture_categories']] + \
                            ['history_version',
                             'attacks_launched', 'attacks_launched_vs_ai', 'attacks_launched_vs_human', 'revenge_attacks_launched_vs_human',
                             'attacks_victory',
                             'attacks_suffered', 'ai_attacks_suffered', 'daily_attacks_suffered', 'revenge_attacks_suffered',
                             'units_manufactured',
                             'money_spent', 'largest_purchase', 'time_in_game', 'logged_in_times',
                             'alliances_joined', 'units_donated', 'donated_units_received', 'alliance_gift_items_sent',
                             'thunder_dome_entered',
                             'iron_deposits_collected',
                             'chat_messages_sent',
                             'ai_sirenum_progress', 'ai_erebus_progress', 'ai_erebus4_progress', 'ai_vostok_progress', 'ai_vostok2_progress', 'ai_hellas_progress', 'ai_medusa_progress', 'ai_medusa2_progress', 'ai_kirat_progress', 'ai_kirat2_progress', 'ai_phantom_progress', 'ai_phantom2_progress', 'ai_radiation_progress', 'ai_ice_progress', 'ai_arsenal_progress', 'ai_blaster_attack_progress',
                             'ai_nu_blizzard_progress', 'ai_learning_storm_progress', 'ai_gala_narcs_progress',

                             "ai_dark_moon_progress", "ai_dark_moon_heroic_progress", "ai_dark_moon_epic_progress",
                             "ai_dark_moon_heroic_speedrun",
                             "ai_dark_moon_times_started", "ai_dark_moon_heroic_times_started", "ai_dark_moon_epic_times_started",
                             "ai_dark_moon_times_completed", "ai_dark_moon_heroic_times_completed", "ai_dark_moon_epic_times_completed",

                             "ai_abyss_progress", "ai_abyss_heroic_progress", "ai_abyss_epic_progress",
                             "ai_abyss_heroic_speedrun",
                             "ai_abyss_times_started", "ai_abyss_heroic_times_started", "ai_abyss_epic_times_started",
                             "ai_abyss_times_completed", "ai_abyss_heroic_times_completed", "ai_abyss_epic_times_completed",

                             "ai_gale_progress", "ai_gale_heroic_progress", "ai_gale_epic_progress",
                             "ai_gale_heroic_speedrun",
                             "ai_gale_times_started", "ai_gale_heroic_times_started", "ai_gale_epic_times_started",
                             "ai_gale_times_completed", "ai_gale_heroic_times_completed", "ai_gale_epic_times_completed",

                             "T158_resurrect_test_exposed",

                             "ai_wasteland_progress", "ai_wasteland_heroic_progress", "ai_wasteland_epic_progress",
                             "ai_wasteland_heroic_speedrun",
                             "ai_wasteland_times_started", "ai_wasteland_heroic_times_started", "ai_wasteland_epic_times_started",
                             "ai_wasteland_times_completed", "ai_wasteland_heroic_times_completed", "ai_wasteland_epic_times_completed",

                             "ai_phantom_attack_progress", "ai_phantom_attack_heroic_progress", "ai_phantom_attack_epic_progress",
                             "ai_phantom_attack_heroic_speedrun",
                             "ai_phantom_attack_times_started", "ai_phantom_attack_heroic_times_started", "ai_phantom_attack_epic_times_started",
                             "ai_phantom_attack_times_completed", "ai_phantom_attack_heroic_times_completed", "ai_phantom_attack_epic_times_completed",

                             "ai_horde_progress", "ai_horde_heroic_progress", "ai_horde_epic_progress",
                             "ai_horde_heroic_speedrun",
                             "ai_horde_times_started", "ai_horde_heroic_times_started", "ai_horde_epic_times_started",
                             "ai_horde_times_completed", "ai_horde_heroic_times_completed", "ai_horde_epic_times_completed",

                             "ai_zero_progress", "ai_zero_heroic_progress", "ai_zero_epic_progress",
                             "ai_zero_heroic_speedrun",
                             "ai_zero_times_started", "ai_zero_heroic_times_started", "ai_zero_epic_times_started",
                             "ai_zero_times_completed", "ai_zero_heroic_times_completed", "ai_zero_epic_times_completed",

                             "ai_meltdown_progress", "ai_meltdown_heroic_progress", "ai_meltdown_epic_progress",
                             "ai_meltdown_heroic_speedrun",
                             "ai_meltdown_times_started", "ai_meltdown_heroic_times_started", "ai_meltdown_epic_times_started",
                             "ai_meltdown_times_completed", "ai_meltdown_heroic_times_completed", "ai_meltdown_epic_times_completed",

                             "ai_crash_conquests", "ai_crash_progress",
                             "ai_crash_heroic_L2_conquests", "ai_crash_heroic_L3_conquests", "ai_crash_heroic_L5_conquests",
                             "ai_crash_heroic_L7_conquests", "ai_crash_heroic_L8_conquests",
                             "ai_crash_epic_L2_conquests", "ai_crash_epic_L3_conquests", "ai_crash_epic_L5_conquests",
                             "ai_crash_epic_L7_conquests", "ai_crash_epic_L8_conquests",
                             "ai_crash_533_conquests", "ai_crash_534_conquests", "ai_crash_535_conquests", "ai_crash_536_conquests", "ai_crash_537_conquests",
                             "ai_crash_538_conquests", "ai_crash_539_conquests", "ai_crash_540_conquests", "ai_crash_541_conquests", "ai_crash_542_conquests",
                             "ai_crash_543_conquests", "ai_crash_544_conquests", "ai_crash_545_conquests", "ai_crash_546_conquests", "ai_crash_547_conquests",
                             "ai_crash_548_conquests",

                             "ai_prisoner_progress",
                             "ai_prisoner_conquests",
                             "ai_prisoner_low_conquests",
                             "ai_prisoner_549_conquests","ai_prisoner_550_conquests","ai_prisoner_551_conquests","ai_prisoner_552_conquests",
                             "ai_prisoner_553_conquests","ai_prisoner_554_conquests","ai_prisoner_555_conquests","ai_prisoner_556_conquests",
                             "ai_prisoner_557_conquests","ai_prisoner_558_conquests",

                             "ai_kingpin_progress",
                             "ai_kingpin_conquests",
                             "ai_kingpin_low_conquests",
                             "ai_kingpin_394_conquests","ai_kingpin_395_conquests","ai_kingpin_396_conquests","ai_kingpin_397_conquests",
                             "ai_kingpin_398_conquests","ai_kingpin_399_conquests","ai_kingpin_400_conquests","ai_kingpin_401_conquests",

                 "ai_mutiny_progress",
                 "ai_mutiny_conquests",
                 "ai_mutiny_low_conquests",
                 "ai_mutiny_692_conquests","ai_mutiny_693_conquests","ai_mutiny_694_conquests","ai_mutiny_695_conquests",
                 "ai_mutiny_696_conquests","ai_mutiny_697_conquests","ai_mutiny_698_conquests","ai_mutiny_699_conquests",

                 "ai_chunk_progress",
                 "ai_chunk_conquests",
                 "ai_chunk_low_conquests",
                 "ai_chunk_584_conquests","ai_chunk_585_conquests","ai_chunk_586_conquests","ai_chunk_587_conquests",
                 "ai_chunk_588_conquests","ai_chunk_589_conquests","ai_chunk_590_conquests","ai_chunk_591_conquests",

                             "ai_ladder_conquests",
                             "ai_ladder_conquests_342", "ai_ladder_conquests_343", "ai_ladder_conquests_344", "ai_ladder_conquests_345",
                             "ai_ladder_conquests_346", "ai_ladder_conquests_347", "ai_ladder_conquests_348", "ai_ladder_conquests_349",
                             "ai_ladder_conquests_350", "ai_ladder_conquests_351", "ai_ladder_conquests_352", "ai_ladder_conquests_353",
                             "ai_ladder_conquests_354", "ai_ladder_conquests_355", "ai_ladder_conquests_356", "ai_ladder_conquests_357",
                             "ai_ladder_conquests_358", "ai_ladder_conquests_359", "ai_ladder_conquests_360",
                             "ai_ladder_conquests_albor", "ai_ladder_conquests_arabia", "ai_ladder_conquests_kalamity", "ai_ladder_conquests_kirat",
                             "ai_ladder_conquests_phobos", "ai_ladder_conquests_prisoner", "ai_ladder_conquests_subareion", "ai_ladder_conquests_tharsis",
                             "ai_ladder_conquests_vell",

                             # TR events
                             "ai_mrskilling_progress", "ai_redpole_progress", "ai_redpole1_conquests",
                             "ai_ambush_progress","ai_ambush_times_started","ai_ambush_times_completed","ai_ambush_conquests",
                             "ai_ambush2_progress","ai_ambush2_times_started","ai_ambush2_times_completed","ai_ambush2_conquests",
                             "ai_ambush3_attempted","ai_ambush3_progress","ai_ambush3_times_started","ai_ambush2_times_completed","ai_ambush3_conquests",
                             "ai_ambush4_attempted","ai_ambush4_progress","ai_ambush4_times_started","ai_ambush4_times_completed","ai_ambush4_conquests",
                             "ai_ambush5_attempted","ai_ambush5_progress","ai_ambush5_times_started","ai_ambush5_times_completed","ai_ambush5_conquests",
                             "ai_hamilton_progress", "ai_hamilton_times_started", "ai_hamilton_times_completed",
                             "ai_hamilton2_progress", "ai_hamilton2_times_started", "ai_hamilton2_times_completed",
                             "ai_hamilton3_progress", "ai_hamilton3_times_started", "ai_hamilton3_times_completed",
                             "ai_hamilton4_attempted", "ai_hamilton4_progress", "ai_hamilton4_times_started", "ai_hamilton4_times_completed",
                             "ai_hamilton5_attempted", "ai_hamilton5_progress", "ai_hamilton5_times_started", "ai_hamilton5_times_completed",
                             "ai_hamilton6_attempted", "ai_hamilton6_progress", "ai_hamilton6_times_started", "ai_hamilton6_times_completed",
                             "ai_pirate_progress","ai_pirate_times_started","ai_pirate_times_completed",
                             "ai_pirate2_progress","ai_pirate2_times_started","ai_pirate2_times_completed",
                             "ai_pirate3_progress","ai_pirate3_times_started","ai_pirate3_times_completed",
                             "ai_pirate4_attempted","ai_pirate4_progress","ai_pirate4_times_started","ai_pirate4_times_completed",
                             "ai_pirate5_attempted","ai_pirate5_progress","ai_pirate5_times_started","ai_pirate5_times_completed",
                             "ai_pirate6_attempted","ai_pirate6_progress","ai_pirate6_times_started","ai_pirate6_times_completed",
                             "ai_pirate7_attempted","ai_pirate7_progress","ai_pirate7_times_started","ai_pirate7_times_completed",
                             "ai_xerxes_progress","ai_xerxes_times_started","ai_xerxes_times_completed",
                             "ai_xerxes2_progress","ai_xerxes2_times_started","ai_xerxes2_times_completed",
                             "ai_xerxes3_progress","ai_xerxes3_times_started","ai_xerxes3_times_completed",
                             "ai_xerxes4_attempted","ai_xerxes4_progress","ai_xerxes4_times_started","ai_xerxes4_times_completed",
                             "ai_xerxes5_attempted","ai_xerxes5_progress","ai_xerxes5_times_started","ai_xerxes5_times_completed",
                             "ai_xerxes6_attempted","ai_xerxes6_progress","ai_xerxes6_times_started","ai_xerxes6_times_completed",
                             "ai_giancarlo_progress","ai_giancarlo_times_started","ai_giancarlo_times_completed",
                             "ai_giancarlo2_progress","ai_giancarlo2_times_started","ai_giancarlo2_times_completed",
                             "ai_giancarlo3_progress","ai_giancarlo3_times_started","ai_giancarlo3_times_completed",
                             "ai_giancarlo4_attempted","ai_giancarlo4_progress","ai_giancarlo4_times_started","ai_giancarlo4_times_completed",
                             "ai_giancarlo5_attempted","ai_giancarlo5_progress","ai_giancarlo5_times_started","ai_giancarlo5_times_completed",
                             "ai_giancarlo6_attempted","ai_giancarlo6_progress","ai_giancarlo6_times_started","ai_giancarlo6_times_completed",
                             "ai_giancarlo7_attempted","ai_giancarlo7_progress","ai_giancarlo7_times_started","ai_giancarlo7_times_completed",
                             "ai_maximilien_progress","ai_maximilien_times_started","ai_maximilien_times_completed",
                             "ai_maximilien2_attempted","ai_maximilien2_progress","ai_maximilien2_times_started","ai_maximilien2_times_completed",
                             "ai_maximilien3_attempted","ai_maximilien3_progress","ai_maximilien3_times_started","ai_maximilien3_times_completed",
                             "ai_maximilien4_attempted","ai_maximilien4_progress","ai_maximilien4_times_started","ai_maximilien4_times_completed",
                             "ai_maximilien5_attempted","ai_maximilien5_progress","ai_maximilien5_times_started","ai_maximilien5_times_completed",
                             "ai_kim_progress","ai_kim_times_started","ai_kim_times_completed",
                             "ai_kim2_progress","ai_kim2_times_started","ai_kim2_times_completed",
                             "ai_kim3_attempted", "ai_kim3_progress","ai_kim3_times_started","ai_kim3_times_completed",
                             "ai_kim4_attempted", "ai_kim4_progress","ai_kim4_times_started","ai_kim4_times_completed",
                             "ai_kim5_attempted", "ai_kim5_progress","ai_kim5_times_started","ai_kim5_times_completed",
                             "ai_kim6_attempted", "ai_kim6_progress","ai_kim6_times_started","ai_kim6_times_completed",
                             "ai_segvec_progress","ai_segvec_times_started","ai_segvec_times_completed",
                             "ai_segvec2_progress","ai_segvec2_times_started","ai_segvec2_times_completed",
                             "ai_segvec3_attempted","ai_segvec3_progress","ai_segvec3_times_started","ai_segvec3_times_completed",
                             "ai_segvec4_attempted","ai_segvec4_progress","ai_segvec4_times_started","ai_segvec4_times_completed",
                             "ai_segvec5_attempted","ai_segvec5_progress","ai_segvec5_times_started","ai_segvec5_times_completed",
                             "ai_segvec6_attempted","ai_segvec6_progress","ai_segvec6_times_started","ai_segvec6_times_completed",
                             "ai_cyclops_progress","ai_cyclops_times_started","ai_cyclops_times_completed","ai_cyclops_conquests",
                             "ai_cyclops2_attempted","ai_cyclops2_progress","ai_cyclops2_times_started","ai_cyclops2_times_completed","ai_cyclops2_conquests",
                             "ai_cyclops3_attempted","ai_cyclops3_progress","ai_cyclops3_times_started","ai_cyclops3_times_completed","ai_cyclops3_conquests",
                             "ai_cyclops4_attempted","ai_cyclops4_progress","ai_cyclops4_times_started","ai_cyclops4_times_completed","ai_cyclops4_conquests",
                             "ai_cyclops5_attempted","ai_cyclops5_progress","ai_cyclops5_times_started","ai_cyclops5_times_completed","ai_cyclops5_conquests",
                             "ai_queen_progress","ai_queen_times_started","ai_queen_times_completed","ai_queen_conquests",
                             "ai_queen2_attempted", "ai_queen2_progress","ai_queen2_times_started","ai_queen2_times_completed","ai_queen2_conquests",
                             "ai_queen3_attempted", "ai_queen3_progress","ai_queen3_times_started","ai_queen3_times_completed","ai_queen3_conquests",
                             "ai_queen4_attempted", "ai_queen4_progress","ai_queen4_times_started","ai_queen4_times_completed","ai_queen4_conquests",
                             "ai_warlord1_progress","ai_warlord1_times_started","ai_warlord1_times_completed","ai_warlord1_conquests",
                             "ai_warlord2_attempted","ai_warlord2_progress","ai_warlord2_times_started","ai_warlord2_times_completed","ai_warlord2_conquests",
                             "ai_warlord3_attempted","ai_warlord3_progress","ai_warlord3_times_started","ai_warlord3_times_completed","ai_warlord3_conquests",
                             "ai_warlord4_attempted","ai_warlord4_progress","ai_warlord4_times_started","ai_warlord4_times_completed","ai_warlord4_conquests",
                             "ai_fugitive1_attempted", "ai_fugitive1_progress","ai_fugitive1_times_started","ai_fugitive1_times_completed","ai_fugitive1_conquests",
                             "ai_fugitive2_attempted", "ai_fugitive2_progress","ai_fugitive2_times_started","ai_fugitive2_times_completed","ai_fugitive2_conquests",
                             "ai_fugitive3_attempted", "ai_fugitive3_progress","ai_fugitive3_times_started","ai_fugitive3_times_completed","ai_fugitive3_conquests",
                             "ai_fugitive4_attempted", "ai_fugitive4_progress","ai_fugitive4_times_started","ai_fugitive4_times_completed","ai_fugitive4_conquests",
                             "ai_piper_progress","ai_piper_times_started","ai_piper_times_completed","ai_piper_conquests",
                             "ai_piper1_progress","ai_piper1_times_started","ai_piper1_times_completed","ai_piper1_conquests",
                             "ai_piper2_attempted","ai_piper2_progress","ai_piper2_times_started","ai_piper2_times_completed","ai_piper2_conquests",
                             "ai_piper3_attempted","ai_piper3_progress","ai_piper3_times_started","ai_piper3_times_completed","ai_piper3_conquests",
                             "ai_piper4_attempted","ai_piper4_progress","ai_piper4_times_started","ai_piper4_times_completed","ai_piper4_conquests",
                             "ai_rogue_attempted","ai_rogue_progress","ai_rogue_times_started","ai_rogue_times_completed","ai_rogue_conquests",
                             "ai_rogue1_attempted","ai_rogue1_progress","ai_rogue1_times_started","ai_rogue1_times_completed","ai_rogue1_conquests",
                             "ai_rogue2_attempted","ai_rogue2_progress","ai_rogue2_times_started","ai_rogue2_times_completed","ai_rogue2_conquests",
                             "ai_rogue3_attempted","ai_rogue3_progress","ai_rogue3_times_started","ai_rogue3_times_completed","ai_rogue3_conquests",
                             "ai_rogue4_attempted","ai_rogue4_progress","ai_rogue4_times_started","ai_rogue4_times_completed","ai_rogue4_conquests",
                             "ai_murderous_attempted","ai_murderous_progress","ai_murderous_times_started","ai_murderous_times_completed","ai_murderous_conquests",
                             "ai_murderous1_attempted","ai_murderous1_progress","ai_murderous1_times_started","ai_murderous1_times_completed","ai_murderous1_conquests",
                             "ai_murderous2_attempted","ai_murderous2_progress","ai_murderous2_times_started","ai_murderous2_times_completed","ai_murderous2_conquests",
                             "ai_murderous3_attempted","ai_murderous3_progress","ai_murderous3_times_started","ai_murderous3_times_completed","ai_murderous3_conquests",
                            "ai_fanatic_attempted","ai_fanatic_progress","ai_fanatic_times_started","ai_fanatic_times_completed","ai_fanatic_conquests",
                            "ai_fanatic1_attempted","ai_fanatic1_progress","ai_fanatic1_times_started","ai_fanatic1_times_completed","ai_fanatic1_conquests",
                            "ai_fanatic2_attempted","ai_fanatic2_progress","ai_fanatic2_times_started","ai_fanatic2_times_completed","ai_fanatic2_conquests",
                             "ai_berkman_conquests", "ai_berkman1_conquests", "ai_berkman2_conquests", "ai_berkman3_conquests",
                             "ai_mandel_conquests", "ai_mandel1_conquests", "ai_mandel2_conquests", "ai_mandel3_conquests",
                             "ai_gashi_conquests", "ai_gashi1_conquests", "ai_gashi2_conquests",
                             "ai_nomad_attempted","ai_nomad_progress","ai_nomad_times_started","ai_nomad_times_completed","ai_nomad_conquests",
                             "ai_nomad1_attempted","ai_nomad1_progress","ai_nomad1_times_started","ai_nomad1_times_completed","ai_nomad1_conquests",
                             "ai_nomad2_attempted","ai_nomad2_progress","ai_nomad2_times_started","ai_nomad2_times_completed","ai_nomad2_conquests",

                             # MF2
                             "ai_tutorial02A_progress", "ai_tutorial02B_progress", "ai_tutorial08_progress", "ai_tutorial25_progress",
                             "ai_guardian_progress","ai_guardian_times_started","ai_guardian_times_completed","ai_guardian_conquests",
                             "ai_guardian1_progress","ai_guardian1_times_started","ai_guardian1_times_completed","ai_guardian1_conquests",
                             "ai_guardian2_progress","ai_guardian2_times_started","ai_guardian2_times_completed","ai_guardian2_conquests",
                             "ai_guardian3_progress","ai_guardian3_times_started","ai_guardian3_times_completed","ai_guardian3_conquests",
                             "ai_harvest_progress","ai_harvest_times_started","ai_harvest_times_completed","ai_harvest_conquests",
                             "ai_harvest1_progress","ai_harvest1_times_started","ai_harvest1_times_completed","ai_harvest1_conquests",
                             "ai_harvest2_attempted","ai_harvest2_progress","ai_harvest2_times_started","ai_harvest2_times_completed","ai_harvest2_conquests",
                             "ai_devil_progress","ai_devil_times_started","ai_devil_times_completed","ai_devil_conquests",
                             "ai_devil1_progress","ai_devil1_times_started","ai_devil1_times_completed","ai_devil1_conquests",
                             "ai_devil2_attempted","ai_devil2_progress","ai_devil2_times_started","ai_devil2_times_completed","ai_devil2_conquests",
                             "ai_turncoat_progress","ai_turncoat_times_started","ai_turncoat_times_completed","ai_turncoat_conquests",
                             "ai_turncoat1_attempted","ai_turncoat1_progress","ai_turncoat1_times_started","ai_turncoat1_times_completed","ai_turncoat1_conquests",
                             "ai_turncoat2_attempted","ai_turncoat2_progress","ai_turncoat2_times_started","ai_turncoat2_times_completed","ai_turncoat2_conquests",
                             "ai_tonca_conquests","ai_tonca1_conquests","ai_tonca2_conquests","ai_tonca3_conquests",
                             "ai_khronic_conquests","ai_khronic1_conquests","ai_khronic2_conquests","ai_khronic3_conquests","ai_khronic4_conquests",
                             "ai_wilder_conquests","ai_wilder1_conquests","ai_wilder2_conquests","ai_wilder3_conquests","ai_wilder4_conquests",
                             "ai_collection_progress","ai_collection_times_started","ai_collection_times_completed","ai_collection_conquests",
                             "ai_collection1_attempted","ai_collection1_progress","ai_collection1_times_started","ai_collection1_times_completed","ai_collection1_conquests",
                             "ai_collection2_attempted","ai_collection2_progress","ai_collection2_times_started","ai_collection2_times_completed","ai_collection2_conquests",
                             "ai_prophecy_progress","ai_prophecy_times_started","ai_prophecy_times_completed","ai_prophecy_conquests",
                             "ai_prophecy1_attempted","ai_prophecy1_progress","ai_prophecy1_times_started","ai_prophecy1_times_completed","ai_prophecy1_conquests",
                             "ai_prophecy2_attempted","ai_prophecy2_progress","ai_prophecy2_times_started","ai_prophecy2_times_completed","ai_prophecy2_conquests",
                             "ai_extinction_progress","ai_extinction_times_started","ai_extinction_times_completed","ai_extinction_conquests",
                             "ai_extinction1_attempted","ai_extinction1_progress","ai_extinction1_times_started","ai_extinction1_times_completed","ai_extinction1_conquests",
                             "ai_defense_waa_progress","ai_defense_waa_times_started","ai_defense_waa_times_completed","ai_defense_waa_conquests",
                             "ai_defense_waa1_attempted","ai_defense_waa1_progress","ai_defense_waa1_times_started","ai_defense_waa1_times_completed","ai_defense_waa1_conquests",
                             "ai_defense_waa2_attempted","ai_defense_waa2_progress","ai_defense_waa2_times_started","ai_defense_waa2_times_completed","ai_defense_waa2_conquests",
                             "ai_monstrous_progress","ai_monstrous_times_started","ai_monstrous_times_completed","ai_monstrous_conquests",
                             "ai_monstrous1_attempted","ai_monstrous1_progress","ai_monstrous1_times_started","ai_monstrous1_times_completed","ai_monstrous1_conquests",
                             "ai_defense_wab_progress","ai_defense_wab_times_started","ai_defense_wab_times_completed","ai_defense_wab_conquests",
                             "ai_defense_wab1_attempted","ai_defense_wab1_progress","ai_defense_wab1_times_started","ai_defense_wab1_times_completed","ai_defense_wab1_conquests",
                             "ai_devious_progress","ai_devious_times_started","ai_devious_times_completed","ai_devious_conquests",
                             "ai_devious1_attempted","ai_devious1_progress","ai_devious1_times_started","ai_devious1_times_completed","ai_devious1_conquests",
                             "ai_defense_wad_progress","ai_defense_wad_times_started","ai_defense_wad_times_completed","ai_defense_wad_conquests",
                             "ai_defense_wad1_attempted","ai_defense_wad1_progress","ai_defense_wad1_times_started","ai_defense_wad1_times_completed","ai_defense_wad1_conquests",
                             "ai_herald_progress","ai_herald_times_started","ai_herald_times_completed","ai_herald_conquests",
                             "ai_herald1_attempted","ai_herald1_progress","ai_herald1_times_started","ai_herald1_times_completed","ai_herald1_conquests",
                             "ai_defense_waf_progress","ai_defense_waf_times_started","ai_defense_waf_times_completed","ai_defense_waf_conquests",
                             "ai_defense_waf1_attempted","ai_defense_waf1_progress","ai_defense_waf1_times_started","ai_defense_waf1_times_completed","ai_defense_waf1_conquests",
                             "ai_ruckus_progress","ai_ruckus_times_started","ai_ruckus_times_completed","ai_ruckus_conquests",
                             "ai_ruckus1_attempted","ai_ruckus1_progress","ai_ruckus1_times_started","ai_ruckus1_times_completed","ai_ruckus1_conquests",
                             "ai_tyrant_progress","ai_tyrant_times_started","ai_tyrant_times_completed","ai_tyrant_conquests",
                             "ai_tyrant1_attempted","ai_tyrant1_progress","ai_tyrant1_times_started","ai_tyrant1_times_completed","ai_tyrant1_conquests",
                             "ai_skar_conquests","ai_skar1_conquests",

                             # add new event player history keys here
                             # YOU MUST ALSO ADD THEM ABOVE AS WELL! SEARCH FOR "ai_ambush_progress"!

                             'resources_looted_from_ai', 'resources_looted_from_human', 'resources_stolen_by_human',
                             'fb_notifications_sent'
                             ] + FEATURE_USE_FIELDS + CLIENT_FIELDS + get_unit_fields(gamedata) + get_item_fields(gamedata):
                    if name in history:
                        obj[name] = history[name]

                # copy these fields directly, omitting if absent in playerdb file
                for field in ['money_spent_by_day',
                              'logins_by_day', 'sessions', 'activity', # 'purchase_ui_log',
                              'friends_in_game', 'initial_friends_in_game',
                              'time_of_first_purchase', 'last_purchase_time',
                              'money_refunded', 'gamebucks_refunded',
                              'payer_promo_offered', 'promo_gamebucks_earned', 'payer_promo_gamebucks_earned', 'fb_gift_cards_redeemed',
                              'quarries_conquered', 'hives_destroyed', 'hive_kill_points', 'hitlist_victories',
                              'random_items_purchased', 'items_purchased', 'free_random_items',
                              'gift_orders_sent', 'gift_orders_received', 'gamebucks_received_from_gift_orders',
                              "gift_orders_refunded", "gift_orders_received_then_refunded", "gamebucks_refunded_from_received_gift_orders",
                              'gamebucks_spent_on_gift_orders',
                              'items_activated', 'items_looted',
                              'gifts_received', 'gifts_sent',
                              'birthday_gifts_received',
                              'fish_completed',
                              gamedata['townhall']+'_level_started',

                              # TIME SERIES needed by ANALYTICS2:
                              'money_spent_at_time', 'gamebucks_spent_at_time',
                              'money_refunded_at_time', 'gamebucks_refunded_at_time',
                              'attacks_launched_at_time', 'attacks_launched_vs_human_at_time', 'attacks_suffered_at_time',
                              'revenge_attacks_launched_vs_human_at_time', 'revenge_attacks_suffered_at_time',
                              'player_level_at_time',

                              # redundant with building:x:max_level_at_time - for legacy code
                              gamedata['townhall']+'_level_at_time'] + \
                              [name+'_level_at_time' for name in get_lab_names(gamedata)] + \
                              ['building:'+name+':max_level_at_time' for name in get_building_names(gamedata)] + \
                              [catname+'_unlocked_at_time' for catname in gamedata['strings']['manufacture_categories']] + \
                              ['tech:'+name+'_at_time' for name in get_tech_names(gamedata)] + \
                              get_viral_fields(gamedata) + \
                              get_fb_notification_fields(gamedata) + \
                              [(currency+'_spent_on_'+thing+'_at_time') for currency in ['money', 'gamebucks'] \
                                   for thing in ['speedups','unit_repair_speedups','base_repairs','building_upgrades','barrier_upgrades',
                                                 'base_growth', 'techs', 'resource_boosts', 'protection', 'base_relocations', 'lottery', 'random_items', 'items', 'gift_orders', 'gamebucks']]:
                    if field in history:
                        obj[field] = history[field]

            if data.has_key('tech'):
                obj['tech'] = data['tech']

            obj['attacks_launched_vs_ai:1007'] = 0
            if data.has_key('battle_history') and data['battle_history'].has_key('1007'):
                obj['attacks_launched_vs_ai:1007'] = data['battle_history']['1007']['count']


            my_base = data['my_base']

            # get levels of important buildings
            obj['inventory_slots_total'] = 0
            obj['inventory_slots_used'] = len(data.get('inventory',[]))

            buildings = set(get_building_names(gamedata))

            obj['research_concurrency'] = 0
            obj['manuf_concurrency'] = 0

            for p in my_base:
                if p['spec'] in buildings:
                    obj[p['spec']+'_level'] = max(obj.get(p['spec']+'_level',0), p.get('level',1))
                    spec = gamedata['buildings'][p['spec']]
                    if 'provides_inventory' in spec:
                        obj['inventory_slots_total'] += spec['provides_inventory'][p.get('level',1)-1]
                    if 'research_start_time' in p:
                        obj['research_concurrency'] += 1
                    if 'manuf_start_time' in p:
                        obj['manuf_concurrency'] += 1

            # get A/B test cohort membership
            if 'abtests' in data:
                for test_name in gamedata['abtests'].iterkeys():
                    if test_name in data['abtests']:
                        obj[test_name] = data['abtests'][test_name]

    # compute dervied metrics

    obj['is_paying_user'] = 0
    obj['is_whale'] = 0
    obj['completed_tutorial'] = 0

    if obj.get('tutorial_state', 'START') == "COMPLETE":
        obj['completed_tutorial'] = 1

    if obj.get('money_spent', 0) > 0:
        obj['is_paying_user'] = 1
        if obj['money_spent'] >= WHALE_LINE:
            obj['is_whale'] = 1

    if 'friends_in_game' in obj:
        if obj['friends_in_game'] >= 10:
            obj['friends_at_least_10'] = 1
        else:
            obj['friends_at_least_10'] = 0

    # check for intervals when a user was reacquired after being lapsed for many days
    sessions = obj.get('sessions',[]) # list of sessions in [ [start1, end1], [start2, end2], ... ] format
    for i in xrange(len(sessions) - 1):
        if sessions[i+1][0] < 0 or sessions[i][1] < 0: continue
        time_between_sessions = sessions[i+1][0] - sessions[i][1]
        for name, seconds in SpinConfig.ACCOUNT_LAPSE_TIMES.iteritems():
            if time_between_sessions >= seconds: # check whether user was ever lapsed for more than the interval length
                obj['reacquired_'+name] = obj.get('reacquired_'+name,0) + 1
                if 'first_time_reacquired_'+name not in obj:
                    obj['first_time_reacquired_'+name] = sessions[i+1][0]
                else:
                    obj['first_time_reacquired_'+name] = min(obj['first_time_reacquired_'+name], sessions[i+1][0])
                if 'last_time_reacquired_'+name not in obj:
                    obj['last_time_reacquired_'+name] = sessions[i+1][0]
                else:
                    obj['last_time_reacquired_'+name] = max(obj['last_time_reacquired_'+name], sessions[i+1][0])

    days_old = -1 # needed for spend_xd and visits_xd metrics (below)
    account_creation_time = -1

    if obj.has_key('account_creation_time'):
        account_creation_time = obj['account_creation_time']
        if account_creation_time > 0:
            days_old = int((time_now - account_creation_time)/(60*60*24))

            # game went live at this time
            join_week = int((account_creation_time - SpinConfig.game_launch_date())/(60*60*24*7))
            obj['join_week'] = join_week

            # attempt to adjust creation_time to user's local time zone
            # (note: does not handle daylight savings time, etc, so is imprecise)
            timezone = obj.get('timezone', 0)
            local_creation_time = account_creation_time + 60*60*int(timezone)

            # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
            tmstruct = time.gmtime(local_creation_time)
            obj['account_creation_wday'] = tmstruct.tm_wday
            obj['account_creation_hour'] = tmstruct.tm_hour

            # note: weekend is Friday->Sunday
            obj['acquired_on_weekend'] = 1 if tmstruct.tm_wday in (4,5,6) else 0

    # NOTE: all computations above are based only on the
    # contents of the userdb/playerdb files. They can safely
    # be cached and re-used across metrics runs IF these files
    # have not been modified since the last time this script
    # ran.

    # NOTE: from this point onwards, some of the computed fields depend on the
    # current time. This means they cannot be re-used if cached.
    # (they are still written into upcache, mostly for doing CSV output, but any "real" analytics
    # tools should NOT reference these fields).

    if account_creation_time > 0:
        # compute retained_xd metrics
        if obj.has_key('last_login_time'):
            last_login_time = obj['last_login_time']
            if last_login_time > 0:
                for days in DAY_MARKS:
                    # only add data if enough time has elapsed to be able to judge
                    if time_now >= (account_creation_time + (days*60*60*24)):
                        interval = last_login_time - account_creation_time
                        if interval > 0 and interval >= (days*60*60*24):
                            retained = 1
                        else:
                            retained = 0
                        obj['retained_%dd' % days] = retained

        # compute returned_x-yh metrics
        for begin, end in ((24,48), (168,192), (672,696)):
            if time_now >= (account_creation_time + end*60*60):
                obj['returned_%d-%dh' % (begin,end)] = 1 if visits_within(obj, end//24, after=begin//24) else 0

    # compute spend_xd and visits_xd metrics
    if days_old >= 0:
        for threshold in DAY_MARKS:
            if days_old >= threshold:
                obj['spend_%dd' % threshold] = 0.0
                obj['visits_%dd' % threshold] = 0
        if 'money_spent_by_day' in obj:
            for strday, amount in obj['money_spent_by_day'].iteritems():
                day = int(strday)
                for threshold in DAY_MARKS:
                    if days_old >= threshold:
                        if day <= threshold:
                            obj['spend_%dd' % threshold] += amount
        if 'logins_by_day' in obj:
            for strday, amount in obj['logins_by_day'].iteritems():
                day = int(strday)
                for threshold in DAY_MARKS:
                    if days_old >= threshold:
                        if day <= threshold:
                            obj['visits_%dd' % threshold] += amount

    return obj

if __name__ == "__main__":
    mode = 'print-csv-fields'

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['mode='])

    for key, val in opts:
        if key == '--mode': mode = val
    if mode == 'print-csv-fields':
        for field in TimeSeriesCSVWriter.SOURCE_FIELDS:
            print field.name,
        print
    elif mode == 'get-facebook-campaign-map':
        # print current FACEBOOK_CAMPAIGN_MAP (e.g. for dumping into an SQL table)
        for k,v in sorted(FACEBOOK_CAMPAIGN_MAP.items()):
            print '%s,%s' % (k,v)
    else:
        raise Exception('unknown mode')
