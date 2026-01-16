from typing import TypedDict, List, Optional, Annotated
from langchain_core.messages import BaseMessage
import operator

class AgentState(TypedDict):
    user_id: str
    messages: Annotated[List[BaseMessage], operator.add]
    user_profile: dict         # Redis에서 로드한 장기 기억
    intent: str                # 분류된 의도
    tool_output: Optional[str] # 도구 실행 결과
    error_count: int           # 에러 반복 횟수 (무한 루프 방지)
    final_answer: str