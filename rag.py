from uuid import uuid4
from dotenv import load_dotenv
from pathlib import Path
from typing import List, Tuple, Optional
import os

import trafilatura

# LangChain
from langchain.chains import RetrievalQAWithSourcesChain, RetrievalQA
from langchain.document_loaders import PyPDFLoader
from langchain_community.document_loaders import UnstructuredURLLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_groq import ChatGroq
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain.prompts import PromptTemplate
from langchain.schema import Document

load_dotenv()

# ---------- Config ----------
CHUNK_SIZE = 1000
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
VECTORSTORE_DIR = Path(__file__).parent / "resources" / "vectorstore_healthcare"
COLLECTION_NAME = "healthcare_docs"

llm: Optional[ChatGroq] = None
vector_store: Optional[Chroma] = None

# ---------- Init ----------
def initialize_components():
    global llm, vector_store

    if llm is None:
        llm = ChatGroq(
            model=os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.0")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024"))
        )

    if vector_store is None:
        ef = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"trust_remote_code": True}
        )
        VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)

        vector_store = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=ef,
            # persist_directory=str(VECTORSTORE_DIR)     #removed for Streamlit-Cloud safe environments
        )

# ---------- URL Loader (Trafilatura) ----------
def _load_url_trafilatura(url: str) -> Optional[Document]:
    try:
        downloaded = trafilatura.fetch_url(url, timeout=30)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded)
        if not text:
            return None
        return Document(page_content=text, metadata={"source": url})
    except Exception:
        return None

# ---------- PDF Loader ----------
def _load_pdf(path_or_bytes) -> List[Document]:
    try:
        loader = PyPDFLoader(path_or_bytes)
        return loader.load()
    except Exception:
        return []

# Fallback URL loader
def _fallback_unstructured(urls: List[str]) -> List[Document]:
    try:
        loader = UnstructuredURLLoader(urls=urls)
        return loader.load()
    except Exception:
        return []

# ---------- Process URLs + PDFs ----------
def process_urls_and_pdfs(urls: List[str], pdf_paths: List[str]):
    initialize_components()
    yield "Initialized components."

    yield "Resetting vectorstore..."
    try:
        vector_store.reset_collection()
    except Exception:
        pass

    docs: List[Document] = []

    # URLs via Trafilatura
    yield f"Processing {len(urls)} URL(s) with Trafilatura..."
    for u in urls:
        d = _load_url_trafilatura(u)
        if d:
            docs.append(d)

    # Fallback loader for failed URLs
    failed_urls = [u for u in urls if not any(doc.metadata.get("source") == u for doc in docs)]
    if failed_urls:
        yield f"Fallback loader for {len(failed_urls)} URLs..."
        fallback_docs = _fallback_unstructured(failed_urls)
        for d in fallback_docs:
            if not d.metadata.get("source"):
                d.metadata["source"] = "unknown_url"
            docs.append(d)

    # PDFs
    yield f"Processing {len(pdf_paths)} PDF(s)..."
    for p in pdf_paths:
        pdf_docs = _load_pdf(p)
        for d in pdf_docs:
            if not d.metadata.get("source"):
                d.metadata["source"] = p
            docs.append(d)

    if not docs:
        yield "⚠️ No documents loaded."
        return

    # Chunking
    yield "Splitting into chunks..."
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ".", " "],
        chunk_size=CHUNK_SIZE
    )
    chunks = splitter.split_documents(docs)

    # Vectorstore
    yield f"Embedding {len(chunks)} chunks..."
    ids = [str(uuid4()) for _ in chunks]
    vector_store.add_documents(chunks, ids=ids)

    yield "Done."

# ---------- Helpers ----------
def _ensure_init():
    if vector_store is None or llm is None:
        raise RuntimeError("⚠ Please process sources before querying.")

def retrieve_docs(query: str, k=4) -> List[Document]:
    _ensure_init()
    retriever = vector_store.as_retriever(search_kwargs={"k": k})
    return retriever.get_relevant_documents(query)

# ---------- Safety ----------
def is_medical_advice(query: str) -> bool:
    q = query.lower()
    triggers = [
        "diagnos", "prescribe", "treat", "treatment plan",
        "should i", "am i", "do i have", "what medicine", "how to cure"
    ]
    return any(t in q for t in triggers)

# ---------- Prompts ----------
HEALTHCARE_QA_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template=(
        "You are a healthcare research assistant. Use ONLY the provided context to answer. "
        "Do NOT provide medical advice. Include short evidence quotes + source URLs.\n\n"
        "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    )
)

HEALTHCARE_SUMMARY_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template=(
        "You are a clinical summarizer. Summarize the evidence without providing medical advice.\n\n"
        "Context:\n{context}\n\nInstruction: {question}\n\nSummary:"
    )
)

HEALTHCARE_EXTRACT_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template=(
        "You are a data extractor. Extract only the requested information in structured bullet points. "
        "Do not provide medical advice.\n\nContext:\n{context}\n\nInstruction: {question}\n\nOutput:"
    )
)

# ---------- API functions ----------
def generate_qa(query: str):
    if is_medical_advice(query):
        return ("⚠️ I cannot provide medical diagnoses or treatment.", "", [])

    _ensure_init()

    chain = RetrievalQAWithSourcesChain.from_llm(
        llm=llm,
        retriever=vector_store.as_retriever(),
    )

    result = chain.invoke({"question": query}, return_only_outputs=True)
    answer = result.get("answer", "")
    sources = result.get("sources", "")

    docs = retrieve_docs(query, k=4)
    snippets = [(d.metadata.get("source", "unknown"), d.page_content[:400].replace("\n"," ")) for d in docs]

    return answer, sources, snippets

def generate_summary(query: str):
    if is_medical_advice(query):
        return ("⚠️ Summary cannot include medical advice.", [])

    _ensure_init()
    retriever = vector_store.as_retriever(search_kwargs={"k": 6})

    chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        chain_type="stuff",
        chain_type_kwargs={"prompt": HEALTHCARE_SUMMARY_PROMPT}
    )

    result = chain.invoke({"query": query})
    summary = result.get("result", "") or ""

    docs = retrieve_docs(query, k=4)
    snippets = [(d.metadata.get("source","unknown"), d.page_content[:400].replace("\n"," ")) for d in docs]
    return summary, snippets

def generate_extract(query: str):
    if is_medical_advice(query):
        return ("⚠️ Cannot extract medical advice-related content.", [])

    _ensure_init()
    retriever = vector_store.as_retriever(search_kwargs={"k": 6})

    chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        chain_type="stuff",
        chain_type_kwargs={"prompt": HEALTHCARE_EXTRACT_PROMPT}
    )

    result = chain.invoke({"query": query})
    out = result.get("result", "")

    docs = retrieve_docs(query, k=4)
    snippets = [(d.metadata.get("source","unknown"), d.page_content[:400].replace("\n"," ")) for d in docs]
    return out, snippets

def init_now():
    initialize_components()

