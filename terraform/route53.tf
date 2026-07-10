# A record for the app hostname → the node's Elastic IP. Created only when a zone+domain
# are supplied (deploy time); empty ⇒ skipped so plan/validate work without them.
resource "aws_route53_record" "app" {
  count   = var.route53_zone_id != "" && var.domain != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain
  type    = "A"
  ttl     = 300
  records = [aws_eip.node.public_ip]
}
