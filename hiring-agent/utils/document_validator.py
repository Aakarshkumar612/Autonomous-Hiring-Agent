"""
utils/document_validator.py
═══════════════════════════════════════════════════════
Document Type Validator for the Autonomous Hiring Agent.

PROBLEM BEING SOLVED
─────────────────────
Users can upload any file to the portal. Without validation:
  - Someone uploads a selfie → OCR produces garbage → scorer gets nonsense
  - Someone uploads a receipt → scorer tries to evaluate it as a resume
  - Someone uploads a meme → wastes Groq quota + pollutes data

WHAT THIS MODULE DOES
──────────────────────
Before any document is processed it passes through TWO gates:

  Gate 1 — Format Gate (instant, zero cost)
    Checks MIME type / file extension is in the allowed set.
    Rejects: .exe, .zip, random binaries, etc.

  Gate 2 — Content Gate (fast LLM call, ~50–200ms)
    Sends the first 800 characters of extracted text to
    llama-3.1-8b-instant and asks: "Is this a hiring document?"
    For images it sends the image to llama-4-scout (vision model)
    which does OCR + classification in a SINGLE API call.
    Rejects: selfies, food photos, homework, invoices, etc.

VALID DOCUMENT TYPES
─────────────────────
  resume / cv           — work experience, skills, education
  cover_letter          — letter applying for a role
  offer_letter          — job offer from a company
  internship_certificate — internship completion certificate
  experience_letter     — letter from a previous employer

FAILURE BEHAVIOUR
──────────────────
If the validation API call itself fails (Groq down, timeout),
the validator fails OPEN — it returns is_valid=True with
confidence=0.0 and a WARNING log. Why:
  - The other gates (MIME, file size) provide basic security
  - Blocking all uploads because Groq is temporarily unavailable
    would halt the entire hiring pipeline, which is worse
    than processing one bad document
"""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass
from typing import Optional

from groq import AsyncGroq

from utils.logger import logger

# ─── Models ─────────────────────────────────────────────────────────────────

# Fast, low-latency text classifier — ideal for validation (not scoring)
_TEXT_VALIDATOR_MODEL  = os.getenv("GROQ_DETECTOR", "llama-3.1-8b-instant")

# Vision-capable model — used for image OCR + classification in one call
# llama-4-scout is lighter and faster than llama-4-maverick for this task
_IMAGE_VALIDATOR_MODEL = os.getenv("GROQ_VISION", "meta-llama/llama-4-scout-17b-16e-instruct")

# How many characters of document text to send for validation.
# 800 chars ≈ ~200 tokens — enough for the model to identify document type
# without wasting quota on the full 3-page resume.
_TEXT_EXCERPT_LENGTH = 800

# Maximum image size (in bytes) before we resize.
# 1 MB is plenty for Groq vision to read document text.
_MAX_IMAGE_BYTES = 1_048_576   # 1 MB

# Minimum extracted text length to be considered a real document.
# Fewer than this many characters after OCR → probably blank/unreadable.
_MIN_TEXT_LENGTH = 40

# ─── System prompts ──────────────────────────────────────────────────────────

_TEXT_VALIDATOR_SYSTEM = """\
You are a strict hiring document classifier.
Your ONLY job: determine if a given text excerpt is from a legitimate \
job application document.

ACCEPT exactly these five document types (nothing else):
  1. resume / cv       — has name, work experience, skills, education
  2. cover_letter      — letter written to apply for a job or internship
  3. offer_letter      — formal job offer issued by a company to a candidate
  4. internship_certificate — certifies completion of an internship
  5. experience_letter — letter from an employer confirming employment

REJECT all other content, including but not limited to:
  - Random photos or image files converted to text (garbled OCR)
  - School homework, essays, or assignments
  - Medical, legal, or financial documents
  - Business documents: invoices, receipts, purchase orders
  - Social media screenshots or app screenshots
  - News articles, blog posts, Wikipedia pages
  - Any document not directly related to job applications/hiring

Output ONLY valid JSON. No markdown, no explanation outside the JSON.\
"""

_TEXT_VALIDATOR_USER = """\
Document text excerpt (first {n} characters):

{excerpt}

---

Classify this document. Respond with ONLY this JSON (no extra text):
{{
  "is_valid": true or false,
  "document_type": "resume" | "cover_letter" | "offer_letter" | "internship_certificate" | "experience_letter" | "invalid",
  "confidence": 0.0 to 1.0,
  "rejection_reason": null if is_valid is true, otherwise a short user-friendly sentence explaining why the document was rejected
}}\
"""

