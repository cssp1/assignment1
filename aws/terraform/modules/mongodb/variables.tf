variable "sitename" {}
variable "extra_backups_bucket" { default = "example" } # gives read access to the backups bucket for this site
variable "backups_bucket" {}
variable "sitedomain" {}
variable "region" {}
variable "key_pair_name" {}
variable "aws_cloud_config_head" {}
variable "aws_cloud_config_tail" {}
variable "aws_ec2_iam_role_fragment" {}
variable "cron_mail_sns_topic" {}
variable "vpc_id" {}
variable "subnet_ids" {
  description = "Comma-separated list of VPC subnets, corresponding to the availability_zones array"
}
variable "availability_zones" {
  description = "Comma-separated list of AWS availability zones to use, including region prefix"
  # e.g. "us-east-1a,us-east-1c"
}
variable "mongodb_instance_type" {
  description = "AWS EC2 instance type for MongoDB"
  # use t2.medium for testing, i3.large for production
}
variable "n_instances" {
  description = "Number of MongoDB server instances"
  default = 1
}
variable "ami" {}
variable "ssh_access_security_group_id" {}
variable "mongodb_security_group_id" {}
