출처: https://github.com/birdf00t/ontology (commit e57e905)
논문 "자동 생성 온톨로지를 이용한 LLM 데이터베이스 질의 성능 비교"의 실험 코드와 결과물 사본.

- movie_3.owl, synthea.owl : RIGOR로 생성한 온톨로지 (업로드 방식의 기본값)
- *.r2rml                 : ontop 조건용 매핑 (이번 범위에서는 참고만)
- agent/                  : sparql 조건 에이전트 코드와 시스템 프롬프트 (agent.py의 PROMPTS["sparql"])
- question_prep/          : 정답 SQL의 PostgreSQL 변환, 난이도 분류 스크립트
- rigor_edit/             : 수정한 RIGOR 코드 (MIT, LICENSE.txt 포함)
- sqlite_to_pg/           : SQLite → PostgreSQL 이전 스크립트 (SQLite 파일을 불러올 때 사용)
