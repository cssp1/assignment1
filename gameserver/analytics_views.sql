-- Copyright (c) 2015 Battlehouse Inc. All rights reserved.
-- Use of this source code is governed by an MIT-style license that can be
-- found in the LICENSE file.

-- This should run AFTER all the raw event data and summaries are available in SQL.
-- It depends on all other ETL scripts being run first, EXCEPT for upcache and anything that is derived from upcache.

-- note: this script is run through a string substitution to replace $GAME_ID with "mf" "tr" etc

-- -------------------
-- SERIES GENERATOR --
-- -------------------

-- create some utility tables that are just lists of UNIX timestamps:
-- u_daily_series: table of day start timestamps for the time range covered by the "sessions" table
-- u_hourly_series: table of hour start timestamps for the time range covered by the "sessions" table

DROP PROCEDURE IF EXISTS make_series;
DELIMITER $$
CREATE PROCEDURE make_series (table_name VARCHAR(255), start INT8, end INT8, step INT8)
BEGIN
        WHILE start < end DO
              SET @qs = CONCAT('INSERT INTO ', table_name, ' VALUES (', start, ',', step, ')');
              PREPARE stmt FROM @qs; EXECUTE stmt; DEALLOCATE PREPARE stmt;
              SET start = start + step;
        END WHILE;
END $$
DELIMITER ;
DROP TABLE IF EXISTS u_daily_series; CREATE TABLE u_daily_series (t INT8, dt INT8);
-- limit daily series to going back no more than 30 days before present
CALL make_series('u_daily_series', 86400*(FLOOR(GREATEST((SELECT MIN(start) FROM $GAME_ID_sessions), UNIX_TIMESTAMP()-30*86400)/86400)), 86400*(FLOOR((SELECT MAX(start) FROM $GAME_ID_sessions)/86400)+1), 86400);
DROP TABLE IF EXISTS u_hourly_series; CREATE TABLE u_hourly_series (t INT8, dt INT8);
-- limit hourly series to going back no more than 15 days before present
CALL make_series('u_hourly_series', 3600*(FLOOR(GREATEST((SELECT MIN(start) FROM $GAME_ID_sessions), UNIX_TIMESTAMP()-15*86400)/3600)), 3600*(FLOOR((SELECT MAX(start) FROM $GAME_ID_sessions)/3600)+1), 3600);

-- -------------------
-- DAU/HAU TRACKING --
-- -------------------

CREATE OR REPLACE VIEW $GAME_ID_sessions_daily_summary_v AS SELECT *, day + 14*86400 AS day_two_weeks_ahead, day + 7*86400 AS day_week_ahead, day - $LAUNCH_DATE AS day_since_launch FROM $GAME_ID_sessions_daily_summary;
CREATE OR REPLACE VIEW $GAME_ID_sessions_hourly_summary_v AS SELECT *, hour + 14*86400 AS hour_two_weeks_ahead, hour + 7*86400 AS hour_week_ahead, hour - $LAUNCH_DATE AS hour_since_launch FROM $GAME_ID_sessions_hourly_summary;
CREATE OR REPLACE VIEW $GAME_ID_sessions_monthly_summary_v AS SELECT *, month + 28*86400 AS month_28d_ahead, month - $LAUNCH_DATE AS month_since_launch FROM $GAME_ID_sessions_monthly_summary;

CREATE OR REPLACE VIEW $GAME_ID_metrics_tutorial_v AS
SELECT metrics.time,
       metrics.frame_platform,
       metrics.country_tier,
       metrics.townhall_level,
       metrics.prev_receipts,
       IF(metrics.event_name IN ('0140_tutorial_oneway_ticket','0140_tutorial_start'),1,NULL) AS tut_start,
       IF(metrics.event_name = '0399_tutorial_complete',1,NULL) AS tut_complete
FROM $GAME_ID_metrics metrics
WHERE metrics.event_name IN ('0140_tutorial_oneway_ticket', '0140_tutorial_start', '0399_tutorial_complete');

-- ----------------------------
-- FACEBOOK CAMPAIGN PARSING --
-- ----------------------------

