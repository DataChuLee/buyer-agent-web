from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI


llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


async def classify_intent(query: str):
    prompt = PromptTemplate.from_template(
        """당신은 구매 어시스턴트 라우터입니다.
    사용자 질문을 아래 4개 라벨 중 정확히 1개로 분류하세요.

    [라벨 정의]
    - general_chat: 일상 대화, 감정/고민/잡담, 구매 의도 없음
    - product_search: 제품 추천/탐색 요청 (예: "축구화 추천", "20만원 이하 제품 찾아줘")
    - seller_search: 구매처/판매처/어디서 사는지 요청 (예: "이거 어디서 사?", "공식몰 링크")
    - product_analysis: 2개 이상 제품/후보의 비교·분석 요청 (예: "A와 B 비교", "장단점 분석")

    [우선순위 규칙]  (중요)
    1) 비교/분석 의도가 있으면 product_analysis
    2) 판매처/구매처 탐색 의도가 있으면 seller_search
    3) 제품 추천/탐색 의도가 있으면 product_search
    4) 그 외는 general_chat

    [출력 규칙]
    - 반드시 다음 중 하나만 출력:
    general_chat
    product_search
    seller_search
    product_analysis
    - 설명, 문장, 부호, 코드블록 없이 라벨만 출력

    [User Question]
    {question}
    """
    )

    # 체인을 생성합니다.
    chain = prompt | llm | StrOutputParser()  # 문자열 출력 파서를 사용합니다.
    result = chain.ainvoke({"question": query})
    return await result
