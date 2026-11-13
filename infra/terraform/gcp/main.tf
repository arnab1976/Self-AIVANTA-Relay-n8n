# AIVANTA Relay on Google Cloud: Cloud Run (api, worker, web, n8n main + workers), Cloud SQL PostgreSQL 16, Memorystore, Cloud Storage,
# Secret Manager and Artifact Registry. Cloud-neutral equivalents are listed in ../README.md.
terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.40" }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  name = "aivanta-relay-${var.environment}"
}

resource "google_artifact_registry_repository" "images" {
  repository_id = local.name
  format        = "DOCKER"
  location      = var.region
}

resource "google_sql_database_instance" "pg" {
  name             = "${local.name}-pg"
  database_version = "POSTGRES_16"
  region           = var.region
  settings {
    tier              = var.db_tier
    availability_type = var.environment == "prod" ? "REGIONAL" : "ZONAL"
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
    ip_configuration {
      ipv4_enabled    = false
      private_network = var.vpc_network
    }
    database_flags {
      name  = "cloudsql.enable_pgvector"
      value = "on"
    }
  }
  deletion_protection = var.environment == "prod"
}

resource "google_sql_database" "aivanta" {
  name     = "aivanta"
  instance = google_sql_database_instance.pg.name
}

resource "google_storage_bucket" "objects" {
  name                        = "${local.name}-objects"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  versioning { enabled = true }
  lifecycle_rule {
    condition { age = var.retention_days }
    action { type = "Delete" }
  }
}

resource "google_secret_manager_secret" "app" {
  for_each  = toset(["DATABASE_URL", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "MCP_GATEWAY_TOKEN"])
  secret_id = "${local.name}-${lower(replace(each.key, "_", "-"))}"
  replication {
    auto {}
  }
}

resource "google_service_account" "runtime" {
  account_id   = substr(replace(local.name, "_", "-"), 0, 28)
  display_name = "AIVANTA Relay runtime"
}

resource "google_cloud_run_v2_service" "api" {
  name     = "${local.name}-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  template {
    service_account = google_service_account.runtime.email
    scaling {
      min_instance_count = 1
      max_instance_count = 6
    }
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${local.name}/api:${var.image_tag}"
      env {
        name  = "AUTH_MODE"
        value = "oidc"
      }
      env {
        name  = "RUN_EXECUTION"
        value = "worker"
      }
      env {
        name  = "SEED_DEMO"
        value = "false"
      }
      env {
        name  = "N8N_MODE"
        value = "rest"
      }
      env {
        name  = "AIVANTA_BRIDGE_URL"
        value = var.api_internal_url
      }
      env {
        name  = "N8N_API_URL"
        value = "${trimsuffix(var.n8n_internal_url, "/")}/api/v1"
      }
      env {
        name  = "N8N_WEBHOOK_URL"
        value = trimsuffix(var.n8n_internal_url, "/")
      }
      env {
        name = "N8N_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.n8n["N8N_API_KEY"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "AIVANTA_BRIDGE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.n8n["AIVANTA_BRIDGE_TOKEN"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app["DATABASE_URL"].secret_id
            version = "latest"
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service" "worker" {
  name     = "${local.name}-worker"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  template {
    service_account = google_service_account.runtime.email
    scaling {
      min_instance_count = 1
      max_instance_count = 4
    }
    containers {
      image   = "${var.region}-docker.pkg.dev/${var.project_id}/${local.name}/api:${var.image_tag}"
      command = ["python", "-m", "aivanta_api.worker"]
      env {
        name  = "RUN_EXECUTION"
        value = "worker"
      }
      env {
        name  = "N8N_MODE"
        value = "rest"
      }
      env {
        name  = "AIVANTA_BRIDGE_URL"
        value = var.api_internal_url
      }
      env {
        name  = "N8N_API_URL"
        value = "${trimsuffix(var.n8n_internal_url, "/")}/api/v1"
      }
      env {
        name  = "N8N_WEBHOOK_URL"
        value = trimsuffix(var.n8n_internal_url, "/")
      }
      env {
        name = "N8N_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.n8n["N8N_API_KEY"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "AIVANTA_BRIDGE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.n8n["AIVANTA_BRIDGE_TOKEN"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app["DATABASE_URL"].secret_id
            version = "latest"
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service" "web" {
  name     = "${local.name}-web"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${local.name}/web:${var.image_tag}"
    }
  }
}
