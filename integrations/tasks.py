"""
Celery tasks for integrations app.
Includes scheduled tasks for exchange rate updates.
"""
import logging
import requests
from datetime import datetime, date
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_exchange_rates(self):
    """
    Fetch exchange rates from configured external API.
    This task is scheduled to run daily at 00:00 hrs.

    The task:
    1. Checks if there's an active ExchangeRateAPISettings configuration
    2. Verifies we haven't already fetched rates today
    3. Calls the external API to get latest rates
    4. Updates local ExchangeRate records
    """
    from integrations.models import ExchangeRateAPISettings
    from core.models import ExchangeRate

    logger.info("Starting exchange rate fetch task")

    try:
        # Get active API settings
        settings = ExchangeRateAPISettings.objects.filter(is_active=True).first()

        if not settings:
            logger.warning("No active exchange rate API settings found")
            return {"status": "skipped", "reason": "No active API settings"}

        # Check if we've already fetched rates today
        today = timezone.now().date()
        if settings.last_fetch_at and settings.last_fetch_at.date() == today:
            logger.info(f"Exchange rates already fetched today at {settings.last_fetch_at}")
            return {"status": "skipped", "reason": "Already fetched today"}

        # Get decrypted access key
        access_key = settings.get_decrypted_access_key()
        if not access_key:
            logger.error("No access key configured for exchange rate API")
            settings.last_fetch_status = 'failed'
            settings.last_fetch_error = 'No access key configured'
            settings.save(update_fields=['last_fetch_status', 'last_fetch_error', 'updated_at'])
            return {"status": "error", "reason": "No access key"}

        # Build API URL with parameters
        target_currencies = settings.target_currencies or ['KES', 'USD', 'EUR', 'GBP']
        currencies_str = ','.join(target_currencies)

        # Build the API request URL
        api_url = f"{settings.api_endpoint}?access_key={access_key}&source={settings.source_currency}&currencies={currencies_str}"

        logger.info(f"Fetching rates from {settings.api_endpoint} for currencies: {currencies_str}")

        # Make API request
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()

        data = response.json()

        # Check for API success
        if not data.get('success', False):
            error_msg = data.get('error', {}).get('info', 'Unknown API error')
            logger.error(f"Exchange rate API error: {error_msg}")
            settings.last_fetch_status = 'failed'
            settings.last_fetch_error = error_msg
            settings.save(update_fields=['last_fetch_status', 'last_fetch_error', 'updated_at'])
            return {"status": "error", "reason": error_msg}

        # Parse and store rates
        quotes = data.get('quotes', {})
        source_currency = settings.source_currency
        rates_updated = 0

        for currency_pair, rate in quotes.items():
            # Currency pair format: "USDKES", "USDEUR", etc.
            # Extract target currency (last 3 characters)
            target_currency = currency_pair[-3:]

            if target_currency == source_currency:
                continue  # Skip same currency

            try:
                # Update or create exchange rate record
                ExchangeRate.objects.update_or_create(
                    from_currency=source_currency,
                    to_currency=target_currency,
                    effective_date=today,
                    defaults={
                        'rate': rate,
                        'source': 'api',
                    }
                )

                # Also create reverse rate if needed
                reverse_rate = 1 / rate if rate > 0 else 0
                ExchangeRate.objects.update_or_create(
                    from_currency=target_currency,
                    to_currency=source_currency,
                    effective_date=today,
                    defaults={
                        'rate': reverse_rate,
                        'source': 'api',
                    }
                )

                rates_updated += 1
                logger.info(f"Updated rate: {source_currency} -> {target_currency} = {rate}")

            except Exception as e:
                logger.error(f"Error saving rate for {target_currency}: {e}")

        # Update settings with success status
        settings.last_fetch_at = timezone.now()
        settings.last_fetch_status = 'success'
        settings.last_fetch_error = None
        settings.save(update_fields=['last_fetch_at', 'last_fetch_status', 'last_fetch_error', 'updated_at'])

        logger.info(f"Exchange rate fetch completed. {rates_updated} rate pairs updated.")

        return {
            "status": "success",
            "rates_updated": rates_updated,
            "timestamp": timezone.now().isoformat()
        }

    except requests.RequestException as e:
        logger.error(f"HTTP error fetching exchange rates: {e}")
        # Update settings with error
        try:
            settings = ExchangeRateAPISettings.objects.filter(is_active=True).first()
            if settings:
                settings.last_fetch_status = 'failed'
                settings.last_fetch_error = str(e)
                settings.save(update_fields=['last_fetch_status', 'last_fetch_error', 'updated_at'])
        except Exception:
            pass

        # Retry the task
        raise self.retry(exc=e)

    except Exception as e:
        logger.error(f"Error in exchange rate fetch task: {e}")
        # Update settings with error
        try:
            settings = ExchangeRateAPISettings.objects.filter(is_active=True).first()
            if settings:
                settings.last_fetch_status = 'failed'
                settings.last_fetch_error = str(e)
                settings.save(update_fields=['last_fetch_status', 'last_fetch_error', 'updated_at'])
        except Exception:
            pass

        return {"status": "error", "reason": str(e)}