-- remap acquisition_campaign values that come from clicks on various Facebook UI elements to be more readable
-- this is based on SpinUpcache.py's remap_facebook_campaigns() function, and should be kept in sync!
-- note: relies on the facebook_campaign_map table created by upcache_to_mysql.py
DROP FUNCTION IF EXISTS remap_facebook_campaigns;
DELIMITER $$
CREATE FUNCTION remap_facebook_campaigns (x VARCHAR(128))
RETURNS VARCHAR(128) DETERMINISTIC
BEGIN
        IF (x LIKE 'viral_%' OR x LIKE 'open_graph_%') THEN
           RETURN 'game_viral';
        END IF;
        IF (x LIKE '%_XP_%') OR (x LIKE '%5145_xp_%') THEN
           RETURN 'cross_promo_free'; -- in-game cross promo
        END IF;
        IF (x LIKE '%_bx_%') THEN
           RETURN 'cross_promo_paid'; -- Skynet paid cross promo
        END IF;
        IF (x LIKE '7112_%') THEN
           RETURN 'battlehouse'; -- click from battlehouse.com
        END IF;
        IF (x LIKE '%/') THEN
           SET x = SUBSTRING(x, 1, CHAR_LENGTH(x)-1);
        END IF;
        IF (x LIKE '%.com%') THEN
           SET x = CONCAT(SUBSTRING_INDEX(x,'.com',1), '.com');
        END IF;
        IF(x LIKE 'canvasbookmark_feat%') THEN
           SET x = 'canvasbookmark_featured';
        END IF;
        RETURN IFNULL((SELECT `to` FROM $GAME_ID_facebook_campaign_map WHERE `from` = x), x);
END $$
DELIMITER ;

-- General classifier for all sorts of acquisition sources.
-- This mirrors the behavior of overlay_mode = 'acquisition_paid_or_free' of cgianalytics.py.
DROP FUNCTION IF EXISTS classify_acquisition_campaign;
DELIMITER $$
CREATE FUNCTION classify_acquisition_campaign (frame_platform VARCHAR(2), camp VARCHAR(128))
RETURNS VARCHAR(128) DETERMINISTIC
BEGIN
        IF frame_platform = 'kg' OR frame_platform = 'k2' THEN
           RETURN 'Kongregate';
        ELSEIF frame_platform = 'ag' THEN
           RETURN 'Armor Games';
        ELSEIF frame_platform = 'bh' THEN
       RETURN CASE camp
       WHEN 'bh_invite' THEN 'BH Invite'
       WHEN 'google' THEN 'BH Google Paid'
       WHEN '7124_GG' THEN 'BH Google Paid'
       WHEN '7120_SRD' THEN 'BH FB Paid'
       WHEN '7130_YT' THEN 'BH YouTube Free'
       WHEN '7131_MC' THEN 'BH MailChimpFree'
       WHEN '7132_YT_cpc' THEN 'BH YouTube Paid'
       WHEN '7133_GG' THEN 'BH Bing Paid'
       WHEN '7133_BG' THEN 'BH Bing Paid'
       ELSE IF(camp LIKE '%_bx_%', 'BH Cross-Promo',
               IF(camp LIKE '712%', 'BH Free (BH.com Link)', 'BH Other')) END;
        ELSEIF frame_platform = 'fb' THEN
           -- if camp maps to facebook_free or game_viral, return those
           -- if camp maps to MISSING, then ignore (!) this user (this is what ANALYTICS2 does - maybe we should report it as 'FB MISSING' instead?)
           -- otherwise, map to 'paid'
           RETURN (CASE (SELECT remap_facebook_campaigns(camp)) COLLATE utf8mb4_unicode_ci
           WHEN 'facebook_free' THEN 'FB Free (Facebook)'
           WHEN 'fb_page' THEN 'FB Free (Fan Page)'
           WHEN 'game_viral' THEN 'FB Free (Game Viral)'
           WHEN 'cross_promo' THEN 'Cross Promo (Paid)' -- legacy data
           WHEN 'cross_promo_paid' THEN 'Cross Promo (Paid)'
           WHEN 'cross_promo_free' THEN 'Cross Promo (Free)'
           WHEN 'battlehouse' THEN 'Battlehouse'
           WHEN 'MISSING' THEN NULL
           ELSE 'FB Paid' END);
        ELSE
           RETURN NULL;
        END IF;
END $$
DELIMITER ;

-- -------------------------
-- FACEBOOK NOTIFICATIONS --
-- -------------------------

