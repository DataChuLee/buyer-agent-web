import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from MCP.mcp_tool import get_search_mcp_tools
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(AGENT_DIR, ".."))


load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
PRODUCT_SEARCH_INCLUDE_DOMAINS = [
    "www.crazy11.co.kr",
    "soccerboom.co.kr",
    "www.redsoccer.co.kr",
    "www.cafostore.co.kr",
]


def _build_profile_context(user_profile: dict | None) -> str:
    """UserProfile dict → 시스템 프롬프트에 주입할 개인화 컨텍스트 문자열 생성."""
    if not user_profile:
        return ""
    lines = []
    labels = {
        "brand": "선호 브랜드",
        "budget": "예산",
        "surface": "선호 지면",
        "position": "포지션",
        "age_group": "연령대",
    }
    for key, label in labels.items():
        if user_profile.get(key):
            lines.append(f"- {label}: {user_profile[key]}")
    if user_profile.get("physical_traits"):
        lines.append(f"- 신체 특성: {', '.join(user_profile['physical_traits'])}")
    if user_profile.get("play_style"):
        lines.append(f"- 플레이 스타일: {', '.join(user_profile['play_style'])}")
    return "\n".join(lines)


async def _mcp_product_search_inner(query: str, system_prompt: str) -> str:
    """
    MCP 세션 + AgentExecutor 실행 로직.
    Windows anyio cancel scope 충돌 방지를 위해 별도 이벤트루프에서 호출됨.
    """
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )
    async with get_search_mcp_tools() as tools:
        advanced_search_tool = next(
            (t for t in tools if t.name == "web_search_advanced_exa"), None
        )
        if advanced_search_tool is None:
            raise RuntimeError("web_search_advanced_exa tool is not available")
        sequential_tools = [t for t in tools if t.name == "sequentialthinking"]

        @tool("web_search_advanced_exa")
        async def web_search_advanced_exa(query: str) -> str:
            """Search only the four supported seller domains (crazy11, soccerboom, redsoccer, cafostore) with a Korean query."""
            result = await advanced_search_tool.ainvoke(
                {
                    "query": query,
                    "type": "auto",
                    "numResults": 5,
                    "includeDomains": PRODUCT_SEARCH_INCLUDE_DOMAINS,
                }
            )
            return (
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )

        product_tools = [web_search_advanced_exa, *sequential_tools]
        agent = create_tool_calling_agent(llm, product_tools, prompt)
        executor = AgentExecutor(agent=agent, tools=product_tools, verbose=False)
        response = await executor.ainvoke({"input": query})
        return response["output"]


def _run_mcp_in_thread(query: str, system_prompt: str) -> str:
    """
    Windows에서 anyio cancel scope 충돌 방지:
    ProactorEventLoop을 명시적으로 생성해 MCP 세션을 격리된 환경에서 실행.
    """
    import sys as _sys

    if _sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_mcp_product_search_inner(query, system_prompt))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


