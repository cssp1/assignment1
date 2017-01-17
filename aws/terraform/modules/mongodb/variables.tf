variable "sitename" {}
variable "extra_sitename" { default = "example" } # gives read access to the backups bucket for this site
variable "sitedomain" {}
variable "region" {}
variable "key_pair_name" {}
variable "ami" {}
variable "cloud_config_boilerplate_rendered" {}
variable "cron_mail_sns_topic" {}
variable "puppet_s3_bucket" {}
variable "vpc_id" {}
variable "subnet_id" {}
variable "ssh_access_security_group_id" {}
variable "mongodb_security_group_id" {}
variable "mongodb_root_password" {}
