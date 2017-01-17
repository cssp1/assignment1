variable "sitename" {
  description = "Name for the deployed stack"
}
variable "sitedomain" {
  description = "DNS Domain on which to deploy"
}
variable "enable_backups" {
  description = "Whether to perform daily backups to S3, for production databases"
  default = false
}
variable "extra_sitename" {
  description = "Sitename whose backup buckets should be read-only accessible"
  default = "example"
}
variable "region" {
  description = "AWS region to use"
  default = "us-east-1"
}
variable "amis" {
  description = "Base AMI to launch AWS instances with"
  default = {
    us-east-1 = "ami-a4827dc9" # Amazon Linux AMI 2016.03.2 HVM (SSD) EBS-Backed 64-bit
  }
}
variable "ssh_sources" {
  description = "CIDR ranges that should be allowed to SSH in. Comma-separated list."
}
variable "key_pair_name" {
  description = "SSH key pair for setting up instances"
}
variable "private_key_file" {
  description = "Local path to private key for the SSH key pair"
  # not used internally by Terraform, only for convenience of tools to query via terraform output
}
variable "jump_host" {
  description = "SSH host from which to connect to VPC machines (IP should be in ssh_sources)"
  # not used internally by Terraform, only for convenience of tools to query via terraform output
}
variable "puppet_s3_bucket" {
  description = "S3 bucket for stashing Puppet modules that instances will pull from"
  default = "spinpunch-puppet"
}
variable "cron_mail_sns_topic" {
  description = "SNS Topic ID for receiving cron error messages"
}
variable "cloudflare_email" {
  default = ""
  description = "CloudFlare account email address"
}
variable "cloudflare_token" {
  default = ""
  description = "CloudFlare account secure token"
}

provider "aws" {
  region = "${var.region}"
}

module "cloud_config" {
  source = "./modules/cloud-config"
  cron_mail_sns_topic = "${var.cron_mail_sns_topic}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  enable_backups = "${var.enable_backups}"
  puppet_s3_bucket = "${var.puppet_s3_bucket}"
}
