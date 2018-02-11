# maintain AWS security groups that allow ingress from selected cloud services
# these are updated automatically by scraping the published IP ranges from each service

# note: duplicated under game/aws/terraform/modules/ipranges/ and battlehouse-infra/terraform/modules/ipranges/

# CLOUDFLARE
resource "aws_security_group" "cloudflare_ingress" {
  name = "${var.sitename}-cloudflare-ingress"
  description = "Allow ingress from CloudFlare IPs"
  vpc_id = "${var.vpc_id}"
  tags { 
    Name = "${var.sitename}-cloudflare-ingress" 
    Terraform = "true"
  }
}
resource "aws_security_group_rule" "cloudflare_ingress_egress" {
  # allow egress to anywhere
  type = "egress"
  to_port = 0
  from_port = 0
  protocol = "-1"
  cidr_blocks = ["0.0.0.0/0"]
  security_group_id = "${aws_security_group.cloudflare_ingress.id}"
}

# CloudFlare publishes their IP lists as raw data
data "http" "cloudflare_ipv4" {
  url = "https://www.cloudflare.com/ips-v4"
}

data "http" "cloudflare_ipv6" {
  url = "https://www.cloudflare.com/ips-v6"
}

resource "aws_security_group_rule" "cloudflare_to_http" {
  count             = "1" # "${var.enable_http ? 1 : 0}"
  type              = "ingress"
  to_port           = 80
  from_port         = 80
  protocol          = "tcp"
  cidr_blocks       = ["${split("\n",trimspace(data.http.cloudflare_ipv4.body))}"]
  ipv6_cidr_blocks  = ["${split("\n",trimspace(data.http.cloudflare_ipv6.body))}"]
  security_group_id = "${aws_security_group.cloudflare_ingress.id}"
}
resource "aws_security_group_rule" "cloudflare_to_https" {
  count             = "1" # "${var.enable_https ? 1 : 0}"
  type              = "ingress"
  to_port           = 443
  from_port         = 443
  protocol          = "tcp"
  cidr_blocks       = ["${split("\n",trimspace(data.http.cloudflare_ipv4.body))}"]
  ipv6_cidr_blocks  = ["${split("\n",trimspace(data.http.cloudflare_ipv6.body))}"]
  security_group_id = "${aws_security_group.cloudflare_ingress.id}"
}

# AMAZON CLOUDFRONT
resource "aws_security_group" "cloudfront_ingress" {
  name = "${var.sitename}-cloudfront-ingress"
  description = "Allow ingress from Amazon CloudFront IPs (non-HTTPS)"
  vpc_id = "${var.vpc_id}"
  tags { 
    Name = "${var.sitename}-cloudfront-ingress" 
    Terraform = "true"
  }
}
resource "aws_security_group_rule" "cloudfront_ingress_egress" {
  # allow egress to anywhere
  type = "egress"
  to_port = 0
  from_port = 0
  protocol = "-1"
  cidr_blocks = ["0.0.0.0/0"]
  security_group_id = "${aws_security_group.cloudfront_ingress.id}"
}

# AWS publishes their IP lists as JSON, so we use a script to parse this
data "external" "cloudfront_ipv4" {
  program = ["python", "${path.module}/get-aws-ip-ranges.py"]
  query = {
    protocol = "IPv4"
    service = "CLOUDFRONT"
  }
}
data "external" "cloudfront_ipv6" {
  program = ["python", "${path.module}/get-aws-ip-ranges.py"]
  query = {
    protocol = "IPv6"
    service = "CLOUDFRONT"
  }
}

resource "aws_security_group_rule" "cloudfront_to_http" {
  count             = "1" # "${var.enable_http ? 1 : 0}"
  type              = "ingress"
  to_port           = 80
  from_port         = 80
  protocol          = "tcp"
  cidr_blocks       = ["${split(",",data.external.cloudfront_ipv4.result["prefix_list_comma_separated"])}"]
  ipv6_cidr_blocks  = ["${split(",",data.external.cloudfront_ipv6.result["prefix_list_comma_separated"])}"]
  security_group_id = "${aws_security_group.cloudfront_ingress.id}"
}
# note: CloudFront has so many IPv4 ranges that there isn't enough room in one security group to have both HTTP and HTTPS rules.
# since we don't care as much about CloudFront querying the origin via HTTPS, skip this for now.
#resource "aws_security_group_rule" "cloudfront_to_https" {
#  count             = "1" # "${var.enable_https ? 1 : 0}"
#  type              = "ingress"
#  to_port           = 443
#  from_port         = 443
#  protocol          = "tcp"
#  cidr_blocks       = ["${split(",",data.external.cloudfront_ipv4.result["prefix_list_comma_separated"])}"]
#  ipv6_cidr_blocks  = ["${split(",",data.external.cloudfront_ipv6.result["prefix_list_comma_separated"])}"]
#  security_group_id = "${aws_security_group.cloudfront_ingress.id}"
#}
