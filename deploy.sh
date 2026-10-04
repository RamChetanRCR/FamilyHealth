#!/bin/bash

set -e

echo "Pulling latest code..."
git pull origin main

echo "Building Docker images..."
docker compose build

echo "Starting containers..."
docker compose up -d

echo "Checking containers..."
docker compose ps

echo "Checking backend health..."
if ! curl -fsS http://127.0.0.1:18100/health >/dev/null; then
    echo "Backend health check failed."
    exit 1
fi

echo "Deployment complete."
