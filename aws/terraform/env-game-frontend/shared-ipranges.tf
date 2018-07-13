module "ipranges" {
  source = "./modules/ipranges"
  vpc_id = "${data.terraform_remote_state.corp.spinpunch_vpc_id}"
  sitename = "${var.sitename}"
}

# make accessible to individual game backend environments
output "cloudfront_ingress_security_group_id_list" {
  value = "${module.ipranges.cloudfront_ingress_security_group_id_list}"
}
