# AIVANTA Relay on Azure: Container Apps (api, worker, web, n8n main, n8n workers) in a VNet-integrated environment,
# Azure Database for PostgreSQL Flexible Server (AIVANTA + n8n databases), Azure Cache for Redis (n8n queue mode),
# Blob Storage, Key Vault, Azure Container Registry and Log Analytics.
terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 3.110" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "azurerm" {
  features {}
}

data "azurerm_client_config" "me" {}

locals {
  name = "aivanta-relay-${var.environment}"
  flat = replace(local.name, "-", "")
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.name}"
  location = var.location
}

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 90
}

resource "azurerm_container_registry" "acr" {
  name                = substr("acr${local.flat}", 0, 50)
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Standard"
}

resource "azurerm_storage_account" "objects" {
  name                            = substr("st${local.flat}", 0, 24)
  resource_group_name             = azurerm_resource_group.rg.name
  location                        = azurerm_resource_group.rg.location
  account_tier                    = "Standard"
  account_replication_type        = var.environment == "prod" ? "ZRS" : "LRS"
  allow_nested_items_to_be_public = false
  min_tls_version                 = "TLS1_2"
  blob_properties {
    versioning_enabled = true
  }
}

resource "random_password" "secret" {
  for_each = toset(["db", "n8n_db", "bridge", "n8n_key"])
  length   = 40
  special  = false
}

resource "azurerm_key_vault" "kv" {
  name                      = substr("kv-${local.name}", 0, 24)
  location                  = azurerm_resource_group.rg.location
  resource_group_name       = azurerm_resource_group.rg.name
  tenant_id                 = data.azurerm_client_config.me.tenant_id
  sku_name                  = "standard"
  purge_protection_enabled  = var.environment == "prod"
  enable_rbac_authorization = true
}

resource "azurerm_postgresql_flexible_server" "pg" {
  name                          = "psql-${local.name}"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  version                       = "16"
  sku_name                      = var.db_sku
  storage_mb                    = 131072
  administrator_login           = "aivanta"
  administrator_password        = random_password.secret["db"].result
  delegated_subnet_id           = var.postgres_subnet_id
  private_dns_zone_id           = var.postgres_private_dns_zone_id
  public_network_access_enabled = false
  backup_retention_days         = 14
  zone                          = "1"
  dynamic "high_availability" {
    for_each = var.environment == "prod" ? [1] : []
    content { mode = "ZoneRedundant" }
  }
}
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.pg.id
  value     = "VECTOR"
}
resource "azurerm_postgresql_flexible_server_database" "db" {
  for_each  = toset(["aivanta", "n8n"])
  name      = each.key
  server_id = azurerm_postgresql_flexible_server.pg.id
}

resource "azurerm_redis_cache" "queue" {
  name                          = "redis-${local.name}"
  location                      = azurerm_resource_group.rg.location
  resource_group_name           = azurerm_resource_group.rg.name
  capacity                      = 1
  family                        = var.environment == "prod" ? "P" : "C"
  sku_name                      = var.environment == "prod" ? "Premium" : "Standard"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
  subnet_id                     = var.environment == "prod" ? var.redis_subnet_id : null
}

resource "azurerm_container_app_environment" "env" {
  name                       = "cae-${local.name}"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  infrastructure_subnet_id   = var.apps_subnet_id
  internal_load_balancer_enabled = false
}

