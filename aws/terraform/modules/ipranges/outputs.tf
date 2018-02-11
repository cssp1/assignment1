output "cloudflare_ingress_security_group_id" {
  value = "${aws_security_group.cloudflare_ingress.id}"
}
output "cloudfront_ingress_security_group_id" {
  value = "${aws_security_group.cloudfront_ingress.id}"
}
