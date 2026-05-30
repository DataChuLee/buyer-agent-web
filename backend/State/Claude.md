# State 폴더

## 역할
LangGraph 에이전트의 상태(State) 스키마 정의.

## 주요 파일
- `AgentState_personalization.py` → **현재 사용** (개인화 포함 최신 버전)
- `AgentState.py` → 기본 버전 (구버전)

## AgentState 주요 필드
- 사용자 메시지 / 대화 히스토리
- 추출된 조건 (상품 조건, 판매자 조건 등)
- 질문 시퀀스 (조건 수집용)
- 검색 결과 (상품, 판매자, 분석)
- 유저 프로필 / 메모리

## 주의
- 새 필드 추가 시 FastAPI Response Schema와 함께 수정 필요
- `AgentState.py`는 레거시, 수정 X
