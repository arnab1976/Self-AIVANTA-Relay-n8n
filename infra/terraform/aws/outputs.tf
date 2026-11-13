output "public_alb_dns" { value = aws_lb.public.dns_name }
output "ecr_repositories" { value = { for k, r in aws_ecr_repository.repo : k => r.repository_url } }
output "rds_endpoint" { value = aws_db_instance.pg.address }
output "redis_endpoint" { value = aws_elasticache_replication_group.redis.primary_endpoint_address }
output "objects_bucket" { value = aws_s3_bucket.objects.bucket }
