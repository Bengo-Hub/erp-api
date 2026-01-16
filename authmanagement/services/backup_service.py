"""
Production-Ready Backup Service

Handles database backups with support for:
- Full and incremental backups
- Local storage and Amazon S3
- Backup scheduling
- Backup retention cleanup
- Download URL generation
- Restore operations
"""

import os
import subprocess
import gzip
import shutil
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


class BackupService:
    """
    Service for managing database backups with local and S3 storage support.
    """

    def __init__(self):
        self.backup_dir = getattr(settings, 'BACKUP_ROOT', '/app/backups')
        self._ensure_backup_dir()

    def _ensure_backup_dir(self):
        """Ensure backup directory exists."""
        if not os.path.exists(self.backup_dir):
            try:
                os.makedirs(self.backup_dir, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create backup directory: {e}")

    def _get_db_config(self):
        """Get database configuration from settings."""
        db_config = settings.DATABASES['default']
        return {
            'engine': db_config.get('ENGINE', ''),
            'name': db_config.get('NAME', ''),
            'user': db_config.get('USER', ''),
            'password': db_config.get('PASSWORD', ''),
            'host': db_config.get('HOST', 'localhost'),
            'port': db_config.get('PORT', '5432'),
        }

    def _get_backup_config(self):
        """Get backup configuration from database."""
        from authmanagement.models import BackupConfig
        config = BackupConfig.objects.first()
        if not config:
            config = BackupConfig.objects.create(
                storage_type='local',
                local_path=self.backup_dir,
                retention_days=30
            )
        return config

    def _get_s3_client(self, config):
        """Get S3 client using backup config credentials."""
        try:
            import boto3
            from botocore.config import Config

            s3_config = Config(
                signature_version='s3v4',
                retries={'max_attempts': 3, 'mode': 'standard'}
            )

            # Use backup-specific credentials if provided, otherwise fall back to settings
            access_key = config.s3_access_key or getattr(settings, 'AWS_ACCESS_KEY_ID', '')
            secret_key = config.s3_secret_key or getattr(settings, 'AWS_SECRET_ACCESS_KEY', '')
            region = config.s3_region or getattr(settings, 'AWS_S3_REGION_NAME', 'us-east-1')

            return boto3.client(
                's3',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=s3_config
            )
        except ImportError:
            logger.error("boto3 not installed. Install with: pip install boto3")
            raise
        except Exception as e:
            logger.error(f"Failed to create S3 client: {e}")
            raise

    def create_backup(self, backup_type='full', user_id=None):
        """
        Create a database backup.

        Args:
            backup_type: 'full' or 'incremental'
            user_id: ID of user initiating backup (for audit)

        Returns:
            Backup model instance
        """
        from authmanagement.models import Backup

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'backup_{backup_type}_{timestamp}.sql'
        compressed_filename = f'{filename}.gz'

        # Create backup record
        backup = Backup.objects.create(
            type=backup_type,
            path='',
            size=0,
            status='in_progress'
        )

        local_path = os.path.join(self.backup_dir, filename)
        compressed_path = os.path.join(self.backup_dir, compressed_filename)

        try:
            db_config = self._get_db_config()
            backup_config = self._get_backup_config()

            # Generate dump command based on database engine
            if 'postgresql' in db_config['engine']:
                success, error_msg = self._create_postgres_backup(db_config, local_path)
            elif 'mysql' in db_config['engine']:
                success, error_msg = self._create_mysql_backup(db_config, local_path)
            else:
                raise ValueError(f"Unsupported database engine: {db_config['engine']}")

            if not success:
                raise Exception(error_msg or "Database dump failed")

            # Compress the backup
            self._compress_file(local_path, compressed_path)

            # Remove uncompressed file
            if os.path.exists(local_path):
                os.remove(local_path)

            # Get file size
            file_size = os.path.getsize(compressed_path)

            # Upload to S3 if configured
            final_path = compressed_path
            s3_key = None

            if backup_config.storage_type == 's3' and backup_config.s3_bucket:
                s3_key = self._upload_to_s3(compressed_path, compressed_filename, backup_config)
                final_path = s3_key

                # Remove local file after successful S3 upload
                if os.path.exists(compressed_path):
                    os.remove(compressed_path)

            # Update backup record
            backup.path = final_path
            backup.size = file_size
            backup.status = 'completed'
            backup.completed_at = timezone.now()
            backup.save()

            logger.info(f"Backup created successfully: {final_path} ({file_size} bytes)")

            # Cleanup old backups
            self._cleanup_old_backups(backup_config)

            return backup

        except Exception as e:
            logger.error(f"Backup failed: {str(e)}")
            backup.status = 'failed'
            backup.error_message = str(e)
            backup.save()

            # Cleanup partial files
            for path in [local_path, compressed_path]:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

            raise

    def _create_postgres_backup(self, db_config, output_path):
        """Create PostgreSQL backup using pg_dump.

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        env = os.environ.copy()
        env['PGPASSWORD'] = db_config['password']

        cmd = [
            'pg_dump',
            '-h', db_config['host'],
            '-p', str(db_config['port']),
            '-U', db_config['user'],
            '-d', db_config['name'],
            '-F', 'p',  # Plain format
            '--no-owner',
            '--no-acl',
            '-f', output_path
        ]

        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )

            if result.returncode != 0:
                error_msg = f"pg_dump error: {result.stderr}"
                logger.error(error_msg)
                return False, error_msg

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True, None
            return False, "Backup file is empty or was not created"

        except subprocess.TimeoutExpired:
            error_msg = "pg_dump timed out after 1 hour"
            logger.error(error_msg)
            return False, error_msg
        except FileNotFoundError:
            error_msg = "pg_dump not found. Install PostgreSQL client tools (e.g., 'apt install postgresql-client' or download from postgresql.org)"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"pg_dump failed: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    def _create_mysql_backup(self, db_config, output_path):
        """Create MySQL backup using mysqldump.

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        cmd = [
            'mysqldump',
            f'--host={db_config["host"]}',
            f'--port={db_config["port"]}',
            f'--user={db_config["user"]}',
            f'--password={db_config["password"]}',
            '--single-transaction',
            '--quick',
            '--lock-tables=false',
            db_config['name'],
        ]

        try:
            with open(output_path, 'w') as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3600
                )

            if result.returncode != 0:
                error_msg = f"mysqldump error: {result.stderr}"
                logger.error(error_msg)
                return False, error_msg

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True, None
            return False, "Backup file is empty or was not created"

        except subprocess.TimeoutExpired:
            error_msg = "mysqldump timed out after 1 hour"
            logger.error(error_msg)
            return False, error_msg
        except FileNotFoundError:
            error_msg = "mysqldump not found. Install MySQL client tools"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"mysqldump failed: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    def _compress_file(self, input_path, output_path):
        """Compress file using gzip."""
        with open(input_path, 'rb') as f_in:
            with gzip.open(output_path, 'wb', compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)

    def _upload_to_s3(self, local_path, filename, config):
        """Upload backup file to S3."""
        s3_client = self._get_s3_client(config)
        s3_key = f'backups/{filename}'

        try:
            s3_client.upload_file(
                local_path,
                config.s3_bucket,
                s3_key,
                ExtraArgs={
                    'ContentType': 'application/gzip',
                    'ServerSideEncryption': 'AES256'
                }
            )
            logger.info(f"Uploaded backup to S3: s3://{config.s3_bucket}/{s3_key}")
            return s3_key
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            raise

    def _cleanup_old_backups(self, config):
        """Remove backups older than retention period."""
        from authmanagement.models import Backup

        cutoff_date = timezone.now() - timedelta(days=config.retention_days)
        old_backups = Backup.objects.filter(
            created_at__lt=cutoff_date,
            status='completed'
        )

        for backup in old_backups:
            try:
                self.delete_backup(backup.id)
                logger.info(f"Cleaned up old backup: {backup.path}")
            except Exception as e:
                logger.error(f"Failed to cleanup backup {backup.id}: {e}")

    def get_download_url(self, backup_id, expires_in=3600):
        """
        Get download URL for a backup.

        Args:
            backup_id: ID of backup
            expires_in: URL expiration time in seconds (for S3)

        Returns:
            Download URL or local path
        """
        from authmanagement.models import Backup

        backup = Backup.objects.get(id=backup_id)
        config = self._get_backup_config()

        if config.storage_type == 's3' and backup.path.startswith('backups/'):
            # Generate presigned S3 URL
            s3_client = self._get_s3_client(config)
            try:
                url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': config.s3_bucket,
                        'Key': backup.path
                    },
                    ExpiresIn=expires_in
                )
                return url
            except Exception as e:
                logger.error(f"Failed to generate presigned URL: {e}")
                raise
        else:
            # Return local path (frontend handles download via API)
            return backup.path

    def download_backup(self, backup_id):
        """
        Get backup file content for download.

        Args:
            backup_id: ID of backup

        Returns:
            Tuple of (file_content, filename, content_type)
        """
        from authmanagement.models import Backup

        backup = Backup.objects.get(id=backup_id)
        config = self._get_backup_config()

        filename = os.path.basename(backup.path)

        if config.storage_type == 's3' and backup.path.startswith('backups/'):
            # Download from S3
            s3_client = self._get_s3_client(config)
            try:
                response = s3_client.get_object(
                    Bucket=config.s3_bucket,
                    Key=backup.path
                )
                content = response['Body'].read()
                return content, filename, 'application/gzip'
            except Exception as e:
                logger.error(f"Failed to download from S3: {e}")
                raise
        else:
            # Read from local filesystem
            if not os.path.exists(backup.path):
                raise FileNotFoundError(f"Backup file not found: {backup.path}")

            with open(backup.path, 'rb') as f:
                content = f.read()

            return content, filename, 'application/gzip'

    def restore_backup(self, backup_id):
        """
        Restore database from backup.

        WARNING: This will overwrite the current database!

        Args:
            backup_id: ID of backup to restore

        Returns:
            bool: Success status
        """
        from authmanagement.models import Backup

        backup = Backup.objects.get(id=backup_id)
        config = self._get_backup_config()
        db_config = self._get_db_config()

        # Download backup if on S3
        if config.storage_type == 's3' and backup.path.startswith('backups/'):
            local_path = os.path.join(self.backup_dir, 'restore_temp.sql.gz')
            s3_client = self._get_s3_client(config)

            try:
                s3_client.download_file(
                    config.s3_bucket,
                    backup.path,
                    local_path
                )
            except Exception as e:
                logger.error(f"Failed to download backup from S3: {e}")
                raise
        else:
            local_path = backup.path

        # Decompress
        decompressed_path = local_path.replace('.gz', '')
        try:
            with gzip.open(local_path, 'rb') as f_in:
                with open(decompressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Restore based on database engine
            if 'postgresql' in db_config['engine']:
                success = self._restore_postgres(db_config, decompressed_path)
            elif 'mysql' in db_config['engine']:
                success = self._restore_mysql(db_config, decompressed_path)
            else:
                raise ValueError(f"Unsupported database engine: {db_config['engine']}")

            return success

        finally:
            # Cleanup temp files
            if os.path.exists(decompressed_path):
                os.remove(decompressed_path)
            if config.storage_type == 's3' and os.path.exists(local_path):
                os.remove(local_path)

    def _restore_postgres(self, db_config, backup_path):
        """Restore PostgreSQL database from backup."""
        env = os.environ.copy()
        env['PGPASSWORD'] = db_config['password']

        cmd = [
            'psql',
            '-h', db_config['host'],
            '-p', str(db_config['port']),
            '-U', db_config['user'],
            '-d', db_config['name'],
            '-f', backup_path
        ]

        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=3600
            )

            if result.returncode != 0:
                logger.error(f"psql restore error: {result.stderr}")
                return False

            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def _restore_mysql(self, db_config, backup_path):
        """Restore MySQL database from backup."""
        cmd = [
            'mysql',
            f'--host={db_config["host"]}',
            f'--port={db_config["port"]}',
            f'--user={db_config["user"]}',
            f'--password={db_config["password"]}',
            db_config['name'],
        ]

        try:
            with open(backup_path, 'r') as f:
                result = subprocess.run(
                    cmd,
                    stdin=f,
                    capture_output=True,
                    text=True,
                    timeout=3600
                )

            if result.returncode != 0:
                logger.error(f"mysql restore error: {result.stderr}")
                return False

            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def delete_backup(self, backup_id):
        """
        Delete a backup.

        Args:
            backup_id: ID of backup to delete
        """
        from authmanagement.models import Backup

        backup = Backup.objects.get(id=backup_id)
        config = self._get_backup_config()

        # Delete file
        if config.storage_type == 's3' and backup.path.startswith('backups/'):
            try:
                s3_client = self._get_s3_client(config)
                s3_client.delete_object(
                    Bucket=config.s3_bucket,
                    Key=backup.path
                )
            except Exception as e:
                logger.error(f"Failed to delete S3 object: {e}")
        else:
            if os.path.exists(backup.path):
                os.remove(backup.path)

        # Delete database record
        backup.delete()

    def list_backups(self, limit=50, offset=0):
        """
        List all backups.

        Args:
            limit: Max number of backups to return
            offset: Offset for pagination

        Returns:
            QuerySet of Backup objects
        """
        from authmanagement.models import Backup

        return Backup.objects.all().order_by('-created_at')[offset:offset + limit]


# Singleton instance
backup_service = BackupService()
