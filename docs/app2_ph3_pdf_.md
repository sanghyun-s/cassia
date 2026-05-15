# Next Session — Phase 3 Close-out (PDF + Migration)

*Last updated: May 13, 2026*

---

## What's left in Phase 3

Two items in one session: **LangChain Chroma migration** first, **PDF upload (C3)** second. Bundled because both touch `rag_pipeline.py` — one edit pass is cleaner than two.

---

## Decisions already made

| Decision | Choice |
|----------|--------|
| **PDF upload UX** | Multiple PDFs in one upload — user shift-clicks files in the picker |
| **Session lifetime** | Session-only — vectors deleted when session deleted (matches CSV pattern) |
| **Chunking strategy** | Same chunk size as existing `rag/phase1_ingest.py` |
| **Migration vs PDF order** | Migration first, then PDF — single touch on `rag_pipeline.py` |
| **Backend shape for multi-PDF** | Frontend calls `/ingest` in a loop, one PDF per call. Backend stays simple. Toast stacks one per file. |

---

## Order of work next session

### 1. LangChain Chroma migration (30–60 min)
- Install `langchain-chroma` package
- Change import in `rag_pipeline.py` from `langchain_community.vectorstores` to `langchain_chroma`
- Run all 10 RAG demo questions to confirm no regression
- Confirm deprecation warning is gone from server startup

### 2. PDF upload backend (1–1.5 hr)
- New file `backend/uploads/document.py` — PDF chunking + embedding
- Reuse chunk size constants from `rag/phase1_ingest.py`
- Add `{session_id, source_type: "user", filename, page}` metadata to each chunk
- Extend `upload_router.py`:
  - `/preview` returns page count + estimated chunk count
  - `/ingest` writes vectors to ChromaDB
  - `/list` already works
  - `/delete` deletes vectors WHERE `metadata.session_id == session_id` AND `metadata.filename == ...`
- Hook into `delete_session` cascade in `main.py` — bulk-delete all session vectors

### 3. RAG pipeline filter (30 min)
- Update `rag_pipeline.py` retrieval to filter: `source_type == "irs"` OR `session_id == current_session`
- Test: ask an IRS question (should hit Pub 15 only), ask a question about uploaded PDF (should hit user vectors only)

### 4. Frontend (30–45 min)
- Update `index.html` file-input `accept` to include `.pdf` and `.txt`
- Add `multiple` attribute to file input for batch
- Update `handleFileSelected` to loop over `files` array, ingest each, stack toasts
- Sidebar uploads list already handles `target: 'rag'` rendering — verify it shows chunks count for PDFs

### 5. Test sweep (20 min)
- Upload `data/irs_pub15b.pdf` (Fringe Benefits) → ask "what fringe benefits are excludable from wages?"
- Upload `data/irs_pub15t.pdf` (Withholding Methods) → ask "how do I calculate withholding using the percentage method?"
- Verify Pub 15 base questions still work (no regression)
- Verify session delete removes vectors from ChromaDB (check via `phase3_inspect.py`)

---

## Files that will change

```
backend/
├── main.py                      cascade hook for ChromaDB cleanup
├── pipelines/rag_pipeline.py    migration + session filter
├── routers/upload_router.py     PDF preview + ingest + delete
├── uploads/document.py          NEW — PDF chunking + embedding
└── static/index.html            multiple files, .pdf accept
```

---

## Test files at hand

- `data/irs_pub15b.pdf` — Fringe Benefits (NOT in current ChromaDB)
- `data/irs_pub15t.pdf` — Withholding Methods (NOT in current ChromaDB)

These are perfect test PDFs since the answers won't be findable from the existing 414 vectors — proves the session-scoped retrieval is actually working.

---

## Open questions for next session (if any)

- None blocking. All design decisions locked.

---

## After this session, Phase 3 is fully closed

Then onto:
- Polish session (Loom + screenshots + a11y + final HANDOFF_v4)
- Phase 4 design (auth + save-to-core + recall)
