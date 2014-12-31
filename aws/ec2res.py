#!/usr/bin/python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this is a raw standalone script that does not depend on a game SVN checkout

import sys, os, time, calendar, getopt
import boto.ec2, boto.rds2

aws_key_file = os.path.join(os.getenv('HOME'), '.ssh', 'dmaas-awssecret')

with open(aws_key_file) as key_fd:
    aws_key, aws_secret = key_fd.readline().strip(), key_fd.readline().strip()

time_now = int(time.time())

class ANSIColor:
    BOLD = '\033[1m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    @classmethod
    def bold(self, x): return self.BOLD+x+self.ENDC
    @classmethod
    def red(self, x): return self.RED+x+self.ENDC
    @classmethod
    def green(self, x): return self.GREEN+x+self.ENDC
    @classmethod
    def yellow(self, x): return self.YELLOW+x+self.ENDC

def decode_time(amztime):
    return calendar.timegm(time.strptime(amztime.split('.')[0], '%Y-%m-%dT%H:%M:%S'))

# return true if this reservation can cover this instance
def ec2_res_match(res, inst):
    return res.instance_type == inst.instance_type and \
           res.availability_zone == inst.placement and \
           res.state == 'active'
def rds_res_match(res, inst, rds_offerings):
    # note: RDS uses slightly different terminology for the reservation "product" and the instance "engine"
    product = rds_offerings[res['ReservedDBInstancesOfferingId']]['ProductDescription']
    engine = inst['Engine']
    return res['DBInstanceClass'] == inst['DBInstanceClass'] and \
           (product == 'postgresql' and engine == 'postgres') and \
           res['MultiAZ'] == inst['MultiAZ']

def pretty_print_ec2_res(res, override_count = None, my_index = None):
    assert res.state == 'active'
    lifetime = decode_time(res.start) + res.duration - time_now
    days = lifetime//86400
    if my_index is not None and res.instance_count > 1:
        count = ' (%d of %d)' % (my_index+1, res.instance_count)
    else:
        instance_count = override_count if override_count is not None else res.instance_count
        count = ' (x%d)' % instance_count if (instance_count!=1 or override_count is not None) else ''
    return '%-10s %-22s %-3d days left' % (res.availability_zone, res.instance_type+count, days)

def pretty_print_rds_res(res, rds_offerings, override_count = None, my_index = None):
    lifetime = res['StartTime'] + res['Duration'] - time_now
    days = lifetime//86400
    if my_index is not None and res['DBInstanceCount'] > 1:
        count = ' (%d of %d)' % (my_index+1, res['DBInstanceCount'])
    else:
        instance_count = override_count if override_count is not None else res['DBInstanceCount']
        count = ' (x%d)' % instance_count if (instance_count!=1 or override_count is not None) else ''
    return 'multi %-1d %-22s %-12s %-3d days left' % (int(res['MultiAZ']), res['DBInstanceClass']+count, rds_offerings[res['ReservedDBInstancesOfferingId']]['ProductDescription'], days)

def pretty_print_ec2_instance(inst):
    return '%-16s %-10s %-16s' % (inst.tags['Name'], inst.placement, inst.instance_type)

def pretty_print_rds_instance(inst):
    return '%-16s %-10s multi %-1d %-16s %-12s' % (inst['DBInstanceIdentifier'], inst['AvailabilityZone'], int(inst['MultiAZ']), inst['DBInstanceClass'], inst['Engine'])

