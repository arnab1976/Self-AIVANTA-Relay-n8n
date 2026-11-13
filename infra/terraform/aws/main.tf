# AIVANTA Relay on AWS: ECS Fargate (api, worker, web, n8n main, n8n workers), RDS PostgreSQL 16 (AIVANTA + n8n databases),
# ElastiCache Redis (n8n queue mode), S3 (objects), Secrets Manager, ECR, Cloud Map private DNS, internal + public ALBs.
# Bring your own VPC (private subnets for tasks and data, public subnets for the public ALB).
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" { region = var.region }

locals {
  name    = "aivanta-relay-${var.environment}"
  ns      = "relay.internal"
  api_url = "http://api.${local.ns}:8000"
  n8n_url = "http://n8n.${local.ns}:5678"
}

# ---------------------------------------------------------------------------- registry, storage, secrets
resource "aws_ecr_repository" "repo" {
  for_each             = toset(["api", "web"])
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_s3_bucket" "objects" { bucket = "${local.name}-objects-${var.account_suffix}" }
resource "aws_s3_bucket_public_access_block" "objects" {
  bucket                  = aws_s3_bucket.objects.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "objects" {
  bucket = aws_s3_bucket.objects.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "random_password" "secret" {
  for_each = toset(["db", "n8n_db", "bridge", "n8n_key", "jwt"])
  length   = 40
  special  = false
}

resource "aws_secretsmanager_secret" "app" {
  for_each = toset(["DATABASE_URL", "AIVANTA_BRIDGE_TOKEN", "N8N_ENCRYPTION_KEY", "N8N_DB_PASSWORD", "N8N_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"])
  name     = "${local.name}/${each.key}"
}
resource "aws_secretsmanager_secret_version" "generated" {
  for_each = {
    DATABASE_URL         = "postgresql://aivanta:${random_password.secret["db"].result}@${aws_db_instance.pg.address}:5432/aivanta"
    AIVANTA_BRIDGE_TOKEN = random_password.secret["bridge"].result
    N8N_ENCRYPTION_KEY   = random_password.secret["n8n_key"].result
    N8N_DB_PASSWORD      = random_password.secret["n8n_db"].result
  }
  secret_id     = aws_secretsmanager_secret.app[each.key].id
  secret_string = each.value
}
# N8N_API_KEY, OPENAI_API_KEY and AZURE_OPENAI_API_KEY are set after deployment (scripts/n8n_bootstrap.py prints the n8n key).

# ---------------------------------------------------------------------------- network security
resource "aws_security_group" "tasks" {
  name   = "${local.name}-tasks"
  vpc_id = var.vpc_id
  ingress {
    from_port = 0
    to_port   = 65535
    protocol  = "tcp"
    self      = true
  }
  ingress {
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_security_group" "data" {
  name   = "${local.name}-data"
  vpc_id = var.vpc_id
  ingress {
    from_port       = 5432
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }
}
resource "aws_security_group" "alb" {
  name   = "${local.name}-alb"
  vpc_id = var.vpc_id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------------------------------------------------------------------------- data
resource "aws_db_subnet_group" "pg" {
  name       = local.name
  subnet_ids = var.private_subnet_ids
}
resource "aws_db_instance" "pg" {
  identifier                   = "${local.name}-pg"
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.db_instance_class
  allocated_storage            = 100
  storage_encrypted            = true
  db_name                      = "aivanta"
  username                     = "aivanta"
  password                     = random_password.secret["db"].result
  db_subnet_group_name         = aws_db_subnet_group.pg.name
  vpc_security_group_ids       = [aws_security_group.data.id]
  multi_az                     = var.environment == "prod"
  backup_retention_period      = 14
  deletion_protection          = var.environment == "prod"
  skip_final_snapshot          = var.environment != "prod"
  performance_insights_enabled = true
}
# The n8n database and role are created once with: CREATE ROLE n8n LOGIN PASSWORD '<N8N_DB_PASSWORD>'; CREATE DATABASE n8n OWNER n8n;

resource "aws_elasticache_subnet_group" "redis" {
  name       = local.name
  subnet_ids = var.private_subnet_ids
}
resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${local.name}-redis"
  description                = "n8n queue mode"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = "cache.t4g.small"
  num_cache_clusters         = var.environment == "prod" ? 2 : 1
  automatic_failover_enabled = var.environment == "prod"
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.data.id]
  at_rest_encryption_enabled = true
}

# ---------------------------------------------------------------------------- ECS
resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}
resource "aws_service_discovery_private_dns_namespace" "ns" {
  name = local.ns
  vpc  = var.vpc_id
}
resource "aws_cloudwatch_log_group" "logs" {
  name              = "/ecs/${local.name}"
  retention_in_days = 90
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "exec" {
  name               = "${local.name}-exec"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}
resource "aws_iam_role_policy_attachment" "exec" {
  role       = aws_iam_role.exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_iam_role_policy" "exec_secrets" {
  role = aws_iam_role.exec.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"],
  Resource = [for s in aws_secretsmanager_secret.app : s.arn] }] })
}
resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}
resource "aws_iam_role_policy" "task_s3" {
  role = aws_iam_role.task.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
  Resource = [aws_s3_bucket.objects.arn, "${aws_s3_bucket.objects.arn}/*"] }] })
}

