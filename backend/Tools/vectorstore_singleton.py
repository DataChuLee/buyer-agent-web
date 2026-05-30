"""
vectorstore_singleton.py
========================
crawl_and_index 와 rag_search 가 공유하는 단일 Chroma 인스턴스.

이 모듈을 import하면 항상 동일한 vectorstore 객체를 반환하므로
import 경로(Tools.rag_search vs rag_search)에 따른 인스턴스 분리 문제가 발생하지 않는다.
"""

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

load_dotenv()

_embedding = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = Chroma(embedding_function=_embedding)
