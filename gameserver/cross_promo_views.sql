-- Copyright (c) 2015 Battlehouse Inc. All rights reserved.
-- Use of this source code is governed by an MIT-style license that can be
-- found in the LICENSE file.

-- v_cross_promo_events: concatenate impression, click, and install events for all game-to-game cross promotions
-- OBSOLETE! - this is now handled by cross_promo_summary_to_sql.py

-- sample spec: '5145_xp_Amf_abfm_bx_x20140713'
CREATE OR REPLACE VIEW v_cross_promo_events AS
SELECT time AS time,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',3),'_',-1) FROM 2) AS from_game,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',4),'_',-1) FROM 2) AS to_game,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',6),'_',-1) FROM 2) AS image,
       IF(event_name='7530_cross_promo_banner_seen',1,0) AS impressions,
       IF(event_name='7531_cross_promo_banner_clicked',1,0) AS clicks,
       0 AS installs
FROM mf_upcache.mf_metrics WHERE code >= 7530 AND code <= 7531
UNION ALL
SELECT account_creation_time AS time,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',3),'_',-1) FROM 2) AS from_game,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',4),'_',-1) FROM 2) AS to_game,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',6),'_',-1) FROM 2) AS image,
        0 AS impressions,
        0 AS clicks,
        1 AS installs
FROM mf_upcache.mf_upcache_lite WHERE acquisition_campaign LIKE '5145_xp_A%'
UNION ALL
SELECT time,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',3),'_',-1) FROM 2) AS from_game,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',4),'_',-1) FROM 2) AS to_game,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',6),'_',-1) FROM 2) AS image,
       IF(event_name='7530_cross_promo_banner_seen',1,0) AS impressions,
       IF(event_name='7531_cross_promo_banner_clicked',1,0) AS clicks,
       0 AS installs
FROM mf2_upcache.mf2_metrics WHERE code >= 7530 AND code <= 7531
UNION ALL
SELECT account_creation_time AS time,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',3),'_',-1) FROM 2) AS from_game,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',4),'_',-1) FROM 2) AS to_game,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',6),'_',-1) FROM 2) AS image,
        0 AS impressions,
        0 AS clicks,
        1 AS installs
FROM mf2_upcache.mf2_upcache WHERE acquisition_campaign LIKE '5145_xp_A%'
UNION ALL
SELECT time,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',3),'_',-1) FROM 2) AS from_game,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',4),'_',-1) FROM 2) AS to_game,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',6),'_',-1) FROM 2) AS image,
       IF(event_name='7530_cross_promo_banner_seen',1,0) AS impressions,
       IF(event_name='7531_cross_promo_banner_clicked',1,0) AS clicks,
       0 AS installs
FROM tr_upcache.tr_metrics WHERE code >= 7530 AND code <= 7531
UNION ALL
SELECT account_creation_time AS time,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',3),'_',-1) FROM 2) AS from_game,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',4),'_',-1) FROM 2) AS to_game,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',6),'_',-1) FROM 2) AS image,
        0 AS impressions,
        0 AS clicks,
        1 AS installs
FROM tr_upcache.tr_upcache WHERE acquisition_campaign LIKE '5145_xp_A%'
UNION ALL
SELECT time,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',3),'_',-1) FROM 2) AS from_game,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',4),'_',-1) FROM 2) AS to_game,
       SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',6),'_',-1) FROM 2) AS image,
       IF(event_name='7530_cross_promo_banner_seen',1,0) AS impressions,
       IF(event_name='7531_cross_promo_banner_clicked',1,0) AS clicks,
       0 AS installs
FROM bfm_upcache.bfm_metrics WHERE code >= 7530 AND code <= 7531
UNION ALL
SELECT account_creation_time AS time,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',3),'_',-1) FROM 2) AS from_game,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',4),'_',-1) FROM 2) AS to_game,
        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',6),'_',-1) FROM 2) AS image,
        0 AS impressions,
        0 AS clicks,
        1 AS installs
FROM bfm_upcache.bfm_upcache WHERE acquisition_campaign LIKE '5145_xp_A%'
;
-- SELECT * from v_cross_promo_events limit 10;

-- create and cache a daily summary of this

CREATE OR REPLACE VIEW v_cross_promo_daily_summary_raw AS
SELECT 86400*FLOOR(time/86400.0) AS day,
       from_game,
       to_game,
       CONCAT(from_game, '->', to_game) AS combo,
       image,
       SUM(impressions) AS impressions,
       SUM(clicks) AS clicks,
       SUM(installs) AS installs,
       IF(SUM(impressions)>0,SUM(clicks)/SUM(impressions),NULL) AS ctr
FROM v_cross_promo_events
GROUP BY day, from_game, to_game, image;
-- SELECT * from v_cross_promo_daily_summary;

DROP TABLE IF EXISTS v_cross_promo_daily_summary; CREATE TABLE v_cross_promo_daily_summary SELECT * FROM v_cross_promo_daily_summary_raw;
