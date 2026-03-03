from Crawling.crawling import (
    crazy11_info,
    redsoccer_info,
    soccerboom_info,
    cafo_info,
    crawl_info,
)
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.prompts import ChatPromptTemplate
from langchain.tools import tool
from kiwipiepy import Kiwi
from kiwipiepy.utils import Stopwords
from langchain_core.documents import Document
from langchain_classic.chains.query_constructor.schema import AttributeInfo
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_classic.retrievers.self_query.base import SelfQueryRetriever
from langchain_core.output_parsers import JsonOutputParser
from langchain_teddynote.tools.tavily import TavilySearch
from langchain_community.query_constructors.chroma import ChromaTranslator
from selenium.webdriver.support import expected_conditions as EC
from pydantic import BaseModel, Field
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from typing import List, Dict, Union, Optional
import hashlib
import re

# import lark
import os

# env 파일에서 OPENAI API KEY 들여옴
load_dotenv()

embedding = OpenAIEmbeddings(
    model="text-embedding-3-large", api_key=os.environ["OPENAI_API_KEY"]
)


# kiwi
kiwi = None
stopwords = None

if Kiwi is not None and Stopwords is not None:
    try:
        kiwi = Kiwi(typos="basic", model_type="sbg")
    except Exception:
        try:
            kiwi = Kiwi(typos="basic")
        except Exception:
            kiwi = None

    if kiwi is not None:
        try:
            stopwords = Stopwords()
            stopwords.remove(("사람", "NNG"))
        except Exception:
            stopwords = None


def kiwi_tokenize(text):
    text = "".join(text) if isinstance(text, (list, tuple)) else str(text)

    if kiwi is None:
        return re.findall(r"[0-9A-Za-z가-힣]+", text.lower())

    result = kiwi.tokenize(text, stopwords=stopwords, normalize_coda=True)
    N_list = [i.form.lower() for i in result if i.tag in ["NNG", "NNP", "SL", "SN"]]
    return N_list


# 상품 정보 모델
class Topic(BaseModel):
    page_content: str = Field(description="축구화 제품에 대한 설명")
    metadata: dict = Field(
        description="seller, product_name, age_group, ground_type, product_price, product_images로 구성된 메타데이터"
    )


# product_price 정규화 함수
## 종종 가격이 int로 출력되어야 하는데, 문자열로 되어 있는 경우가 발생
def normalize_price_and_size(summaries):
    """
    제품 가격(product_price)과 사이즈(product_size)를 정규화하는 함수.
    - 가격은 숫자만 추출하여 int형으로 변환
    - 사이즈는 여러 값(콤마, 대괄호, mm 단위 포함)에서도 숫자만 추출해 정렬된 문자열로 변환 ("250,255,260")
    """
    for doc in summaries:
        metadata = doc.get("metadata", {})

        # 1️⃣ 가격 정규화
        price = metadata.get("product_price")
        if isinstance(price, str):
            digits = re.sub(r"[^\d]", "", price)
            metadata["product_price"] = int(digits) if digits else None
        elif isinstance(price, (float, int)):
            metadata["product_price"] = int(price)
        else:
            metadata["product_price"] = None

        # 2️⃣ 사이즈 정규화 (복수 사이즈 대응)
        size = metadata.get("product_size")
        sizes = None

        if isinstance(size, str):
            # 문자열에서 모든 숫자 추출
            numbers = re.findall(r"\d{2,3}", size)
            if numbers:
                sizes = sorted(list(set(int(n) for n in numbers)))
        elif isinstance(size, (list, tuple)):
            numbers = [
                int(re.sub(r"[^\d]", "", str(s)))
                for s in size
                if re.sub(r"[^\d]", "", str(s))
            ]
            if numbers:
                sizes = sorted(list(set(numbers)))

        # ✅ 리스트를 문자열로 직렬화 ("250,255,260") 형태로 저장
        if sizes:
            metadata["product_size"] = ",".join(map(str, sizes))
        else:
            metadata["product_size"] = None

    return summaries


# 🔑 문서마다 고유 ID를 생성
def make_id(meta):
    # URL이나 (판매처+제품명) 등 결정적 키를 사용
    key = (
        meta.get("product_url")
        or f"{meta.get('seller','')}_{meta.get('product_name','')}"
    )
    return hashlib.sha1(key.encode()).hexdigest()


