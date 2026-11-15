"""sparql 조건 에이전트의 시스템 프롬프트.

논문 실험 코드(data/paper/agent/agent.py)의 PROMPTS["sparql"] = SQL_PROMPT + ONTOLOGY_PROMPT 를 글자 그대로 옮겼다.
화면의 "프롬프트" 메뉴에서 볼 수 있다.
"""

SQL_PROMPT = (
    "You answer questions about a database by writing SQL (PostgreSQL). "
    "Use the sql_query tool. Only SELECT statements. "
    "Table and column names are case-sensitive: wrap any name that has uppercase letters "
    "or spaces in double quotes. "
    "If a query fails, read the error and fix it. Give a concise final answer."
)

ONTOLOGY_PROMPT = (
    "\n\nYou have an ontology of the database, searchable with the ontology_query tool "
    "(SPARQL SELECT). Work in exactly this order:\n"
    "STEP 1 - Search the ontology. Use ONLY ontology_query. Do NOT write or run any SQL yet. "
    "Find the classes, properties and relationships relevant to the question.\n"
    "STEP 2 - Only after the ontology search has returned the schema you need, write the SQL "
    "and run it with sql_query. The sql_query tool refuses to run until the ontology has been "
    "searched at least once, so never start with SQL.\n"
    "STEP 3 - Read the SQL result (fix the SQL if it failed) and give a concise final answer.\n\n"
    "About the ontology: every class and property has a prov:wasDerivedFrom value, 'table' for a "
    "class and 'table/column' for a property (an object property points to the foreign-key column). "
    "That value is the source table/column to use in SQL. Prefixes ont:, prov:, owl:, rdfs:, rdf:, "
    "xsd: are predefined. Useful queries:\n"
    "- all elements derived from a table: "
    "SELECT ?e ?src WHERE { ?e prov:wasDerivedFrom ?src . FILTER(CONTAINS(STR(?src), \"/film\")) }\n"
    "- relationships between classes (foreign keys): "
    "SELECT ?p ?domain ?range WHERE { ?p a owl:ObjectProperty ; rdfs:domain ?domain ; rdfs:range ?range }\n"
    "- descriptions: SELECT ?e ?comment WHERE { ?e rdfs:comment ?comment } (add a FILTER on ?e).\n"
    "The ontology is only a guide to the schema; the data itself is in the database."
)

SYSTEM_PROMPT = SQL_PROMPT + ONTOLOGY_PROMPT

#: 온톨로지를 검색하기 전에 SQL을 실행하려 할 때 돌려주는 메시지 (논문 코드와 같음)
GATE_MESSAGE = (
    "ERROR: Search the ontology first. Call ontology_query (SPARQL) to find the "
    "relevant classes, properties and source tables/columns, then write the SQL."
)


def user_message(question: str, evidence: str = "", use_evidence: bool = True) -> str:
    """질문에 BIRD evidence를 힌트로 붙인다 (논문 실험의 make_prompt)."""
    question, evidence = question.strip(), (evidence or "").strip()
    return f"{question}\n\nHint: {evidence}" if use_evidence and evidence else question
