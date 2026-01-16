import random

def get_cafeteria_menu(location: str, date: str):
    """
    실제로는 학교 홈페이지나 API를 크롤링해야 합니다.
    현재는 아키텍처 예시를 위해 Mock 데이터를 반환합니다.
    """
    menus = {
        "복지관": "등심돈가스, 쫄면무침",
        "정보센터": "참치마요덮밥, 미소장국",
        "기숙사": "제육볶음, 상추쌈"
    }
    return menus.get(location, "해당 식당의 메뉴 정보가 없습니다.")

def recommend_nearby_restaurant(location: str, preference: str):
    """
    사용자 위치와 선호도(장기기억) 기반 추천
    """
    # 실제로는 네이버 지도 API 등을 연동
    recommendations = [
        {"name": "경대컵밥", "menu": "제육컵밥", "category": "한식"},
        {"name": "파스타부오노", "menu": "봉골레", "category": "양식"},
        {"name": "서브웨이", "menu": "샌드위치", "category": "간편식"}
    ]
    
    # 간단한 필터링 로직
    filtered = [r for r in recommendations if preference in r['category'] or preference == "상관없음"]
    return filtered if filtered else recommendations