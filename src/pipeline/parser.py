from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

try:
    import fitz  # pymupdf
except Exception:
    fitz = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@dataclass
class ParsedContract:
    contract_id: str
    source_name: str
    text: str
    raw_text_path: Path


def _safe_contract_id(filename: str, timestamp: str) -> str:
    stem = Path(filename).stem if filename else "contract"
    clean = "".join(char if char.isalnum() else "_" for char in stem)
    clean = clean.strip("_") or "contract"
    return f"{clean}_{timestamp}"


class DocumentParser:
    def __init__(self, raw_upload_dir: Path | str = Path("data/raw/uploads")) -> None:
        self.raw_upload_dir = Path(raw_upload_dir)

    def parse_upload(self, filename: str, file_bytes: bytes, contract_id: str | None = None) -> ParsedContract:
        if not file_bytes:
            raise ValueError("Uploaded file is empty.")

        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise ValueError("File exceeds 10MB maximum size limit.")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        resolved_contract_id = contract_id or _safe_contract_id(filename=filename, timestamp=timestamp)

        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            text = self._extract_pdf_text(file_bytes)
        else:
            text = file_bytes.decode("utf-8", errors="ignore")

        if not text.strip():
            raise ValueError("Could not extract text from uploaded file.")

        self.raw_upload_dir.mkdir(parents=True, exist_ok=True)
        raw_text_path = self.raw_upload_dir / f"{resolved_contract_id}.txt"
        raw_text_path.write_text(text, encoding="utf-8")

        return ParsedContract(
            contract_id=resolved_contract_id,
            source_name=filename,
            text=text,
            raw_text_path=raw_text_path,
        )

    @staticmethod
    def _extract_pdf_text(file_bytes: bytes) -> str:
        if fitz is not None:
            try:
                document = fitz.open(stream=file_bytes, filetype="pdf")
                pages = [page.get_text("text") for page in document]
                document.close()
                return "\n".join(pages)
            except Exception:
                pass

        if PdfReader is not None:
            try:
                reader = PdfReader(BytesIO(file_bytes))
                pages = [page.extract_text() or "" for page in reader.pages]
                return "\n".join(pages)
            except Exception:
                pass

        raise ValueError("PDF parsing failed. Install pymupdf (preferred) or ensure pypdf is available.")
