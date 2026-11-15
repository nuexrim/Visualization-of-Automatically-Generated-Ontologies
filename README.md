# OntoLens (프로토타입)

논문 "자동 생성 온톨로지를 이용한 LLM 데이터베이스 질의 성능 비교"의 **sparql 조건**이 어떻게 동작하는지 보여주는 웹 애플리케이션입니다.
DB를 불러와 ERD를 그리고, RIGOR 방식으로 온톨로지를 만들고, LLM 에이전트가 온톨로지를 SPARQL로 검색한 뒤 SQL로 답하는 과정을 캔버스 위에 단계별로 보여줍니다.

> 현재는 프로토타입입니다. 알려진 한계를 정리한 뒤 최종 README(설치 상세, 스크린샷, 예시 시나리오)를 작성할 예정입니다.

## 실행

준비물: Docker(Compose 포함), Anthropic API 키

```bash
cp .env.example .env   # ANTHROPIC_API_KEY, AGENT_MODEL, ONTOLOGY_GEN_MODEL, DB 비밀번호를 채운다
docker compose up -d --build
```

브라우저에서 http://localhost:5173 을 엽니다. (DB 5433, 백엔드 8010 포트를 씁니다)

## 사용 순서

1. **DB 불러오기**: `data/dumps/`의 `movie_3.dump` 또는 `synthea.dump`(또는 .sql / .sqlite)를 고르면 ERD가 그려집니다.
2. **온톨로지 생성하기**: RIGOR 방식(LLM 보강·판정) 또는 Direct Mapping만으로 온톨로지 파일을 만듭니다.
3. **온톨로지 불러오기**: 만든 파일을 불러오면 클래스·관계 그래프가 나타나고 ERD와 연결됩니다.
4. **채팅**: 질문(또는 BIRD 예시 질문)을 실행하면 온톨로지 검색 → SQL 실행 → 답변 과정이 타임라인과 캔버스에 단계별로 강조됩니다. 저장된 기록은 다시 열어 재생할 수 있습니다.
5. **수정**: 오른쪽 패널에서 라벨, 설명, 관계, 트리플 등을 고치면 다음 질문부터 에이전트가 바로 사용합니다. 되돌리기, 버전 저장, 원본과의 차이(diff)를 지원합니다.

## 구성

- `frontend/`: React + TypeScript + Vite, React Flow, elkjs, Zustand, Tailwind
- `backend/`: Python 3.11 + FastAPI, rdflib, sqlglot, LangGraph ReAct 에이전트 (도구 2개: `ontology_query`, `sql_query`)
- `data/`: 샘플 DB 덤프, BIRD 컬럼 설명·질문, 논문 실험 결과물(`data/paper/`)

## 테스트

```bash
cd backend && uv sync && .venv/bin/python -m pytest -q
```

(DB 컨테이너가 떠 있어야 합니다)