-- parse away the "_24h"/"_168h" added to FB notification fb_ref strings when the notification is sent in the critical window
DROP FUNCTION IF EXISTS parse_fb_notification_fb_ref;
DELIMITER $$
CREATE FUNCTION parse_fb_notification_fb_ref (fb_ref VARCHAR(128))
RETURNS VARCHAR(128) DETERMINISTIC
BEGIN
        RETURN REPLACE(REPLACE(fb_ref, '_24h', ''), '_168h', '');
END $$
DELIMITER ;

CREATE OR REPLACE VIEW $GAME_ID_fb_notifications_daily_summary_v AS
SELECT *,
       IF(event_name = '7130_fb_notification_sent',count,0) AS sends,
       IF(event_name = '7131_fb_notification_hit',count,0) AS hits,
       parse_fb_notification_fb_ref(fb_ref) AS canonical_ref
FROM $GAME_ID_fb_notifications_daily_summary;

-- -----------------------
-- FACEBOOK PERMISSIONS --
-- -----------------------

CREATE OR REPLACE VIEW $GAME_ID_fb_permissions_v AS
SELECT time, anon_id, country, country_tier, browser_os, browser_name, browser_version, splash_image,
       IF(event_name = '0031_request_permission_prompt', 1, 0) AS prompts,
       IF(event_name = '0032_request_permission_prompt_success', 1, 0) AS accepts
FROM $GAME_ID_fb_permissions
WHERE method = 'fb_guest_page' AND
      ((event_name = '0031_request_permission_prompt' AND attempts = 0) OR -- only count first attempt per session as a "prompt"
       (event_name = '0032_request_permission_prompt_success'))
;

-- --------------
-- PURCHASE UI --
-- --------------

CREATE OR REPLACE VIEW $GAME_ID_credits_daily_summary_v AS SELECT *, day + 14*86400 AS day_two_weeks_ahead, day + 7*86400 AS day_week_ahead, day - $LAUNCH_DATE AS day_since_launch FROM $GAME_ID_credits_daily_summary;

-- v_credits: add is_first_purchase
CREATE OR REPLACE VIEW v_credits AS
SELECT *,
       1-EXISTS(SELECT 1 FROM $GAME_ID_credits cr2 WHERE cr2.user_id = credits.user_id AND cr2.time < credits.time) AS is_first_purchase
FROM $GAME_ID_credits credits;
-- test: SELECT count(1), is_first_purchase FROM v_credits GROUP BY is_first_purchase;

-- v_purchase_ui_daily_summary: for Chartio
-- XXXXXX this needs to be made independent of upcache by using denormalized summary dimensinos
-- CREATE OR REPLACE VIEW v_purchase_ui_daily_summary AS
-- SELECT 86400*FLOOR(purchase_ui.time/86400.0) AS day,
--        SUM(IF(event_name = '4410_buy_gamebucks_dialog_open',1,0)) AS buy_gamebucks_dialog_opens,
--        SUM(IF(event_name = '4440_buy_gamebucks_init_payment',1,0)) AS payment_inits,
--        SUM(IF(event_name = '4450_buy_gamebucks_payment_complete',1,0)) AS payment_completes,
--        SUM(IF(event_name = '4440_buy_gamebucks_init_payment',1,0))/SUM(IF(event_name = '4410_buy_gamebucks_dialog_open',1,0)) AS payment_init_rate,
--        SUM(IF(event_name = '4450_buy_gamebucks_payment_complete',1,0))/SUM(IF(event_name = '4440_buy_gamebucks_init_payment',1,0)) AS payment_complete_rate,
--        SUM(IF(event_name = '4450_buy_gamebucks_payment_complete',1,0)) AS num_purchases,
--        SUM(IF(event_name = '4450_buy_gamebucks_payment_complete',gamebucks,0)) AS gamebucks_purchased,
--        IF(upcache.country_tier IS NOT NULL, upcache.country_tier, '4') AS country_tier,
--        IF(upcache.money_spent IS NOT NULL AND upcache.money_spent>0,1,0) AS is_payer,
--        IF(gui_version IS NOT NULL, gui_version, 1) AS gui_version
-- FROM $GAME_ID_purchase_ui purchase_ui
-- LEFT JOIN $UPCACHE_TABLE upcache ON upcache.user_id = purchase_ui.user_id
-- GROUP BY 86400*FLOOR(purchase_ui.time/86400.0),
--          IF(upcache.country_tier IS NOT NULL, upcache.country_tier, '4'),
--          IF(upcache.money_spent IS NOT NULL AND upcache.money_spent>0,1,0),
--          IF(gui_version IS NOT NULL, gui_version, 1)
-- ORDER BY NULL;

