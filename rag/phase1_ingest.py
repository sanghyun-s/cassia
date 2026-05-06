"""
=============================================================
PHASE 1 — Ingest: PDF → Chunks → Embeddings → ChromaDB
=============================================================

Session 6 Homework: IRS Publication 15 RAG pipeline
Step-by-step:
  1. Load a PDF with LangChain's PyPDFLoader
  2. Split it into overlapping chunks (TextSplitter)
  3. Embed each chunk with OpenAI text-embedding-3-small
  4. Store chunks + embeddings in ChromaDB (local, persistent)

Run this ONCE to build the index. Then use phase2_query.py to ask questions.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track
import re

# LangChain document loaders & splitters
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

# LangChain + OpenAI embeddings
from langchain_openai import OpenAIEmbeddings

# ChromaDB via LangChain wrapper
from langchain_community.vectorstores import Chroma

# ── Setup ──────────────────────────────────────────────────
load_dotenv()
console = Console()

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR     = PROJECT_ROOT / "data"
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"

# ChromaDB collection name (think of it like a table name)
COLLECTION_NAME = "irs_pub15"

# Maps PDF filename → human-readable label shown in citations
DOC_LABELS = {
    "irs_pub15.pdf":   "Pub 15 (Employer's Tax Guide)",
    "irs_pub15t.pdf":  "Pub 15-T (Withholding Methods)",
    "irs_pub15b.pdf":  "Pub 15-B (Fringe Benefits)",
}

# Regex patterns for IRS PDF print-production boilerplate.
# These appear on every page of Pub 15-T and pollute chunk previews.
BOILERPLATE_PATTERNS = [
    r"Page \d+ of \d+",
    r"Fileid:\s*\S+",
    r"\d{1,2}:\d{2}\s*-\s*\d{1,2}-[A-Za-z]{3}-\d{4}",
    r"The type and rule above prints on all proofs.*",
    r"including departmental reproduction.*",
]

def clean_page_text(text: str) -> str:
    """Strip IRS print-production boilerplate and collapse whitespace."""
    for pat in BOILERPLATE_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ── Config: chunking strategy ──────────────────────────────
# Why 1000 chars with 200 overlap?
#   - 1000 chars ≈ 250 tokens — fits well within embedding model limits
#   - 200 char overlap ensures context isn't lost at chunk boundaries
#   - RecursiveCharacterTextSplitter tries to split at paragraphs → sentences → words
CHUNK_SIZE    = 1000   # characters per chunk
CHUNK_OVERLAP = 200    # characters shared between adjacent chunks


def load_all_pdfs(data_dir: Path) -> list:
    """
    Load every PDF in data_dir and tag each page with a source_doc label.
    Returns a flat list of LangChain Documents across all PDFs.
    """
    pdf_files = sorted(data_dir.glob("*.pdf"))
    if not pdf_files:
        return []

    console.print(f"\n[bold cyan]📄 Found {len(pdf_files)} PDF(s) in {data_dir.name}/[/bold cyan]")

    all_pages = []
    for pdf_path in pdf_files:
        label = DOC_LABELS.get(pdf_path.name, pdf_path.stem)
        console.print(f"   • Loading [bold]{pdf_path.name}[/bold] → {label}")

        loader = PyPDFLoader(str(pdf_path))
        pages = loader.load()

        # Tag every page with a stable source label and a clean filename
        for p in pages:
            p.metadata["source_doc"] = label
            p.metadata["source_file"] = pdf_path.name
            # PyPDFLoader pages are 0-indexed; convert to 1-indexed for display
            p.metadata["page_display"] = p.metadata.get("page", 0) + 1

        console.print(f"     ✓ {len(pages)} pages")
        all_pages.extend(pages)

    console.print(f"   ✓ Total pages across all PDFs: [bold]{len(all_pages)}[/bold]")
    return all_pages


def split_into_chunks(pages: list) -> list:
    """
    Split page Documents into smaller overlapping chunks.

    Why RecursiveCharacterTextSplitter?
      It tries separators in order: ["\n\n", "\n", " ", ""]
      This means it prefers to split at paragraph breaks, then
      sentence breaks, then word breaks — keeping semantic units
      together as much as possible.
    """
    console.print("\n[bold cyan]✂️  Splitting into chunks...[/bold cyan]")
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],  # try these in order
    )
    
    chunks = splitter.split_documents(pages)
    
    # Show a sample chunk so you can see what you're working with
    console.print(f"   ✓ Created [bold]{len(chunks)}[/bold] chunks")
    console.print(f"   ✓ Avg chunk size: ~{sum(len(c.page_content) for c in chunks) // len(chunks)} chars")
    console.print("\n[dim]── Sample chunk (chunk #5) ──────────────────────────────────[/dim]")
    if len(chunks) > 5:
        sample = chunks[5]
        console.print(f"[dim]{sample.page_content[:300]}...[/dim]")
        console.print(f"[dim]Metadata: {sample.metadata}[/dim]")
    console.print("[dim]─────────────────────────────────────────────────────────────[/dim]")
    
    return chunks


def embed_and_store(chunks: list) -> Chroma:
    """
    Convert each chunk into a vector embedding and store in ChromaDB.

    What is an embedding?
      A list of ~1536 floats that represents the meaning of the text.
      Similar meanings → vectors that are close together in space.
      text-embedding-3-small is fast and cheap (~$0.00002 per 1K tokens).

    ChromaDB stores three things per chunk:
      1. The raw text (so we can return it to the LLM)
      2. The vector embedding (for similarity search)
      3. The metadata (source file, page number)
    """
    console.print("\n[bold cyan]🔢 Embedding chunks → ChromaDB...[/bold cyan]")
    console.print(f"   Model: text-embedding-3-small")
    console.print(f"   Destination: {CHROMA_DIR}")
    
    # Initialize the embedding model
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",  # 1536 dimensions, fast & cheap
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )
    
    # Chroma.from_documents():
    #   - Calls embeddings.embed_documents() on all chunks (batched)
    #   - Stores text + vectors + metadata in the local ChromaDB folder
    #   - Returns a Chroma object you can query immediately
    console.print(f"   Sending {len(chunks)} chunks to OpenAI for embedding...")
    
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),  # saves to disk so you don't re-embed
    )
    
    console.print(f"   ✓ Stored [bold]{len(chunks)}[/bold] vectors in ChromaDB")
    console.print(f"   ✓ Collection: [bold]{COLLECTION_NAME}[/bold]")
    console.print(f"   ✓ Persisted to disk at: {CHROMA_DIR}")
    
    return vectorstore


def run_quick_test(vectorstore: Chroma):
    """
    Run a quick similarity search to verify the index works
    before we build the full Q&A chain in phase2.
    """
    console.print("\n[bold cyan]🔍 Quick test — similarity search...[/bold cyan]")
    
    test_query = "What are the federal income tax withholding requirements for employers?"
    console.print(f"   Query: [italic]\"{test_query}\"[/italic]")
    
    # similarity_search returns the top-k most relevant chunks (no LLM yet)
    results = vectorstore.similarity_search(test_query, k=3)
    
    console.print(f"\n   Top 3 matching chunks:\n")
    for i, doc in enumerate(results, 1):
        page = doc.metadata.get("page", "?")
        preview = doc.page_content[:200].replace("\n", " ")
        console.print(f"   [bold]#{i}[/bold] (page {page}): {preview}...")
        console.print()


def main():
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")
    console.print("[bold white]  PHASE 1 — RAG Ingestion Pipeline                [/bold white]")
    console.print("[bold white]  IRS Publications → ChromaDB                     [/bold white]")
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")
    
    # ── Check for PDFs ──────────────────────────────────────
    if not any(DATA_DIR.glob("*.pdf")):
        console.print(f"\n[bold red]❌ No PDFs found in {DATA_DIR}[/bold red]")
        console.print("\n[yellow]Download at least one IRS publication, e.g.:[/yellow]")
        console.print("[dim]  curl -o data/irs_pub15.pdf  https://www.irs.gov/pub/irs-pdf/p15.pdf[/dim]")
        console.print("[dim]  curl -o data/irs_pub15t.pdf https://www.irs.gov/pub/irs-pdf/p15t.pdf[/dim]")
        console.print("[dim]  curl -o data/irs_pub15b.pdf https://www.irs.gov/pub/irs-pdf/p15b.pdf[/dim]")
        return
    
    # ── Check API key ───────────────────────────────────────
    if not os.getenv("OPENAI_API_KEY"):
        console.print("\n[bold red]❌ OPENAI_API_KEY not found in .env[/bold red]")
        console.print("[yellow]Copy .env.example to .env and add your key[/yellow]")
        return
    
    # ── Check if already indexed ────────────────────────────
    if CHROMA_DIR.exists() and any(CHROMA_DIR.iterdir()):
        console.print(f"\n[yellow]⚠️  ChromaDB already exists at {CHROMA_DIR}[/yellow]")
        console.print("[yellow]   Delete the outputs/chroma_db folder to re-index.[/yellow]")
        console.print("[yellow]   Loading existing index for quick test...[/yellow]")
        
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )
        vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=str(CHROMA_DIR),
        )
        run_quick_test(vectorstore)
        return
    
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    
    # ── Run the pipeline ────────────────────────────────────
    pages       = load_all_pdfs(DATA_DIR)
    chunks      = split_into_chunks(pages)
    vectorstore = embed_and_store(chunks)
    run_quick_test(vectorstore)
    
    console.print("\n[bold green]✅ Phase 1 complete![/bold green]")
    console.print("[green]   Run [bold]python rag/phase2_query.py[/bold] to start asking questions.[/green]\n")

if __name__ == "__main__":
    main()
