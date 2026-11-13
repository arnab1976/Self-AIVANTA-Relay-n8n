output "api_url" { value = google_cloud_run_v2_service.api.uri }
output "web_url" { value = google_cloud_run_v2_service.web.uri }
output "objects_bucket" { value = google_storage_bucket.objects.name }
output "sql_instance" { value = google_sql_database_instance.pg.connection_name }

output "n8n_main_uri" { value = google_cloud_run_v2_service.n8n_main.uri }
output "redis_host" { value = google_redis_instance.queue.host }
