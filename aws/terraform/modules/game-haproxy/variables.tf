variable "sitename" {}
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
variable "instance_type" {
  description = "AWS EC2 instance type for HAproxy"
  default = "t2.micro"
}
variable "n_instances" {
  description = "Number of HAproxy server instances"
  default = 1
}
variable "ami" {}
variable "security_group_id_list" { type = "list" }

