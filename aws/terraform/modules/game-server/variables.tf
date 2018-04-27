variable "sitename" {}
variable "sitedomain" {}
variable "region" {}
variable "key_pair_name" {}
variable "aws_cloud_config_head" {}
variable "aws_cloud_config_tail" {}
variable "aws_ec2_iam_role_fragment" {}
variable "cron_mail_sns_topic" {}
variable "emergency_sns_topic" { default = "" }
variable "tournament_winners_sns_topic" {}
variable "pglith_pgsql_endpoint" {}
variable "analytics_mysql_endpoint" {}
variable "skynet_mongo_endpoint" {}
variable "cgianalytics_hosts" {}
variable "vpc_id" {}
variable "subnet_ids" {
  description = "Comma-separated list of VPC subnets, corresponding to the availability_zones array"
}
variable "availability_zones" {
  description = "Comma-separated list of AWS availability zones to use, including region prefix"
  # e.g. "us-east-1a,us-east-1c"
}
variable "zone_index" {
  description = "Index within subnet_ids and availability_zone list to use, for single server"
}
variable "instance_type" {
  description = "AWS EC2 instance type for game servers"
  default = "t2.micro"
}
variable "ami" {}
variable "security_group_id_list" { type = "list" }
variable "n_instances" { default = 1 }
variable "game_server_snam" { default = "" }
variable "game_id" {}
variable "game_id_long" {}
variable "game_mail_from" {}
variable "tournament_continents" {
  description = "space-separated list of continent IDs for which to calculate scores"
}
variable "logs_size_gb" { default = 8 }
variable "swap_size_gb" { default = 8 }
variable "game_repo" { default = "github.com/spinpunch/game" }
variable "game_branch" { default = "master" }
variable "enable_swap_alarm" { default = false }