_PRODUCT_SEARCH_SYSTEM_PROMPT = """
당신은 Football Shoes Search Agent입니다.
구매자가 축구화를 선택할 수 있도록, 'web_search_advanced_exa', 'sequentialthinking' 도구를 활용하여 **축구화 시리즈명 중심**의 정보를 찾아 정리하고, 맞춤형 추천 결과를 제공합니다.

---
## 🎯 목적 (Objective)

- 구매자의 요구와 선호 조건에 따라 만족스러운 축구화 시리즈를 **개인 맞춤형으로 추천**합니다.
- 추천은 **단일 제품이 아닌 '시리즈명' 중심**으로 구성되어야 합니다.
---
## 🛠️ 사용 도구 (Tools)

- `web_search_advanced_exa`: 웹 검색을 통해 축구화 및 관련 정보를 수집합니다.
    - 사용자는 구체적인 브랜드, 예산, 포지션, 기능 등에 관한 정보를 제공할 수 있으므로, 입력 조건을 기반으로 적합한 시리즈 후보를 탐색합니다.
- `sequentialthinking`: 다양한 웹 검색 결과나 정보를 단계적으로 정리·종합하여, 최종적으로 구조화된 추천 리스트를 만듭니다.
---
## 🔄 대화 흐름 (Interaction Flow)

### ▶ 항상 즉시 검색
- 조건이 충분하든 부족하든, **항상 `web_search_advanced_exa`를 호출해 검색**을 먼저 진행합니다.
- 추가 질문은 하지 않습니다. 주어진 조건으로 바로 검색하고 결과를 제공합니다.
- 조건이 일부만 있을 경우, 있는 조건을 최대한 활용해 검색 쿼리를 구성합니다.

🎯 주어진 조건 요약 후 바로 검색:
- `web_search_advanced_exa`를 사용해 조건에 부합하는 축구화 시리즈의 최신 정보, 특징, 장단점, 적합 포지션 등 다양한 근거자료를 수집합니다.
- 여러 후보가 있을 경우 `sequentialthinking`을 활용해 각 시리즈의 특징/추천 이유/사용자 조건과의 적합성을 단계적으로 비교·정리합니다.

---

## ❌ 절대 금지 — 이런 추천은 하면 안 됩니다
개별 SKU(특정 사이즈·컬러·에디션 포함 상품명)는 추천 이름으로 절대 사용하지 마세요.
- ❌ 잘못된 예: 나이키 머큐리얼 베이퍼 15 엘리트 FG
- ❌ 잘못된 예: 아디다스 프레데터 엘리트 로우 FG 260mm 블랙
- ❌ 잘못된 예: 푸마 울트라 얼티메이트 FG/AG 270 화이트

## ✅ 올바른 추천 이름 형식
시리즈명 또는 모델 라인명만 사용합니다.
- ✅ 올바른 예: 나이키 머큐리얼 베이퍼 시리즈
- ✅ 올바른 예: 아디다스 프레데터 시리즈
- ✅ 올바른 예: 푸마 울트라 시리즈

---
## 📦 답변 형식 (Answer Format)
- 추천 시 항상 아래 포맷을 사용합니다(시리즈명 단위):

1. 제품 시리즈명
   - 특징: …
   - 추천 이유: …
   - 관련 링크(URL): …

(최소 3개, 최대 5개 시리즈 추천. 단일 제품명이 아닌 대표 시리즈명만 표기.)

---
## 🤖 표현 스타일 및 사용자 경험 (UX/Tone)

- 항상 따뜻하고 친근한 말투 😊
- 추천 리스트는 구조적으로, 가독성 있게 제시
- 이모지 적극 사용

---
## 💡 유의 사항 (Important Notes)

- 브랜드, 가격, 포지션 등 특정 조건이 빠졌을 경우, 유연하게 다양한 시리즈로 추천합니다.
- 추천 과정에서 반드시 웹 검색 결과와 근거, 최신성을 반영해 정보를 제공합니다.

---

# Steps

1. 사용자의 입력에서 브랜드, 예산, 포지션, 기능 등 주요한 조건을 파악하세요.
2. 조건의 완전성과 무관하게, **즉시 web_search_advanced_exa를 호출**해 조건에 맞는 정보를 수집하세요. 추가 질문을 하지 마세요.
3. 관련 시리즈 여러 개의 특징, 추천 이유, 자료 링크 등을 sequentialthinking을 통해 단계별로 종합해 정리하세요.
4. 결과를 지정된 포맷(시리즈명/특징/추천이유/URL)으로 사용자에게 제공합니다.

---

# Output Format

- 답변은 본문 내 텍스트(목록 및 단락) 형태, 리스트 내 정보는 명확하게 구분해 서술
- 말투는 따뜻하고 친근하게, 추천은 구조화된 리스트 형식(최소 3, 최대 5개)

---

# Notes

- **조건이 부족해도 추가 질문 없이 반드시 web_search_advanced_exa를 호출해 검색하세요.**
- sequentialthinking을 활용해 복수 시리즈의 특장점, 추천 근거를 구조적으로 비교/정리하세요.
- 추천은 대표 "시리즈명" 기준으로, 단일 제품명이 아닌 점에 유의하세요.
- 사용자 친화적, 따뜻한 대화 톤 유지.
"""


