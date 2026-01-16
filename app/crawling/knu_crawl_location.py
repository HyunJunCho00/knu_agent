import pandas as pd
import requests
import json
import re
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()
KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")

MANUAL_FIX = {
    # -----------------------------------------------------
    # 1. API 검색 실패했던 4개 완벽 해결
    # -----------------------------------------------------
    "외국어교육관": "경북대학교 언어교육원",  # 행정명 vs 지도명 불일치 해결
    "수의대해부학실습실": "경북대학교 수의과대학", # 세부 시설 -> 본관 매핑
    "칠곡 캠퍼스 의생명과학관": (35.9575, 128.5630), # 칠곡 의대 연구동 좌표
    "대구광역시 도심캠퍼스 1호관": (35.8717, 128.5894), # 중구 태평로 (도심캠퍼스 위치)

    # -----------------------------------------------------
    # 2. 엉뚱한 위치(타지역)로 튀는 오류 방지 (Critical!)
    # -----------------------------------------------------
    "동물병원": (35.8866, 128.6138), # 김포로 튀는 것 방지 -> 산격동 좌표 고정

    # -----------------------------------------------------
    # 3. 동인동(의대) 및 병원 관련 (API가 층수를 모름)
    # -----------------------------------------------------
    "의대신관및강의동": "경북대학교 의과대학",
    "의학 전문대학원": "경북대학교 의과대학",
    "복지후생동": "경북대학교 의과대학",
    "치의학임상연구동": "경북대학교 치과대학",
    "수의과대학1": "경북대학교 수의과대학",
    
    # 병원 좌표 하드코딩 (건물이 커서 검색보다 좌표 지정이 정확함)
    "경북대학교병원": (35.8660, 128.6040),        # 삼덕동 본원
    "경북대학교치과병원": (35.8640, 128.6010),    # 삼덕동 치과
    "칠곡경북대학교병원": (35.9560, 128.5640),    # 칠곡 분원

    # -----------------------------------------------------
    # 4. 기타 및 상주캠퍼스
    # -----------------------------------------------------
    "테니스장대기실": (35.8898, 128.6053), # 제2체육관 옆
    "수영장": (35.8898, 128.6053),
    "정보전산원": "경북대학교 정보전산원",
    "대구테크노파크 지역대학협력센터": "대구테크노파크 성서캠퍼스",
    "농업생명과학대학 부속 실습장 친환경농업교육및연구센터": "경북대 농대2호관", # 인근 매핑
    "국가물산업클러스터 워터캠퍼스동": (35.6690, 128.4230), # 달성군 구지면

    # 상주캠퍼스 Fallback용
    "상주캠퍼스 본관": (36.3794, 128.1450),
    "상주캠퍼스": (36.3794, 128.1450)
}

def get_kakao_coord(query):
    """카카오 API로 검색하여 좌표(lat, lon) 반환"""
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    
    try:
        resp = requests.get(url, headers=headers, params={"query": query})
        data = resp.json()
        if data['documents']:
            return float(data['documents'][0]['y']), float(data['documents'][0]['x'])
    except Exception as e:
        print(f"    ⚠️ API Error: {e}")
        return None, None
    return None, None

def clean_name_final(raw_name):
    """
    건물명 전처리 (병원 층수 제거, 캠퍼스명 정리)
    """
    if pd.isna(raw_name) or str(raw_name).strip() == "": return None
    name = str(raw_name)

    # [1] 병원 이름 정규화
    if "칠곡경북대학교병원" in name: return "칠곡경북대학교병원"
    if "경북대학교병원" in name: return "경북대학교병원"
    if "치과병원" in name: return "경북대학교치과병원"

    # [2] 콤마(,) 처리
    if "," in name: name = name.split(",")[0]

    # [3] 괄호 및 불필요한 수식어 제거
    name = re.sub(r'\([^)]*\)', '', name)
    name = name.replace("산격동 캠퍼스", "").replace("동인동 캠퍼스", "").replace("대구 캠퍼스", "")
    
    # [4] 상주캠퍼스 처리 ("제" 제거)
    if "상주캠퍼스" in name:
        name = name.replace("제", "").strip()
        if "경북대" not in name:
            return f"경북대 {name}"
        return name

    return name.strip()

def generate_building_map(csv_file):
    print(f"📂 데이터 로딩 중: {csv_file}")
    df = pd.read_csv(csv_file)
    
    raw_buildings = df['강의실'].dropna().unique()
    print(f"🔍 발견된 고유 건물명: {len(raw_buildings)}개")
    
    coord_map = {}
    success_count = 0
    fail_count = 0
    
    print("🚀 카카오 지도로 좌표 매핑 시작...")
    
    for raw in raw_buildings:
        # 1. 이름 정제
        clean_name = clean_name_final(raw)
        if not clean_name: continue

        # 2. [Priority 1] 수동 매핑(MANUAL_FIX) 확인
        if clean_name in MANUAL_FIX:
            val = MANUAL_FIX[clean_name]
            if isinstance(val, tuple): # 좌표 직접 입력
                coord_map[raw] = list(val)
                print(f"  ✅ [수동] '{clean_name}'")
            else: # 대체 검색어
                lat, lon = get_kakao_coord(val)
                if lat:
                    coord_map[raw] = [lat, lon]
                    print(f"  ✅ [대체] '{clean_name}' -> '{val}'")
            success_count += 1
            continue

        # 3. [Priority 2] 상주캠퍼스 Fallback
        if "상주캠퍼스" in clean_name:
            lat, lon = get_kakao_coord(clean_name)
            if not lat:
                lat, lon = MANUAL_FIX["상주캠퍼스"] # 본관 좌표
                print(f"  ⚠️ [상주] '{raw}' -> 본관 좌표로 대체")
            
            if lat:
                coord_map[raw] = [lat, lon]
                success_count += 1
                continue

        # 4. [Priority 3] 일반 API 검색
        search_query = clean_name
        if "경북대" not in search_query and "병원" not in search_query:
            search_query = f"경북대 {clean_name}"
            
        lat, lon = get_kakao_coord(search_query)
        
        if lat:
            coord_map[raw] = [lat, lon]
            print(f"  ✅ [API] '{raw}' -> {lat}, {lon}")
            success_count += 1
        else:
            # 5. [Final Fallback] 절대 죽지 않는 로직
            print(f"  ❌ [최종실패] '{clean_name}' (원본: {raw}) -> 복지관 좌표 대체")
            coord_map[raw] = [35.8895, 128.611] # 복지관
            fail_count += 1

    # 결과 저장
    output_file = "building_coords.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(coord_map, f, ensure_ascii=False, indent=4)
        
    print("-" * 50)
    print(f"🎉 최종 완료! (성공: {success_count}, 실패(대체): {fail_count})")
    print(f"💾 좌표 파일 저장됨: {os.path.abspath(output_file)}")

if __name__ == "__main__":
    generate_building_map("knu_full_data_2025_2학기.csv")