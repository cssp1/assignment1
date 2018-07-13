output "cloudflare_ingress_security_group_id_list" {
  description = "List of security groups you need to be a member of to allow ingress from CloudFlare"
  value = ["${aws_security_group.cloudflare_ingress_chunked.*.id}"]
}
output "cloudfront_ingress_security_group_id_list" {
  description = "List of security groups you need to be a member of to allow ingress from CloudFront"
  value = ["${aws_security_group.cloudfront_ingress_chunked.*.id}"]
}
