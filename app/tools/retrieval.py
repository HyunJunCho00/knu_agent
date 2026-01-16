from app.lib.knu_notice_retriever import KNUSearcher

# 전역 인스턴스 (메모리 절약)
searcher = KNUSearcher()

def search_notice(query: str, dept: str = "공통") -> str:
    """공지사항 검색 도구"""
    # search 메소드 활용
    results, _, _ = searcher.search(query, target_dept=dept)
    
    if not results:
        return "관련된 공지사항을 찾을 수 없습니다."
        
    # LLM이 읽기 좋게 포맷팅
    context_list = []
    for r in results[:3]: # 상위 3개만 사용 (토큰 절약)
        context_list.append(f"- [{r['date']}] {r['title']}: {r['content'][:150]}... (링크: {r['url']})")
    
    return "\n".join(context_list)