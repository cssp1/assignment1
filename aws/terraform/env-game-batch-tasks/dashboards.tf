# S3 bucket for Jupyter dashboards
# Exposed from S3 via HTTP but restricted to CloudFlare IPs

provider "cloudflare" {
  email   = data.external.management_secrets.result["CLOUDFLARE_EMAIL"]
  api_key = data.external.management_secrets.result["CLOUDFLARE_TOKEN"]
}

resource "aws_s3_bucket" "dashboards" {
  # must match deployment hostname so that the CNAME will work.
  bucket = "dashboards.spinpunch.com"
  website {
    index_document = "index.html"
    error_document = "error.html"
  }

  tags = {
    Terraform = "true"
  }
}

# index.html document
resource "aws_s3_bucket_object" "dashboards_index" {
    bucket = aws_s3_bucket.dashboards.bucket
    key = "index.html"
    content = "<html>Index for ${aws_s3_bucket.dashboards.bucket}</html>"
    content_type = "text/html"
}
resource "aws_s3_bucket_object" "dashboards_error" {
    bucket = aws_s3_bucket.dashboards.bucket
    key = "error.html"
    content = "<html>Error for ${aws_s3_bucket.dashboards.bucket}</html>"
    content_type = "text/html"
}

# Allow reads from CloudFlare IPs only
# (this is copied from spin-tf-ipranges, without the VPC/SG stuff)

# CloudFlare publishes their IP lists as raw data
data "http" "cloudflare_ipv4" {
  url = "https://www.cloudflare.com/ips-v4"
}
data "http" "cloudflare_ipv6" {
  url = "https://www.cloudflare.com/ips-v6"
}

locals {
  cloudflare_ipv4_list = split("\n", trimspace(data.http.cloudflare_ipv4.body))
  cloudflare_ipv6_list = split("\n", trimspace(data.http.cloudflare_ipv6.body))
}

resource "aws_s3_bucket_policy" "dashboards" {
  bucket = aws_s3_bucket.dashboards.id
  policy = jsonencode({
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "PublicReadGetObject",
        "Effect": "Allow",
        "Principal": "*",
        "Action": ["s3:GetObject"],
        "Resource": [aws_s3_bucket.dashboards.arn, format("%s/*", aws_s3_bucket.dashboards.arn)],
        "Condition": {
            "IpAddress": {
                "aws:SourceIp": concat(local.cloudflare_ipv4_list, local.cloudflare_ipv6_list)
            }
        }
    }]
  })
}

# Create CloudFlare record for the bucket
resource "cloudflare_record" "dashboards" {
  zone_id = data.terraform_remote_state.corp.outputs.spinpunch_com_cloudflare_zone_id
  name = "dashboards.spinpunch.com"
  type = "CNAME"
  value = aws_s3_bucket.dashboards.bucket_domain_name
  proxied = true
}

# Configure CloudFlare Access security
resource "cloudflare_access_application" "dashboards" {
  zone_id                   = data.terraform_remote_state.corp.outputs.spinpunch_com_cloudflare_zone_id
  name                      = "Dashboards S3 Bucket"
  domain                    = "dashboards.spinpunch.com"
  #type                      = "self_hosted"
  session_duration          = "24h"
  auto_redirect_to_identity = true
}

# Allow access by @battlehouse.com accounts
resource "cloudflare_access_policy" "dashboards_from_battlehouse_auth" {
  zone_id        = data.terraform_remote_state.corp.outputs.spinpunch_com_cloudflare_zone_id
  application_id = cloudflare_access_application.dashboards.id
  name           = "Allow *@battlehouse.com"
  precedence     = "1"
  decision       = "allow"
  include {
    email_domain = ["battlehouse.com"]
  }
}