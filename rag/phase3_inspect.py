"""
=============================================================
PHASE 3 — Inspect: Peek inside your ChromaDB
=============================================================

This is a learning / debugging tool.
Run it to understand exactly what got stored in your vector DB:
  - How many chunks exist
  - What a raw embedding looks like (1536 floats)
  - How similarity scores work
  - How metadata filtering works

This is the "open the hood" script — not needed to run the app,
but very useful for understanding RAG internals.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma

# ── Setup ──────────────────────────────────────────────────
load_dotenv()
console = Console()

PROJECT_ROOT = Path(__file__).parent.parent
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"
COLLECTION_NAME = "irs_pub15"


def inspect_collection():
    """Show a summary of everything stored in ChromaDB."""
    
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )
    
    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(CHROMA_DIR),
    )
    
    # Access the raw ChromaDB collection
    collection = vectorstore._collection
    total = collection.count()
    
    console.print(f"\n[bold cyan]📊 Collection: '{COLLECTION_NAME}'[/bold cyan]")
    console.print(f"   Total vectors stored: [bold]{total}[/bold]")
    
    # Fetch a sample of the raw data
    sample = collection.get(limit=5, include=["documents", "metadatas", "embeddings"])
    
    # ── Show chunk table ─────────────────────────────────
    table = Table(title="Sample Chunks (first 5)", show_lines=True)
    table.add_column("ID",       style="dim",    width=8)
    table.add_column("Page",     style="cyan",   width=6)
    table.add_column("Text preview",             width=55)
    table.add_column("Vector dims", style="green", width=11)
    
    for i in range(len(sample["ids"])):
        chunk_id  = sample["ids"][i][-8:]         # last 8 chars of UUID
        page      = sample["metadatas"][i].get("page", "?")
        text      = sample["documents"][i][:120].replace("\n", " ") + "..."
        vec_dims  = str(len(sample["embeddings"][i])) if sample["embeddings"] else "n/a"
        table.add_row(chunk_id, str(page), text, vec_dims)
    
    console.print(table)
    
    # ── Show a raw embedding snippet ─────────────────────
    if sample["embeddings"]:
        vec = sample["embeddings"][0]
        console.print(f"\n[bold cyan]🔢 What a vector looks like (first 8 of {len(vec)} floats):[/bold cyan]")
        console.print(f"   [{', '.join(f'{v:.4f}' for v in vec[:8])}, ...]")
        console.print(f"   [dim]Each number encodes a tiny aspect of semantic meaning.[/dim]")
        console.print(f"   [dim]Similar texts → similar vectors → close in 1536-dimensional space.[/dim]")
    
    return vectorstore


def demo_similarity_scores(vectorstore: Chroma):
    """
    Show similarity scores for different queries.
    This makes it concrete why some chunks get retrieved and others don't.
    """
    console.print("\n[bold cyan]📐 Similarity score demo[/bold cyan]")
    console.print("   [dim]Scores are cosine similarity: 1.0 = identical, 0.0 = unrelated[/dim]\n")
    
    queries = [
        "Social Security tax rate for employees",
        "How to make apple pie",         # irrelevant — should score low
        "federal income tax withholding tables",
    ]
    
    for query in queries:
        results = vectorstore.similarity_search_with_score(query, k=2)
        console.print(f"   Query: [italic]\"{query}\"[/italic]")
        for doc, score in results:
            page    = doc.metadata.get("page", "?")
            preview = doc.page_content[:80].replace("\n", " ")
            # ChromaDB returns distance (lower = more similar), convert to similarity
            similarity = round(1 - score, 3)
            bar = "█" * int(similarity * 20)
            console.print(f"     Score {similarity:.3f} {bar}  page {page}: {preview}...")
        console.print()


def demo_metadata_filter(vectorstore: Chroma):
    """
    Show how to filter ChromaDB results by metadata (e.g., specific pages).
    Useful for App 2 when you want to search only certain document sections.
    """
    console.print("\n[bold cyan]🔎 Metadata filter demo[/bold cyan]")
    console.print("   [dim]ChromaDB lets you filter by metadata before similarity search.[/dim]")
    console.print("   [dim]Useful for: search only pages 1-20, or only a specific company's docs.[/dim]\n")
    
    # Filter to only search chunks from pages 1-10
    results = vectorstore.similarity_search(
        query="employer tax deposit requirements",
        k=3,
        filter={"page": {"$lte": 10}},   # ChromaDB filter syntax
    )
    
    console.print("   Query: 'employer tax deposit requirements' | Filter: page ≤ 10")
    for doc in results:
        page    = doc.metadata.get("page", "?")
        preview = doc.page_content[:100].replace("\n", " ")
        console.print(f"     Page {page}: {preview}...")


def main():
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")
    console.print("[bold white]  PHASE 3 — ChromaDB Inspector                    [/bold white]")
    console.print("[bold white]  Understand what's inside your vector DB         [/bold white]")
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")
    
    if not os.getenv("OPENAI_API_KEY"):
        console.print("\n[bold red]❌ OPENAI_API_KEY not found in .env[/bold red]")
        return
    
    if not CHROMA_DIR.exists():
        console.print(f"\n[bold red]❌ No ChromaDB found. Run phase1_ingest.py first.[/bold red]")
        return
    
    vectorstore = inspect_collection()
    demo_similarity_scores(vectorstore)
    demo_metadata_filter(vectorstore)
    
    console.print("\n[bold green]✅ Inspection complete![/bold green]\n")


if __name__ == "__main__":
    main()