_IMAGE_VALIDATOR_SYSTEM = """\
You are a hiring document OCR + classifier.
You receive a photo or scan of a document.

Step 1 — Extract all readable text from the image exactly as it appears.
Step 2 — Determine if the document is a legitimate hiring document.

ACCEPT: resume/CV, cover letter, offer letter, internship certificate, experience letter
REJECT: photos of people/food/places, memes, school homework, invoices, screenshots,
        blank images, images where no meaningful text is present.

Output ONLY valid JSON. No markdown, no explanation outside the JSON.\
"""

_IMAGE_VALIDATOR_USER = """\
Analyse this document image. Do both OCR extraction and classification.

Return ONLY this JSON (no other text):
{
  "raw_text": "all text you can read from the image, preserving structure",
  "is_valid": true or false,
  "document_type": "resume" | "cover_letter" | "offer_letter" | "internship_certificate" | "experience_letter" | "invalid",
  "confidence": 0.0 to 1.0,
  "rejection_reason": null if is_valid is true, otherwise a short user-friendly sentence
}\
"""


# ─── Result type ─────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """
    Result of document validation.

    Attributes:
        is_valid          — True if the document passed both gates
        document_type     — classified type ("resume", "cover_letter", etc.)
        confidence        — model confidence 0.0–1.0 (0.0 = service failure/unknown)
        rejection_reason  — user-friendly rejection message (set when is_valid=False)
        extracted_text    — OCR text extracted from image (None for non-image inputs)
        validation_skipped — True when the API call failed and we failed-open
    """
    is_valid:           bool
    document_type:      str              = "unknown"
    confidence:         float            = 0.0
    rejection_reason:   Optional[str]   = None
    extracted_text:     Optional[str]   = None
    validation_skipped: bool            = False


# ─── Validator ───────────────────────────────────────────────────────────────

class DocumentValidator:
    """
    Fast document type validator.

    Two entry points:
      validate_text(text)              — for PDF/DOCX (text already extracted)
      validate_image(image_bytes, mime) — for JPEG/PNG/WEBP (OCR + classify)

    Both are async because they call the Groq API.
    Stateless — one shared instance is safe.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.client = AsyncGroq(api_key=api_key or os.environ["GROQ_API_KEY"])

    # ─── Text validation (PDF / DOCX) ────────────────────────────────────────

    async def validate_text(self, text: str) -> ValidationResult:
        """
        Validate a text-based document (already extracted from PDF/DOCX).

        Strategy: send only the first _TEXT_EXCERPT_LENGTH characters.
        The document type is almost always determinable from the opening
        section — name/header area for a resume, salutation for a cover
        letter, company letterhead for an offer letter.

        Time: ~50–80 ms on llama-3.1-8b-instant.
        """
        # Pre-flight: minimum text length check (no API call needed)
        stripped = text.strip()
        if len(stripped) < _MIN_TEXT_LENGTH:
            return ValidationResult(
                is_valid=False,
                document_type="invalid",
                confidence=1.0,
                rejection_reason=(
                    "The document appears to be blank or contains too little text "
                    "to be a valid hiring document. Please upload a complete document."
                ),
            )

        excerpt = stripped[:_TEXT_EXCERPT_LENGTH]

        try:
            response = await self.client.chat.completions.create(
                model=_TEXT_VALIDATOR_MODEL,
                messages=[
                    {"role": "system", "content": _TEXT_VALIDATOR_SYSTEM},
                    {
                        "role": "user",
                        "content": _TEXT_VALIDATOR_USER.format(
                            n=len(excerpt),
                            excerpt=excerpt,
                        ),
                    },
                ],
                temperature=0.0,       # deterministic classification
                max_tokens=120,        # JSON response is tiny
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content.strip()
            return self._parse_text_response(raw)

        except Exception as exc:
            # Fail-open: don't block uploads when the validation service is down.
            logger.warning(
                f"DOC_VALIDATOR | Text validation API call failed (failing open): {exc}"
            )
            return ValidationResult(
                is_valid=True,
                document_type="unknown",
                confidence=0.0,
                validation_skipped=True,
            )

    def _parse_text_response(self, raw: str) -> ValidationResult:
        """Parse the JSON response from the text classifier."""
        try:
            data = json.loads(raw)
            is_valid  = bool(data.get("is_valid", False))
            doc_type  = str(data.get("document_type", "invalid"))
            conf      = float(data.get("confidence", 0.5))
            reason    = data.get("rejection_reason")
            return ValidationResult(
                is_valid=is_valid,
                document_type=doc_type,
                confidence=conf,
                rejection_reason=reason if not is_valid else None,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(f"DOC_VALIDATOR | Failed to parse text classifier response: {exc}")
            # If we can't parse the response, fail-open
            return ValidationResult(
                is_valid=True,
                document_type="unknown",
                confidence=0.0,
                validation_skipped=True,
            )

    # ─── Image validation (JPEG / PNG / WEBP) ───────────────────────────────

    async def validate_image(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> ValidationResult:
        """
        Validate an image document by:
          1. Resizing to ≤ 1 MB (if larger) for cost and speed
          2. Sending to llama-4-scout vision model
          3. Getting back extracted text + classification in ONE API call

        This is the key efficiency win for images — OCR and validation
        happen simultaneously, not sequentially.

        Time: ~300–600 ms on llama-4-scout (vision processing takes longer
        than text classification but still well under 1 second).
        """
        # Pre-flight: shrink large images before sending to Groq
        processed_bytes, final_mime = _resize_image_if_needed(image_bytes, mime_type)

        # Base64 encode for the Groq vision API (OpenAI-compatible format)
        b64 = base64.b64encode(processed_bytes).decode("utf-8")
        data_url = f"data:{final_mime};base64,{b64}"

        try:
            response = await self.client.chat.completions.create(
                model=_IMAGE_VALIDATOR_MODEL,
                messages=[
                    {"role": "system", "content": _IMAGE_VALIDATOR_SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                            {
                                "type": "text",
                                "text": _IMAGE_VALIDATOR_USER,
                            },
                        ],
                    },
                ],
                temperature=0.0,
                max_tokens=2000,       # more room for OCR text extraction
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content.strip()
            return self._parse_image_response(raw)

        except Exception as exc:
            logger.warning(
                f"DOC_VALIDATOR | Image validation API call failed (failing open): {exc}"
            )
            return ValidationResult(
                is_valid=True,
                document_type="unknown",
                confidence=0.0,
                validation_skipped=True,
            )

    def _parse_image_response(self, raw: str) -> ValidationResult:
        """Parse the JSON response from the vision classifier."""
        try:
            data          = json.loads(raw)
            extracted_text = str(data.get("raw_text", "")).strip()
            is_valid       = bool(data.get("is_valid", False))
            doc_type       = str(data.get("document_type", "invalid"))
            conf           = float(data.get("confidence", 0.5))
            reason         = data.get("rejection_reason")

            # Secondary check: even if model says valid, very short OCR
            # means the image probably has no real text (photo, blank page)
            if is_valid and len(extracted_text) < _MIN_TEXT_LENGTH:
                return ValidationResult(
                    is_valid=False,
                    document_type="invalid",
                    confidence=0.9,
                    rejection_reason=(
                        "The image does not appear to contain a readable document. "
                        "Please upload a clear scan or photo of your document."
                    ),
                    extracted_text=extracted_text,
                )

            return ValidationResult(
                is_valid=is_valid,
                document_type=doc_type,
                confidence=conf,
                rejection_reason=reason if not is_valid else None,
                extracted_text=extracted_text if extracted_text else None,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(f"DOC_VALIDATOR | Failed to parse image classifier response: {exc}")
            return ValidationResult(
                is_valid=True,
                document_type="unknown",
                confidence=0.0,
                validation_skipped=True,
            )


# ─── Image preprocessing helper ──────────────────────────────────────────────

def _resize_image_if_needed(
    image_bytes: bytes,
    mime_type: str,
) -> tuple[bytes, str]:
    """
    Resize image to ≤ _MAX_IMAGE_BYTES if it exceeds that size.

    Why this matters:
    - A modern phone photo is 3–10 MB. Sending that to Groq's vision API
      uses more tokens, costs more, and is slower — for zero benefit when
      all we need is to read text.
    - Downsizing to 1 MB preserves all text legibility in document scans.
    - We always output JPEG (not PNG) after resizing to maximize compression.

    Falls back to the original bytes if Pillow is not installed or fails.
    """
    if len(image_bytes) <= _MAX_IMAGE_BYTES:
        return image_bytes, mime_type

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))

        # Convert RGBA → RGB (JPEG doesn't support transparency)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Iteratively reduce quality until we hit the target size
        quality = 85
        while quality >= 40:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            result = buf.getvalue()
            if len(result) <= _MAX_IMAGE_BYTES:
                logger.info(
                    f"DOC_VALIDATOR | Image resized: "
                    f"{len(image_bytes)//1024} KB → {len(result)//1024} KB "
                    f"(quality={quality})"
                )
                return result, "image/jpeg"
            quality -= 15

        # Last resort: scale the image down
        max_dim = 1280
        w, h = img.size
        scale = min(max_dim / w, max_dim / h)
        if scale < 1.0:
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60, optimize=True)
        result = buf.getvalue()
        logger.info(
            f"DOC_VALIDATOR | Image scaled down: "
            f"{len(image_bytes)//1024} KB → {len(result)//1024} KB"
        )
        return result, "image/jpeg"

    except Exception as exc:
        logger.warning(
            f"DOC_VALIDATOR | Image resize failed (sending original): {exc}"
        )
        return image_bytes, mime_type


# ─── Global instance ─────────────────────────────────────────────────────────

document_validator = DocumentValidator()