-- ---------------------
-- BATTLE RISK/REWARD --
-- ---------------------

--  functions to help compute risk/reward for each individual battle
-- "value" quantities are all in units of gamebucks, where positive = good for the player, negative = bad for the player
-- note: pricing formulas below are symmetric with respect to negative input amounts F(-x) = -F(x)
-- this makes accounting easier since we can freely sum negative and positive values

-- convert an item's value to gamebucks
DROP FUNCTION IF EXISTS item_price; -- obsolete
DROP FUNCTION IF EXISTS item_value;
CREATE FUNCTION item_value (specname VARCHAR(128), stack INT, townhall_level INT, prev_receipts FLOAT)
RETURNS INT DETERMINISTIC
RETURN CASE WHEN stack<=0 THEN 0 -- negative stack
        WHEN specname LIKE 'boost_res3_%' THEN res3_value(CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(specname,'_',3),'_',-1) AS UNSIGNED), townhall_level, prev_receipts) -- res3 resource boosts
        WHEN specname LIKE 'boost_iron_%' THEN iron_value(CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(specname,'_',3),'_',-1) AS UNSIGNED), townhall_level, prev_receipts) -- iron/water resource
        WHEN specname LIKE 'boost_water_%' THEN water_value(CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(specname,'_',3),'_',-1) AS UNSIGNED), townhall_level, prev_receipts) -- iron/water resource
        WHEN specname LIKE 'mine_%' THEN stack*5 -- landmines
        WHEN specname = 'gamebucks' OR specname = 'alloy' THEN stack
            WHEN (SELECT value_str from $GAME_ID_stats WHERE kind = 'item' AND spec = specname AND stat = 'category') = 'token' THEN
             IFNULL((SELECT value_num from $GAME_ID_stats WHERE kind = 'item' AND spec = specname AND stat = 'analytics_value_coeff'),1) * token_value(stack, townhall_level, prev_receipts) -- special case for tokens
        WHEN EXISTS(SELECT value_num from $GAME_ID_stats WHERE kind = 'item' AND spec = specname AND stat = 'analytics_value') -- check for manual override
             THEN FLOOR(stack*(SELECT value_num from $GAME_ID_stats WHERE kind = 'item' AND spec = specname AND stat = 'analytics_value'))
        ELSE 0 -- anything else
        END;

-- return the analytics_tag that was in effect for a given base_type, base_template, and (AI) user_id at time t
DROP FUNCTION IF EXISTS get_analytics_tag;
CREATE FUNCTION get_analytics_tag (base_type VARCHAR(8), base_template VARCHAR(32), user_id INT4, t INT8)
RETURNS VARCHAR(32) DETERMINISTIC
RETURN (SELECT DISTINCT(analytics_tag) FROM $GAME_ID_ai_analytics_tag_assignments assign
           WHERE (((base_type = 'hive' OR SUBSTRING(base_type, 1, 4) = 'raid') AND
                   assign.base_type = base_type AND
                   assign.base_template = base_template AND
                   assign.user_id = -1)
                  OR
                  (base_type = 'home' AND
                   assign.base_type = base_type AND
                   assign.base_template = 'home' AND
                   assign.user_id = user_id))
                  AND -- timing matches
                 (((assign.start_time = -1) OR (t >= assign.start_time)) -- event is not in the future
                  AND
                  ((assign.end_time = -1) OR
                   (t < assign.end_time) OR -- event is not in the past
                   ((assign.repeat_interval IS NOT NULL) AND -- event repeats and we are during a repeat
                    (MOD(t - assign.start_time, assign.repeat_interval) < (assign.end_time - assign.start_time)))
                 )));

-- NOTE! now see battle_risk_reward_to_sql.py, which materializes some risk_reward views for much better speed

