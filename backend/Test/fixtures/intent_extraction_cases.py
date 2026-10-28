"""extract_conditions_and_intent 실제 LLM 정확도 측정용 라벨 데이터셋.

각 케이스는 (message, history, expected_intent, expected_capabilities) 튜플이다.
- history: [(role, content), ...] — role은 "user"/"assistant". 대명사/맥락 참조 케이스에서
  직전 턴을 재현하기 위해 사용한다.
- expected_intent: extract_conditions_and_intent가 최종적으로 반환하는 intent
  (product_search/seller_search/product_analysis/product_guide/chitchat/purchase_prepare).
- expected_capabilities: shopping 계열일 때 기대하는 orchestration_plan(순서 무관, 집합 비교).
  product_guide/chitchat/purchase_prepare는 빈 리스트.
"""

INTENT_EXTRACTION_CASES: list[dict] = [
    # --- 멀티 capability ---
    {
        "message": "나이키 10만원대 축구화 추천해주고 어디서 파는지도 알려줘",
        "history": [],
        "expected_intent": "product_search",
        "expected_capabilities": ["product_search", "seller_search"],
    },
    {
        "message": "머큐리얼 베이퍼 판매처 비교하고 상세 분석까지 해줘",
        "history": [],
        "expected_intent": "seller_search",
        "expected_capabilities": ["seller_search", "product_analysis"],
    },
    {
        "message": "10만원대 TF 축구화 추천해주고 판매처 비교한 뒤 제일 싼 곳에서 분석해줘",
        "history": [],
        "expected_intent": "product_search",
        "expected_capabilities": ["product_search", "seller_search", "product_analysis"],
    },
    # --- 대명사/맥락 참조 ---
    {
        "message": "거기서 제일 싼 거 분석해줘",
        "history": [
            ("user", "나이키 머큐리얼 베이퍼 판매처 알려줘"),
            ("assistant", "크레이지11, 사커붐, 레드사커, 카포스토어에서 판매 중입니다."),
        ],
        "expected_intent": "product_analysis",
        "expected_capabilities": ["product_analysis"],
    },
    {
        "message": "그거 사려면 어디로 가야돼?",
        "history": [
            ("user", "공격수용 축구화 추천해줘"),
            ("assistant", "머큐리얼 베이퍼 15를 추천드립니다."),
        ],
        "expected_intent": "seller_search",
        "expected_capabilities": ["seller_search"],
    },
    {
        "message": "그럼 TF는?",
        "history": [
            ("user", "나이키 10만원대 축구화 추천해줘"),
            ("assistant", "머큐리얼 베이퍼 15를 추천드립니다."),
        ],
        "expected_intent": "product_search",
        "expected_capabilities": ["product_search"],
    },
    # --- Bug B 회귀: 구매 의도 표현이 seller_search로 오분류되면 안 됨 ---
    {
        "message": "나이키 축구화를 구매하려고 하는데 어떤 게 좋을까? 공격수이거든",
        "history": [],
        "expected_intent": "product_search",
        "expected_capabilities": ["product_search"],
    },
    {
        "message": "풋살화 구매하려고 하는데 뭐가 괜찮아?",
        "history": [],
        "expected_intent": "product_search",
        "expected_capabilities": ["product_search"],
    },
    # --- 진짜 판매처 질문 (seller_search 유지되어야 함) ---
    {
        "message": "머큐리얼 베이퍼 16 어디서 사?",
        "history": [],
        "expected_intent": "seller_search",
        "expected_capabilities": ["seller_search"],
    },
    {
        "message": "이 제품 제일 싸게 파는 판매처가 어디야?",
        "history": [
            ("user", "나이키 10만원대 축구화 추천해줘"),
            ("assistant", "머큐리얼 베이퍼 15를 추천드립니다."),
        ],
        "expected_intent": "seller_search",
        "expected_capabilities": ["seller_search"],
    },
    # --- product_guide (쇼핑 인접이지만 실검색 아님) ---
    {
        "message": "FG랑 TF 차이가 뭐야?",
        "history": [],
        "expected_intent": "product_guide",
        "expected_capabilities": [],
    },
    {
        "message": "공격수는 축구화 고를 때 뭘 우선으로 봐야 해?",
        "history": [],
        "expected_intent": "product_guide",
        "expected_capabilities": [],
    },
    {
        "message": "포지션별로는 어떤 스터드를 사용하는 게 좋아?",
        "history": [],
        "expected_intent": "product_guide",
        "expected_capabilities": [],
    },
    # --- 쇼핑 인접 잡담 (product_search로 오분류되면 안 됨) ---
    {
        "message": "축구화 신고 뛰었는데 발이 너무 아파",
        "history": [],
        "expected_intent": "chitchat",
        "expected_capabilities": [],
    },
    {
        "message": "어제 축구 경기 봤어? 손흥민 골 미쳤더라",
        "history": [],
        "expected_intent": "chitchat",
        "expected_capabilities": [],
    },
    # --- 순수 잡담 ---
    {
        "message": "ㅎㅇ 오늘 날씨 좋다",
        "history": [],
        "expected_intent": "chitchat",
        "expected_capabilities": [],
    },
    {
        "message": "고마워 도움 많이 됐어",
        "history": [],
        "expected_intent": "chitchat",
        "expected_capabilities": [],
    },
    # --- 구매 의도 (LLM 호출 전 정규식 선차단 — purchase_prepare) ---
    {
        "message": "이걸로 살게",
        "history": [],
        "expected_intent": "purchase_prepare",
        "expected_capabilities": [],
    },
    {
        "message": "그냥 이거 구매해줘",
        "history": [],
        "expected_intent": "purchase_prepare",
        "expected_capabilities": [],
    },
]
