#!/bin/bash
# Media directory initialization script for containerized Django
# Ensures media directory exists with proper permissions

set -e

MEDIA_DIR="${MEDIA_ROOT:-/app/media}"

echo "Initializing media directory: ${MEDIA_DIR}"

# Create media directory if it doesn't exist
if [ ! -d "${MEDIA_DIR}" ]; then
    echo "Creating media directory: ${MEDIA_DIR}"
    mkdir -p "${MEDIA_DIR}"
fi

# Create common subdirectories for Django media uploads
# These match the upload_to paths in models
mkdir -p "${MEDIA_DIR}/business"
mkdir -p "${MEDIA_DIR}/products"
mkdir -p "${MEDIA_DIR}/employees"
mkdir -p "${MEDIA_DIR}/documents"
mkdir -p "${MEDIA_DIR}/avatars"
mkdir -p "${MEDIA_DIR}/invoices"
mkdir -p "${MEDIA_DIR}/receipts"

# Ensure the current user has write permissions
# In Kubernetes, the directory might be owned by root
chmod -R 755 "${MEDIA_DIR}" 2>/dev/null || echo "Warning: Could not set permissions on ${MEDIA_DIR}"

echo "✓ Media directory initialized successfully"
ls -la "${MEDIA_DIR}"