locals {
  secret = { for k, s in aws_secretsmanager_secret.app : k => s.arn }
  n8n_env = [
    { name = "DB_TYPE", value = "postgresdb" }, { name = "DB_POSTGRESDB_HOST", value = aws_db_instance.pg.address },
    { name = "DB_POSTGRESDB_DATABASE", value = "n8n" }, { name = "DB_POSTGRESDB_USER", value = "n8n" },
    { name = "DB_POSTGRESDB_SSL_ENABLED", value = "true" }, { name = "DB_POSTGRESDB_SSL_REJECT_UNAUTHORIZED", value = "false" },
    { name = "EXECUTIONS_MODE", value = "queue" }, { name = "QUEUE_BULL_REDIS_HOST", value = aws_elasticache_replication_group.redis.primary_endpoint_address },
    { name = "WEBHOOK_URL", value = "${local.n8n_url}/" }, { name = "N8N_EDITOR_BASE_URL", value = var.n8n_editor_url },
    { name = "N8N_DIAGNOSTICS_ENABLED", value = "false" }, { name = "N8N_PERSONALIZATION_ENABLED", value = "false" },
    { name = "N8N_RUNNERS_ENABLED", value = "true" }, { name = "OFFLOAD_MANUAL_EXECUTIONS_TO_WORKERS", value = "true" },
    { name = "EXECUTIONS_DATA_PRUNE", value = "true" }, { name = "EXECUTIONS_DATA_MAX_AGE", value = "336" },
    { name = "NODES_EXCLUDE", value = "[\"n8n-nodes-base.executeCommand\",\"n8n-nodes-base.ssh\",\"n8n-nodes-base.readWriteFile\"]" },
  ]
  n8n_secrets = [{ name = "N8N_ENCRYPTION_KEY", valueFrom = local.secret["N8N_ENCRYPTION_KEY"] }, { name = "DB_POSTGRESDB_PASSWORD", valueFrom = local.secret["N8N_DB_PASSWORD"] }]
  app_env = [
    { name = "AUTH_MODE", value = "oidc" }, { name = "SEED_DEMO", value = "false" }, { name = "RUN_EXECUTION", value = "worker" },
    { name = "N8N_MODE", value = "rest" }, { name = "N8N_API_URL", value = "${local.n8n_url}/api/v1" }, { name = "N8N_WEBHOOK_URL", value = local.n8n_url },
    { name = "AIVANTA_BRIDGE_URL", value = local.api_url }, { name = "LLM_PROVIDER", value = var.llm_provider },
    { name = "OIDC_ISSUER", value = var.oidc_issuer }, { name = "OIDC_AUDIENCE", value = var.oidc_audience }, { name = "OIDC_JWKS_URL", value = var.oidc_jwks_url },
    { name = "STORAGE_DIR", value = "/data/objects" }, { name = "CORS_ORIGINS", value = var.web_origin },
  ]
  app_secrets = [for k in ["DATABASE_URL", "AIVANTA_BRIDGE_TOKEN", "N8N_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"] : { name = k, valueFrom = local.secret[k] }]
  services = {
    api        = { image = "${aws_ecr_repository.repo["api"].repository_url}:${var.image_tag}", port = 8000, cpu = 1024, mem = 2048, count = 2, cmd = null, env = local.app_env, secrets = local.app_secrets }
    worker     = { image = "${aws_ecr_repository.repo["api"].repository_url}:${var.image_tag}", port = null, cpu = 512, mem = 1024, count = 2, cmd = ["python", "-m", "aivanta_api.worker"], env = local.app_env, secrets = local.app_secrets }
    web        = { image = "${aws_ecr_repository.repo["web"].repository_url}:${var.image_tag}", port = 3000, cpu = 512, mem = 1024, count = 2, cmd = null, env = [], secrets = [] }
    n8n        = { image = "docker.n8n.io/n8nio/n8n:${var.n8n_version}", port = 5678, cpu = 2048, mem = 4096, count = 1, cmd = null, env = local.n8n_env, secrets = local.n8n_secrets }
    n8n-worker = { image = "docker.n8n.io/n8nio/n8n:${var.n8n_version}", port = null, cpu = 2048, mem = 4096, count = var.n8n_workers, cmd = ["worker"], env = local.n8n_env, secrets = local.n8n_secrets }
  }
}

