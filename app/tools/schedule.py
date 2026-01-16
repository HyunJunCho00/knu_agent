from app.lib.knu_scheduler import KnuScheduler # [cite: 1]
import pandas as pd
from app.core.databases import db

def generate_timetable(dept: str, grade: str, constraints: list) -> str:
    """
    제약조건 기반 시간표 생성
    constraints 예시: [{"type": "block", "day": 4, "start": 900, "end": 1800}] (금공강)
    """
    # 1. Neo4j에서 해당 학과/학년 강좌 데이터 로드
    cypher = """
    MATCH (d:Department {name: $dept})-[:OFFERS]->(c:Course)-[:HAS_INSTANCE]->(l:Lecture)
    WHERE l.grade = $grade
    RETURN l.id as id, l.name as name, l.credit as credit, l.time as time, l.prof as prof
    """
    # 실제로는 Building 좌표(lat, lon)도 가져와야 함
    
    with db.neo4j_driver.session() as session:
        data = session.run(cypher, dept=dept, grade=grade).data()
    
    if not data:
        return "해당 학과/학년의 개설 강좌 정보를 찾을 수 없습니다."
        
    df = pd.DataFrame(data)
    
    # 2. 스케줄러 실행
    scheduler = KnuScheduler(df)
    
    # 설정 구성 (LLM이 추출한 constraints 반영)
    config = {
        "min_credit": 15,
        "max_credit": 21,
        "user_grade": grade,
        "block_times": [], # constraints 파싱하여 채움
        "must_have": []
    }
    
    solutions = scheduler.solve(config)
    
    if not solutions:
        return "조건을 만족하는 시간표를 만들 수 없습니다. 조건을 완화해주세요."
        
    # 결과 요약
    best = solutions[0]['lectures']
    summary = "\n".join([f"- {l['name']} ({l['time']})" for l in best])
    return f"추천 시간표(총 {solutions[0]['total_credit']}학점):\n{summary}"