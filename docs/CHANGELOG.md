# 변경 이력 (CHANGELOG)

---

## v3.1 — 2026-03-19

### 추가

#### 3단계 캐싱 시스템 (`src/utils/cache_manager.py`)

파이프라인 각 단계의 결과를 JSON으로 저장하여 재실행 시 API 비용을 절약합니다.

```
output/cache/{rfp파일명}/
├── rfp_text_cache.json      ← Phase 1: PDF 파싱 결과
├── rfp_analysis_cache.json  ← Phase 2: RFP LLM 분석 결과
└── content_cache.json       ← Phase 3: 8-Phase 콘텐츠 생성 결과
```

- RFP 파일 수정 시각(`mtime`) 기반 자동 캐시 무효화
- RFP 파일명별 독립 캐시 디렉토리 (다중 프로젝트 동시 관리 가능)
- Pydantic 모델 자동 직렬화/역직렬화 지원

#### 캐시 제어 CLI 플래그 (`main.py`)

| 플래그 | 설명 | API 비용 |
|--------|------|---------|
| `--pptx-only` | 캐시에서 콘텐츠 로드 → PPTX만 재생성 | **0원** |
| `--force-rfp` | PDF 재파싱 강제 | 없음 |
| `--force-analysis` | RFP 재분석 강제 | Phase 2만 발생 |
| `--force-content` | 콘텐츠 재생성 강제 | Phase 3만 발생 |
| `--cache-dir` | 캐시 디렉토리 경로 지정 | - |

**사용 패턴:**

```bash
# PPTX 레이아웃/디자인 수정 → LLM 비용 없음
python main.py generate input/rfp.pdf --pptx-only

# 콘텐츠만 재생성 (PDF·RFP분석 캐시 재사용)
python main.py generate input/rfp.pdf --force-content

# RFP 교체 후 전체 재실행
python main.py generate input/rfp.pdf --force-rfp --force-analysis --force-content
```

### 개선

#### Phase별 RFP 컨텍스트 슬라이싱 (`src/agents/content_generator.py`)

기존에는 모든 Phase(0~7)에 `RFPAnalysis` 전체(~10,000자)를 전달했으나,
각 Phase에 실제로 필요한 필드만 선별하여 전달하도록 개선.

| Phase | 전달 필드 수 | 변경 전 | 변경 후 | 절감 |
|-------|------------|--------|--------|------|
| 0 HOOK | 6개 | ~10,000자 | ~2,000자 | ~80% |
| 2 INSIGHT | 6개 | ~10,000자 | ~2,500자 | ~75% |
| 4 ACTION | 7개 | ~10,000자 | ~8,000자 | ~20% |
| 5 MANAGEMENT | 4개 | ~10,000자 | ~1,500자 | ~85% |
| 7 INVESTMENT | 5개 | ~10,000자 | ~1,500자 | ~85% |

**Phase별 선별 필드 정책:**
- **Phase 0 (HOOK)**: `project_overview`, `pain_points`, `winning_strategy`, `win_theme_candidates`
- **Phase 2 (INSIGHT)**: `pain_points`, `hidden_needs`, `potential_risks`, `competitive_landscape`
- **Phase 3 (CONCEPT)**: `winning_strategy`, `differentiation_points`, `evaluation_strategy`
- **Phase 4 (ACTION)**: `key_requirements`, `technical_requirements`, `deliverables`, `timeline` (최대 20개 항목)
- **Phase 5 (MANAGEMENT)**: `deliverables`, `timeline`, `potential_risks`
- **Phase 6 (WHY US)**: `evaluation_criteria`, `competitive_landscape`, `win_theme_candidates`
- **Phase 7 (INVESTMENT)**: `budget`, `timeline`, `deliverables`

#### `--pptx-only` 시 API 키 불필요 (`main.py`)

`--pptx-only` 플래그 사용 시 LLM을 호출하지 않으므로 `ANTHROPIC_API_KEY` 없이도 실행 가능.

### 수정

#### `.gitignore` 보완

| 추가 항목 | 이유 |
|----------|------|
| `company_data/` | 회사 프로필 JSON (민감 정보 포함 가능) |
| `.env.*` | `.env.local`, `.env.production` 등 변형 차단 |
| `venv/`, `.venv/` | 파이썬 가상환경 |
| `log/`, `*.log` | 로그 파일 |
| `*.egg-info/`, `dist/`, `build/` | Python 빌드 산출물 |

#### git remote URL 변경

저장소명 변경에 따라 remote URL 업데이트:
- 변경 전: `https://github.com/sdkimzero-kkk/proposal-agent-github-main`
- 변경 후: `https://github.com/sdkimzero-kkk/proposal-agent`

---

## v3.0 — 초기 릴리스

- Impact-8 Framework 기반 8-Phase 제안서 자동 생성
- Claude API (Anthropic) 단일 프로바이더
- PDF/DOCX RFP 파싱
- PPTX 자동 생성 (`slide_kit.py` 렌더링 엔진)
- Win Theme 전달 체인, C-E-I 설득 구조
- 레퍼런스 PPTX 디자인 분석 및 테마 적용
- 6가지 제안서 유형 지원 (marketing_pr, event, it_system, public, consulting, general)
