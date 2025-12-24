"""Utility helpers for the finance app."""
from typing import Iterable, Optional
import os
import re
import html
from django.conf import settings
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Image, Flowable
from reportlab.lib import colors

try:
    from django.contrib.staticfiles import finders
except Exception:
    finders = None


def _safe_str(val) -> str:
    if val is None:
        return ''
    if isinstance(val, str):
        return val
    try:
        return str(val)
    except Exception:
        # Fallback to common attribute
        return getattr(val, 'name', '') or ''


def format_location_address(location, fields: Optional[Iterable[str]] = None) -> str:
    """Build a sane, deduplicated address string from a location-like object.

    - Converts non-string values (like Country objects) to strings safely
    - Removes empty parts
    - Deduplicates parts case-insensitively while preserving order

    Args:
        location: object with attributes (e.g., building_name, street_name, city, county, state, country)
        fields: optional iterable of attribute names to consider

    Returns:
        A single-line address string (comma separated) or empty string.
    """
    if not location:
        return ''

    if fields is None:
        fields = ['building_name', 'street_name', 'city', 'county', 'state', 'country']

    seen = set()
    parts = []
    for f in fields:
        try:
            raw = getattr(location, f, None)
        except Exception:
            raw = None
        v = _safe_str(raw).strip()
        if not v:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(v)

    return ', '.join(parts)


def get_customer_name(doc):
    """Get customer name from document"""
    try:
        customer = getattr(doc, 'customer', None)
        # Prefer customer business name, then customer user name
        if customer:
            bname = getattr(customer, 'business_name', None)
            if bname:
                return bname
            user = getattr(customer, 'user', None)
            if user and (user.first_name or user.last_name):
                return f"{user.first_name or ''} {user.last_name or ''}".strip()
        # Fallback: if doc has an associated created_by user, use that
        created_by = getattr(doc, 'created_by', None)
        if created_by:
            return f"{created_by.first_name or ''} {created_by.last_name or ''}".strip() or created_by.username
        return 'N/A'
    except:
        return "N/A"


def get_customer_email(doc):
    """Get customer email from document"""
    try:
        customer = getattr(doc, 'customer', None)
        if customer and getattr(customer, 'user', None):
            return getattr(customer.user, 'email', 'N/A')
        created_by = getattr(doc, 'created_by', None)
        if created_by:
            return getattr(created_by, 'email', 'N/A')
        return 'N/A'
    except:
        return "N/A"


def get_customer_phone(doc):
    """Get customer phone from document"""
    try:
        customer = getattr(doc, 'customer', None)
        if customer:
            # contact may have phone directly or via user
            phone = getattr(customer, 'phone', None)
            if phone:
                return phone
            user = getattr(customer, 'user', None)
            if user and getattr(user, 'phone', None):
                return user.phone
        # fallback to created_by phone or N/A
        created_by = getattr(doc, 'created_by', None)
        if created_by and getattr(created_by, 'phone', None):
            return created_by.phone
        return "N/A"
    except:
        return "N/A"

