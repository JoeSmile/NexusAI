"""Chat session attachments (Task 76)."""

from packages.attachments.errors import ParseError
from packages.attachments.parse import AttachmentBlock, ParseResult, parse_document
from packages.attachments.validate import ATTACHMENT_MAX_BYTES, validate_attachment_bytes

__all__ = [
    "ATTACHMENT_MAX_BYTES",
    "AttachmentBlock",
    "ParseError",
    "ParseResult",
    "parse_document",
    "validate_attachment_bytes",
]