def get_rds_res_offerings(rds):
    ret = {}
    marker = None
    while True:
        r = rds.describe_reserved_db_instances_offerings(marker=marker)['DescribeReservedDBInstancesOfferingsResponse']['DescribeReservedDBInstancesOfferingsResult']
        rlist = r['ReservedDBInstancesOfferings']
        marker = r['Marker']
        for x in rlist: ret[x['ReservedDBInstancesOfferingId']] = x
        if not rlist or not marker:
            break
    return ret

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'v', [])
    verbose = False
    region = 'us-east-1'
    for key, val in opts:
        if key == '-v': verbose = True

    conn = boto.ec2.connect_to_region(region, aws_access_key_id=aws_key, aws_secret_access_key=aws_secret)
    rds = boto.rds2.connect_to_region(region, aws_access_key_id=aws_key, aws_secret_access_key=aws_secret)

    ec2_instance_list = conn.get_only_instances()
    ec2_res_list = conn.get_all_reserved_instances()
    ec2_status_list = conn.get_all_instance_status()

    rds_instance_list = rds.describe_db_instances()['DescribeDBInstancesResponse']['DescribeDBInstancesResult']['DBInstances']
    rds_res_list = rds.describe_reserved_db_instances()['DescribeReservedDBInstancesResponse']['DescribeReservedDBInstancesResult']['ReservedDBInstances']

    rds_res_offerings = get_rds_res_offerings(rds)

    #print rds_instance_list
    #print rds_res_list
    #print rds_res_offerings['d6a5b4d4-6488-404b-a405-33f01f6a54aa']

    # only show running instances, and sort by name
    ec2_instance_list = sorted(filter(lambda x: x.state=='running' and not x.spot_instance_request_id,
                                      ec2_instance_list), key = lambda x: x.tags['Name'])
    rds_instance_list.sort(key = lambda x: x['DBInstanceIdentifier'])

    # disregard expired reservations
    ec2_res_list = filter(lambda x: x.state=='active', ec2_res_list)
    rds_res_list = filter(lambda x: x['State']=='active', rds_res_list)

    # maps instance ID -> reservation
    ec2_res_coverage = dict((inst.id, None) for inst in ec2_instance_list)
    rds_res_coverage = dict((inst['DBInstanceIdentifier'], None) for inst in rds_instance_list)

    # maps reservation ID -> instances
    ec2_res_usage = dict((res.id, []) for res in ec2_res_list)
    rds_res_usage = dict((res['ReservedDBInstanceId'], []) for res in rds_res_list)

    # figure out which instances are covered
    for res in ec2_res_list:
        for i in xrange(res.instance_count):
            for inst in ec2_instance_list:
                if ec2_res_coverage[inst.id]: continue # instance already covered
                if ec2_res_match(res, inst):
                    ec2_res_coverage[inst.id] = res
                    ec2_res_usage[res.id].append(inst)
                    break

    for res in rds_res_list:
        for i in xrange(res['DBInstanceCount']):
            for inst in rds_instance_list:
                if rds_res_coverage[inst['DBInstanceIdentifier']]: continue # instance already covered
                if rds_res_match(res, inst, rds_res_offerings):
                    rds_res_coverage[inst['DBInstanceIdentifier']] = res
                    rds_res_usage[res['ReservedDBInstanceId']].append(inst)
                    break

    # map instance ID -> events
    ec2_instance_status = {}
    for stat in ec2_status_list:
        if stat.events:
            for event in stat.events:
                if '[Canceled]' in event.description or '[Completed]' in event.description: continue
                if stat.id not in ec2_instance_status: ec2_instance_status[stat.id] = []
                msg = event.description
                for timestring in (event.not_before,): # event.not_after):
                    ts = decode_time(timestring)
                    days_until = (ts - time_now)//86400
                    st = time.gmtime(ts)
                    msg += ' in %d days (%s/%d)' % (days_until, st.tm_mon, st.tm_mday)
                ec2_instance_status[stat.id].append(msg)

    print 'EC2 INSTANCES:'
    for inst in ec2_instance_list:
        res = ec2_res_coverage[inst.id]
        if res:
            my_index = ec2_res_usage[res.id].index(inst)
            print ANSIColor.green(pretty_print_ec2_instance(inst)+' '+pretty_print_ec2_res(res, my_index = my_index)),
        else:
            print ANSIColor.red(pretty_print_ec2_instance(inst)+' NOT COVERED'),
        if inst.id in ec2_instance_status:
            print ANSIColor.yellow('EVENTS! '+','.join(ec2_instance_status[inst.id])),
        print

    print 'EC2 UNUSED RESERVATIONS:'
    for res in ec2_res_list:
        use_count = len(ec2_res_usage[res.id])
        if use_count >= res.instance_count: continue
        print ANSIColor.red(pretty_print_ec2_res(res, override_count = res.instance_count - use_count)), res.id

    print 'RDS INSTANCES:'
    for inst in rds_instance_list:
        res = rds_res_coverage[inst['DBInstanceIdentifier']]
        if res:
            my_index = rds_res_usage[res['ReservedDBInstanceId']].index(inst)
            print ANSIColor.green(pretty_print_rds_instance(inst)+' '+pretty_print_rds_res(res, rds_res_offerings, my_index = my_index)),
        else:
            print ANSIColor.red(pretty_print_rds_instance(inst)+' NOT COVERED'),
        print
    print 'RDS UNUSED RESERVATIONS:'
    for res in rds_res_list:
        use_count = len(rds_res_usage[res['ReservedDBInstanceId']])
        if use_count >= res['DBInstanceCount']: continue
        print ANSIColor.red(pretty_print_rds_res(res, rds_res_offerings, override_count = res['DBInstanceCount'] - use_count)), res['ReservedDBInstanceId']
