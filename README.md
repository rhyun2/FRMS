# FRMS — IoT 플랫폼 기능요구사항 관리 시스템

IoT 플랫폼의 기능 요구사항 한 건이 **접수부터 완료까지 어느 단계에 있고 지금 누가
처리해야 하는지를 한 화면에서 보여주는** 웹 애플리케이션.

사업담당 · 개발담당 · UI담당 · 검수담당 4개 역할이 하나의 요구사항 원장을 공유하고,
단계 전이는 역할별 권한과 필수 입력 규칙으로 강제된다. 검수 단계의 보완요청은
**어디로 되돌아가는지(요건 / UI / 구현)를 반드시 분류**하게 하여, 반복되는 재작업의
원인이 데이터로 드러나게 한다.

---

## 현재 상태

> **Phase 1 (MVP) 구현 완료.** 등록·전이·보완요청·칸반·내 할 일·역할 권한이 동작한다.

[Phase 1 종료 조건](./docs/roadmap.md#46-phase-1-종료-조건-exit-criteria)은 실사용
데이터로 판정하므로, 4개 역할이 2주간 실제 업무로 사용해 봐야 Phase 2에 착수할 수 있다.
운영 배포 전에는 [오픈 이슈](./docs/PRD.md#13-오픈-이슈) O1(호스팅 위치)과
O3(Entra ID 앱 등록)이 확정되어야 한다.

---

## 실행

> **Python 3.11 이상이 필요합니다.** macOS 시스템 기본 Python은 3.9이므로 그대로
> venv를 만들면 실행되지 않습니다 ([트러블슈팅](#트러블슈팅) 참조).

```bash
python3 --version           # 3.11 이상인지 먼저 확인
# 낮다면: brew install python@3.12   (또는 pyenv install 3.12)

python3.12 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m app.seed          # 데모 사용자 7명 + 요구사항 8건 생성
uvicorn app.main:app --reload
```

http://localhost:8000 접속 → 개발용 로그인 화면에서 역할별 데모 계정을 골라 로그인한다.

| 계정 | 역할 | 이 계정으로 볼 것 |
|---|---|---|
| 김사업 | 사업담당 | 요구사항 등록·제출, 내 요청 추적 |
| 박개발 | 개발담당 | 요건검토 승인, 개발완료, 구현 보완요청 접수 |
| 정유아이 | UI담당 | UI설계 완료 처리 |
| 한검수 | 검수담당 | 검수 통과 / 보완요청(회귀 대상 지정) |
| 운영자 | 관리자 | 사용자·역할 관리 |

**같은 요구사항을 서로 다른 계정으로 열어 보면** 화면에 뜨는 행동 버튼이 달라지는 것을
확인할 수 있다. 그것이 이 시스템의 핵심이다.

### 설정

`.env.example` 을 `.env` 로 복사해 수정한다. 기본값은 SQLite + 개발용 로컬 로그인이다.

- `DATABASE_URL` 을 `postgresql+psycopg://...` 로 바꾸면 PostgreSQL로 전환된다.
- `ENTRA_TENANT_ID` / `ENTRA_CLIENT_ID` / `ENTRA_CLIENT_SECRET` 을 채우면
  **Entra ID SSO 모드로 전환되고 개발용 로컬 로그인은 닫힌다.**

### 트러블슈팅

**`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`**
또는 `Unable to evaluate type annotation 'str | None'`

venv가 Python 3.10 이하로 만들어진 경우입니다. 이 코드는 `X | None` 유니온(3.10+)과
`StrEnum`(3.11+)을 쓰므로 3.11 이상이 필요합니다.

```bash
rm -rf .venv                       # 낮은 버전으로 만든 venv 폐기
python3.12 -m venv .venv
source .venv/bin/activate
python --version                   # 3.12.x 확인
pip install -r requirements-dev.txt
```

> Pydantic이 안내하는 **`eval_type_backport` 설치로는 해결되지 않습니다.** 그 오류만
> 넘어갈 뿐, 바로 다음 임포트인 `StrEnum`에서 `ImportError`가 납니다.

3.11 미만에서 실행하면 `app/__init__.py`의 버전 가드가 위 안내를 담은 메시지와 함께
즉시 중단시킵니다.

### 테스트

```bash
pytest
```

62건. 전이 매트릭스 전건 구조 검증, 필드 권한, HTTP 계층, 그리고
[로드맵 4.5절](./docs/roadmap.md#45-테스트-전략)의 필수 E2E 시나리오 8종을 포함한다.
그중 **E5~E8은 "거부되는 것이 정답"인 테스트**다.

---

## 코드 구조

```
app/
  workflow.py     ★ 전이 매트릭스 — 이 제품의 심장
  permissions.py    필드 그룹별 편집 권한
  services.py       전이 실행·필드 수정 (모든 쓰기 경로가 여기를 지난다)
  models.py         SQLAlchemy 모델
  enums.py          상태·역할·우선순위·회귀 대상
  notifications.py  앱 내 알림
  routers/          HTTP 껍데기
  templates/        Jinja2 화면
  seed.py           데모 데이터
tests/              62건
```

**`app/workflow.py` 의 `TRANSITIONS` 하나에서 네 가지가 파생된다**: 전이 권한 검증,
필수 입력 검증, 화면의 버튼 노출, "내 할 일" 큐. 새 전이나 권한 변경은 이 테이블만
고친다 — 규칙이 여러 곳에 흩어지면 반드시 어긋난다.

---

## 문서

| 문서 | 내용 |
|---|---|
| [docs/PRD.md](./docs/PRD.md) | **제품 요구사항 정의서.** 배경·목표·페르소나·유저스토리·기능요구사항(FR-###)·화면 요구사항·비기능 요구사항·성공 지표·리스크·오픈 이슈 |
| [docs/data-model.md](./docs/data-model.md) | 데이터 모델과 워크플로 정의. 엔티티·필드 사전, **상태 전이 매트릭스(22건)**, 역할×권한 매트릭스 |
| [docs/platform-decision.md](./docs/platform-decision.md) | 플랫폼 결정 기록. MS Teams vs 자체 웹앱 비교 평가와 **웹앱 단독 채택 근거**, 재검토 조건 |
| [docs/roadmap.md](./docs/roadmap.md) | 단계별 개발 로드맵. Phase 1~3 범위, **각 단계의 종료 조건(Exit Criteria)**, 테스트 전략 |

### 읽는 순서

1. **처음 보는 경우** — [PRD](./docs/PRD.md) 1~5절(개요·문제·목표·페르소나)만 읽으면
   이 제품이 무엇인지 파악된다.
2. **"왜 Teams가 아니라 웹앱인가"가 궁금하면** — [플랫폼 결정 기록](./docs/platform-decision.md)
3. **"언제 무엇이 나오는가"가 궁금하면** — [로드맵](./docs/roadmap.md)
4. **구현을 맡았다면** — [데이터 모델](./docs/data-model.md)의 상태 전이 매트릭스부터.
   이 표가 제품의 심장이며, 권한 검증·필수 입력 검증·화면 버튼 노출·내 할 일 큐가
   모두 여기서 파생된다.

---

## 핵심 결정 요약

| 항목 | 결정 | 근거 |
|---|---|---|
| 타겟 플랫폼 | **자체 웹 애플리케이션 단독** | [결정 기록](./docs/platform-decision.md) |
| MS Teams 연동 | **MVP 범위 제외.** Phase 3 선택 과제(FR-804) | 두 플랫폼 동시 검증은 MVP를 흐린다 |
| 구현 스택 | Python 3.11 · FastAPI · Jinja2 서버 렌더링 · SQLAlchemy · SQLite/PostgreSQL | [PRD 9절](./docs/PRD.md#9-기술-스택) |
| 인증 | Microsoft Entra ID OIDC (자체 비밀번호 없음) | 사내 계정 그대로 사용 |
| 개발 방식 | 최소 MVP 후 단계적 확장. **각 단계 종료 조건 충족 시에만 다음 단계 착수** | [로드맵 1절](./docs/roadmap.md#1-원칙) |
| 상태 모델 | 12개 상태 / 22개 전이 | [데이터 모델 3~5절](./docs/data-model.md#3-상태-정의) |

## 진행단계 한눈에 보기

```
작성중 → 접수 → 요건검토 → UI설계 → 개발중 → 개발완료 → 검수중 → 완료
                    │           ↑         ↑                  │
                    │           └─────────┴──── 보완요청 ◀────┘
                    │                            (요건/UI/구현 분류)
                    └→ 보류 / 반려                          
```

전체 다이어그램과 전이 규칙은 [데이터 모델 4~5절](./docs/data-model.md#4-상태-다이어그램)에 있다.
