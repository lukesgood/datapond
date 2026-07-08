# Durable vault for the app's critical secrets (ENCRYPTION_KEY, JWT_SECRET,
# INTERNAL_API_KEY, DB master password). Created EMPTY — values are Helm-generated
# at runtime and are seeded here by the documented post-install step (see
# docs/DISASTER_RECOVERY.md). TF never stores the values (they'd leak into state).
resource "aws_secretsmanager_secret" "critical" {
  name                    = "${var.name_prefix}/critical-secrets"
  description             = "DataPond critical secrets — DR vault (ENCRYPTION_KEY etc.). Seeded post-install."
  recovery_window_in_days = 30
  kms_key_id              = var.db_kms_key_id # reuse the optional CMK var; null ⇒ AWS-managed key
}
