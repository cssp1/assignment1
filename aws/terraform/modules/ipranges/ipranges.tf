# maintain AWS security groups that allow ingress from selected cloud services
# these are updated automatically by scraping the published IP ranges from each service

# note: duplicated under game/aws/terraform/modules/ipranges/ and battlehouse-infra/terraform/modules/ipranges/

# AWS SECURITY GROUP USAGE

# Security groups can have up to 50 rules (with separate total counts for IPv4 and IPv6).
# EC2 instances and network interfaces can be a member of up to 5 security groups.

# We are already hitting this limit for production game servers, which have
# frontend_ingress + backend + cloudfront_ingress (x2) + ssh_access

# If CloudFront/CloudFlare keep adding more IP ranges such that this overflows,
# then the next step might be to force all CloudFront traffic to go via the HAproxy frontend.

# CLOUDFLARE

# CloudFlare publishes their IP lists as raw data
data "http" "cloudflare_ipv4" {
  url = "https://www.cloudflare.com/ips-v4"
}

data "http" "cloudflare_ipv6" {
  url = "https://www.cloudflare.com/ips-v6"
}

# IP ranges, broken into lists of <= 25 elements.
# We put both an HTTP and HTTPS rule for each IP range into the same security group.

locals {
  cloudflare_ipv4_chunked = "${chunklist(split("\n",trimspace(data.http.cloudflare_ipv4.body)), 25)}"
  cloudflare_ipv6_chunked = "${chunklist(split("\n",trimspace(data.http.cloudflare_ipv6.body)), 25)}"
}

resource "aws_security_group" "cloudflare_ingress_chunked" {
  count = "${max(length(local.cloudflare_ipv4_chunked), length(local.cloudflare_ipv6_chunked))}"
  name = "${var.sitename}-cloudflare-ingress-chunked-${count.index}"
  description = "Allow ingress from CloudFlare IPs"
  vpc_id = "${var.vpc_id}"
  tags { 
    Name = "${var.sitename}-cloudflare-ingress-chunked-${count.index}"
    Terraform = "true"
  }
}

resource "aws_security_group_rule" "cloudflare_ingress_chunked_egress" {
  # Allow egress to anywhere. Apply this rule to all chunks.
  count = "${max(length(local.cloudflare_ipv4_chunked), length(local.cloudflare_ipv6_chunked))}"
  type = "egress"
  to_port = 0
  from_port = 0
  protocol = "-1"
  cidr_blocks = ["0.0.0.0/0"]
  security_group_id = "${aws_security_group.cloudflare_ingress_chunked.*.id[count.index]}"
}

resource "aws_security_group_rule" "cloudflare_to_http_ipv4_chunked" {
  count             = "${length(local.cloudflare_ipv4_chunked)}"
  type              = "ingress"
  to_port           = 80
  from_port         = 80
  protocol          = "tcp"
  cidr_blocks       = ["${local.cloudflare_ipv4_chunked[count.index]}"]
  security_group_id = "${aws_security_group.cloudflare_ingress_chunked.*.id[count.index]}"
}
resource "aws_security_group_rule" "cloudflare_to_https_ipv4_chunked" {
  count             = "${length(local.cloudflare_ipv4_chunked)}"
  type              = "ingress"
  to_port           = 443
  from_port         = 443
  protocol          = "tcp"
  cidr_blocks       = ["${local.cloudflare_ipv4_chunked[count.index]}"]
  security_group_id = "${aws_security_group.cloudflare_ingress_chunked.*.id[count.index]}"
}

resource "aws_security_group_rule" "cloudflare_to_http_ipv6_chunked" {
  count             = "${length(local.cloudflare_ipv6_chunked)}"
  type              = "ingress"
  to_port           = 80
  from_port         = 80
  protocol          = "tcp"
  ipv6_cidr_blocks  = ["${local.cloudflare_ipv6_chunked[count.index]}"]
  security_group_id = "${aws_security_group.cloudflare_ingress_chunked.*.id[count.index]}"
}
resource "aws_security_group_rule" "cloudflare_to_https_ipv6_chunked" {
  count             = "${length(local.cloudflare_ipv6_chunked)}"
  type              = "ingress"
  to_port           = 443
  from_port         = 443
  protocol          = "tcp"
  ipv6_cidr_blocks  = ["${local.cloudflare_ipv6_chunked[count.index]}"]
  security_group_id = "${aws_security_group.cloudflare_ingress_chunked.*.id[count.index]}"
}

# AMAZON CLOUDFRONT

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

# IP ranges, broken into lists of <= 50 elements
# Note: right now we only add rules for HTTP on port 80.
# If we also want rules for HTTPS on port 443, then we'd need to break into smaller lists, or use more chunks.
locals {
  cloudfront_ipv4_chunked = "${chunklist(split(",",data.external.cloudfront_ipv4.result["prefix_list_comma_separated"]), 50)}"
  cloudfront_ipv6_chunked = "${chunklist(split(",",data.external.cloudfront_ipv6.result["prefix_list_comma_separated"]), 50)}"
}

resource "aws_security_group" "cloudfront_ingress_chunked" {
  count = "${max(length(local.cloudfront_ipv4_chunked), length(local.cloudfront_ipv6_chunked))}"
  name = "${var.sitename}-cloudfront-ingress-chunked-${count.index}"
  description = "Allow ingress from Amazon CloudFront IPs (non-HTTPS)"
  vpc_id = "${var.vpc_id}"
  tags { 
    Name = "${var.sitename}-cloudfront-ingress-chunked-${count.index}" 
    Terraform = "true"
  }
}

resource "aws_security_group_rule" "cloudfront_ingress_chunked_egress" {
  # Allow egress to anywhere. Apply this rule to all chunks.
  count = "${max(length(local.cloudfront_ipv4_chunked), length(local.cloudfront_ipv6_chunked))}"
  type = "egress"
  to_port = 0
  from_port = 0
  protocol = "-1"
  cidr_blocks = ["0.0.0.0/0"]
  security_group_id = "${aws_security_group.cloudfront_ingress_chunked.*.id[count.index]}"
}

resource "aws_security_group_rule" "cloudfront_to_http_ipv4_chunked" {
  count             = "${length(local.cloudfront_ipv4_chunked)}"
  type              = "ingress"
  to_port           = 80
  from_port         = 80
  protocol          = "tcp"
  cidr_blocks       = ["${local.cloudfront_ipv4_chunked[count.index]}"]
  security_group_id = "${aws_security_group.cloudfront_ingress_chunked.*.id[count.index]}"
}
resource "aws_security_group_rule" "cloudfront_to_http_ipv6_chunked" {
  count             = "${length(local.cloudfront_ipv6_chunked)}"
  type              = "ingress"
  to_port           = 80
  from_port         = 80
  protocol          = "tcp"
  ipv6_cidr_blocks  = ["${local.cloudfront_ipv6_chunked[count.index]}"]
  security_group_id = "${aws_security_group.cloudfront_ingress_chunked.*.id[count.index]}"
}