def _sanitize_text_for_pdf(text):
    """
    Sanitize HTML-ish text for PDF output.
    Returns plain text with newlines preserved.
    """
    try:
        if not text:
            return ''

        # Convert bytes to str if necessary
        if isinstance(text, bytes):
            text = text.decode('utf-8', errors='ignore')

        # Normalize common block separators to newlines
        text = re.sub(r'</p\s*>', '\n\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

        # Strip remaining tags
        text = re.sub(r'<[^>]+>', '', text)

        # Unescape HTML entities (e.g., &nbsp;, &amp;)
        text = html.unescape(text)

        # Replace multiple newlines with at most two
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()
    except Exception:
        return str(text)


def _get_logo_image(company_info, max_width=2*inch, max_height=1*inch):
    """Get logo image with proper aspect ratio.

    Accepts multiple forms for `logo_path`: path str, URL, bytes, file-like objects, or Django FieldFile.
    Returns a reportlab Image sized to fit within max_width/max_height, or None on failure.
    """
    data_source = None

    try:
        candidate = None
        if company_info:
            candidate = company_info.get('logo_path') if isinstance(company_info, dict) else getattr(company_info, 'logo_path', None)

        # Resolve candidate
        if candidate:
            # String (path, static path or URL)
            if isinstance(candidate, str):
                if os.path.exists(candidate):
                    data_source = candidate
                else:
                    try:
                        if finders:
                            found = finders.find(candidate.lstrip('/')) or finders.find('logo/logo.png')
                            if found:
                                data_source = found
                    except Exception:
                        pass

                    if not data_source and (candidate.startswith('http://') or candidate.startswith('https://')):
                        try:
                            from urllib.request import urlopen
                            resp = urlopen(candidate, timeout=5)
                            data = resp.read()
                            data_source = BytesIO(data)
                        except Exception:
                            data_source = None

                    if not data_source:
                        try:
                            potential = os.path.join(settings.BASE_DIR, candidate.lstrip('/'))
                            if os.path.exists(potential):
                                data_source = potential
                        except Exception:
                            pass

            # file-like
            elif hasattr(candidate, 'read'):
                try:
                    try:
                        candidate.seek(0)
                    except Exception:
                        pass
                    content = candidate.read()
                    if isinstance(content, str):
                        content = content.encode('utf-8')
                    data_source = BytesIO(content)
                except Exception:
                    try:
                        candidate.open()
                        content = candidate.read()
                        data_source = BytesIO(content if isinstance(content, (bytes, bytearray)) else str(content).encode('utf-8'))
                    except Exception:
                        data_source = None

            elif isinstance(candidate, (bytes, bytearray)):
                data_source = BytesIO(candidate)

            elif hasattr(candidate, '__fspath__'):
                try:
                    p = os.fspath(candidate)
                    if os.path.exists(p):
                        data_source = p
                except Exception:
                    pass

        # Default static fallback
        if not data_source:
            try:
                if finders:
                    default_found = finders.find('logo/logo.png') or finders.find('static/logo/logo.png')
                    if default_found:
                        data_source = default_found
                else:
                    candidate_path = os.path.join(settings.BASE_DIR, 'static', 'logo', 'logo.png')
                    if os.path.exists(candidate_path):
                        data_source = candidate_path
            except Exception:
                pass

            # Additional fallback: try staticfiles directory directly
            if not data_source:
                try:
                    staticfiles_path = os.path.join(settings.BASE_DIR, 'staticfiles', 'logo', 'logo.png')
                    if os.path.exists(staticfiles_path):
                        data_source = staticfiles_path
                    else:
                        # Try with hashed filename pattern
                        import glob
                        pattern = os.path.join(settings.BASE_DIR, 'staticfiles', 'logo', 'logo.*.png')
                        matches = glob.glob(pattern)
                        if matches:
                            data_source = matches[0]
                except Exception:
                    pass

        if not data_source:
            return None

        # Use ImageReader for robust size detection
        from reportlab.lib.utils import ImageReader
        ir = ImageReader(data_source)
        iw, ih = ir.getSize()
        if not iw or not ih:
            return None

        iw = float(iw)
        ih = float(ih)
        aspect = iw / ih

        if aspect > (float(max_width) / float(max_height)):
            drawW = float(max_width)
            drawH = float(max_width) / aspect
        else:
            drawH = float(max_height)
            drawW = float(max_height) * aspect

        img = Image(data_source, width=drawW, height=drawH)
        img.imageWidth = iw
        img.imageHeight = ih
        img.drawWidth = drawW
        img.drawHeight = drawH
        return img

    except Exception:
        return None


def _build_company_details_section(company_info):
    """Build company details section with proper formatting"""
    company_details = []

    if not company_info:
        return company_details

    # helper accessor: prefer dict.get, fall back to getattr for model-like objects
    def _ci(key, default=None):
        try:
            return company_info.get(key, default)
        except Exception:
            return getattr(company_info, key, default)

    # Company Name
    name = _ci('name') or _ci('business_name')
    if name:
        
        company_details.append(Paragraph(f"<b>{_safe_str(name)}</b>", ParagraphStyle('CompanyName', parent=getSampleStyleSheet()['Normal'], fontSize=12, textColor=colors.HexColor('#1f2937'))))

    # Primary address: prefer a preformatted 'address' if provided, else assemble parts
    address_text = _safe_str(_ci('address'))
    if not address_text:
        po_box_parts = []
        if _ci('postal_code'):
            po_box_parts.append(f"P.O Box {_ci('postal_code')}")
        if _ci('zip_code'):
            po_box_parts.append(_ci('zip_code'))
        if _ci('city'):
            po_box_parts.append(_ci('city'))
        if po_box_parts:
            company_details.append(Paragraph(", ".join(po_box_parts), ParagraphStyle('Address', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#6b7280'))))

        address_parts = []
        if _ci('floor_number'):
            address_parts.append(_ci('floor_number'))
        if _ci('building_name'):
            address_parts.append(_ci('building_name'))
        if _ci('street_name'):
            address_parts.append(_ci('street_name'))
        if address_parts:
            company_details.append(Paragraph(", ".join([_safe_str(p) for p in address_parts]), ParagraphStyle('Address', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#6b7280'))))
    else:
        company_details.append(Paragraph(_safe_str(address_text), ParagraphStyle('Address', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#6b7280'))))

    # Contact: phone / contact_number and email
    phone = _ci('phone') or _ci('contact_number')
    email = _ci('email')
    # Show each contact detail on its own line
    if phone:
        company_details.append(Paragraph(f"Tel: {_safe_str(phone)}", ParagraphStyle('Contact', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#6b7280'))))
    if email:
        company_details.append(Paragraph(f"Email: {_safe_str(email)}", ParagraphStyle('Contact', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#6b7280'))))

    # PIN (KRA Number) - accept 'pin' or 'kra_number'
    pin = _ci('pin') or _ci('kra_number')
    if pin:
        company_details.append(Paragraph(f"PIN: {_safe_str(pin)}", ParagraphStyle('PIN', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#6b7280'))))

    return company_details
def get_brand_color(company_info, default="#2563eb"):
    """Return a reportlab Color for the company's brand color if available.

    Accepts either a hex string in company_info['brand_color'] or returns a default.
    """
    try:
        col = None
        try:
            col = company_info.get('brand_color') if isinstance(company_info, dict) else getattr(company_info, 'brand_color', None)
        except Exception:
            col = None
        if not col:
            col = company_info.get('primary_color') if isinstance(company_info, dict) else getattr(company_info, 'primary_color', None)
        if not col:
            col = default
        # Ensure hex format
        if isinstance(col, str):
            # allow values like '#rrggbb' or 'rrggbb'
            c = col.strip()
            if not c.startswith('#'):
                c = '#' + c
            return colors.HexColor(c)
    except Exception:
        pass
    return colors.HexColor(default)



def resolve_company_info(business=None, branch=None):
    """Build a company_info dict used by PDF generator from Business and optional Branch.

    Returns a dict with keys: name, address, email, phone, logo_path, pin, primary_color, secondary_color, text_color.
    """
    info = {
        'name': '',
        'address': '',
        'email': '',
        'phone': '',
        'logo_path': None,
        'pin': '',
        'primary_color': None,
        'secondary_color': None,
        'text_color': None,
    }

    try:
        if branch is None and business and getattr(business, 'branches', None):
            try:
                branch = business.branches.filter(is_main_branch=True, is_active=True).first()
            except Exception:
                branch = None

        # Name
        if business:
            info['name'] = getattr(business, 'name', '')

        # Logo path
        try:
            if business and getattr(business, 'logo', None) and hasattr(business.logo, 'path'):
                info['logo_path'] = business.logo.path
        except Exception:
            info['logo_path'] = None

        # Contact & email: branch preferred
        if branch:
            info['email'] = getattr(branch, 'email', '') or getattr(business, 'email', '') if business else ''
            info['phone'] = getattr(branch, 'contact_number', '') or getattr(business, 'contact_number', '') if business else ''
            loc = getattr(branch, 'location', None)
            if loc:
                info['address'] = format_location_address(loc)

        # Fallback to business-level location
        if not info['address'] and business:
            loc = getattr(business, 'location', None)
            if loc:
                info['address'] = format_location_address(loc)

        # PIN/KRA
        if business:
            info['pin'] = getattr(business, 'kra_number', '') or ''

        # Branding colors
        if business:
            bs = business.get_branding_settings() if hasattr(business, 'get_branding_settings') else None
            if isinstance(bs, dict):
                info['primary_color'] = bs.get('primary_color') or getattr(business, 'business_primary_color', None)
                info['secondary_color'] = bs.get('secondary_color') or getattr(business, 'business_secondary_color', None)
                info['text_color'] = bs.get('text_color') or getattr(business, 'business_text_color', None)
            else:
                info['primary_color'] = getattr(business, 'business_primary_color', None)
                info['secondary_color'] = getattr(business, 'business_secondary_color', None)
                info['text_color'] = getattr(business, 'business_text_color', None)

    except Exception:
        pass

    return info


def _build_client_details_section(client_info, document_type):
    """Build client/supplier details section"""
    client_details = []

    if client_info:
        # Client/Supplier header
        header_text = "CLIENT" if document_type in ['invoice', 'quotation', 'delivery_note'] else "SUPPLIER/VENDOR"
        client_details.append(Paragraph(f"<b>{header_text}</b>", ParagraphStyle('ClientHeader', parent=getSampleStyleSheet()['Normal'], fontSize=10, textColor=colors.HexColor('#1f2937'))))

        # Name
        if client_info.get('name'):
            client_details.append(Paragraph(client_info['name'], ParagraphStyle('ClientName', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))))

        # Address
        address_parts = []
        if client_info.get('floor_number'):
            address_parts.append(client_info['floor_number'])
        if client_info.get('building_name'):
            address_parts.append(client_info['building_name'])
        if client_info.get('street_name'):
            address_parts.append(client_info['street_name'])
        if client_info.get('city'):
            address_parts.append(client_info['city'])
        if address_parts:
            client_details.append(Paragraph(", ".join(address_parts), ParagraphStyle('ClientAddress', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#6b7280'))))

        # Contact Info - each on its own line
        if client_info.get('email'):
            client_details.append(Paragraph(f"Email: {_safe_str(client_info['email'])}", ParagraphStyle('ClientContact', parent=getSampleStyleSheet()['Normal'], fontSize=8, textColor=colors.HexColor('#6b7280'))))
        if client_info.get('phone'):
            client_details.append(Paragraph(f"Tel: {_safe_str(client_info['phone'])}", ParagraphStyle('ClientContact', parent=getSampleStyleSheet()['Normal'], fontSize=8, textColor=colors.HexColor('#6b7280'))))

    return client_details


def _build_document_details_section(document_info, document_type):
    """Build document details section (right side)"""
    doc_details = []

    if document_info:
        # Document Number
        if document_info.get('number'):
            label = "Invoice #:" if document_type == 'invoice' else "Quotation #:" if document_type == 'quotation' else "LPO #:" if document_type == 'lpo' else "#:"
            doc_details.append(Paragraph(f"<b>{label}</b> {document_info['number']}", ParagraphStyle('DocDetail', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))))

        # RFQ for quotations
        if document_type == 'quotation' and document_info.get('rfq_number'):
            doc_details.append(Paragraph(f"<b>RFQ:</b> {document_info['rfq_number']}", ParagraphStyle('DocDetail', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))))

        # Tender/Quotation Ref for quotations
        if document_type == 'quotation' and document_info.get('tender_quotation_ref'):
            doc_details.append(Paragraph(f"<b>Tender/Quotation Ref:</b> {document_info['tender_quotation_ref']}", ParagraphStyle('DocDetail', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))))

        # Date
        if document_info.get('date'):
            date_label = "Invoice Date:" if document_type == 'invoice' else "Quotation Date:" if document_type == 'quotation' else "Order Date:" if document_type == 'lpo' else "Date:"
            doc_details.append(Paragraph(f"<b>{date_label}</b> {document_info['date']}", ParagraphStyle('DocDetail', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))))

        # Due Date for invoices
        if document_type == 'invoice' and document_info.get('due_date'):
            doc_details.append(Paragraph(f"<b>Due Date:</b> {document_info['due_date']}", ParagraphStyle('DocDetail', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))))

        # Valid Until for quotations
        if document_type == 'quotation' and document_info.get('valid_until'):
            doc_details.append(Paragraph(f"<b>Valid Until:</b> {document_info['valid_until']}", ParagraphStyle('DocDetail', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))))

        # Expected Delivery for LPO
        if document_type == 'lpo' and document_info.get('expected_delivery'):
            doc_details.append(Paragraph(f"<b>Expected Delivery:</b> {document_info['expected_delivery']}", ParagraphStyle('DocDetail', parent=getSampleStyleSheet()['Normal'], fontSize=9, textColor=colors.HexColor('#374151'))))

    return doc_details


class BoxedSection(Flowable):
    """Flowable that draws a rounded rectangle background and places child flowables inside.

    Usage: BoxedSection([Paragraph(...), Spacer(...), Table(...)], width=4*inch)
    """
    def __init__(self, content, width: Optional[float] = None, padding=6, stroke=colors.HexColor('#e5e7eb'), fill=None, radius=6):
        super().__init__()
        self.content = content or []
        self.padding = padding
        # Store optional width separately to avoid overriding Flowable.width typing
        self._width = float(width) if width is not None else None
        self.stroke = stroke
        self.fill = fill
        self.radius = radius
        self._content_sizes = []
        self._inner_width = 0.0
        self._inner_height = 0.0

    # Match base Flowable.wrap parameter names for compatibility with type checkers
    def wrap(self, aW, aH):
        # Ensure we operate with numeric widths/heights
        try:
            outer_width = float(self._width) if self._width is not None else float(aW)
        except Exception:
            outer_width = float(aW or 0)
        inner_width = max(0.0, outer_width - 2 * float(self.padding))

        total_h = 0.0
        max_w = 0.0
        self._content_sizes = []

        for f in self.content:
            try:
                wrapped = f.wrap(inner_width, aH)
                if not wrapped or len(wrapped) != 2:
                    fw, fh = 0.0, 0.0
                else:
                    fw, fh = wrapped
                    fw = float(fw) if fw is not None else 0.0
                    fh = float(fh) if fh is not None else 0.0
            except Exception:
                fw, fh = 0.0, 0.0

            self._content_sizes.append((fw, fh))
            total_h += fh
            max_w = max(max_w, fw)

        # Save computed inner sizes
        self._inner_width = max_w
        self._inner_height = total_h

        height = total_h + 2 * float(self.padding)
        width = float(self._width) if self._width is not None else (max_w + 2 * float(self.padding))

        # Ensure returned values are floats
        try:
            return float(width), float(height)
        except Exception:
            return 0.0, 0.0

    def draw(self):
        c = self.canv
        # Determine actual width/height to use for drawing
        try:
            w = float(self.width) if getattr(self, 'width', None) else (self._inner_width + 2 * float(self.padding))
        except Exception:
            w = (self._inner_width + 2 * float(self.padding))
        try:
            h = float(self._inner_height + 2 * float(self.padding))
        except Exception:
            h = 0.0

        # Guard against degenerate sizes
        if w <= 0 or h <= 0:
            return

        # Draw rounded rectangle
        c.saveState()
        if self.fill:
            try:
                c.setFillColor(self.fill)
                c.roundRect(0, 0, w, h, self.radius, stroke=0, fill=1)
            except Exception:
                pass
        try:
            c.setLineWidth(1)
            c.setStrokeColor(self.stroke)
            c.roundRect(0, 0, w, h, self.radius, stroke=1, fill=0)
        except Exception:
            pass

        # Draw children
        y = h - self.padding
        for (f, (fw, fh)) in zip(self.content, self._content_sizes):
            y -= fh
            try:
                if fh > 0:
                    f.drawOn(c, self.padding, y)
            except Exception:
                # If a child fails to draw, continue with remaining children
                continue
        c.restoreState()

