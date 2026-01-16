from app.core.databases import db

def query_graduation_rule(dept: str, keyword: str) -> str:
    """졸업 요건 및 학사 규정 조회 (Graph DB)"""
    #
    cypher = """
    MATCH (d:Department {name: $dept})-[:HAS_RULE]->(req:Requirement)
    WHERE req.content CONTAINS $keyword OR req.category CONTAINS $keyword
    RETURN req.category as cat, req.content as content
    LIMIT 3
    """
    
    with db.neo4j_driver.session() as session:
        result = session.run(cypher, dept=dept, keyword=keyword)
        rules = [f"[{r['cat']}] {r['content']}" for r in result]
        
    if not rules:
        return f"{dept}의 '{keyword}' 관련 졸업 요건 정보를 찾을 수 없습니다."
    return "\n".join(rules)