# Tools 정의
@tool
def product_recommend(query: str) -> str:
    """구매자가 축구화 제품에 대한 추천 및 정보를 원할 시 이에 대한 정보를 제공하는 도구입니다."""
    tavily_tool = TavilySearch(
        include_domains=["naver.com", "youtube.com"],
        exclude_domains=["spam.com", "ads.com"],
    )
    result = tavily_tool.search(
        query=query,  # 검색 쿼리
        topic="general",  # 일반 주제
        max_results=5,  # 최대 5개 결과
        include_answer=False,  # 답변 포함
        include_raw_content=False,  # 원본 콘텐츠 포함
        # format_output=True,  # 결과 포맷팅
    )
    return result


@tool
def site_search(query: str) -> str:
    """구매자가 원하는 제품을 팔고 있는 축구화 전문 온라인 판매점에 대한 정보를 제공할 때 사용하는 도구입니다."""
    tavily_tool = TavilySearch(
        include_domains=["naver.com", "youtube.com"],
        exclude_domains=["spam.com", "ads.com"],
    )
    result = tavily_tool.search(
        query=query,  # 검색 쿼리
        topic="general",  # 일반 주제
        max_results=5,  # 최대 5개 결과
        include_answer=False,  # 답변 포함
        include_raw_content=False,  # 원본 콘텐츠 포함
        # format_output=True,  # 결과 포맷팅
    )
    return result


@tool
def crawl_info_parallel(
    site_keywords: List[str], product_keyword: str, min_price: int, max_price: int
) -> Dict[str, List[Dict]]:
    """
    여러 축구화 판매 사이트에서 병렬로 제품 정보를 크롤링하는 도구입니다.

    Args:
        site_keywords (List[str]): 판매자 사이트 리스트
        product_keyword (str): 검색할 제품 키워드
        min_price (int): 하한가
        max_price (int): 상한가

    Returns:
        Dict[str, List[Dict]]: 사이트별 크롤링된 결과 딕셔너리
    """
    results = {}

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_site = {}
        for site in site_keywords:
            fut = executor.submit(
                crawl_info, site, product_keyword, min_price, max_price
            )
            future_to_site[fut] = site

        for future in as_completed(future_to_site):
            site = future_to_site[future]
            try:
                data = future.result()
                results[site] = data
            except Exception as e:
                results[site] = [{"error": f"❌ 오류: {str(e)}"}]
    return results


