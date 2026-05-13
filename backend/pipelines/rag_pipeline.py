"""
=============================================================
RAG PIPELINE — ChromaDB retrieval for unstructured documents
=============================================================

Changes from Phase 1:
  - Added response_type field (answer / rag_not_found)
  - Pipeline logic: unchanged
"""

from pathlib import Path
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
import os

PROJECT_ROOT = Path(__file__).parent.parent.parent

RAG_PROMPT = PromptTemplate(
    template="""You are a helpful tax and payroll assistant with expertise in IRS regulations.
Use ONLY the following excerpts from IRS Publication 15 to answer the question.
If the answer is not in the excerpts, say "I couldn't find that in Publication 15."
Always cite the page number when available in the metadata.

--------- IRS PUB 15 EXCERPTS ---------
{context}
----------------------------------------

Question: {question}

Answer (be specific, cite page numbers where available):""",
    input_variables=["context", "question"],
)

_NOT_FOUND_PHRASES = [
    "couldn't find",
    "cannot find",
    "not found in",
    "not in publication",
    "no information",
    "not covered",
]


def get_vectorstore(chroma_dir: Path) -> Chroma:
    if not chroma_dir.exists():
        raise FileNotFoundError(
            f"ChromaDB not found at {chroma_dir}. "
            "Run rag/phase1_ingest.py first."
        )
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )
    return Chroma(
        collection_name="irs_pub15",
        embedding_function=embeddings,
        persist_directory=str(chroma_dir),
    )


def run_rag_pipeline(question: str, llm: ChatOpenAI, chroma_dir: Path) -> dict:
    """
    Full RAG pipeline.
    Returns dict with: answer, sources, response_type, chart_hint
    """
    vectorstore = get_vectorstore(chroma_dir)

    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 4},
    )

    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,
        chain_type_kwargs={"prompt": RAG_PROMPT},
    )

    result = qa_chain.invoke({"query": question})
    answer = result["result"]

    # Determine response_type
    answer_lower = answer.lower()
    if any(phrase in answer_lower for phrase in _NOT_FOUND_PHRASES):
        response_type = "rag_not_found"
    else:
        response_type = "answer"

    sources = []
    for doc in result.get("source_documents", []):
        page    = doc.metadata.get("page", "?")
        preview = doc.page_content[:150].replace("\n", " ")
        sources.append({"page": page, "preview": preview})

    return {
        "pipeline":      "rag",
        "response_type": response_type,
        "chart_hint":    "none",   # RAG never generates charts
        "answer":        answer,
        "sources":       sources,
        "sql":           None,
        "raw_data":      [],
        "columns":       [],
    }
