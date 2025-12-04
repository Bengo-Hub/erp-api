#!/bin/bash
# Media directory initialization script for containerized Django
# Ensures media directory exists and is writable by app user

set -e

MEDIA_DIR="${MEDIA_ROOT:-/app/media}"

echo "📁 Initializing media directory: ${MEDIA_DIR}"

# Check if media directory exists
if [ ! -d "${MEDIA_DIR}" ]; then
    echo "   Creating media directory..."
    mkdir -p "${MEDIA_DIR}" 2>/dev/null || {
        echo "   ⚠️ Cannot create ${MEDIA_DIR} (will be created by Kubernetes PVC)"
    }
fi

# Create common subdirectories for Django media uploads
# These match the upload_to paths in models
# Use -p to avoid errors if already exist
for subdir in business products employees documents avatars invoices receipts userprofiles; do
    if [ -d "${MEDIA_DIR}" ]; then
        mkdir -p "${MEDIA_DIR}/${subdir}" 2>/dev/null || true
    fi
done

# Test write permissions by creating a test file
if [ -d "${MEDIA_DIR}" ] && [ -w "${MEDIA_DIR}" ]; then
    touch "${MEDIA_DIR}/.writable_test" 2>/dev/null && rm -f "${MEDIA_DIR}/.writable_test" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "   ✅ Media directory is writable"
    else
        echo "   ⚠️ Media directory exists but may not be writable"
    fi
else
    echo "   ⚠️ Media directory not writable (will be mounted by Kubernetes PVC)"
fi

# Try to set permissions only if we own the directory
if [ -d "${MEDIA_DIR}" ] && [ -O "${MEDIA_DIR}" ]; then
    chmod -R u+rwX "${MEDIA_DIR}" 2>/dev/null || echo "   ℹ️ Running with existing permissions"
fi

echo "   ✅ Media directory ready"

# Show directory status (suppress errors if not accessible)
ls -la "${MEDIA_DIR}" 2>/dev/null | head -10 || echo "   (Directory details unavailable)"

