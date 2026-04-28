import os
import json
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAISS_PATH = os.path.join(BASE_DIR, "data", "faiss_store")
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"

_embeddings = None
_store = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBED_MODEL,
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings


def _get_store():
    global _store
    if _store is None and os.path.exists(FAISS_PATH):
        _store = FAISS.load_local(
            FAISS_PATH, _get_embeddings(), allow_dangerous_deserialization=True
        )
    return _store


def add_session(jd: str, role_name: str, questions: list):
    global _store
    doc = Document(
        page_content=jd,
        metadata={
            "role_name": role_name,
            "questions": json.dumps(questions, ensure_ascii=False),
        },
    )
    emb = _get_embeddings()
    if _store is None and os.path.exists(FAISS_PATH):
        _store = FAISS.load_local(FAISS_PATH, emb, allow_dangerous_deserialization=True)

    if _store is None:
        _store = FAISS.from_documents([doc], emb)
    else:
        _store.add_documents([doc])

    os.makedirs(FAISS_PATH, exist_ok=True)
    _store.save_local(FAISS_PATH)


def retrieve_examples(jd: str, k: int = 3) -> list:
    import time
    store = _get_store()
    if store is None:
        return []
    t0 = time.time()
    docs = store.similarity_search(jd, k=k)
    print(f"[RAG] FAISS 检索耗时: {(time.time()-t0)*1000:.1f}ms，命中 {len(docs)} 条")
    return [
        {
            "role_name": d.metadata.get("role_name", ""),
            "questions": json.loads(d.metadata.get("questions", "[]")),
        }
        for d in docs
    ]
