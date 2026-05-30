# Agent 폴더

## 역할
LangGraph 기반 멀티에이전트 오케스트레이션. 사용자 의도 파악 → 조건 수집 → 상품/판매자 검색 → 분석까지 전체 대화 흐름 관리.

## 주요 파일 (현재 사용)
- `LangGraph_buyeragent_with_personalization.py` → **메인 에이전트** (LangMem 개인화 포함)
- `LangGraph_orchestrator_agent.py` → 오케스트레이터
- `sub_agent.py` → 서브에이전트 (최신)
- `product_analysis_agent.py` → 상품 분석 전담

## 구버전 (수정 X)
- `LangGraph_buyeragent(with_personalization).py`
- `orchestrator_agent.py`, `orchestrator_agent_0310.py`
- `sub_agent_0310.py`

## 노드 흐름
```
load_user_memory
  → extract_conditions_and_intent
  → check_conditions
    → ask_missing_node        (조건 부족 시)
    → chitchat_node           (일반 대화)
    → product_search_node
      → seller_search_node
        → product_analysis_node
  → save_user_memory
```

## 의존성
- State: `State/AgentState_personalization.py`
- Tools: `Tools/tool.py`
- Memory: LangMem (langmem 라이브러리)
