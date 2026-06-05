# Corpus sources & licensing

The RAG corpus is a **frozen, dated snapshot** committed under `data/corpus/`. Only the
corpus is the source of truth; the ChromaDB vector store (`data/chroma/`) is a derived
artifact, gitignored and rebuilt by `python -m src.ingest`.

Machine-readable provenance (used by ingestion to attach `url` / `retrieved_at` to every
chunk's citation metadata) lives in `data/corpus/sources.json`. This file is the
human-readable companion and the licensing record.

**Reform caveat:** Regulation (EC) No 261/2004 is under reform (Council position June 2025;
Parliament TRAN committee October 2025), but **not yet enacted**. This corpus targets the
**current in-force rules** (3-hour threshold; €250 / €400 / €600 bands). See the README.

---

## Documents

| File | Document | Source | Retrieved | License |
|------|----------|--------|-----------|---------|
| `reg_261_2004.html` | Regulation (EC) No 261/2004 (full text, EN) | EUR-Lex / Publications Office, CELEX `32004R0261` | 2026-06-03 | © European Union — reuse permitted with source acknowledgement |
| `guidelines_2024.html` | Commission Interpretative Guidelines on Reg. 261/2004 (Commission Notice, OJ C/2024/5687, 25.9.2024) — the 2024 refresh, incorporating CJEU case law through 2024 | EUR-Lex / Publications Office, OJ `C_202405687` | 2026-06-03 | © European Union — reuse permitted with source acknowledgement |
| `legissum_261_2004.html` | EUR-Lex legislative summary of Reg. 261/2004 (Summaries of EU legislation) | EUR-Lex, `LEGISSUM:l24173` | 2026-06-03 | © European Union — reuse permitted with source acknowledgement |
| `plain_language_summary.md` | Air passenger rights — official plain-language summary | Your Europe (europa.eu) | 2026-06-03 | © European Union — reuse permitted with source acknowledgement |

Fetch methods (the EUR-Lex web UI sits behind an AWS WAF that blocks `curl`):
- The **regulation** and **2024 guidelines** were fetched as structured (X)HTML via the
  Publications Office **Cellar REST API** (content negotiation), which serves the same
  authoritative text without the WAF challenge.
- The **EUR-Lex legislative summary** was fetched from the EUR-Lex **TXT/HTML export
  endpoint** (`/legal-content/EN/TXT/HTML/?uri=LEGISSUM:l24173`) using Python `requests`,
  whose default client passes the WAF where `curl` does not.
- The **Your Europe summary** was extracted from the page's `<main>` content (navigation /
  cookie / script chrome stripped) and frozen as Markdown; see the comment header in that file.

## Attribution notes

- **EUR-Lex / Publications Office content** (© European Union, 1998–2026) is reusable with
  source acknowledgement, per the EUR-Lex copyright notice.
- **OpenFlights airport data** (`data/airports.dat`, used by the Phase 3 compensation
  calculator for IATA → lat/lon great-circle distance — **not** part of this RAG corpus) is
  © OpenFlights.org, licensed under the **Open Database License (ODbL) v1.0**. Retrieved
  2026-06-03 from the upstream repository
  (`https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat`).
  Any produced work that uses this data must keep it open and credit OpenFlights, per ODbL.
