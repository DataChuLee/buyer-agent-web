# Chain 폴더

## 역할
LangChain 체인 모듈. 에이전트 노드에서 호출하는 단위 체인.

## 주요 파일
- `intent_chain.py` → 사용자 메시지 의도 분류 체인
- `general_chat_chain.py` → 일반 대화(chitchat) 체인
- `data_nor.ipynb` → 데이터 정규화 실험 노트북 (참고용)

## 의존성
- langchain-anthropic (Claude 모델)
- Agent 노드에서 import해서 사용
