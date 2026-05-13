# Development Log

A chronological record of build sessions for CoReckoner.

This is the development journal for the project — design decisions, debugging journeys, and lessons learned. Each entry covers one or more build sessions.

---

## Sessions

### [Sessions 7+8+9 — Major Build Sprint (May 5–6, 2026)](SESSION_7_UPDATE.md)

**Topics:** Multi-source RAG with citations, Plotly auto-charts, conversation memory, bilingual comprehension, sidebar restructure, friendly error handling

**Key milestones:**
- Indexed 3 IRS publications with grouped source citations
- Implemented bar/pie/line auto-chart detection
- Added pragmatic conversation memory via explicit-pass approach
- Verified Korean question handling end-to-end
- Restructured sidebar with new chat button and conversation history
- Categorized error messages (connection / API key / database / vector store)

---

## How to Read These Logs

Each session log follows a consistent format:

- **Goal** — what was being attempted
- **Files edited** — which parts of the codebase changed
- **Verified scenarios** — what was tested
- **Known issues** — limitations and trade-offs
- **Next steps** — what comes after

The logs are written for two audiences:
1. **My future self** — to remember why decisions were made
2. **Portfolio reviewers** — to see how the project was actually built

---

## Topics Index (Coming Soon)

As more sessions are added, this section will let you find specific topics:

- **RAG implementation** — Sessions 7
- **Conversation memory** — Sessions 7, 8
- **Bilingual support** — Session 8
- **UX polish** — Session 9
- **Deployment & demo** — TBD
