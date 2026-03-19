"""파이프라인 캐시 관리자

deliverable-agent의 캐시 전략을 proposal-agent에 이식.
각 단계(PDF 파싱 / RFP 분석 / 콘텐츠 생성)마다 중간 결과를 JSON으로 저장하여
재실행 시 API 비용을 절약합니다.

캐시 구조:
    output/cache/{rfp_stem}/
        rfp_text_cache.json      # Phase 1: PDF 파싱 결과
        rfp_analysis_cache.json  # Phase 2: RFP 분석 결과 (RFPAnalysis)
        content_cache.json       # Phase 3: 콘텐츠 생성 결과 (ProposalContent)
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .logger import get_logger

logger = get_logger("cache_manager")


class CacheManager:
    """JSON 기반 파이프라인 캐시 관리자"""

    FILES = {
        "rfp_text": "rfp_text_cache.json",
        "rfp_analysis": "rfp_analysis_cache.json",
        "content": "content_cache.json",
    }

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        filename = self.FILES.get(key, f"{key}.json")
        return self.cache_dir / filename

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def is_valid(self, key: str, source_file: Optional[Path] = None) -> bool:
        """캐시 유효성 확인.

        source_file이 제공되면 RFP 파일의 mtime을 캐시와 비교.
        RFP 파일이 캐시보다 최신이면 무효 처리.
        """
        cache_path = self._path(key)
        if not cache_path.exists():
            return False
        if source_file and source_file.exists():
            if source_file.stat().st_mtime > cache_path.stat().st_mtime:
                logger.info(f"캐시 만료 ({key}): RFP 파일이 더 최신입니다")
                return False
        return True

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        """캐시에서 JSON 로드"""
        cache_path = self._path(key)
        if not cache_path.exists():
            return None
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            logger.info(f"캐시 히트: {cache_path.name}")
            return data
        except Exception as e:
            logger.warning(f"캐시 로드 실패 ({key}): {e}")
            return None

    def save(self, key: str, data: Any) -> Path:
        """데이터를 캐시에 JSON으로 저장 (Pydantic 모델 자동 직렬화)"""
        cache_path = self._path(key)
        try:
            if hasattr(data, "model_dump_json"):
                # Pydantic v2
                text = data.model_dump_json(indent=2, ensure_ascii=False)
            elif hasattr(data, "json"):
                # Pydantic v1
                text = data.json(indent=2, ensure_ascii=False)
            else:
                text = json.dumps(data, indent=2, ensure_ascii=False)
            cache_path.write_text(text, encoding="utf-8")
            logger.info(f"캐시 저장: {cache_path.name}")
            return cache_path
        except Exception as e:
            logger.warning(f"캐시 저장 실패 ({key}): {e}")
            raise

    def clear(self, key: Optional[str] = None) -> None:
        """캐시 삭제. key=None이면 전체 삭제."""
        if key:
            p = self._path(key)
            if p.exists():
                p.unlink()
                logger.info(f"캐시 삭제: {p.name}")
        else:
            deleted = 0
            for p in self.cache_dir.glob("*.json"):
                p.unlink()
                deleted += 1
            logger.info(f"전체 캐시 삭제: {deleted}개 파일")

    def info(self) -> Dict[str, Any]:
        """현재 캐시 상태 요약"""
        result = {}
        for key, filename in self.FILES.items():
            p = self.cache_dir / filename
            if p.exists():
                stat = p.stat()
                result[key] = {
                    "exists": True,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "path": str(p),
                }
            else:
                result[key] = {"exists": False}
        return result
