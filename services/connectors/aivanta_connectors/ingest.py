"""Upload pipeline: malware scan -> PII redaction -> text extraction.

RFPs and retrieved content are untrusted. Nothing in them can change tool
permissions or approval policy; the runtime only ever passes their text to
agents as data.
"""
from __future__ import annotations

import io
import os
import re
import socket
from dataclasses import dataclass

MAX_BYTES = int(os.getenv("UPLOAD_MAX_BYTES", str(25 * 1024 * 1024)))
ALLOWED_EXT = {".pdf", ".docx", ".xlsx", ".txt", ".md"}
BLOCKED_MAGIC = [b"MZ", b"\x7fELF", b"#!/", b"\xca\xfe\xba\xbe"]
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

PII_PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone", re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9,11}\d(?!\d)")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("aadhaar", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
]


class UploadRejected(Exception):
    pass


@dataclass
class ScanResult:
    clean: bool
    engine: str
    detail: str = ""


def malware_scan(data: bytes, filename: str) -> ScanResult:
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_EXT:
        raise UploadRejected(f"File type '{ext}' is not allowed. Upload PDF, DOCX, XLSX or TXT.")
    if len(data) > MAX_BYTES:
        raise UploadRejected(f"File exceeds {MAX_BYTES // (1024 * 1024)} MB.")
    if any(data.startswith(m) for m in BLOCKED_MAGIC) or EICAR in data:
        raise UploadRejected("File failed the malware scan.")
    host = os.getenv("CLAMAV_HOST")
    if host:  # clamd INSTREAM protocol
        port = int(os.getenv("CLAMAV_PORT", "3310"))
        with socket.create_connection((host, port), timeout=30) as s:
            s.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), 8192):
                chunk = data[i:i + 8192]
                s.sendall(len(chunk).to_bytes(4, "big") + chunk)
            s.sendall((0).to_bytes(4, "big"))
            reply = s.recv(4096).decode(errors="ignore")
        if "FOUND" in reply:
            raise UploadRejected("File failed the malware scan.")
        return ScanResult(True, "clamav", reply.strip())
    return ScanResult(True, "builtin-signatures")


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for name, pat in PII_PATTERNS:
        text, n = pat.subn(f"[REDACTED:{name}]", text)
        if n:
            counts[name] = counts.get(name, 0) + n
    return text, counts


def extract_text(data: bytes, filename: str) -> tuple[str, int]:
    """Returns (text, pages). Scanned PDFs without a text layer return little text; route them to OCR."""
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages), len(reader.pages)
    if ext == ".docx":
        from docx import Document
        d = Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts), max(1, len(parts) // 40)
    if ext == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        lines = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                vals = [str(v) for v in row if v is not None]
                if vals:
                    lines.append(" | ".join(vals))
        return "\n".join(lines), len(wb.worksheets)
    return data.decode("utf-8", errors="ignore"), 1


@dataclass
class IngestResult:
    text: str
    pages: int
    pii_counts: dict[str, int]
    scan: ScanResult


def ingest(data: bytes, filename: str) -> IngestResult:
    scan = malware_scan(data, filename)
    raw, pages = extract_text(data, filename)
    clean, counts = redact_pii(raw)
    return IngestResult(text=clean, pages=pages, pii_counts=counts, scan=scan)