locals {
  pg_host = azurerm_postgresql_flexible_server.pg.fqdn
  secrets = {
    "database-url"        = "postgresql://aivanta:${random_password.secret["db"].result}@${local.pg_host}:5432/aivanta?sslmode=require"
    "bridge-token"        = random_password.secret["bridge"].result
    "n8n-encryption-key"  = random_password.secret["n8n_key"].result
    "n8n-db-password"     = random_password.secret["db"].result
    "n8n-api-key"         = var.n8n_api_key
    "azure-openai-key"    = var.azure_openai_api_key
    "redis-password"      = azurerm_redis_cache.queue.primary_access_key
  }
  n8n_env = {
    DB_TYPE = "postgresdb", DB_POSTGRESDB_HOST = local.pg_host, DB_POSTGRESDB_DATABASE = "n8n", DB_POSTGRESDB_USER = "aivanta",
    DB_POSTGRESDB_SSL_ENABLED = "true", EXECUTIONS_MODE = "queue", QUEUE_BULL_REDIS_HOST = azurerm_redis_cache.queue.hostname,
    QUEUE_BULL_REDIS_PORT = "6380", QUEUE_BULL_REDIS_TLS = "true", WEBHOOK_URL = "http://n8n/", N8N_EDITOR_BASE_URL = var.n8n_editor_url,
    N8N_DIAGNOSTICS_ENABLED = "false", N8N_PERSONALIZATION_ENABLED = "false", N8N_RUNNERS_ENABLED = "true",
    OFFLOAD_MANUAL_EXECUTIONS_TO_WORKERS = "true", EXECUTIONS_DATA_PRUNE = "true", EXECUTIONS_DATA_MAX_AGE = "336",
    NODES_EXCLUDE = "[\"n8n-nodes-base.executeCommand\",\"n8n-nodes-base.ssh\",\"n8n-nodes-base.readWriteFile\"]",
  }
  n8n_secret_env = { N8N_ENCRYPTION_KEY = "n8n-encryption-key", DB_POSTGRESDB_PASSWORD = "n8n-db-password", QUEUE_BULL_REDIS_PASSWORD = "redis-password" }
  app_env = {
    AUTH_MODE = "oidc", SEED_DEMO = "false", RUN_EXECUTION = "worker", N8N_MODE = "rest", N8N_API_URL = "http://n8n/api/v1",
    N8N_WEBHOOK_URL = "http://n8n", AIVANTA_BRIDGE_URL = "http://api", LLM_PROVIDER = "azure_openai",
    AZURE_OPENAI_ENDPOINT = var.azure_openai_endpoint, OIDC_ISSUER = var.oidc_issuer, OIDC_AUDIENCE = var.oidc_audience,
    OIDC_JWKS_URL = var.oidc_jwks_url, STORAGE_DIR = "/data/objects", CORS_ORIGINS = var.web_origin,
  }
  app_secret_env = { DATABASE_URL = "database-url", AIVANTA_BRIDGE_TOKEN = "bridge-token", N8N_API_KEY = "n8n-api-key", AZURE_OPENAI_API_KEY = "azure-openai-key" }
  apps = {
    api        = { image = "${azurerm_container_registry.acr.login_server}/api:${var.image_tag}", port = 8000, external = true, min = 2, max = 6, cmd = null, env = local.app_env, sec = local.app_secret_env, cpu = 1, mem = "2Gi" }
    worker     = { image = "${azurerm_container_registry.acr.login_server}/api:${var.image_tag}", port = null, external = false, min = 2, max = 6, cmd = ["python", "-m", "aivanta_api.worker"], env = local.app_env, sec = local.app_secret_env, cpu = 0.5, mem = "1Gi" }
    web        = { image = "${azurerm_container_registry.acr.login_server}/web:${var.image_tag}", port = 3000, external = true, min = 2, max = 4, cmd = null, env = {}, sec = {}, cpu = 0.5, mem = "1Gi" }
    n8n        = { image = "docker.n8n.io/n8nio/n8n:${var.n8n_version}", port = 5678, external = false, min = 1, max = 1, cmd = null, env = local.n8n_env, sec = local.n8n_secret_env, cpu = 2, mem = "4Gi" }
    n8n-worker = { image = "docker.n8n.io/n8nio/n8n:${var.n8n_version}", port = null, external = false, min = 1, max = var.n8n_workers_max, cmd = ["worker"], env = local.n8n_env, sec = local.n8n_secret_env, cpu = 2, mem = "4Gi" }
  }
}

resource "azurerm_user_assigned_identity" "apps" {
  name                = "id-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}
resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}
resource "azurerm_role_assignment" "blob" {
  scope                = azurerm_storage_account.objects.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

resource "azurerm_container_app" "app" {
  for_each                     = local.apps
  name                         = each.key
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }
  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }
  dynamic "secret" {
    for_each = { for k, v in local.secrets : k => v if contains(values(each.value.sec), k) }
    content {
      name  = secret.key
      value = secret.value
    }
  }
  dynamic "ingress" {
    for_each = each.value.port == null ? [] : [1]
    content {
      external_enabled = each.value.external
      target_port      = each.value.port
      transport        = "auto"
      traffic_weight {
        latest_revision = true
        percentage      = 100
      }
    }
  }
  template {
    min_replicas = each.value.min
    max_replicas = each.value.max
    container {
      name    = each.key
      image   = each.value.image
      cpu     = each.value.cpu
      memory  = each.value.mem
      command = each.value.cmd
      dynamic "env" {
        for_each = each.value.env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = each.value.sec
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }
}
# Expose only web and /api publicly (Front Door or Application Gateway with WAF in front of the api and web apps);
# block /internal/* and /gateway/* at the edge: they are for n8n → API traffic inside the environment.