-- note: wrap this in a procedure since it cannot run on MF, which has no battles table
DROP PROCEDURE IF EXISTS make_battle_risk_reward_views;
DELIMITER $$
CREATE PROCEDURE make_battle_risk_reward_views ()
BEGIN
IF (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '$GAME_ID_battles') THEN

DROP VIEW IF EXISTS v_battle_risk_reward_individual;
DROP VIEW IF EXISTS v_battle_risk_reward_summary_raw;
DROP VIEW IF EXISTS v_battle_risk_reward_summary;

-- alias to support old users of this table
-- CREATE OR REPLACE VIEW v_battle_risk_reward_summary AS SELECT * FROM $GAME_ID_battles_risk_reward_daily_summary;

-- supplemental summary view that takes an overall look at a given analytics tag (event)
CREATE OR REPLACE VIEW v_battle_risk_reward_summary_by_tag AS
SELECT day,
       FLOOR((day-1337274000)/(7*86400)) AS week_num, -- live ops week number - see matchmaking.json for the correct "week_origin" value
       townhall_level AS player_townhall_level,
       base_type,
       base_template,
       opponent_id,
       analytics_tag,
       battle_type,
       SUM(n_unique_players) AS unique_players,
       SUM(n_battles) AS n_battles,
       SUM(n_victories) AS n_victories,
       SUM(n_victories)/SUM(n_unique_players) AS avg_victories,
       SUM(total_duration)/60.0 AS total_mins,
       (SUM(total_duration)/60.0)/SUM(n_unique_players) AS avg_mins,
       SUM(total_gamebucks_spent_5min) AS total_gamebucks_spent_5min,
       SUM(total_gamebucks_spent_5min)/SUM(n_unique_players) AS avg_gamebucks_spent_5min,
       ROUND(SUM(loot_res_value)/SUM(n_unique_players)) AS avg_loot_res,
       ROUND(SUM(loot_items_value)/SUM(n_unique_players)) AS avg_loot_items,
       ROUND(SUM(consumed_items_value)/SUM(n_unique_players)) AS avg_consumed_items,
       ROUND(SUM(damage_res_value)/SUM(n_unique_players)) AS avg_damage_res,
       ROUND(SUM(damage_time_value)/SUM(n_unique_players)) AS avg_damage_time,
       ROUND(SUM(total_risk)/SUM(n_unique_players)) AS avg_risk,
       ROUND(SUM(total_reward)/SUM(n_unique_players)) AS avg_reward,
       ROUND(SUM(total_profit)/SUM(n_unique_players)) AS avg_profit
FROM $GAME_ID_battles_risk_reward_daily_summary
GROUP BY day, player_townhall_level, base_type, base_template, opponent_id, analytics_tag ORDER BY NULL;

CREATE OR REPLACE VIEW v_battle_risk_reward_weekly_summary_by_tag AS
SELECT week,
       FLOOR((week-1337274000)/(7*86400)) AS week_num, -- live ops week number - see matchmaking.json for the correct "week_origin" value
       townhall_level AS player_townhall_level,
       base_type,
       base_template,
       opponent_id,
       analytics_tag,
       battle_type,
       SUM(n_unique_players) AS unique_players,
       SUM(n_battles) AS n_battles,
       SUM(n_victories) AS n_victories,
       SUM(n_victories)/SUM(n_unique_players) AS avg_victories,
       SUM(total_duration)/60.0 AS total_mins,
       (SUM(total_duration)/60.0)/SUM(n_unique_players) AS avg_mins,
       SUM(total_gamebucks_spent_5min) AS total_gamebucks_spent_5min,
       SUM(total_gamebucks_spent_5min)/SUM(n_unique_players) AS avg_gamebucks_spent_5min,
       ROUND(SUM(loot_res_value)/SUM(n_unique_players)) AS avg_loot_res,
       ROUND(SUM(loot_items_value)/SUM(n_unique_players)) AS avg_loot_items,
       ROUND(SUM(consumed_items_value)/SUM(n_unique_players)) AS avg_consumed_items,
       ROUND(SUM(damage_res_value)/SUM(n_unique_players)) AS avg_damage_res,
       ROUND(SUM(damage_time_value)/SUM(n_unique_players)) AS avg_damage_time,
       ROUND(SUM(total_risk)/SUM(n_unique_players)) AS avg_risk,
       ROUND(SUM(total_reward)/SUM(n_unique_players)) AS avg_reward,
       ROUND(SUM(total_profit)/SUM(n_unique_players)) AS avg_profit
