# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Adaptor that sits on top of the SpinDBClient/SpinNoSQLClient
# database connection and caches the mapping of login platform user IDs to
# game player IDs.

# Due to the that game player IDs never change once assigned, it's safe
# to cache them in local process memory.

class SocialIDCache:
    def __init__(self, db_client):
        assert db_client
        self.db_client = db_client
        self.cache = {}

    def social_id_to_spinpunch(self, social_id, intrusive):
        social_id = str(social_id)
        if self.cache.has_key(social_id):
            return self.cache[social_id]
        result = self.db_client.social_id_to_spinpunch_single(social_id, intrusive)
        if result < 0:
            result = None
        else:
            self.cache[social_id] = result
        return result

    # query a whole bunch of IDs at once efficiently. Return None for social IDs that have no corresponding game user ID.
    def social_id_to_spinpunch_batch(self, social_ids):
        query = []
        index = []
        ret = []
        for id in social_ids:
            if id in (-1, '-1', 0, '0', None): # AIs
                ret.append(None)
            elif self.cache.has_key(id):
                ret.append(self.cache[id])
            else:
                index.append(len(ret))
                ret.append(-2)
                query.append(str(id))

        if len(query) > 0:
            query_ret = self.db_client.social_id_to_spinpunch_batch(query)
            for i in range(len(query)):
                result = query_ret[i]
                if result < 0:
                    result = None
                else:
                    self.cache[query[i]] = result
                ret[index[i]] = result
        return ret

    def update_social_id_single(self, social_id, spin_id):
        self.invalidate_social_id_to_spinpunch_cache_entry(self, social_id)
        return self.db_client.mutate_social_id_to_spinpunch_single(social_id, spin_id)

    def invalidate_social_id_to_spinpunch_cache_entry(self, social_id):
        if social_id in self.cache:
            del self.cache[social_id]

    def invalidate_social_id_to_spinpunch_cache_all(self):
        self.cache = {}
