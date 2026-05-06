"""
=============================================================
RAG PIPELINE — ChromaDB retrieval for unstructured documents
=============================================================
Multi-source version: handles multiple IRS publications with
inline citations of the form [Pub name, p.X].
"""

from pathlib import Path
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
import os

PROJECT_ROOT = Path(__file__).parent.parent.parent
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"

RAG_PROMPT = PromptTemplate(
    template="""You are a helpful tax and payroll assistant with expertise in IRS regulations.
Use ONLY the following excerpts from IRS publications to answer the question.
If the answer is not in the excerpts, say "I couldn't find that in the available IRS publications."

Each excerpt is tagged with its source document and page number. When you use information
from an excerpt, cite it inline using this exact format: [Pub name, p.X]

Example: "Employers must deposit federal income tax withheld [Pub 15, p.23]."

If two sources discuss the same topic, cite both. If they disagree, note the discrepancy.

{history_block}--------- IRS PUBLICATION EXCERPTS ---------
{context}
--------------------------------------------

Question: {question}

If the question is a follow-up that refers to prior turns (e.g. "what about
fringe benefits", "tell me more", "and what's the deadline"), use the prior
conversation context to understand what's being asked, then answer using
ONLY the excerpts above.

Answer:""",
    input_variables=["context", "question", "history_block"],
)

# Formats each retrieved chunk with its metadata before it reaches the LLM,
# so the model can see the source label and copy it into its inline citations.
DOCUMENT_PROMPT = PromptTemplate(
    template="[{source_doc}, p.{page_display}]\n{page_content}",
    input_variables=["source_doc", "page_display", "page_content"],
)


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


def run_rag_pipeline(question: str, llm: ChatOpenAI, chroma_dir: Path, history: str = "") -> dict:
    """
    Full RAG pipeline:
      question → embed → ChromaDB search → prompt → LLM → answer
    Returns dict with answer, sources, and a count of distinct documents.

    Args:
        question: The user's current question
        llm: ChatOpenAI instance for answer synthesis
        chroma_dir: Path to ChromaDB persistence directory
        history: Optional formatted prior conversation. Enables follow-ups
                 like "what about fringe benefits" after a Pub 15 question.
    """
    vectorstore = get_vectorstore(chroma_dir)

    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 5},   # bumped from 4 to 5 for multi-source coverage
    )

    # Build the history block (empty when no prior turns)
    history_block = ""
    if history:
        history_block = f"PRIOR CONVERSATION (most recent last):\n{history}\n\n"

    # Bind history_block as a partial — RetrievalQA only passes context + question,
    # so we pre-fill the third variable here.
    prompt_with_history = RAG_PROMPT.partial(history_block=history_block)

    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,
        chain_type_kwargs={
            "prompt": prompt_with_history,
            "document_prompt": DOCUMENT_PROMPT,
        },
    )

    result = qa_chain.invoke({"query": question})

    # Build a deduplicated, source-aware citation list
    sources = []
    seen = set()
    for doc in result.get("source_documents", []):
        source_doc = doc.metadata.get("source_doc", "Unknown")
        page = doc.metadata.get("page_display", doc.metadata.get("page", "?"))
        key = (source_doc, page)
        if key in seen:
            continue
        seen.add(key)

        preview = doc.page_content[:150].replace("\n", " ")
        sources.append({
            "source_doc": source_doc,
            "page": page,
            "preview": preview,
        })

    distinct_docs = len({s["source_doc"] for s in sources})

    return {
        "pipeline": "rag",
        "answer": result["result"],
        "sources": sources,
        "distinct_sources": distinct_docs,
        "sql": None,
        "raw_data": [],
        "columns": [],
    }