@tool
# @tool
## 이 놈이 크롤링한 데이터를 정리 및 요약해주기 때문에 이놈의 역할이 중요함
def json_summary(results: Union[List[Dict], Dict[str, List[Dict]]]):
    """
    크롤링된 제품 데이터를 구조화된 JSON 형태로 요약하는 도구입니다.

    Args:
        results: crawl_info_parallel 도구의 결과값 (Dict[str, List[Dict]] 또는 List[Dict])

    Returns:
        List[Dict]: 각 제품의 요약 정보 리스트. self_query_rag 도구의 summaries 매개변수로 사용됩니다.
    """
    # 1. 결과 형태 정규화: Dict[str, List[Dict]] → List[Dict]
    if isinstance(results, dict):
        combined_results = []
        for site, product_list in results.items():
            for product in product_list:
                if isinstance(product, dict):
                    product["site"] = site  # 판매처 정보 명시
                    # product["seller"] = site.replace(" ","")
                    combined_results.append(product)
        results = combined_results  # flatten된 리스트

    # 2. 요약용 파서 및 프롬프트 설정
    parser = JsonOutputParser(pydantic_object=Topic)
    summary_prompt = ChatPromptTemplate.from_template(
        """
        당신은 제품 요약 전문가입니다. 아래에 주어진 크롤링된 제품 정보(results)를 다음의 규칙에 따라 각각 요약해 주세요.
        ─────────────────────────────
        📌 요약 규칙 (RULES)

        1. 여러 개의 제품이 포함된 경우라도, **각 제품마다 개별적으로 요약**해야 합니다.

        2. `page_content`에는 다음 정보를 자연스러운 문장으로 기술합니다:
        - 제품에 대한 구체적인 설명 (가격, 사이즈 포함)
            - 가격에 대한 설명은 할인가만 기술하세요.
            - results에 구체적인 설명이 없다면 알고 있는 지식으로 작성하세요. 
        - 색깔, 소재, 사이즈, 주요 특징 등 구체적인 스펙 정보가 있다면 함께 포함

        3. 각 제품의 `metadata`에는 반드시 아래 항목들을 포함해야 합니다:
        - `seller`: 사이트 이름 (예: 크레이지 11, 사커붐, 레드사커 등)
        - `product_name`: 제품 이름
        - `product_price`: 가격에 대한 설명은 반드시 **할인가(할인 적용된 실제 판매가)** 기준으로 기술하세요. 정가(표시가)는 언급하지 마세요. 무조건 int형태로 기술하세요.
        - `product_size`: 제품의 사이즈를 나타냅니다. (품절된 사이즈는 언급하지 마세요.)
        - `product_category`: 제품 카테고리를 나타냅니다. (예: FG, AG, HG -> `축구화`, TF -> `풋살화`)
        - `age_group`: 제품을 사용할 수 있는 연령대를 나타냅니다. (예: '유소년용', '성인용')
        - `ground_type`: 축구화가 사용되는 지면의 종류입니다.
            - 예: (FG, AG, SG, HG, TF)
        - `product_url`: 제품 URL (리스트가 아닌 문자열로 변환)
        - `product_images`: 제품 이미지 URL (리스트가 아닌 문자열로 변환)
            - 예시: 'product_images': 'https://www.crazy11.co.kr/shopimages/'

        4. 출력은 **유효한 JSON 형식**으로 반환해야 합니다.
        ⚠️ 설명이나 부가 텍스트는 포함하지 말고, JSON 객체들의 리스트만 출력하세요.

        ─────────────────────────────
        # 입력 데이터 (Input):
        {information}

        # 출력 형식 (Output Format):
        {format_instructions}
        """
    ).partial(format_instructions=parser.get_format_instructions())

    # 3. 요약 실행
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    chain = summary_prompt | model | parser

    # 4. 각 제품에 대해 {"information": 제품정보} 형태로 변환
    batch_inputs = [{"information": p} for p in results]

    # 5. LangChain batch 실행 (병렬 처리)
    summaries = chain.batch(batch_inputs, config={"max_concurrency": 20})

    return summaries


