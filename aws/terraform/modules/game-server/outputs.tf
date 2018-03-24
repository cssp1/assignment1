output "sitename" {
  value = "${var.sitename}"
}
output "raw_public_dns_list" {
  value = ["${aws_instance.game_server.*.public_dns}"]
}
output "raw_private_dns_list" {
  value = ["${aws_instance.game_server.*.private_dns}"]
}
output "instance_id_list" {
  value = ["${aws_instance.game_server.*.id}"]
}
output "n_instances" {
  value = "${var.n_instances}"
}
