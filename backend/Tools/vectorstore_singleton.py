"""
vectorstore_singleton.py
========================
crawl_and_index 와 rag_search 가 공유하는 단일 Chroma 인스턴스.

이 모듈을 import하면 항상 동일한 vectorstore 객체를 반환하므로
import 경로(Tools.rag_search vs rag_search)에 따른 인스턴스 분리 문제가 발생하지 않는다.

`persist_directory` 가 지정되어 있어 `add_documents` 호출 시 자동으로 디스크에 저장됨.
서버 재시작 후에도 인덱스가 살아남아 동일 상품을 재크롤·재임베딩할 필요가 없다.
"""

import os

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

load_dotenv()

# 기본 경로: backend/.chroma_store/. CHROMA_PERSIST_DIR 환경 변수로 오버라이드 가능.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHROMA_PERSIST_DIR = os.path.abspath(
    os.getenv("CHROMA_PERSIST_DIR", os.path.join(_BACKEND_DIR, ".chroma_store"))
)
os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)

_embedding = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = Chroma(
    embedding_function=_embedding,
    persist_directory=CHROMA_PERSIST_DIR,
    collection_name="soccer_shoes",
)
