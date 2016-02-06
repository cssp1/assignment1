#!/bin/bash

# update AWS EC2 security groups used for production game servers
# (assumes you are running this with proper AWS credentials in the environment)

function format_ip_list {
    # Convert raw list of IPs/ports into an --ip-permissions argument for authorize-security-group-ingress
    export IP_LIST=$1 # "1.2.3.4 5.6.7.8 ..."
    export PORT_LIST=$2 # "80 443"
    python -c "import json, sys, os; ip_list, port_list = os.getenv('IP_LIST').strip().split(' '), map(int, os.getenv('PORT_LIST').strip().split(' ')); print json.dumps( \
[{'IpProtocol':'tcp','FromPort':port,'ToPort':port,'IpRanges':[{'CidrIp':ip} for ip in ip_list]} for port in port_list])"
}

function find_deletions {
    # find any existing ingress rules NOT in ip_list/port_list
    GROUP_ID=$1
    export IP_LIST=$2
    export PORT_LIST=$3
    export GROUP_DESCR=$4
    python -c "
import json, sys, os
ip_list, port_list = os.getenv('IP_LIST').strip().split(' '), map(int, os.getenv('PORT_LIST').strip().split(' '))
deletions = []
for entry in json.loads(os.getenv('GROUP_DESCR'))['SecurityGroups'][0]['IpPermissions']:
    for ip in entry['IpRanges']:
        if ip['CidrIp'] not in ip_list or entry['ToPort'] not in port_list or entry['IpProtocol'] != 'tcp' or entry['ToPort']!=entry['FromPort']:
            deletions.append({'IpProtocol':entry['IpProtocol'],'ToPort':entry['ToPort'],'FromPort':entry['FromPort'],'IpRanges':[{'CidrIp':ip['CidrIp']}]})
print json.dumps(deletions) if deletions else ''"
    }
function find_additions {
    # find any new rules we need to add for ip_list/port_list
    GROUP_ID=$1
    export IP_LIST=$2
    export PORT_LIST=$3
    export GROUP_DESCR=$4
    python -c "
import json, sys, os
ip_list, port_list = os.getenv('IP_LIST').strip().split(' '), map(int, os.getenv('PORT_LIST').strip().split(' '))
additions = []
perms = json.loads(os.getenv('GROUP_DESCR'))['SecurityGroups'][0]['IpPermissions']
for port in port_list:
    for ip in ip_list:
        found = False
        for entry in perms:
            if entry['IpProtocol'] == 'tcp' and entry['ToPort'] == port and entry['FromPort'] == port:
                for iprange in entry['IpRanges']:
                    if iprange['CidrIp'] == ip:
                        found = True; break
                if found: break
            if found: break
        if not found:
            additions.append({'IpProtocol':'tcp','ToPort':port,'FromPort':port,'IpRanges':[{'CidrIp':ip}]})
print json.dumps(additions) if additions else ''"
    }
function do_conform {
    # conform the security group to the correct ip_list/post_list
    GROUP_ID=$1
    IP_LIST=$2
    PORT_LIST=$3
    GROUP_DESCR=`aws ec2 describe-security-groups --group-id ${GROUP_ID}`
    DELETIONS=$(find_deletions "${GROUP_ID}" "${IP_LIST}" "${PORT_LIST}" "${GROUP_DESCR}")
    ADDITIONS=$(find_additions "${GROUP_ID}" "${IP_LIST}" "${PORT_LIST}" "${GROUP_DESCR}")

    if [ "${DELETIONS}" != "" ]; then
    echo "${GROUP_ID} DELETE ${DELETIONS}"
    aws ec2 revoke-security-group-ingress --group-id ${GROUP_ID} --ip-permissions "${DELETIONS}"
    fi
    if [ "${ADDITIONS}" != "" ]; then
    echo "${GROUP_ID} ADD ${ADDITIONS}"
    aws ec2 authorize-security-group-ingress --group-id ${GROUP_ID} --ip-permissions "${ADDITIONS}"
    fi
}

# Amazon CloudFront
AWS_CLOUDFRONT_IPS=`curl -s https://ip-ranges.amazonaws.com/ip-ranges.json | \
    python -c 'import json, sys; print " ".join(x["ip_prefix"] for x in json.load(sys.stdin)["prefixes"] if x["service"] == "CLOUDFRONT")'`
AWS_CLOUDFRONT_PORTS="80"
do_conform "sg-584f7632" "${AWS_CLOUDFRONT_IPS}" "${AWS_CLOUDFRONT_PORTS}" # cloudfront
do_conform "sg-7f070d06" "${AWS_CLOUDFRONT_IPS}" "${AWS_CLOUDFRONT_PORTS}" # cloudfront-vpc-sg

# CloudFlare
CLOUDFLARE_IPS=`curl -s https://www.cloudflare.com/ips-v4 | tr '\n' ' '`
CLOUDFLARE_PORTS="80 443"
do_conform "sg-d14a73bb" "${CLOUDFLARE_IPS}" "${CLOUDFLARE_PORTS}" # cloudflare
do_conform "sg-a6060cdf" "${CLOUDFLARE_IPS}" "${CLOUDFLARE_PORTS}" # cloudflare-vpc-sg

# Incapsula
INCAPSULA_IPS=`curl -s --data "resp_format=text" https://my.incapsula.com/api/integration/v1/ips | grep -v '::' | tr '\n' ' '`
INCAPSULA_PORTS="80 443"
do_conform "sg-e34f7689" "${INCAPSULA_IPS}" "${INCAPSULA_PORTS}" # incapsula
do_conform "sg-54070d2d" "${INCAPSULA_IPS}" "${INCAPSULA_PORTS}" # incapsula-vpc-sg

