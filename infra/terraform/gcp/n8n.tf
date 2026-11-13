# n8n for AIVANTA Relay on Google Cloud: Cloud SQL database for n8n, Memorystore Redis (queue mode),
# Cloud Run services for the n8n main process (editor, API, webhooks) and the queue workers.
# The API reaches n8n on the internal URL; n8n reaches the API's /internal and /gateway routes the same way.

resource "google_sql_database" "n8n" {
  name     = "n8n"
  instance = google_sql_database_instance.pg.name
}

resource "google_redis_instance" "queue" {
  name               = "${local.name}-redis"
  tier               = var.environment == "prod" ? "STANDARD_HA" : "BASIC"
  memory_size_gb     = 1
  region             = var.region
  authorized_network = var.vpc_network
  redis_version      = "REDIS_7_2"
}

resource "google_secret_manager_secret" "n8n" {
  for_each  = toset(["N8N_ENCRYPTION_KEY", "N8N_DB_PASSWORD", "N8N_API_KEY", "AIVANTA_BRIDGE_TOKEN"])
  secret_id = "${local.name}-${lower(replace(each.key, "_", "-"))}"
  replication {
    auto {}
  }
}

locals {
  n8n_env = {
    DB_TYPE                       = "postgresdb"
    DB_POSTGRESDB_HOST            = google_sql_database_instance.pg.private_ip_address
    DB_POSTGRESDB_DATABASE        = "n8n"
    DB_POSTGRESDB_USER            = "n8n"
    EXECUTIONS_MODE               = "queue"
    QUEUE_BULL_REDIS_HOST         = google_redis_instance.queue.host
    QUEUE_BULL_REDIS_PORT         = tostring(google_redis_instance.queue.port)
    N8N_DIAGNOSTICS_ENABLED       = "false"
    N8N_PERSONALIZATION_ENABLED   = "false"
    N8N_PUBLIC_API_DISABLED       = "false"
    N8N_RUNNERS_ENABLED           = "true"
    EXECUTIONS_DATA_PRUNE         = "true"
    EXECUTIONS_DATA_MAX_AGE       = "336"
    OFFLOAD_MANUAL_EXECUTIONS_TO_WORKERS = "true"
    NODES_EXCLUDE                 = "[\"n8n-nodes-base.executeCommand\",\"n8n-nodes-base.ssh\",\"n8n-nodes-base.readWriteFile\"]"
    WEBHOOK_URL                   = var.n8n_internal_url
    N8N_EDITOR_BASE_URL           = var.n8n_editor_url
  }
  n8n_secrets = { N8N_ENCRYPTION_KEY = "N8N_ENCRYPTION_KEY", DB_POSTGRESDB_PASSWORD = "N8N_DB_PASSWORD" }
}

resource "google_cloud_run_v2_service" "n8n_main" {
  name     = "${local.name}-n8n"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"   # editor for the platform team behind IAP; webhooks internal
  template {
    service_account = google_service_account.runtime.email
    scaling {
      min_instance_count = 1
      max_instance_count = 1                            # one main process; scale workers instead
    }
    vpc_access {
      network_interfaces { network = var.vpc_network }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = "docker.n8n.io/n8nio/n8n:${var.n8n_version}"
      ports { container_port = 5678 }
      resources {
        limits = { cpu = "2", memory = "4Gi" }
        cpu_idle = false
      }
      dynamic "env" {
        for_each = local.n8n_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.n8n_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.n8n[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service" "n8n_worker" {
  name     = "${local.name}-n8n-worker"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  template {
    service_account = google_service_account.runtime.email
    scaling {
      min_instance_count = var.n8n_workers_min
      max_instance_count = var.n8n_workers_max
    }
    vpc_access {
      network_interfaces { network = var.vpc_network }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = "docker.n8n.io/n8nio/n8n:${var.n8n_version}"
      args  = ["worker"]
      resources {
        limits   = { cpu = "2", memory = "4Gi" }
        cpu_idle = false
      }
      dynamic "env" {
        for_each = local.n8n_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.n8n_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.n8n[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
}
