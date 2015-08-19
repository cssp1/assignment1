-- Copyright (c) 2015 SpinPunch Studios. All rights reserved.
-- Use of this source code is governed by an MIT-style license that can be
-- found in the LICENSE file.

-- GRANT EXECUTE ON skynet.* TO 'chartio'@'%';

-- Guess a correct tgt_purpose for historical ads that are missing it, based on other parameters
DROP FUNCTION IF EXISTS get_ad_purpose;
CREATE FUNCTION get_ad_purpose (tgt_game VARCHAR(64), tgt_version VARCHAR(64), tgt_purpose VARCHAR(64), tgt_keyword VARCHAR(64), tgt_custom_audiences VARCHAR(64))
RETURNS VARCHAR(64) DETERMINISTIC
RETURN IF(tgt_purpose IS NOT NULL,tgt_purpose,
       IF(tgt_version IS NOT NULL AND tgt_version LIKE 'b%','b',
         IF(tgt_keyword IS NOT NULL,'h',
           IF(tgt_custom_audiences LIKE 'lap%','l',
             IF(tgt_custom_audiences LIKE CONCAT(tgt_game, '-%'),'r',
               IF(tgt_custom_audiences IS NOT NULL, 'x', NULL))))));

-- REST OF THIS FILE IS OBSOLETE! - this is now handled by skynet_summary_to_sql.py

-- Summary of receipts/installs for one day's worth of aquisitions
CREATE OR REPLACE VIEW v_conversions_by_cohort AS
SELECT 86400*FLOOR(account_creation_time/86400.0) AS cohort_day,
       tgt_game,
       tgt_version,
       tgt_bid_type,
       tgt_ad_type,
       tgt_country,
       tgt_age_range,
       get_ad_purpose(tgt_game, tgt_version, tgt_purpose, tgt_keyword, tgt_custom_audiences) AS ad_purpose,
       SUM(usd_receipts_cents) AS cohort_receipts_cents,
       SUM(IF(time - account_creation_time < 90*86400, usd_receipts_cents,0)) AS cohort_receipts_d90_cents,
       SUM(IF(kpi='acquisition_event',1,0)) AS cohort_installs
FROM conversions
GROUP BY 86400*FLOOR(account_creation_time/86400.0), tgt_game, tgt_version, tgt_bid_type, tgt_ad_type, tgt_country, tgt_version, get_ad_purpose(tgt_game, tgt_version, tgt_purpose, tgt_keyword, tgt_custom_audiences);

-- Summary of receipts/installs for one day of clock time
CREATE OR REPLACE VIEW v_conversions_by_time AS
SELECT 86400*FLOOR(time/86400.0) AS day,
       tgt_game,
       tgt_version,
       tgt_bid_type,
       tgt_ad_type,
       tgt_country,
       tgt_age_range,
       get_ad_purpose(tgt_game, tgt_version, tgt_purpose, tgt_keyword, tgt_custom_audiences) AS ad_purpose,
       SUM(usd_receipts_cents) AS daily_receipts_cents,
       SUM(IF(kpi='acquisition_event',1,0)) AS daily_installs
FROM conversions
GROUP BY 86400*FLOOR(time/86400.0), tgt_game, tgt_version, tgt_bid_type, tgt_ad_type, tgt_country, tgt_age_range, get_ad_purpose(tgt_game, tgt_version, tgt_purpose, tgt_keyword, tgt_custom_audiences);

-- Summary of ad costs for one day of clock time
CREATE OR REPLACE VIEW v_adstats_daily AS
SELECT 86400*FLOOR(time/86400.0) AS day,
       tgt_game,
       tgt_version,
       tgt_bid_type,
       tgt_ad_type,
       tgt_country,
       tgt_age_range,
       get_ad_purpose(tgt_game, tgt_version, tgt_purpose, tgt_keyword, tgt_custom_audiences) AS ad_purpose,
       SUM(impressions) AS impressions,
       SUM(clicks) AS clicks,
       SUM(spent) AS spent_cents
FROM adstats_hourly
GROUP BY 86400*FLOOR(time/86400.0), tgt_game, tgt_version, tgt_bid_type, tgt_ad_type, tgt_country, tgt_age_range, get_ad_purpose(tgt_game, tgt_version, tgt_purpose, tgt_keyword, tgt_custom_audiences);

-- Join adstat, cohort, and clock-time data into a summary
-- note: MySQL does not support OUTER JOIN
-- CREATE OR REPLACE VIEW v_daily_summary_raw AS
-- SELECT stats.*,
--        cohort.cohort_receipts_cents,
--        cohort.cohort_receipts_d90_cents,
--        cohort.cohort_installs,
--        today.daily_receipts_cents,
--        today.daily_installs
-- FROM v_adstats_daily AS stats
-- OUTER JOIN v_conversions_by_cohort AS cohort ON (
--      cohort.cohort_day = stats.day
--      AND cohort.tgt_game = stats.tgt_game
--      AND cohort.tgt_version = stats.tgt_version
--      AND cohort.tgt_bid_type = stats.tgt_bid_type
--      AND cohort.tgt_ad_type = stats.tgt_ad_type
--      AND cohort.ad_purpose = stats.ad_purpose)
-- OUTER JOIN v_conversions_by_time AS today ON (
--      today.day = stats.day
--      AND today.tgt_game = stats.tgt_game
--      AND today.tgt_version = stats.tgt_version
--      AND today.tgt_bid_type = stats.tgt_bid_type
--      AND today.tgt_ad_type = stats.tgt_ad_type
--      AND today.ad_purpose = stats.ad_purpose);

-- hacky UNION version that accomplishes the same thing
-- (as long as you remember to SUM() the data you want over some function of "day")
CREATE OR REPLACE VIEW v_daily_summary_raw AS
SELECT day,
       tgt_game,
       tgt_version,
       tgt_bid_type,
       tgt_ad_type,
       tgt_country,
       tgt_age_range,
       ad_purpose,
       impressions,
       clicks,
       spent_cents,
       0 AS cohort_receipts_cents,
       0 AS cohort_receipts_d90_cents,
       0 AS cohort_installs,
       0 AS daily_receipts_cents,
       0 AS daily_installs
FROM v_adstats_daily AS stats
UNION
SELECT cohort_day AS day,
       tgt_game,
       tgt_version,
       tgt_bid_type,
       tgt_ad_type,
       tgt_country,
       tgt_age_range,
       ad_purpose,
       0 AS impressions,
       0 AS clicks,
       0 AS spent_cents,
       cohort_receipts_cents,
       cohort_receipts_d90_cents,
       cohort_installs,
       0 AS daily_receipts_cents,
       0 AS daily_installs
FROM v_conversions_by_cohort AS cohort
UNION
SELECT day,
       tgt_game,
       tgt_version,
       tgt_bid_type,
       tgt_ad_type,
       tgt_country,
       tgt_age_range,
       ad_purpose,
       0 AS impressions,
       0 AS clicks,
       0 AS spent_cents,
       0 AS cohort_receipts_cents,
       0 AS cohort_receipts_d90_cents,
       0 AS cohort_installs,
       daily_receipts_cents,
       daily_installs
FROM v_conversions_by_time AS daily;

-- obsolete, see skynet_summary_to_sql.py
-- DROP TABLE IF EXISTS v_daily_summary; CREATE TABLE v_daily_summary SELECT * FROM v_daily_summary_raw;
