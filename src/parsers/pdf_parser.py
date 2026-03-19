"""PDF 문서 파서

deliverable-agent의 pdf_extractor.py 방식을 이식:
- 한글 NFC 정규화 (HWP→PDF 깨진 한글 복원)
- 표를 GFM Markdown으로 변환하여 LLM 가독성 향상
- ### [Page N] 마커로 페이지 위치 추적
- 텍스트+표를 페이지 단위로 통합한 단일 문자열 출력
- PDF 1회만 개방 (pdfplumber로 텍스트+표 동시 처리)
"""

import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

import pypdf
import pdfplumber

from .base_parser import BaseParser
from ..utils.logger import get_logger

logger = get_logger("pdf_parser")


def _normalize_korean(text: str) -> str:
    """HWP→PDF 변환으로 분리된 한글 자모를 NFC로 결합."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", text)


def _table_to_markdown(table: List[List[Optional[str]]]) -> str:
    """pdfplumber 2D 배열을 GitHub Flavored Markdown 표로 변환."""
    if not table or not table[0]:
        return ""

    # 셀 정규화: None → "", 셀 내 줄바꿈 → 공백
    cleaned = []
    for row in table:
        cleaned_row = []
        for cell in (row or []):
            text = str(cell).replace("\n", " ").strip() if cell is not None else ""
            cleaned_row.append(_normalize_korean(text))
        cleaned.append(cleaned_row)

    header = cleaned[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in cleaned[1:]:
        # 헤더 길이에 맞게 패딩/절단
        while len(row) < len(header):
            row.append("")
        row = row[: len(header)]
        lines.append("| " + " | ".join(row) + " |")

    return "\n" + "\n".join(lines) + "\n"


class PDFParser(BaseParser):
    """PDF 문서 파서 (deliverable-agent 방식 이식)"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    def parse(self, file_path: Path) -> Dict[str, Any]:
        """
        PDF를 파싱하여 구조화된 데이터 반환.

        raw_text: 페이지 마커 + 표(Markdown) + 텍스트 통합 문자열
                  (LLM에 직접 전달 가능)
        tables:   구조화된 표 데이터 (하위 호환용)
        """
        logger.info(f"PDF 파싱 시작: {file_path}")

        raw_text, tables = self._extract_combined(file_path)
        page_count = len(tables) and self._get_page_count(file_path)

        # page_count 별도 계산 (tables가 비어도 정확히)
        page_count = self._get_page_count(file_path)
        metadata = self._extract_metadata(file_path)
        sections = self._extract_sections(raw_text)

        logger.info(
            f"PDF 파싱 완료: {len(raw_text):,}자, "
            f"{len(tables)}개 테이블, {page_count}페이지"
        )

        return {
            "raw_text": raw_text,
            "tables": tables,
            "page_count": page_count,
            "metadata": metadata,
            "sections": sections,
        }

    def _extract_combined(
        self, file_path: Path
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        pdfplumber 단일 패스로 텍스트+표를 페이지 단위 통합 추출.

        반환:
            combined_text: ### [Page N] 마커 + 표 Markdown + 텍스트
            tables:        구조화된 표 목록 (하위 호환)
        """
        page_blocks: List[str] = []
        tables_structured: List[Dict[str, Any]] = []

        try:
            with pdfplumber.open(file_path) as pdf:
                total = len(pdf.pages)
                logger.info(f"전체 페이지: {total}")

                for i, page in enumerate(pdf.pages):
                    raw_text = page.extract_text() or ""
                    normalized = _normalize_korean(raw_text)
                    page_tables = page.extract_tables() or []

                    # 텍스트도 표도 없으면 건너뜀
                    if not normalized.strip() and not page_tables:
                        continue

                    block = f"### [Page {i + 1}]\n"

                    # 표 → Markdown 삽입 + 구조화 저장
                    for j, table in enumerate(page_tables):
                        if table and len(table) > 1:
                            block += f"\n**Table {j + 1}:**\n"
                            block += _table_to_markdown(table)

                            # 구조화 테이블 (하위 호환)
                            headers = [
                                _normalize_korean(str(c).strip()) if c else ""
                                for c in table[0]
                            ]
                            rows = [
                                [
                                    _normalize_korean(str(c).strip()) if c else ""
                                    for c in row
                                ]
                                for row in table[1:]
                            ]
                            tables_structured.append(
                                {
                                    "page": i + 1,
                                    "table_index": j,
                                    "headers": headers,
                                    "rows": rows,
                                    "raw_data": table,
                                }
                            )

                    # 페이지 텍스트 추가
                    if normalized.strip():
                        if page_tables:
                            block += f"\n**Page Text:**\n{normalized}\n"
                        else:
                            block += f"\n{normalized}\n"

                    page_blocks.append(block)

        except Exception as e:
            logger.error(f"PDF 추출 실패: {e}")

        combined = "\n---\n".join(page_blocks)
        return combined, tables_structured

    def _get_page_count(self, file_path: Path) -> int:
        try:
            return len(pypdf.PdfReader(file_path).pages)
        except Exception:
            return 0

    def _extract_metadata(self, file_path: Path) -> Dict[str, Any]:
        try:
            meta = pypdf.PdfReader(file_path).metadata
            if meta:
                return {
                    "title": meta.get("/Title", ""),
                    "author": meta.get("/Author", ""),
                    "subject": meta.get("/Subject", ""),
                    "creator": meta.get("/Creator", ""),
                    "creation_date": str(meta.get("/CreationDate", "")),
                }
        except Exception as e:
            logger.warning(f"메타데이터 추출 실패: {e}")
        return {}

    def _extract_sections(self, text: str) -> List[Dict[str, Any]]:
        """텍스트에서 섹션 구조 추출 (휴리스틱)."""
        if not text:
            return []

        sections = []
        section_patterns = [
            "제1장", "제2장", "제3장", "제4장", "제5장",
            "1.", "2.", "3.", "4.", "5.",
            "I.", "II.", "III.", "IV.", "V.",
            "가.", "나.", "다.", "라.",
            "1)", "2)", "3)",
        ]

        current = {"title": "시작", "content": [], "level": 0}
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            is_header = any(
                line.startswith(p) and len(line) < 100
                for p in section_patterns
            )
            if is_header:
                if current["content"]:
                    sections.append(current)
                current = {"title": line, "content": [], "level": 1}
            else:
                current["content"].append(line)

        if current["content"]:
            sections.append(current)

        return sections

    # ── 하위 호환 메서드 (외부에서 직접 호출하는 경우 대비) ──────────

    def extract_text(self, file_path: Path) -> str:
        """raw_text만 필요한 경우 사용."""
        raw_text, _ = self._extract_combined(file_path)
        return raw_text

    def extract_tables(self, file_path: Path) -> List[Dict[str, Any]]:
        """tables만 필요한 경우 사용."""
        _, tables = self._extract_combined(file_path)
        return tables