@tool
def self_query_rag(summaries: Optional[List[Dict]], user_query: str):
    """
    구조화된 요약 데이터(summaries)를 기반으로 사용자 질문(user_query)에 부합하는 축구화 제품을 필터링하고 비교표로 제시합니다.
    summaries가 제공되지 않은 경우, 기존 RAG 상태(persist_directory)를 불러와 검색만 수행합니다.

    Args:
        summaries (List[Dict]): json_summary 도구의 결과값입니다. 반드시 json_summary를 먼저 실행한 후 그 결과를 전달해야 합니다.
            documents는 다음과 같은 형식입니다. 반드시 아래의 형식을 따라야 합니다.
            [{'page_content': '~~~~',
                'metadata': {'seller': '~~~~',
                'product_name': '~~~~',
                'product_price': '~~~~',
                'product_size': '~~~~'
                'product_category': '~~~~',
                'age_group': '~~~~',
                'ground_type': '~~~~',
                'product_url': '~~~~',
                'product_images': '~~~~'}]
        user_query (str): 사용자의 질문 또는 검색 조건

    Returns:
        str: 마크다운 형태의 제품 비교표
    """
    print(f"�� DEBUG: self_query_rag 호출됨")
    print(f"�� DEBUG: summaries 타입: {type(summaries)}")
    print(
        f"�� DEBUG: summaries 길이: {len(summaries) if isinstance(summaries, list) else 'N/A'}"
    )
    print(f"�� DEBUG: user_query: {user_query}")

    model = ChatOpenAI(model="gpt-4o", temperature=0)
    embedding = OpenAIEmbeddings(model="text-embedding-3-small")

    # 1️⃣ 데이터 정규화
    summaries = normalize_price_and_size(summaries)
    print(f"📦 정규화된 데이터 수: {len(summaries)}")

    # 2️⃣ Document 변환
    docs = [
        Document(
            page_content=item["page_content"],
            metadata={
                "seller": item["metadata"].get("seller", "미상"),
                "product_name": item["metadata"].get("product_name", "정보없음"),
                "product_price": item["metadata"].get("product_price", 0),
                "product_size": item["metadata"].get("product_size", 0),
                "product_category": item["metadata"].get(
                    "product_category", "정보없음"
                ),
                "age_group": item["metadata"].get("age_group", "정보없음"),
                "ground_type": item["metadata"].get("ground_type", "정보없음"),
                "product_url": item["metadata"].get("product_url", ""),
                "product_images": item["metadata"].get("product_images", ""),
            },
        )
        for item in summaries
    ]

    # 3️⃣ ID 부여
    ids = [make_id(d.metadata) for d in docs]

    # 4️⃣ 벡터스토어 생성 (기존 컬렉션 초기화 포함)
    try:
        vectorstore = Chroma.from_documents(
            documents=docs, embedding=embedding, ids=ids
        )

        # 기존 데이터 모두 삭제 후 새로 추가
        all_ids = vectorstore._collection.get()["ids"]
        for i in range(0, len(all_ids), 500):
            batch = all_ids[i : i + 500]
            vectorstore._collection.delete(ids=batch)
        print("🧹 컬렉션 초기화 완료")

        vectorstore.add_documents(docs, ids=ids)
        print(f"✅ 벡터스토어에 {len(docs)}개 문서 삽입 완료")

    except Exception as e:
        return f"❌ 벡터스토어 생성 중 오류 발생: {e}"

    # 5️⃣ 메타데이터 필드 정보 정의
    metadata_info = [
        AttributeInfo(
            name="seller",
            description="제품을 판매하고 있는 판매자명 혹은 사이트명 (예: 레드사커, 사커붐, 카포스토어)",
            type="string",
        ),
        AttributeInfo(name="product_name", description="제품 이름", type="string"),
        AttributeInfo(
            name="product_price",
            description="제품의 실제 판매가(할인가) (예: 10만원대 -> 100000 ~ 200000 / 15만원 이상 -> 150000 ~ 200000 등)",
            type="integer",
        ),
        AttributeInfo(
            name="product_category",
            description="The category of the football product. One of ['축구화', '풋살화']",
            type="string",
        ),
        AttributeInfo(
            name="age_group",
            description="제품의 사용 연령대. '성인용'은 일반 성인 사이즈 제품, '유소년용'은 주니어/어린이용 사이즈 제품을 의미",
            type="string",
        ),
        AttributeInfo(
            name="ground_type",
            description="축구화가 사용되는 지면의 종류 (예: FG, AG, SG, HG, TF)",
            type="string",
        ),
    ]

    content = """
    여러 판매자로부터 수집된 축구화 제품 데이터입니다.
    각 문서에는 다음과 같은 메타데이터 필드를 가집니다:

    - seller: 판매처명 (해당 제품을 판매하고 있는 판매자 및 사이트 이름)
    - product_name: 제품명 (제품 이름 / 예: 나이키 머큐리얼 베이퍼 15)
    - product_price: 판매 가격 (제품의 가격 / 숫자, 원 단위)
    - product_category: 제품 카테고리 (축구화, 풋살화)
    - age_group: 연령대 (예: 유소년용 / 성인용)
    - ground_type: 사용 지면 (TF, HG, AG, SG, FG)
    """

    # 6️⃣ SelfQueryRetriever 설정
    retriever = SelfQueryRetriever.from_llm(
        llm=model,
        vectorstore=vectorstore,
        document_contents=content,
        metadata_field_info=metadata_info,
        structured_query_translator=ChromaTranslator(),
        enable_limit=True,
    )

    # 7️⃣ 최종 질의 및 응답 생성
    final_prompt = PromptTemplate.from_template(
        """
        You are a product comparison assistant specializing in soccer shoes.
        Your role is to answer user queries by analyzing structured product data retrieved from multiple online sources.  
        Each product is represented as a structured object with the following fields:
        ---

        ## Product Metadata Fields

        - `seller` (string): 제품을 판매하는 판매처명 또는 사이트명
        - `product_name` (string): 제품명
        - `product_price` (integer): 제품 판매가 (₩)
        - `product_size` (integer): 제품 사이즈 
        - `product_category` (string): 제품 카테고리 (예: "축구화", "풋살화")
        - `age_group` (string): 사용 연령대 (예: "유소년용", "성인용")
        - `ground_type` (string): 지면 종류 (예: "FG", "AG", "SG", "HG", "TF")
        - `product_url` (string): 제품 상세 URL 문자열
        - `product_images` (string): 제품 이미지의 URL 문자열 (단일 이미지)
        ---

        ## Objective

        Your task is to extract up to **3 soccer shoes**:

        - **product_name**
        - **product_price**
        - **product_category**
        - **age_group**
        - **ground_type**
        - **기능 키워드** (예: 경량성, 내구성, 접지력, 슈팅 성능 등)
        - **카테고리**: `age_group`과 `ground_type` 조합으로 판단
            - 예: 유소년용 풋살화 → age_group = "유소년용" & ground_type = "TF"
        - 제품이 **3개 이하인 경우**, **가능한 모든 관련 제품을 포함**하세요.

        Use only the information provided in the context variable.
        ---

        ## Output Instructions

        - Return a **Markdown table**
        - 각 항목에 포함해야 할 정보:
        - `판매처 (seller)`
        - `상품명 (product_name)`
        - `가격 (product_price)`
        - `사이즈` (product_size)
        - `주요 특징 (features)`:
            - 기능 키워드 기반으로 최소 3가지 이상 구체적 특징 작성
            - `ground_type` 값을 해석하여 **어떤 지면에 적합한지 설명 포함**
            (예: ✔ TF 스터드 (인조잔디용), ✔ FG 스터드 (천연잔디용))
            - `age_group`을 반영해 **사용 연령대** 명시
        - `링크`: `product_url` 필드의 **URL 문자열을 그대로** 사용하여 마크다운 출력 (링크에 jpg, png이 제외된 링크)
        - `이미지`: `product_images` 필드의 **URL 문자열을 그대로** 사용하여 마크다운 이미지 출력 (링크에 jpg, png이 포함된 링크) 
        ---

        ## User Question
        {question}

        ---
        ## Product Context
        {context}

        ---
        ## Output Format Example

        **✅ 축구화 제품 비교표**

        | 판매처     | 상품명                              | 가격      | 주요 특징 | 이미지 | 링크 |
        |------------|-------------------------------------|-----------|---------------------------------------------------|--------|---------------------------------------------------|
        | 크레이지11 | 나이키 머큐리얼 베이퍼 16 프로 TF | ₩89,000 | ✔ 경량성, ✔ TF 스터드 (인조잔디용), ✔ 유소년용, ✔ 내구성 강화| ![이미지](https://example.com/image1.jpg) | [🔗 제품 상세보기](https://example.com/url1) |
        | 사커붐     | 머큐리얼 베이퍼 16 KM FG | ₩113,900 | ✔ 스피드 향상, ✔ FG 스터드 (천연잔디용), ✔ 성인용, ✔ 슈팅 퍼포먼스 향상 | ![이미지](https://example.com/image2.jpg)|[🔗 제품 상세보기](https://example.com/url2) |
        | 레드사커   | 나이키 줌 머큐리얼 베이퍼 16 AG | ₩152,900 | ✔ 스피드 향상, ✔ FG 스터드 (천연잔디용), ✔ 성인용, ✔ 슈팅 퍼포먼스 향상 | ![이미지](https://example.com/image3.jpg)|[🔗 제품 상세보기](https://example.com/url3) |        
        ---

        ## Restrictions
        - 절대 제품 정보를 임의로 생성하지 마세요.
        - 단, 만약 정말로 검색 결과가 없을 경우에만 아래 문장을 출력하세요. 그렇지 않다면 절대로 아래 문장을 포함하지 마세요.
            - "요청하신 조건에 부합하는 축구화 정보를 찾을 수 없습니다."
        """
    )

    try:
        final_chain = (
            {"question": RunnablePassthrough(), "context": retriever}
            | final_prompt
            | model
            | StrOutputParser()
        )
        response = final_chain.invoke(user_query)
        print("✅ 질의 완료")
        return response

    except Exception as e:
        return f"❌ 질의 실행 중 오류 발생: {str(e)}"
