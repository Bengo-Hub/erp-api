"""
Document Number Service - Centralized document numbering for ERP system.

This service provides atomic, concurrency-safe document number generation
for all billing and commercial documents following the standard format:
<PREFIX><AAAA>-<DDMMYY>

Where:
- PREFIX: 3-letter code (configurable via business.PrefixSettings)
- AAAA: Zero-padded, auto-incrementing sequence per document type
- DDMMYY: Document creation date (backend time)

Examples:
- INV0033-150126 (Invoice #33 on Jan 15, 2026)
- LSO0034-150126 (Purchase Order #34 on Jan 15, 2026)
- CRN0001-150126 (Credit Note #1 on Jan 15, 2026)

Usage:
    from business.document_service import DocumentNumberService

    # Generate a document number
    doc_number = DocumentNumberService.generate_number(
        business=business_instance,
        document_type='invoice',
        document_date=timezone.now()
    )

    # Preview next number without incrementing
    preview = DocumentNumberService.get_next_sequence_preview(
        business=business_instance,
        document_type='invoice'
    )
"""

from django.db import transaction
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


# Document type constants for type safety
class DocumentType:
    """Document type constants matching DocumentSequence.DOCUMENT_TYPE_CHOICES."""
    INVOICE = 'invoice'
    PURCHASE_ORDER = 'purchase_order'
    CREDIT_NOTE = 'credit_note'
    DEBIT_NOTE = 'debit_note'
    QUOTATION = 'quotation'
    DELIVERY_NOTE = 'delivery_note'
    EXPENSE = 'expense'
    STOCK_TRANSFER = 'stock_transfer'
    STOCK_ADJUSTMENT = 'stock_adjustment'
    PURCHASE_REQUISITION = 'purchase_requisition'
    SALE_RETURN = 'sale_return'
    PURCHASE_RETURN = 'purchase_return'

    # Default prefixes (used if PrefixSettings not configured)
    DEFAULT_PREFIXES = {
        INVOICE: 'INV',
        PURCHASE_ORDER: 'LSO',
        CREDIT_NOTE: 'CRN',
        DEBIT_NOTE: 'DBN',
        QUOTATION: 'QOT',
        DELIVERY_NOTE: 'POD',
        EXPENSE: 'EP',
        STOCK_TRANSFER: 'STR',
        STOCK_ADJUSTMENT: 'ADJ',
        PURCHASE_REQUISITION: 'PRQ',
        SALE_RETURN: 'SR',
        PURCHASE_RETURN: 'PRT',
    }