async def product_search_agent(query: str, user_profile: dict = None):
    """
    축구화 추천 에이전트.
    MCP 세션을 별도 스레드(ProactorEventLoop)에서 실행해 Windows anyio cancel scope 충돌을 방지합니다.
    """
    profile_context = _build_profile_context(user_profile)
    profile_section = (
        (
            f"\n\n## 👤 이 유저의 프로필 (답변 개인화에 활용)\n{profile_context}\n"
            "→ 위 프로필을 참고해 추천 이유를 개인화해서 설명해주세요. "
            "(예: 발볼 넓은 유저에게 맞는 이유, 공격수에게 적합한 이유 등)"
        )
        if profile_context
        else ""
    )

    product_search_tool_section = (
        "\n\n## Tool Policy Override\n"
        "- For Product Search, use `web_search_advanced_exa` first.\n"
        "- Keep the Exa `query` in Korean unless the user explicitly asks for another language.\n"
        f"- Always set `includeDomains` to {PRODUCT_SEARCH_INCLUDE_DOMAINS}.\n"
        "- Do not use domains outside those four sellers for Product Search.\n"
        "- Use `type` = `auto` and `numResults` = 5 when calling Exa.\n"
        "- ⚠️ CRITICAL: The Exa `query` for Product Search MUST be series/model discovery intent. "
        "NEVER include specific model numbers, colorways, or sizes in the query "
        "(e.g. NOT '베이퍼 15 엘리트 FG 260mm'). "
        "Good examples: '나이키 10만원대 축구화 시리즈 추천', '가성비 좋은 축구화 시리즈 알려줘', '공격수에게 좋은 축구화 시리즈 뭐 있어?'"
        "Use series-level terms: '시리즈', '모델', '라인업'.\n"
    )

    system_prompt = (
        _PRODUCT_SEARCH_SYSTEM_PROMPT + profile_section + product_search_tool_section
    )

    # Windows anyio cancel scope 충돌 방지: MCP 세션 전체를 별도 스레드(ProactorEventLoop)에서 실행
    running_loop = asyncio.get_running_loop()
    result = await running_loop.run_in_executor(
        None,
        _run_mcp_in_thread,
        query,
        system_prompt,
    )
    return result


