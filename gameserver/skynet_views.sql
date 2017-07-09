-- Copyright (c) 2015 Battlehouse Inc. All rights reserved.
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

-- REST OF THIS FILE IS OBSOLETE! summaries are now handled by skynet_summary_to_sql.py
