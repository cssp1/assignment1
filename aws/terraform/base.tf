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
variable "extra_backups_bucket" {
  description = "An extra S3 bucket for backups that should be read-only accessible (for sharing data between production and test)"
  default = "example"
}
variable "region" {
  description = "AWS region to use"
  default = "us-east-1"
}
variable "amis" {
  description = "Base AMI to launch AWS instances with"
  # note 1: AWS instances have ignore_changes set for "ami", because changing them all over at once in an update would be disruptive.
  #         When updating, manually taint instances individually to do a slow roll-out.
  default = {
#    us-east-1 = "ami-a4827dc9" # Amazon Linux AMI 2016.03.2 HVM (SSD) EBS-Backed 64-bit
    us-east-1 = "ami-97785bed" # Amazon Linux AMI 2017.09.1 HVM (SSD) EBS-Backed 64-bit
  }
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
variable "envkey" {
  description = "Envkey.com secret for this deployment"
}
variable "secrets_bucket" {
  description = "S3 bucket for backing up envkey"
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

provider "cloudflare" {
  email = "${var.cloudflare_email}"
  token = "${var.cloudflare_token}"
}

module "aws_cloud_init" {
  source = "./modules/aws-cloud-init"
  cron_mail_sns_topic = "${var.cron_mail_sns_topic}"
  region = "${var.region}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  enable_backups = "${var.enable_backups}"
  envkey = "${var.envkey}"
  secrets_bucket = "${var.secrets_bucket}"
}