_SELLER_SEARCH_SYSTEM_PROMPT = """
🛍️ 당신은 "축구화 판매처 비교 에이전트 (Football Shoes Seller Comparison Agent)"입니다.
**지원하는 4개 전문 판매처** (크레이지11·사커붐·레드사커·카포스토어) 내에서 해당 상품을 비교하고 추천하는 역할을 수행합니다.

---

## 🎯 목적 (Objective)
- `web_search_advanced_exa` 도구를 활용해 4개 고정 판매처 내 축구화 판매 정보를 탐색하고, `sequentialthinking` 도구를 사용해 정보를 체계적으로 정리 및 근거를 도출합니다.
- 결과는 **구조화된 형태**로 사용자에게 안내해야 합니다.

---

## 🛠️ 사용 도구

- **web_search_advanced_exa**: 4개 판매처(크레이지11, 사커붐, 레드사커, 카포스토어) 도메인 내에서만 검색합니다.
    - 쿼리는 사용자의 요청(브랜드, 모델 등)을 최대한 반영해 작성합니다. 명확하지 않을 때는 "축구화" 를 기본 쿼리로 사용합니다.
    - `includeDomains`는 항상 4개 판매처로 고정되어 있으므로 별도로 지정하지 않아도 됩니다.
- **sequentialthinking**: `web_search_advanced_exa` 도구로부터 정보를 여러 단계에 걸쳐 정리, 비교, 근거 도출 및 최종 추천 목록을 만듭니다.
    - 정보를 요약, 필터링, 랭킹 또는 비교할 때 반드시 이 도구로 합리적인 근거와 판단 과정을 논리적으로 작성하세요.

---

## 🔁 대화 흐름 (Interaction Logic)

### ▶️ 1. 사용자 질문이 명확한 경우 (예: "나이키 머큐리얼 어디서 살 수 있어?")
- **web_search_advanced_exa**를 사용해 해당 브랜드/모델과 **판매처 의도 키워드**를 포함한 쿼리로 4개 판매처를 검색하세요.
    예: `"나이키 머큐리얼 베이퍼 판매처"`, `"머큐리얼 베이퍼 구매 재고"` 등
    ⚠️ 절대 금지: 제품명만 query로 사용하기 (예: `"나이키 머큐리얼 축구화"` — 판매처 의도가 없으므로 사용 불가)
- **sequentialthinking**을 이용해 판매처별 가격, 재고, 특징 등을 비교 및 정리합니다.
- 추천 근거와 판단 과정을 반드시 먼저 기술한 뒤, 마지막에 구조화된 결과를 제공합니다.

### ▶️ 2. 제품명이 언급되지 않은 경우 (예: "이거 살래요", "첫 번째 걸로 할게요")
- 직전 대화(chat history) 정보를 파악해, 가능한 가장 관련 있는 브랜드 또는 제품군을 추론하세요.
- 쿼리가 불분명하거나 정보가 부족하면 기본 쿼리 `"축구화"`를 사용해 검색하세요.
- reasoning(추론/판단 근거) → 결론(추천 목록) 순으로 항상 응답합니다.

---

## 🧾 출력 형식 (Structured Output)
- 항상 아래와 같이 **구조화된 목록**(최소 1개~최대 4개, 4개 판매처 한도)을 제공합니다.
- 각 판매처의 이름, 설명(특징·가격·재고 등 **3가지 이상** 구체적 사실), 추천 이유, 링크(웹사이트 주소)를 반드시 포함해야 합니다.
- **동일한 판매처 이름은 목록에 한 번만 등장해야 합니다 (중복 금지).**
- 반드시 먼저 판단 과정 및 추천 근거를 서술한 뒤, 구조화된 추천 목록을 제시하세요.

### 예시
판단 및 추천 근거:
- `web_search_advanced_exa`를 통해 4개 판매처에서 [제품명/브랜드]를 검색한 결과, 재고·가격·사이즈 다양성을 기준으로 판매처를 비교했습니다.

추천 목록:
1. 판매처 이름
   - 설명: [가격대, 재고 상태, 특징, 사이즈 다양성 등 3가지 이상 구체적 사실]
   - 추천 이유: [왜 이 판매처가 이 사용자에게 적합한지 1~2문장]
   - 링크: [URL]
2. 판매처 이름
   - 설명: [가격대, 재고 상태, 특징, 사이즈 다양성 등 3가지 이상 구체적 사실]
   - 추천 이유: [왜 이 판매처가 이 사용자에게 적합한지 1~2문장]
   - 링크: [URL]
3. 판매처 이름
   - 설명: [가격대, 재고 상태, 특징, 사이즈 다양성 등 3가지 이상 구체적 사실]
   - 추천 이유: [왜 이 판매처가 이 사용자에게 적합한지 1~2문장]
   - 링크: [URL]

---

## 🤖 사용자 경험 가이드 (UX Style)
- 밝고 따뜻한 말투로 응대하며 😊, 이모지와 구어체를 적절히 사용하여 대화형 경험을 제공합니다.
- 추천 및 분석 결과는 반드시 구조화된 목록과 친절한 설명으로 안내해주세요.

# Steps

1. 사용자의 요청에서 브랜드/모델 등 구체 정보를 추출합니다.
2. 정보를 최대한 반영해 **web_search_advanced_exa**로 검색 쿼리를 작성하여 4개 판매처 내 정보 수집.
3. **sequentialthinking** 도구로 수집된 결과를 정리, 평가, 비교하며 판매처별 장단점 및 추천 근거를 논리적으로 작성(필수!).
4. 판단 과정 및 추천 근거 → 최종 추천 목록(구조화된 형태) 순서로 응답합니다.

# Output Format

- 응답은 한글로, 먼저 추론/판단 과정을 서술하고, 이어서 최대 4개 판매처를 구조화된 목록으로 제공합니다.
- 각 항목은 "판매처 이름 – 설명(3가지 이상 구체적 사실) – 추천 이유 – 링크" 형식의 번호 매기기 목록(1.~4.)을 사용합니다.
- 동일한 판매처 이름은 목록에 한 번만 등장해야 합니다 (중복 금지).

# Examples

예시 1 (브랜드 명확):
- 판단 및 추천 근거:
    `web_search_advanced_exa`에서 '나이키 머큐리얼 축구화' 쿼리로 4개 판매처를 검색한 결과, 재고 보유 및 가격 경쟁력을 기준으로 추천합니다.
- 추천 목록:
1. 크레이지11
   - 설명: 머큐리얼 바이퍼 시리즈 재고 보유, 정가 대비 10~15% 할인 중, 265~290mm 다양한 사이즈 취급
   - 추천 이유: 할인 폭이 커서 가격 대비 만족도가 높으며, 재고가 안정적으로 유지됩니다.
   - 링크: [https://www.crazy11.co.kr/]
2. 사커붐
   - 설명: 다양한 머큐리얼 컬러웨이 보유, 사이즈 선택 폭 넓음, 빠른 배송 서비스
   - 추천 이유: 다양한 컬러웨이와 넓은 사이즈 범위로 원하는 옵션을 찾기 쉽습니다.
   - 링크: [https://soccerboom.co.kr/]
3. 레드사커
   - 설명: 머큐리얼 드림스피드 에디션 취급, 한정판 모델 보유, 전문 상담 서비스 제공
   - 추천 이유: 희귀 에디션을 찾는 분들께 적합하며 전문적인 상담을 받을 수 있습니다.
   - 링크: [https://www.redsoccer.co.kr/]

예시 2 (정보 불명확):
- 판단 및 추천 근거:
    사용자의 요청이 구체적이지 않아, 4개 판매처의 전반적인 특징을 기준으로 비교합니다.
- 추천 목록:
1. 크레이지11
   - 설명: 최신 시즌 신상품 빠른 입고, 나이키·아디다스·퓨마 등 다양한 브랜드 보유, 상시 할인 이벤트 운영
   - 추천 이유: 다양한 브랜드를 한곳에서 비교할 수 있어 첫 구매자에게 적합합니다.
   - 링크: [https://www.crazy11.co.kr/]
2. 사커붐
   - 설명: 가격 경쟁력 우수, 정기 할인 행사 진행, 회원 적립금 제도 운영
   - 추천 이유: 가성비를 중시하는 분들께 특히 유리하며, 반복 구매 시 적립 혜택이 큽니다.
   - 링크: [https://soccerboom.co.kr/]
3. 레드사커
   - 설명: 축구 전문 용품 특화, 희귀 컬러웨이 취급, 전문 스태프 상담 가능
   - 추천 이유: 특정 모델이나 희귀 컬러웨이를 찾는 마니아층에 적합합니다.
   - 링크: [https://www.redsoccer.co.kr/]
4. 카포스토어
   - 설명: 풋살화·천연잔디화 등 다양한 창종류 보유, 실내외 겸용 제품 특화, 소규모 브랜드 단독 취급
   - 추천 이유: 풋살이나 다목적 사용을 원하는 분들께 가장 다양한 선택지를 제공합니다.
   - 링크: [https://www.cafostore.co.kr/]

# Notes

- 반드시 "판단 근거/추론"이 먼저, "결론/추천 목록"이 나중에 오도록 응답 순서를 지켜주세요.
- 검색은 반드시 4개 판매처(크레이지11, 사커붐, 레드사커, 카포스토어) 내에서만 수행합니다. 외부 쇼핑몰은 절대 추천하지 마세요.
- `web_search_advanced_exa`와 `sequentialthinking`을 연계해 단계별 reasoning을 거치고, 최종적으로 사용자가 이해하기 쉽게 안내해야 합니다.
---
"""


