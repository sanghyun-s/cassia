"""
=============================================================
PHASE 2 — Query: Natural Language → RAG → Answer
=============================================================

This script builds a RetrievalQA chain that:
  1. Takes your plain-English question
  2. Embeds it using the same model used in phase1
  3. Finds the top-k most relevant chunks in ChromaDB
  4. Sends those chunks + your question to GPT-4o-mini
  5. Returns a grounded answer (with source pages cited)

Run AFTER phase1_ingest.py has built your ChromaDB index.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# LangChain core
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

# ── Setup ──────────────────────────────────────────────────
load_dotenv()
console = Console()

PROJECT_ROOT = Path(__file__).parent.parent
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"
COLLECTION_NAME = "irs_pub15"

# How many chunks to retrieve per question
# More = more context for the LLM, but also more tokens (cost)
TOP_K = 4


# ── Prompt Template ────────────────────────────────────────
# This controls exactly what the LLM sees.
# {context} = the retrieved chunks from ChromaDB
# {question} = the user's question
RAG_PROMPT = PromptTemplate(
    template="""You are a helpful tax and payroll assistant with expertise in IRS regulations.
Use ONLY the following excerpts from IRS Publication 15 to answer the question.
If the answer is not in the excerpts, say "I couldn't find that in Publication 15."
Always cite the page number when you can find it in the metadata.

--------- IRS PUB 15 EXCERPTS ---------
{context}
----------------------------------------

Question: {question}

Answer (be specific, cite page numbers where available):""",
    input_variables=["context", "question"],
)


def load_vectorstore() -> Chroma:
    """Load the existing ChromaDB index from disk."""
    if not CHROMA_DIR.exists():
        raise FileNotFoundError(
            f"ChromaDB not found at {CHROMA_DIR}\n"
            "Run phase1_ingest.py first to build the index."
        )
    
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )
    
    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(CHROMA_DIR),
    )
    
    count = vectorstore._collection.count()
    console.print(f"   ✓ Loaded ChromaDB: [bold]{count}[/bold] vectors in collection '{COLLECTION_NAME}'")
    return vectorstore


def build_qa_chain(vectorstore: Chroma) -> RetrievalQA:
    """
    Build the RetrievalQA chain.

    Chain flow:
      question
        → embed question (same model as phase1)
        → similarity_search in ChromaDB → top K chunks
        → format chunks into {context}
        → send prompt to LLM
        → return answer + source_documents
    """
    llm = ChatOpenAI(
        model="gpt-4o-mini",     # fast and cheap; swap to gpt-4o for harder questions
        temperature=0,            # 0 = deterministic, factual answers
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )
    
    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": TOP_K},
    )
    
    # chain_type="stuff" = stuff all retrieved chunks into one prompt
    # Good for short-to-medium docs. Use "map_reduce" for very long docs.
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=True,   # so we can show where the answer came from
        chain_type_kwargs={"prompt": RAG_PROMPT},
    )
    
    return qa_chain


def ask(qa_chain: RetrievalQA, question: str, q_num: int):
    """Send a question through the chain and display the result."""
    console.print(f"\n[bold white]── Question {q_num} ─────────────────────────────────────────[/bold white]")
    console.print(f"[bold yellow]❓ {question}[/bold yellow]\n")
    
    # The chain does: embed → retrieve → prompt → LLM → answer
    result = qa_chain.invoke({"query": question})
    
    answer = result["result"]
    sources = result["source_documents"]
    
    # Print the answer
    console.print(Panel(
        Text(answer, style="white"),
        title="[bold green]💡 Answer[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))
    
    # Print the source chunks the LLM used
    console.print("[dim]📎 Source chunks used:[/dim]")
    for i, doc in enumerate(sources, 1):
        page    = doc.metadata.get("page", "?")
        source  = doc.metadata.get("source", "IRS Pub 15")
        preview = doc.page_content[:120].replace("\n", " ")
        console.print(f"   [dim]{i}. Page {page} — {preview}...[/dim]")


def run_homework_questions(qa_chain: RetrievalQA):
    """
    The 5 homework questions for Session 6.
    These cover a range of topics in IRS Publication 15 so you can
    see how RAG handles different types of tax/payroll questions.
    """
    questions = [
        # Q1: A direct factual lookup — tests basic retrieval
        "What are the federal income tax withholding rates for a single employee "
        "earning $3,500 per month in 2024?",
        
        # Q2: A process/how-to question — tests multi-chunk synthesis
        "How does an employer calculate Social Security and Medicare (FICA) taxes "
        "and what are the current rates and wage base limits?",
        
        # Q3: A definitions question — tests semantic search precision
        "What is a 'supplemental wage payment' and how should employers "
        "withhold taxes on bonuses and commissions?",
        
        # Q4: A compliance/deadline question — tests metadata retrieval
        "What are the deposit schedules for federal employment taxes — "
        "when must an employer deposit monthly vs semi-weekly?",
        
        # Q5: An edge-case question — tests hallucination resistance
        "What happens if an employee claims exempt from withholding on Form W-4 "
        "and what are the employer's responsibilities in that case?",
    ]
    
    for i, question in enumerate(questions, 1):
        ask(qa_chain, question, i)
        console.print()


def interactive_mode(qa_chain: RetrievalQA):
    """
    After the 5 homework questions, drop into an interactive Q&A loop.
    Type 'quit' to exit.
    """
    console.print("\n[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]  Interactive Mode — ask your own questions         [/bold cyan]")
    console.print("[bold cyan]  Type 'quit' to exit                               [/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]\n")
    
    q_num = 6
    while True:
        try:
            question = console.input("[bold yellow]You: [/bold yellow]").strip()
        except (KeyboardInterrupt, EOFError):
            break
        
        if not question or question.lower() in ("quit", "exit", "q"):
            console.print("\n[dim]Goodbye![/dim]")
            break
        
        ask(qa_chain, question, q_num)
        q_num += 1


def main():
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")
    console.print("[bold white]  PHASE 2 — RAG Query Chain                       [/bold white]")
    console.print("[bold white]  IRS Publication 15 Natural Language Q&A         [/bold white]")
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")
    
    if not os.getenv("OPENAI_API_KEY"):
        console.print("\n[bold red]❌ OPENAI_API_KEY not found in .env[/bold red]")
        return
    
    console.print("\n[bold cyan]📦 Loading vector index...[/bold cyan]")
    try:
        vectorstore = load_vectorstore()
    except FileNotFoundError as e:
        console.print(f"\n[bold red]❌ {e}[/bold red]")
        return
    
    console.print("\n[bold cyan]🔗 Building RetrievalQA chain...[/bold cyan]")
    qa_chain = build_qa_chain(vectorstore)
    console.print("   ✓ Chain ready: ChromaDB retriever → GPT-4o-mini")
    
    # Run the 5 homework questions
    run_homework_questions(qa_chain)
    
    console.print("\n[bold green]✅ All 5 homework questions answered![/bold green]")
    
    # Drop into interactive mode for extra exploration
    interactive_mode(qa_chain)


if __name__ == "__main__":
    main()
