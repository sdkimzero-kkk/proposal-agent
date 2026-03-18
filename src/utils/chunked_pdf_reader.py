"""대형 PDF 청크 분할 리더

1000페이지 이상 RFP PDF를 일정 페이지 단위로 분할하여 읽고,
각 청크를 구조화된 텍스트로 반환합니다.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import pypdf
import pdfplumber

from .logger import get_logger

logger = get_logger("chunked_pdf_reader")


class ChunkedPDFReader:
    """대형 PDF를 페이지 단위 청크로 분할하여 읽는 유틸리티"""

    def __init__(self, pages_per_chunk: int = 30):
        """
        Args:
            pages_per_chunk: 청크당 페이지 수 (기본 30 → 청크당 약 15~20KB)
        """
        self.pages_per_chunk = pages_per_chunk

    # ──────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────

    def read_chunks(self, pdf_path: str | Path) -> List[Dict[str, Any]]:
        """PDF를 청크로 분할하여 반환

        Args:
            pdf_path: PDF 파일 경로

        Returns:
            청크 리스트. 각 항목:
            {
                "chunk_index": int,
                "page_start": int,   # 1-based
                "page_end": int,     # inclusive
                "text": str,
                "tables": List[dict],
            }
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 파일 없음: {pdf_path}")

        page_count = self._get_page_count(pdf_path)
        logger.info(f"PDF 청크 분할 시작: {pdf_path.name} ({page_count}페이지, "
                    f"청크당 {self.pages_per_chunk}페이지)")

        chunks = []
        chunk_idx = 0

        for start in range(0, page_count, self.pages_per_chunk):
            end = min(start + self.pages_per_chunk - 1, page_count - 1)
            text = self._extract_text_range(pdf_path, start, end)
            tables = self._extract_tables_range(pdf_path, start, end)

            chunks.append({
                "chunk_index": chunk_idx,
                "page_start": start + 1,      # 1-based
                "page_end": end + 1,           # 1-based inclusive
                "text": text,
                "tables": tables,
            })

            logger.debug(f"  청크 {chunk_idx}: 페이지 {start+1}~{end+1}, "
                         f"{len(text):,}자, 테이블 {len(tables)}개")
            chunk_idx += 1

        logger.info(f"청크 분할 완료: 총 {len(chunks)}개 청크")
        return chunks

    def read_full(self, pdf_path: str | Path) -> Dict[str, Any]:
        """전체 PDF를 읽어서 반환 (기존 PDFParser 호환 형식)

        작은 PDF(300페이지 이하)에 적합. 큰 파일은 read_chunks()를 사용하세요.

        Returns:
            {"raw_text": str, "tables": List, "page_count": int, "chunks": List}
        """
        chunks = self.read_chunks(pdf_path)
        all_text = "\n\n".join(c["text"] for c in chunks)
        all_tables = []
        for c in chunks:
            all_tables.extend(c["tables"])

        return {
            "raw_text": all_text,
            "tables": all_tables,
            "page_count": sum(
                c["page_end"] - c["page_start"] + 1 for c in chunks
            ),
            "chunks": chunks,
        }

    def extract_sections_from_chunks(
        self, chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """청크 리스트에서 섹션 구조 추출 (헤더 기반 휴리스틱)

        Returns:
            섹션 리스트. 각 항목:
            {
                "title": str,
                "content": str,
                "page_start": int,
                "chunk_index": int,
            }
        """
        section_patterns = [
            "제1장", "제2장", "제3장", "제4장", "제5장",
            "제6장", "제7장", "제8장", "제9장", "제10장",
            "I.", "II.", "III.", "IV.", "V.",
            "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.",
            "가.", "나.", "다.", "라.", "마.",
        ]

        sections: List[Dict[str, Any]] = []
        current = {
            "title": "서문",
            "content_lines": [],
            "page_start": 1,
            "chunk_index": 0,
        }

        for chunk in chunks:
            for line in chunk["text"].split("\n"):
                line = line.strip()
                if not line:
                    continue
                is_header = any(
                    line.startswith(p) and len(line) < 120
                    for p in section_patterns
                )
                if is_header:
                    if current["content_lines"]:
                        sections.append({
                            "title": current["title"],
                            "content": "\n".join(current["content_lines"]),
                            "page_start": current["page_start"],
                            "chunk_index": current["chunk_index"],
                        })
                    current = {
                        "title": line,
                        "content_lines": [],
                        "page_start": chunk["page_start"],
                        "chunk_index": chunk["chunk_index"],
                    }
                else:
                    current["content_lines"].append(line)

        if current["content_lines"]:
            sections.append({
                "title": current["title"],
                "content": "\n".join(current["content_lines"]),
                "page_start": current["page_start"],
                "chunk_index": current["chunk_index"],
            })

        return sections

    def merge_chunk_summaries(self, summaries: List[str], max_chars: int = 24000) -> str:
        """여러 청크 요약을 하나의 컨텍스트 문자열로 병합

        각 요약 사이에 구분자를 삽입하고, 전체 길이를 max_chars로 제한합니다.

        Args:
            summaries: 청크별 요약 문자열 리스트
            max_chars: 최대 문자 수

        Returns:
            병합된 문자열 (max_chars 이내)
        """
        parts = []
        total = 0
        for i, summary in enumerate(summaries):
            header = f"\n\n[섹션 {i+1}/{len(summaries)}]\n"
            block = header + summary.strip()
            if total + len(block) > max_chars:
                remaining = max_chars - total
                if remaining > 200:
                    parts.append(block[:remaining] + "\n... (잘림)")
                break
            parts.append(block)
            total += len(block)

        return "".join(parts)

    # ──────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────

    def _get_page_count(self, pdf_path: Path) -> int:
        try:
            reader = pypdf.PdfReader(pdf_path)
            return len(reader.pages)
        except Exception as e:
            logger.error(f"페이지 수 조회 실패: {e}")
            return 0

    def _extract_text_range(self, pdf_path: Path, start: int, end: int) -> str:
        """start~end 페이지(0-based) 텍스트 추출"""
        try:
            reader = pypdf.PdfReader(pdf_path)
            parts = []
            for i in range(start, min(end + 1, len(reader.pages))):
                page_text = reader.pages[i].extract_text()
                if page_text:
                    parts.append(f"--- 페이지 {i+1} ---\n{page_text}")
            return "\n\n".join(parts)
        except Exception as e:
            logger.error(f"텍스트 추출 실패 (페이지 {start+1}~{end+1}): {e}")
            return ""

    def _extract_tables_range(
        self, pdf_path: Path, start: int, end: int
    ) -> List[Dict[str, Any]]:
        """start~end 페이지(0-based) 테이블 추출"""
        tables = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for i in range(start, min(end + 1, len(pdf.pages))):
                    page = pdf.pages[i]
                    for j, table in enumerate(page.extract_tables() or []):
                        if table and len(table) > 1:
                            headers = [
                                str(c).strip() if c else "" for c in table[0]
                            ]
                            rows = [
                                [str(c).strip() if c else "" for c in row]
                                for row in table[1:]
                            ]
                            tables.append({
                                "page": i + 1,
                                "table_index": j,
                                "headers": headers,
                                "rows": rows,
                            })
        except Exception as e:
            logger.error(f"테이블 추출 실패 (페이지 {start+1}~{end+1}): {e}")
        return tables


# ──────────────────────────────────────────────────────────
# 모듈 레벨 편의 함수
# ──────────────────────────────────────────────────────────

def read_pdf_chunked(
    pdf_path: str | Path,
    pages_per_chunk: int = 30,
) -> List[Dict[str, Any]]:
    """PDF를 청크로 분할하여 반환하는 편의 함수

    Args:
        pdf_path: PDF 파일 경로
        pages_per_chunk: 청크당 페이지 수

    Returns:
        청크 리스트 (각 청크: {chunk_index, page_start, page_end, text, tables})
    """
    return ChunkedPDFReader(pages_per_chunk).read_chunks(pdf_path)


def read_large_rfp(pdf_path: str | Path) -> Dict[str, Any]:
    """대형 RFP PDF 전체 읽기 편의 함수 (청크 자동 처리)

    Returns:
        {"raw_text": str, "tables": List, "page_count": int, "chunks": List}
    """
    return ChunkedPDFReader(pages_per_chunk=30).read_full(pdf_path)