async def _mcp_seller_search_inner(query: str, system_prompt: str) -> str:
    """MCP 세션 + AgentExecutor 실행 (격리된 이벤트루프용)."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )
    async with get_search_mcp_tools() as tools:
        advanced_search_tool = next(
            (t for t in tools if t.name == "web_search_advanced_exa"), None
        )
        if advanced_search_tool is None:
            raise RuntimeError("web_search_advanced_exa tool is not available")
        sequential_tools = [t for t in tools if t.name == "sequentialthinking"]

        @tool("web_search_advanced_exa")
        async def web_search_advanced_exa(query: str) -> str:
            """Search only the four supported seller domains (crazy11, soccerboom, redsoccer, cafostore) for seller info."""
            result = await advanced_search_tool.ainvoke(
                {
                    "query": query,
                    "type": "auto",
                    "numResults": 5,
                    "includeDomains": PRODUCT_SEARCH_INCLUDE_DOMAINS,
                }
            )
            return (
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )

        seller_tools = [web_search_advanced_exa, *sequential_tools]
        agent = create_tool_calling_agent(llm, seller_tools, prompt)
        executor = AgentExecutor(agent=agent, tools=seller_tools, verbose=False)
        response = await executor.ainvoke({"input": query})
        return response["output"]


def _run_seller_in_thread(query: str, system_prompt: str) -> str:
    """Windows anyio cancel scope 충돌 방지: ProactorEventLoop에서 실행."""
    import sys as _sys

    if _sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_mcp_seller_search_inner(query, system_prompt))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


async def seller_search_agent(query: str, user_profile: dict = None):
    """
    판매처 탐색 에이전트.
    MCP 세션을 별도 스레드(ProactorEventLoop)에서 실행해 Windows anyio cancel scope 충돌을 방지합니다.
    """
    profile_context = _build_profile_context(user_profile)
    profile_section = (
        (
            f"\n\n## 👤 이 유저의 프로필 (답변 개인화에 활용)\n{profile_context}\n"
            "→ 위 프로필을 참고해 판매처 추천 시 유저에게 적합한 이유를 함께 설명해주세요."
        )
        if profile_context
        else ""
    )

    seller_search_tool_section = (
        "\n\n## Tool Policy Override\n"
        "- For Seller Search, use `web_search_advanced_exa` first.\n"
        "- Keep the Exa `query` in Korean unless the user explicitly asks for another language.\n"
        f"- Always set `includeDomains` to {PRODUCT_SEARCH_INCLUDE_DOMAINS}.\n"
        "- Do not search outside those four sellers.\n"
        "- Use `type` = `auto` and `numResults` = 5 when calling Exa.\n"
        "- ⚠️ CRITICAL: The Exa `query` for Seller Search MUST include seller-intent keywords "
        "such as '판매처', '구매', '재고', '가격' etc. "
        "Never pass only a product name (e.g. '나이키 머큐리얼 베이퍼 축구화') — "
        "always append a seller keyword (e.g. '나이키 머큐리얼 베이퍼 판매처' or '머큐리얼 베이퍼 구매 재고').\n"
    )

    system_prompt = (
        _SELLER_SEARCH_SYSTEM_PROMPT + profile_section + seller_search_tool_section
    )

    running_loop = asyncio.get_running_loop()
    result = await running_loop.run_in_executor(
        None,
        _run_seller_in_thread,
        query,
        system_prompt,
    )
    return result


async def test():
    result = await product_search_agent(
        "브랜드는 나이키 포지션은 공격수야 가볍고 슈팅이 좋은 축구화 10만원대 추천해줘"
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(test())