resource "aws_ecs_task_definition" "svc" {
  for_each                 = local.services
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.mem
  execution_role_arn       = aws_iam_role.exec.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([merge({
    name         = each.key
    image        = each.value.image
    essential    = true
    environment  = each.value.env
    secrets      = each.value.secrets
    portMappings = each.value.port == null ? [] : [{ containerPort = each.value.port }]
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.logs.name, awslogs-region = var.region, awslogs-stream-prefix = each.key } }
  }, each.value.cmd == null ? {} : { command = each.value.cmd })])
}

resource "aws_service_discovery_service" "svc" {
  for_each = { for k, v in local.services : k => v if v.port != null }
  name     = each.key
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.ns.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}

resource "aws_ecs_service" "svc" {
  for_each        = local.services
  name            = each.key
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.svc[each.key].arn
  desired_count   = each.value.count
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.tasks.id]
  }
  dynamic "service_registries" {
    for_each = each.value.port == null ? [] : [1]
    content { registry_arn = aws_service_discovery_service.svc[each.key].arn }
  }
  dynamic "load_balancer" {
    for_each = contains(["web", "api"], each.key) ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.public[each.key].arn
      container_name   = each.key
      container_port   = each.value.port
    }
  }
}

# ---------------------------------------------------------------------------- public ALB: web and /api only.
# /internal/* and /gateway/* (n8n → API) and the n8n editor are never exposed publicly.
resource "aws_lb" "public" {
  name               = substr("${local.name}-pub", 0, 32)
  load_balancer_type = "application"
  subnets            = var.public_subnet_ids
  security_groups    = [aws_security_group.alb.id]
}
resource "aws_lb_target_group" "public" {
  for_each    = { web = 3000, api = 8000 }
  name        = substr("${local.name}-${each.key}", 0, 32)
  port        = each.value
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id
  health_check { path = each.key == "api" ? "/api/health" : "/" }
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.public.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.public["web"].arn
  }
}
resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.public["api"].arn
  }
  condition {
    path_pattern { values = ["/api/*"] }
  }
}