FROM $GAME_ID_battles_risk_reward_weekly_summary
GROUP BY week, player_townhall_level, base_type, base_template, opponent_id, analytics_tag ORDER BY NULL;

CREATE OR REPLACE VIEW v_battle_risk_reward_cc5plus_hourly_summary_by_tag AS
SELECT hour,
       FLOOR((hour-1337274000)/(7*86400)) AS week_num, -- live ops week number - see matchmaking.json for the correct "week_origin" value
       townhall_level AS player_townhall_level,
       base_type,
       base_template,
       opponent_id,
       analytics_tag,
       battle_type,
       SUM(n_unique_players) AS unique_players,
       SUM(n_battles) AS n_battles,
       SUM(n_victories) AS n_victories,
       SUM(n_victories)/SUM(n_unique_players) AS avg_victories,
       SUM(total_duration)/60.0 AS total_mins,
       (SUM(total_duration)/60.0)/SUM(n_unique_players) AS avg_mins,
       SUM(total_gamebucks_spent_5min) AS total_gamebucks_spent_5min,
       SUM(total_gamebucks_spent_5min)/SUM(n_unique_players) AS avg_gamebucks_spent_5min,
       ROUND(SUM(loot_res_value)/SUM(n_unique_players)) AS avg_loot_res,
       ROUND(SUM(loot_items_value)/SUM(n_unique_players)) AS avg_loot_items,
       ROUND(SUM(consumed_items_value)/SUM(n_unique_players)) AS avg_consumed_items,
       ROUND(SUM(damage_res_value)/SUM(n_unique_players)) AS avg_damage_res,
       ROUND(SUM(damage_time_value)/SUM(n_unique_players)) AS avg_damage_time,
       ROUND(SUM(total_risk)/SUM(n_unique_players)) AS avg_risk,
       ROUND(SUM(total_reward)/SUM(n_unique_players)) AS avg_reward,
       ROUND(SUM(total_profit)/SUM(n_unique_players)) AS avg_profit
FROM $GAME_ID_battles_risk_reward_cc5plus_hourly_summary
GROUP BY hour, player_townhall_level, base_type, base_template, opponent_id, analytics_tag ORDER BY NULL;

CREATE OR REPLACE VIEW v_battle_risk_reward_summary_by_tag_human_readable AS
SELECT townhall_level AS player_townhall_level,
       base_type,
       base_template,
       opponent_id,
       analytics_tag,
       battle_type,
       SUM(n_unique_players) AS unique_players,
       SUM(n_battles) AS n_battles,
       SUM(n_victories) AS n_victories,
       SUM(n_victories)/SUM(n_unique_players) AS avg_victories,
       SUM(total_duration)/60.0 AS total_mins,
       (SUM(total_duration)/60.0)/SUM(n_unique_players) AS avg_mins,
       SUM(total_gamebucks_spent_5min) AS total_gamebucks_spent_5min,
       SUM(total_gamebucks_spent_5min)/SUM(n_unique_players) AS avg_gamebucks_spent_5min,
       ROUND(SUM(loot_res_value)/SUM(n_unique_players)) AS avg_loot_res,
       ROUND(SUM(loot_items_value)/SUM(n_unique_players)) AS avg_loot_items,
       ROUND(SUM(consumed_items_value)/SUM(n_unique_players)) AS avg_consumed_items,
       ROUND(SUM(damage_res_value)/SUM(n_unique_players)) AS avg_damage_res,
       ROUND(SUM(damage_time_value)/SUM(n_unique_players)) AS avg_damage_time,
       ROUND(SUM(total_risk)/SUM(n_unique_players)) AS avg_risk,
       ROUND(SUM(total_reward)/SUM(n_unique_players)) AS avg_reward,
       ROUND(SUM(total_profit)/SUM(n_unique_players)) AS avg_profit
FROM $GAME_ID_battles_risk_reward_daily_summary
GROUP BY analytics_tag, player_townhall_level, base_type, base_template, opponent_id;

END IF;
END $$
DELIMITER ;
CALL make_battle_risk_reward_views();
DROP PROCEDURE make_battle_risk_reward_views;
