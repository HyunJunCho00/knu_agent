import json
from langchain_upstage import ChatUpstage
from langchain_core.messages import SystemMessage, HumanMessage
from app.core.config import settings
from app.memory.redis_memory import LongTermMemory
from app.tools import retrieval, academic, schedule, lifestyle

# [Upstage 연결 부분]
# API Key는 config.py를 통해 .env에서 가져옵니다.
llm = ChatUpstage(api_key=settings.UPSTAGE_API_KEY, model="solar-pro")

def load_memory_node(state: dict):
    """메모리 로드 및 필수 정보 체크"""
    mem = LongTermMemory(state["user_id"])
    profile = mem.get_profile()
    
    # [하이브리드 온보딩 전략]
    # 프로필에 필수 정보(dept, grade)가 없으면 intent를 'ONBOARDING'으로 강제 전환
    if not profile.get("dept") or not profile.get("grade"):
        return {"user_profile": profile, "intent": "ONBOARDING", "error_count": 0}
        
    return {"user_profile": profile, "error_count": 0}

def router_node(state: dict):
    """의도 분류"""
    if state.get("intent") == "ONBOARDING":
        return {"intent": "ONBOARDING"}

    profile = state["user_profile"]
    last_msg = state["messages"][-1].content
    
    # Upstage LLM을 활용한 추론
    prompt = f"""
    Context: {profile}
    Query: {last_msg}
    
    Classify intent into JSON:
    {{
        "intent": "NOTICE" | "ACADEMIC" | "TIMETABLE" | "LIFESTYLE" | "CHITCHAT",
        "args": "arguments for tool"
    }}
    """
    response = llm.invoke(prompt)
    try:
        # JSON 파싱 로직 (실제론 OutputParser 사용 권장)
        parsed = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
        return {"intent": parsed["intent"], "tool_output": parsed.get("args")}
    except:
        return {"intent": "CHITCHAT"}

def tool_node(state: dict):
    """도구 실행"""
    intent = state["intent"]
    args = state.get("tool_output")
    profile = state["user_profile"]
    
    result = ""
    try:
        if intent == "NOTICE":
            result = retrieval.search_notice(args, profile.get("dept", "공통"))
        elif intent == "ACADEMIC":
            result = academic.query_graduation_rule(profile.get("dept"), args)
        elif intent == "TIMETABLE":
            # args가 단순 문자열일 수 있으므로 LLM으로 JSON 변환 필요할 수 있음
            result = schedule.generate_timetable(profile.get("dept"), profile.get("grade"), [])
        elif intent == "LIFESTYLE":
            if "메뉴" in str(args):
                result = lifestyle.get_cafeteria_info()
            else:
                result = lifestyle.recommend_restaurant(profile.get("preference"))
    except Exception as e:
        result = f"Error: {str(e)}"
        
    return {"tool_output": result}

def generator_node(state: dict):
    """최종 응답 생성"""
    intent = state["intent"]
    
    # [온보딩 대화 처리]
    if intent == "ONBOARDING":
        return {"messages": ["반갑습니다! 더 정확한 도움을 드리기 위해 '학과'와 '학년'을 알려주시겠어요?"], "final_answer": "Onboarding requested"}
    
    # 일반 대화 처리
    context = state.get("tool_output", "")
    query = state["messages"][-1].content
    
    prompt = f"""
    당신은 경북대학교 AI 비서입니다. 아래 정보를 바탕으로 답변하세요.
    정보: {context}
    질문: {query}
    """
    res = llm.invoke(prompt)
    return {"messages": [res.content], "final_answer": res.content}