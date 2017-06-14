output "boilerplate_rendered" {
  value = "${data.template_file.cloud_config_boilerplate.rendered}"
}
