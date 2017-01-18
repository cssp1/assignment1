variable "sitename" {}
variable "extra_backups_bucket" { default = "example" } # gives read access to the backups bucket for this site
variable "sitedomain" {}
variable "region" {}
variable "key_pair_name" {}
variable "cloud_config_boilerplate_rendered" {}
variable "cron_mail_sns_topic" {}
variable "puppet_s3_bucket" {}
variable "vpc_id" {}
variable "subnet_ids" {
  description = "Comma-separated list of VPC subnets, corresponding to the availability_zones array"
}
variable "availability_zones" {
  description = "Comma-separated list of AWS availability zones to use, including region prefix"
  # e.g. "us-east-1a,us-east-1c"
}
variable "ssh_access_security_group_id" {}
variable "mongodb_security_group_id" {}
variable "mongodb_root_password" {}
