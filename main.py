from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.workflows.graph import build_graph
from app.memory.redis_memory import LongTermMemory

app = FastAPI(title="KNU Agent API")
agent_graph = build_graph()

# 1. 초기 정보 수집용 모델
class UserProfile(BaseModel):
    user_id: str
    dept: str       # 필수
    grade: str      # 필수
    preference: str | None = None # 선택 (식성 등)

class ChatRequest(BaseModel):
    user_id: str
    message: str

@app.post("/user/onboard")
async def onboard_user(profile: UserProfile):
    """
    [하이브리드 온보딩]
    앱 최초 실행 시 이 API를 호출하여 필수 정보를 Redis에 심습니다.
    """
    try:
        mem = LongTermMemory(profile.user_id)
        # dict 변환 시 None 값 제외
        data = profile.dict(exclude_none=True)
        mem.set_profile(data)
        return {"status": "success", "message": f"{profile.dept} {profile.grade}학년 프로필 등록 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def chat(req: ChatRequest):
    """
    대화 API
    - 온보딩이 안 된 유저가 들어오면 Agent가 알아서 학과/학년을 물어봅니다.
    """
    try:
        inputs = {
            "user_id": req.user_id,
            "messages": [("user", req.message)],
            "user_profile": {},
            "intent": "",
            "error_count": 0
        }
        
        result = await agent_graph.ainvoke(inputs)
        return {"response": result["final_answer"]}
    except Exception as e:
        # 로그 기록 필요
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)