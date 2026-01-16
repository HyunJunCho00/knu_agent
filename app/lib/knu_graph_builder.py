import os
import pandas as pd
import re
import json
from neo4j import GraphDatabase
from tqdm import tqdm

# Neo4j 설정 (환경 변수 또는 직접 입력)
NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", os.getenv("NEO4J_PASSWORD", "20260220"))

class KnuGraphBuilder:
    def __init__(self, coord_file_path=None):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        self.coords_map = {}
        
        # 좌표 파일 로드 (건물 위치 정보)
        if coord_file_path and os.path.exists(coord_file_path):
            with open(coord_file_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                # 검색 최적화를 위해 키 정규화 (공백 제거)
                self.coords_map = {k.replace(" ", "").replace("산격동캠퍼스", ""): v for k, v in raw_data.items()}

    def close(self):
        self.driver.close()

    def normalize_text(self, text):
        """데이터 정규화: 공백 제거 및 문자열 변환"""
        if pd.isna(text): return ""
        return str(text).strip()

    def init_schema(self):
        """데이터베이스 스키마 및 인덱스 초기화"""
        print("[Graph] Initializing Schema...")
        with self.driver.session() as session:
            constraints = [
                "CREATE CONSTRAINT FOR (d:Department) REQUIRE d.name IS UNIQUE",
                "CREATE CONSTRAINT FOR (c:Course) REQUIRE c.code IS UNIQUE",
                "CREATE INDEX FOR (c:Course) ON (c.name)",
                "CREATE INDEX FOR (l:Lecture) ON (l.id)",
                "CREATE INDEX FOR (b:Building) ON (b.name)",
                "CREATE INDEX FOR (req:Requirement) ON (req.dept)"
            ]
            for q in constraints:
                try: session.run(q)
                except Exception as e: pass # 이미 존재하면 무시
        print("[Graph] Schema Initialized.")

    def ingest_roadmap(self, csv_path):
        """1단계: 로드맵 데이터 적재 (커리큘럼 기준 정보)"""
        print(f"[Graph] Ingesting Roadmap from {csv_path}...")
        df = pd.read_csv(csv_path).fillna('')

        query = """
        UNWIND $batch AS row
        MERGE (d:Department {name: row.dept})
        
        // Course 노드 생성 (과목 코드로 식별)
        MERGE (c:Course {code: row.code})
        ON CREATE SET c.name = row.name
        
        // 추천 관계 설정
        MERGE (d)-[r:RECOMMENDS]->(c)
        SET r.grade = row.grade,
            r.semester = row.semester,
            r.category = '로드맵'
        """

        batch = []
        with self.driver.session() as session:
            for _, row in tqdm(df.iterrows(), total=len(df)):
                batch.append({
                    'dept': self.normalize_text(row['학과']),
                    'code': self.normalize_text(row['과목코드']),
                    'name': self.normalize_text(row['교과목명']),
                    'grade': str(row['학년']),
                    'semester': self.normalize_text(row['학기'])
                })
                if len(batch) >= 1000:
                    session.run(query, batch=batch)
                    batch = []
            if batch: session.run(query, batch=batch)

    def ingest_guide(self, csv_path):
        """2단계: 가이드 데이터 적재 (졸업 요건 및 규정)"""
        print(f"[Graph] Ingesting Guides from {csv_path}...")
        df = pd.read_csv(csv_path).fillna('')

        # 요건(Requirement) 노드 생성
        query_req = """
        UNWIND $batch AS row
        MATCH (d:Department {name: row.dept})
        MERGE (req:Requirement {id: row.req_id})
        SET req.category = row.category, 
            req.content = row.content,
            req.min_credit = row.min_credit
        MERGE (d)-[:HAS_RULE]->(req)
        """
        
        # 필수 과목 지정 관계 (Rule -> Course)
        query_mandate = """
        UNWIND $batch AS row
        MATCH (req:Requirement {id: row.req_id})
        MATCH (c:Course {name: row.course_name})
        MERGE (req)-[:MANDATES]->(c)
        """

        batch_req = []
        batch_mandate = []

        for idx, row in df.iterrows():
            dept = self.normalize_text(row['학과'])
            category = self.normalize_text(row['구분'])
            content = self.normalize_text(row['내용'])
            req_id = f"{dept}_{idx}" # 고유 ID

            # 학점 정보 추출 (예: "전공 72학점")
            credits = re.findall(r'(\d+)학점', content)
            min_credit = int(credits[0]) if credits else 0

            batch_req.append({
                'dept': dept,
                'req_id': req_id,
                'category': category,
                'content': content,
                'min_credit': min_credit
            })

            # 필수 과목 추출 로직 (텍스트 분석)
            # "필수" 혹은 "지정"이라는 단어가 들어간 요건에서 과목명으로 추정되는 단어 추출
            if '필수' in category or '지정' in content or '필수' in content:
                # 2글자 이상의 한글/영문 단어 추출
                candidates = re.findall(r'[가-힣A-Za-z0-9]{2,}', content)
                keywords = ['이수', '학점', '이상', '포함', '졸업', '대상자', '반드시', '과목', '전공', '교양', '선택']
                
                for word in candidates:
                    if word not in keywords:
                        # 로드맵에 있는 과목명과 일치하는지 확인하면 더 좋지만, 
                        # 여기서는 일단 연결을 시도합니다 (Graph DB의 유연성 활용)
                        batch_mandate.append({'req_id': req_id, 'course_name': word})

        with self.driver.session() as session:
            # 배치 처리
            for i in range(0, len(batch_req), 500):
                session.run(query_req, batch=batch_req[i:i+500])
            for i in range(0, len(batch_mandate), 500):
                session.run(query_mandate, batch=batch_mandate[i:i+500])

    def ingest_lectures(self, csv_path):
        """3단계: 개설 강좌 데이터 적재 (실제 실행 정보)"""
        print(f"[Graph] Ingesting Lectures from {csv_path}...")
        df = pd.read_csv(csv_path).fillna('')

        query = """
        UNWIND $batch AS row
        MATCH (d:Department {name: row.dept})
        
        // Course 연결 (없으면 생성)
        MERGE (c:Course {code: row.course_code})
        ON CREATE SET c.name = row.course_name, c.credit = row.credit
        
        // Lecture 생성
        MERGE (l:Lecture {id: row.lecture_id})
        SET l.name = row.course_name, 
            l.time = row.time,
            l.prof = row.prof,
            l.grade = row.grade,
            l.credit = row.credit
            
        // Building 연결 (좌표 포함)
        MERGE (b:Building {name: row.building})
        ON CREATE SET b.lat = row.lat, b.lon = row.lon
        
        // 관계 설정
        MERGE (d)-[:OFFERS]->(c)
        MERGE (c)-[:HAS_INSTANCE]->(l)
        MERGE (l)-[:HELD_AT]->(b)
        """

        batch = []
        with self.driver.session() as session:
            for _, row in tqdm(df.iterrows(), total=len(df)):
                room = self.normalize_text(row['강의실'])
                dept = self.normalize_text(row['개설학과'])
                
                # 건물명 및 좌표 추출
                building_name = room.split()[0] if room else "Unknown"
                search_key = building_name.replace(" ", "")
                
                lat, lon = 0.0, 0.0
                # 좌표 매핑 시도
                for key, val in self.coords_map.items():
                    if key in search_key or search_key in key:
                        lat, lon = val
                        break
                
                batch.append({
                    'dept': dept,
                    'course_code': self.normalize_text(row['강좌번호']).split('-')[0],
                    'course_name': self.normalize_text(row['교과목명']),
                    'credit': int(row['학점']) if row['학점'] != '' else 0,
                    'lecture_id': self.normalize_text(row['강좌번호']),
                    'time': self.normalize_text(row['강의시간']),
                    'prof': self.normalize_text(row['담당교수']),
                    'grade': str(row['학년']),
                    'building': building_name,
                    'lat': lat,
                    'lon': lon
                })
                
                if len(batch) >= 500:
                    session.run(query, batch=batch)
                    batch = []
            if batch: session.run(query, batch=batch)

if __name__ == "__main__":
    # 사용 예시
    builder = KnuGraphBuilder("building_coords.json")
    builder.init_schema()
    
    # 데이터 적재 순서 중요 (Roadmap -> Guide -> Lecture)
    if os.path.exists("knu_road_final.csv"):
        builder.ingest_roadmap("knu_road_final.csv")
    if os.path.exists("knu_guide_final.csv"):
        builder.ingest_guide("knu_guide_final.csv")
    if os.path.exists("knu_full_data_2026_1학기.csv"):
        builder.ingest_lectures("knu_full_data_2026_1학기.csv")
        
    builder.close()
    print("[Graph] Build Complete.")