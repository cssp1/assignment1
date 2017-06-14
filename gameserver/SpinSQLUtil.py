#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# generic SQL utility library, helps adapt between MySQL/Postgres
# and includes some data-warehousing tools

class SQLUtil(object):
    def disable_warnings(self): pass
    def sym(self, s):
        return '"'+s+'"'
    def bit_type(self): return 'BIT(1)'
    def do_insert(self, cur, table_name, keyvals):
        cur.execute("INSERT INTO " + self.sym(table_name) + \
                    "("+', '.join([self.sym(x[0]) for x in keyvals])+")"+ \
                    " VALUES ("+', '.join(['%s'] * len(keyvals)) +")",
                    [x[1] for x in keyvals])
        return cur.rowcount or 0

    def do_insert_batch(self, cur, table_name, keyvals_list):
        if len(keyvals_list) < 1: return 0
        cur.executemany("INSERT INTO " + self.sym(table_name) + \
                        "("+', '.join([self.sym(x[0]) for x in keyvals_list[0]])+")"+ \
                        " VALUES ("+', '.join(['%s'] * len(keyvals_list[0])) +")",
                        [[x[1] for x in keyvals] for keyvals in keyvals_list])
        return cur.rowcount or 0

    # return the standard dimensions for summary tables
    def summary_in_dimensions(self, prefix=''):
        return [(prefix+'frame_platform', 'CHAR(2)'),
                (prefix+'country_tier', 'CHAR(1)'),
                (prefix+'townhall_level', 'INT4'),
                (prefix+'prev_receipts', 'FLOAT4')]
    def summary_out_dimensions(self, prefix=''):
        return [(prefix+'frame_platform', 'CHAR(2)'),
                (prefix+'country_tier', 'CHAR(1)'),
                (prefix+'townhall_level', 'INT4'),
                (prefix+'spend_bracket', 'INT4')]
    def parse_brief_summary(self, summary, prefix=''):
        return [(prefix+'frame_platform', summary['plat'] if summary else None),
                (prefix+'country_tier', str(summary['tier']) if summary else None),
                (prefix+'townhall_level', summary['cc'] if summary else None),
                (prefix+'prev_receipts', summary['rcpt'] if summary else None)]
    def encode_spend_bracket(self, col):
        return "IF(%s>=1000,1000, IF(%s>=100,100, IF(%s>=10,10, IF(%s>0,1, 0))))" % (col,col,col,col)
    def get_spend_bracket(self, receipts):
        if receipts >= 1000: return 1000
        if receipts >= 100: return 100
        if receipts >= 10: return 10
        if receipts > 0: return 1
        return 0

class MySQLUtil(SQLUtil):
    def disable_warnings(self):
        from warnings import filterwarnings
        import MySQLdb
        filterwarnings('ignore', category = MySQLdb.Warning)
    def sym(self, s):
        return '`'+s+'`'
    def ensure_table(self, cur, name, schema, temporary = False):
        for iname, idata in schema.get('indices',{}).iteritems():
            assert not idata.get('where') # MySQL does not support partial indexes

        cur.execute("CREATE "+("TEMPORARY" if temporary else "")+" TABLE IF NOT EXISTS "+self.sym(name)+" (" + \
                    ", ".join([(self.sym(key)+" "+type) for key, type in schema['fields']] + \
                              [(("UNIQUE " if idata.get('unique', False) else '') + "KEY %s (" % self.sym(name+'_'+iname)) + ",".join([self.sym(key)+" "+order for key, order in idata['keys']]) + ")" \
                               for iname, idata in schema.get('indices',{}).iteritems()]) + \
                    ") CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")

    # string-concat trick to get percentile aggregates
    def percentile(self, expr, fraction):
        return """SUBSTRING_INDEX(
                    SUBSTRING_INDEX(
                      GROUP_CONCAT(%s ORDER BY %s SEPARATOR ','),
                      ',',
                      %f * COUNT(*) + 1),
                      ',' , -1) + 0.0""" % (expr, expr, fraction)

class PostgreSQLUtil(SQLUtil):
    def ensure_table(self, cur, name, schema, temporary = False):
        cur.execute("CREATE "+("TEMPORARY" if temporary else "")+" TABLE IF NOT EXISTS "+self.sym(name)+" (" + \
                    ", ".join([(self.sym(key)+" "+type) for key, type in schema['fields']]) + \
                    ")")
        for iname, idata in schema.get('indices',{}).iteritems():
            index_name = name+'_'+iname
            cur.execute("SELECT COUNT(*) FROM pg_class WHERE relname = %s", [index_name])
            if cur.fetchall()[0][0] == 0:
                cur.execute("CREATE %s INDEX %s ON %s (" % ('UNIQUE' if idata.get('unique',False) else '', self.sym(index_name), self.sym(name)) + \
                            ", ".join([(self.sym(key)+" "+order) for key, order in idata['keys']]) + \
                            ")" + ((' WHERE '+idata['where']) if idata.get('where') else ''))