class DocumentNumberService:
    """
    Centralized service for generating document numbers.

    This service is the ONLY authoritative source for document number generation.
    All document models should use this service instead of implementing their own
    number generation logic.

    Thread-safe and concurrency-safe through database row locking.
    """

    @staticmethod
    @transaction.atomic
    def generate_number(business, document_type, document_date=None):
        """
        Generate a unique document number.

        Args:
            business: The business entity (Bussiness model instance or ID)
            document_type: One of DocumentType constants
            document_date: Optional date for the document (defaults to now)

        Returns:
            str: The generated document number (e.g., "INV0033-150126")

        Raises:
            ValueError: If document_type is invalid
            Bussiness.DoesNotExist: If business_id doesn't exist
        """
        from business.models import Bussiness, DocumentSequence, PrefixSettings

        # Validate document type
        valid_types = [choice[0] for choice in DocumentSequence.DOCUMENT_TYPE_CHOICES]
        if document_type not in valid_types:
            raise ValueError(f"Invalid document type: {document_type}. Must be one of {valid_types}")

        # Get business instance if ID was passed
        if isinstance(business, int):
            business = Bussiness.objects.get(pk=business)

        # Use provided date or current time
        if document_date is None:
            document_date = timezone.now()

        # Get or create sequence with row-level lock for concurrency safety
        sequence, created = DocumentSequence.objects.select_for_update().get_or_create(
            business=business,
            document_type=document_type,
            defaults={'current_sequence': 0}
        )

        # Increment sequence
        sequence.current_sequence += 1
        sequence.save(update_fields=['current_sequence', 'updated_at'])

        # Get prefix from PrefixSettings or use default
        prefix = DocumentType.DEFAULT_PREFIXES.get(document_type, 'DOC')
        try:
            prefix_settings = PrefixSettings.objects.filter(business=business).first()
            if prefix_settings:
                custom_prefix = prefix_settings.get_prefix(document_type)
                if custom_prefix:
                    prefix = custom_prefix
        except Exception as e:
            logger.warning(f"Could not load custom prefix settings: {e}")

        # Format: PREFIX0000-DDMMYY
        seq_str = f"{sequence.current_sequence:04d}"

        # Format date as DDMMYY
        if hasattr(document_date, 'date'):
            date_obj = document_date.date()
        else:
            date_obj = document_date
        date_str = date_obj.strftime('%d%m%y')

        document_number = f"{prefix}{seq_str}-{date_str}"

        logger.info(f"Generated document number: {document_number} for {business.name}")

        return document_number

    @staticmethod
    def get_next_sequence_preview(business, document_type):
        """
        Get a preview of the next document number without incrementing.

        Useful for displaying "Next number will be: INV0034" in UI.

        Args:
            business: The business entity
            document_type: One of DocumentType constants

        Returns:
            dict: Contains 'next_number', 'current_sequence', and 'prefix'
        """
        from business.models import Bussiness, DocumentSequence, PrefixSettings

        if isinstance(business, int):
            business = Bussiness.objects.get(pk=business)

        try:
            sequence = DocumentSequence.objects.get(
                business=business,
                document_type=document_type
            )
            next_seq = sequence.current_sequence + 1
        except DocumentSequence.DoesNotExist:
            next_seq = 1

        # Get prefix
        prefix = DocumentType.DEFAULT_PREFIXES.get(document_type, 'DOC')
        try:
            prefix_settings = PrefixSettings.objects.filter(business=business).first()
            if prefix_settings:
                custom_prefix = prefix_settings.get_prefix(document_type)
                if custom_prefix:
                    prefix = custom_prefix
        except Exception:
            pass

        # Preview with today's date
        date_str = timezone.now().strftime('%d%m%y')
        preview_number = f"{prefix}{next_seq:04d}-{date_str}"

        return {
            'next_number': preview_number,
            'current_sequence': next_seq - 1,
            'prefix': prefix,
        }

    @staticmethod
    @transaction.atomic
    def set_sequence(business, document_type, sequence_value):
        """
        Set the current sequence value for a document type.

        Use this for migration or manual correction purposes.

        Args:
            business: The business entity
            document_type: One of DocumentType constants
            sequence_value: The sequence value to set

        Returns:
            DocumentSequence: The updated sequence object
        """
        from business.models import Bussiness, DocumentSequence

        if isinstance(business, int):
            business = Bussiness.objects.get(pk=business)

        sequence, _ = DocumentSequence.objects.select_for_update().get_or_create(
            business=business,
            document_type=document_type
        )

        sequence.current_sequence = sequence_value
        sequence.save(update_fields=['current_sequence', 'updated_at'])

        logger.info(f"Set sequence for {document_type} in {business.name} to {sequence_value}")

        return sequence

    @staticmethod
    def get_all_sequences(business):
        """
        Get all document sequences for a business.

        Returns:
            QuerySet: All DocumentSequence objects for the business
        """
        from business.models import Bussiness, DocumentSequence

        if isinstance(business, int):
            business = Bussiness.objects.get(pk=business)

        return DocumentSequence.objects.filter(business=business)

    @staticmethod
    def initialize_sequences_for_business(business, starting_value=32):
        """
        Initialize all document sequences for a new business.

        Args:
            business: The business entity
            starting_value: The starting sequence value (default 32, so next is 33)

        Returns:
            list: Created DocumentSequence objects
        """
        from business.models import Bussiness, DocumentSequence

        if isinstance(business, int):
            business = Bussiness.objects.get(pk=business)

        sequences = []
        for doc_type, _ in DocumentSequence.DOCUMENT_TYPE_CHOICES:
            seq, created = DocumentSequence.objects.get_or_create(
                business=business,
                document_type=doc_type,
                defaults={'current_sequence': starting_value}
            )
            sequences.append(seq)

        return sequences
