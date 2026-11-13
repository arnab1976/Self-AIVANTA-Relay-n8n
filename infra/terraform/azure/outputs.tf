output "api_fqdn" { value = azurerm_container_app.app["api"].ingress[0].fqdn }
output "web_fqdn" { value = azurerm_container_app.app["web"].ingress[0].fqdn }
output "acr_login_server" { value = azurerm_container_registry.acr.login_server }
output "postgres_fqdn" { value = azurerm_postgresql_flexible_server.pg.fqdn }
output "redis_hostname" { value = azurerm_redis_cache.queue.hostname }