@shared_task
def manual_fetch_exchange_rates():
    """
    Manually trigger exchange rate fetch (bypasses daily check).
    Use this for testing or when rates need immediate refresh.
    """
    from integrations.models import ExchangeRateAPISettings
    from core.models import ExchangeRate

    logger.info("Starting manual exchange rate fetch")

    try:
        settings = ExchangeRateAPISettings.objects.filter(is_active=True).first()

        if not settings:
            return {"status": "error", "reason": "No active API settings"}

        access_key = settings.get_decrypted_access_key()
        if not access_key:
            return {"status": "error", "reason": "No access key configured"}

        target_currencies = settings.target_currencies or ['KES', 'USD', 'EUR', 'GBP']
        currencies_str = ','.join(target_currencies)

        api_url = f"{settings.api_endpoint}?access_key={access_key}&source={settings.source_currency}&currencies={currencies_str}"

        response = requests.get(api_url, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data.get('success', False):
            error_msg = data.get('error', {}).get('info', 'Unknown API error')
            settings.last_fetch_status = 'failed'
            settings.last_fetch_error = error_msg
            settings.save(update_fields=['last_fetch_status', 'last_fetch_error', 'updated_at'])
            return {"status": "error", "reason": error_msg}

        quotes = data.get('quotes', {})
        source_currency = settings.source_currency
        today = timezone.now().date()
        rates_updated = 0

        for currency_pair, rate in quotes.items():
            target_currency = currency_pair[-3:]

            if target_currency == source_currency:
                continue

            try:
                ExchangeRate.objects.update_or_create(
                    from_currency=source_currency,
                    to_currency=target_currency,
                    effective_date=today,
                    defaults={
                        'rate': rate,
                        'source': 'api',
                    }
                )

                reverse_rate = 1 / rate if rate > 0 else 0
                ExchangeRate.objects.update_or_create(
                    from_currency=target_currency,
                    to_currency=source_currency,
                    effective_date=today,
                    defaults={
                        'rate': reverse_rate,
                        'source': 'api',
                    }
                )

                rates_updated += 1

            except Exception as e:
                logger.error(f"Error saving rate for {target_currency}: {e}")

        settings.last_fetch_at = timezone.now()
        settings.last_fetch_status = 'success'
        settings.last_fetch_error = None
        settings.save(update_fields=['last_fetch_at', 'last_fetch_status', 'last_fetch_error', 'updated_at'])

        return {
            "status": "success",
            "rates_updated": rates_updated,
            "timestamp": timezone.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error in manual exchange rate fetch: {e}")
        return {"status": "error", "reason": str(e)}
