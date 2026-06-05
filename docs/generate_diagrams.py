"""Generate the README graph diagrams as PNGs.

Run from the repo root (with the project venv active):

    python docs/generate_diagrams.py

Each compiled LangGraph is rendered to a left-to-right Mermaid PNG via LangGraph's
``draw_mermaid_png`` helper, which posts the Mermaid source to the mermaid.ink API — so this
needs network access. The PNGs are committed, so the README itself renders offline and on
GitHub without re-running this. Because the diagrams come from the live compiled graphs
(``draw_mermaid()``), they can't drift from the actual wiring.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langchain_core.runnables.graph_mermaid import draw_mermaid_png  # noqa: E402

from src.graph import build_agent_graph  # noqa: E402
from src.rag import build_rag_graph  # noqa: E402

OUT = Path(__file__).resolve().parent


def _render(graph, name: str, direction: str = "LR") -> None:
    """Render one compiled graph to ``<name>.png`` (left-to-right by default)."""
    src = graph.get_graph().draw_mermaid()
    if direction == "LR":
        src = src.replace("graph TD;", "graph LR;", 1)
    png = draw_mermaid_png(src)
    path = OUT / f"{name}.png"
    path.write_bytes(png)
    print(f"wrote {path.relative_to(ROOT)} ({len(png):,} bytes)")


def main() -> None:
    _render(build_agent_graph(), "main_graph")
    _render(build_rag_graph(), "rag_subgraph")


if __name__ == "__main__":
    main()
