terraform {
  backend "s3" {
    bucket = "spinpunch-terraform-state"
    key    = "game-mf2.tfstate"
    region = "us-east-1"
    dynamodb_table = "spinpunch-terraform-state-lock"
  }
}

# pull in company-wide resources
data "terraform_remote_state" "corp" {
  backend = "s3"
  config {
    bucket = "spinpunch-terraform-state"
    key    = "static.tfstate"
    region = "us-east-1"
    dynamodb_table = "spinpunch-terraform-state-lock"
  }
}
# pull in frontend resources
data "terraform_remote_state" "game_frontend" {
  backend = "s3"
  config {
    bucket = "spinpunch-terraform-state"
    key    = "game-frontend.tfstate"
    region = "us-east-1"
    dynamodb_table = "spinpunch-terraform-state-lock"
  }
}


variable "region" { default = "us-east-1" }
variable "sitename" { default = "prod" }
variable "sitedomain" { default = "spinpunch.com" }
variable "enable_backups" { default = "0" }
variable "envkey_mf2prod" {}


data "external" "management_secrets" {
  program = ["envkey-fetch", "${data.terraform_remote_state.corp.management_envkey}", "--cache"]
}
provider "aws" {
  region = "${var.region}"
  version = "~> 1.8"
}
provider "cloudflare" {
  email = "${data.external.management_secrets.result["CLOUDFLARE_EMAIL"]}"
  token = "${data.external.management_secrets.result["CLOUDFLARE_TOKEN"]}"
  version = "~> 0.1"
}

# note: each game title has its own envkey, so this module must be instanced with unique envkey_subs
module "aws_cloud_init_mf2" {
  source = "./modules/aws-cloud-init"
  cron_mail_sns_topic = "${data.terraform_remote_state.corp.cron_mail_sns_topic}"
  region = "${var.region}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  enable_backups = "${var.enable_backups}"
  envkey = "${var.envkey_mf2prod}"
  envkey_sub = "mf2prod"
  secrets_bucket = "${data.terraform_remote_state.corp.secrets_bucket}"
  puppet_branch = "dev"
}

module "game_server_mf2" {
  source = "../modules/game-server"

  vpc_id = "${data.terraform_remote_state.corp.spinpunch_vpc_id}"
  subnet_ids = "${data.terraform_remote_state.corp.spinpunch_prod_subnet_ids}"
  availability_zones = "${data.terraform_remote_state.corp.spinpunch_prod_availability_zones}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  region = "${var.region}"
  ami = "${module.aws_cloud_init_mf2.current_amazon_linux_ami_id}"
  key_pair_name = "${data.external.management_secrets.result["SSH_KEYPAIR_NAME"]}"
  aws_cloud_config_head = "${module.aws_cloud_init_mf2.cloud_config_head}"
  aws_cloud_config_tail = "${module.aws_cloud_init_mf2.cloud_config_tail}"
  aws_ec2_iam_role_fragment = "${module.aws_cloud_init_mf2.ec2_iam_role_fragment}"
  cron_mail_sns_topic = "${data.terraform_remote_state.corp.cron_mail_sns_topic}"
  security_group_id_list = "${concat(
list(data.terraform_remote_state.corp.spinpunch_ssh_access_security_group_id),
list(data.terraform_remote_state.corp.spinpunch_prod_backend_security_group_id),
data.terraform_remote_state.game_frontend.cloudfront_ingress_security_group_id_list)}"
  tournament_winners_sns_topic = "${data.terraform_remote_state.corp.tournament_winners_sns_topic}"
  pglith_pgsql_endpoint = "${data.terraform_remote_state.corp.pglith_pgsql_endpoint}"
  analytics_mysql_endpoint = "${data.terraform_remote_state.corp.analytics_mysql_endpoint}"
  skynet_mongo_endpoint = "${data.terraform_remote_state.corp.skynet_mongo_endpoint}"
  cgianalytics_hosts = "${data.terraform_remote_state.corp.cgianalytics_hosts}"

  # specific to each game
  game_id = "mf2"
  game_id_long = "marsfrontier2"
  game_mail_from = "Quinn"
  tournament_continents = "fb"
  zone_index = 0 # us-east-1a
  instance_type = "m5.large"
  game_server_snam = "srv0"

  # to test alongside legacy server, set snam to "srv2" and make CloudFlare DNS entry "mf2prod-srv2.spinpunch.com"
  # to take over as the master, set snam to "srv0" (or blank?) and make DNS entries "mf2prod-raw.spinpunch.com" and "mf2prod-srv0.spinpunch.com"
}
