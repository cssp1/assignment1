module "ipranges" {
  source = "git@github.com:spinpunch/spin-tf-ipranges.git?ref=3e1f54d1f0ad45dd0e4dbf13c712d1c43339c8aa"
  vpc_id   = data.terraform_remote_state.corp.outputs.spinpunch_vpc_id
  sitename = var.sitename
}

# make accessible to individual game backend environments
output "cloudfront_ingress_security_group_id_list" {
  value = module.ipranges.cloudfront_ingress_security_group_id_list
}

