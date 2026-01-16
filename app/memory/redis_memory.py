import json
from app.core.databases import db

class LongTermMemory:
    def __init__(self, user_id: str):
        self.r = db.redis
        self.user_id = user_id
        self.profile_key = f"user:{user_id}:profile"
        
    def get_profile(self) -> dict:
        """사용자 프로필 로드"""
        data = self.r.get(self.profile_key)
        return json.loads(data) if data else {}

    def set_profile(self, profile_data: dict):
        """[중요] 온보딩 시 사용자 정보를 최초 저장"""
        current = self.get_profile()
        current.update(profile_data)
        self.r.set(self.profile_key, json.dumps(current))
        
    def get_context_string(self) -> str:
        """프롬프트 주입용"""
        p = self.get_profile()
        if not p: return ""
        # 나이/성별 대신 학과, 학년, 식성 등 기능적 정보만 사용
        return f"사용자 정보: 소속({p.get('dept', '미정')}), 학년({p.get('grade', '미정')}), 선호({p.get('preference', '없음')})"