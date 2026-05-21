#!/bin/bash
# DataPond Disk Cleanup Script
# This script safely cleans up unused Docker resources to free disk space

set -e

echo "=== DataPond Disk Cleanup ==="
echo ""

echo "Current disk usage:"
df -h / | grep -v "Filesystem"
echo ""

echo "Current Docker usage:"
docker system df
echo ""

echo "Step 1: Cleaning Docker build cache..."
docker builder prune -af --filter "until=24h"
echo "✓ Build cache cleaned"
echo ""

echo "Step 2: Cleaning unused Docker images..."
docker image prune -af --filter "until=168h"
echo "✓ Unused images cleaned"
echo ""

echo "Step 3: Cleaning Docker system (containers, networks, volumes)..."
docker system prune -f --volumes
echo "✓ System cleaned"
echo ""

echo "Final disk usage:"
df -h / | grep -v "Filesystem"
echo ""

echo "Final Docker usage:"
docker system df
echo ""

echo "✅ Cleanup complete!"
