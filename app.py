"""COBOL Flow Analyzer - Streamlit front end.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from src.analyzer.paragraph_analyzer import paragraph_detail, search_paragraphs  # noqa: E402
from src.export.report_generator import (  # noqa: E402
    call_sites_frame, execution_frame, paragraphs_frame, statements_frame,
    to_csv_bytes, to_excel_bytes, to_json_text,
)
from src.pipeline import analyze_source  # noqa: E402
from src.storage import list_analyses, save_analysis  # noqa: E402
from src.visualization.flow_diagram import neighbourhood_dot, program_map_dot  # noqa: E402

SAMPLE_PATH = os.path.join(ROOT, "sample_programs", "sample01.cbl")
DB_PATH = os.path.join(ROOT, "output", "cobol_flow.db")

SCREENS = [
    "1. Program Upload",
    "2. Program Overview",
    "3. Paragraph Explorer",
    "4. Paragraph Flow",
    "5. Program Flow Map",
]

st.set_page_config(page_title="COBOL Flow Analyzer", layout="wide")


def _state():
    st.session_state.setdefault("analysis", None)
    st.session_state.setdefault("source_text", "")


def _require_analysis() -> bool:
    if st.session_state["analysis"] is None:
        st.info("Upload or select a COBOL program on screen 1 first.")
        return False
    return True


# --------------------------------------------------------------------------- screen 1
def screen_upload():
    st.header("Program Upload")
    st.write("Upload one COBOL source file (fixed or free format).")

    col_a, col_b = st.columns([2, 1])
    with col_a:
        uploaded = st.file_uploader("COBOL source", type=["cbl", "cob", "cobol", "txt", "CBL", "COB"])
    with col_b:
        st.write("")
        st.write("")
        use_sample = st.button("Load sample program (sample01.cbl)")

    save_to_db = st.checkbox("Also save the analysis to the local SQLite database", value=False)

    if use_sample:
        with open(SAMPLE_PATH, encoding="utf-8") as handle:
            st.session_state["pending"] = ("sample01.cbl", handle.read())
    if uploaded is not None:
        st.session_state["pending"] = (uploaded.name, uploaded.getvalue().decode("utf-8", errors="replace"))

    pending = st.session_state.get("pending")
    st.caption(f"Selected: {pending[0]}" if pending else "Nothing selected yet.")

    if st.button("Analyze", type="primary", disabled=pending is None):
        name, text = pending
        analysis = analyze_source(text, source_name=name)
        st.session_state["analysis"] = analysis
        st.session_state["source_text"] = text
        if save_to_db:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            run_id = save_analysis(DB_PATH, analysis, text)
            st.success(f"Saved to {DB_PATH} (analysis #{run_id}).")
        st.success(f"Analyzed {analysis.program.name}: {len(analysis.program.paragraphs)} paragraphs, "
                   f"{len(analysis.call_sites)} call sites.")

    if st.session_state["analysis"] is not None:
        st.subheader("Current program")
        analysis = st.session_state["analysis"]
        st.write(f"**{analysis.program.name}** from `{analysis.program.source_name}`")
        st.caption("Go to the other screens in the sidebar.")

    with st.expander("Saved analyses"):
        rows = list_analyses(DB_PATH) if os.path.exists(DB_PATH) else []
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.write("No saved analyses yet.")


# --------------------------------------------------------------------------- screen 2
def screen_overview():
    st.header("Program Overview")
    if not _require_analysis():
        return
    a = st.session_state["analysis"]
    p = a.program
    statements = sum(para.statement_count for para in p.paragraphs)

    cols = st.columns(6)
    cols[0].metric("Divisions", len(p.divisions))
    cols[1].metric("Sections", len(p.sections))
    cols[2].metric("Paragraphs", len(p.paragraphs))
    cols[3].metric("Statements", statements)
    cols[4].metric("Call sites", len(a.call_sites))
    cols[5].metric("Never called", len(a.never_called))

    st.subheader("Divisions")
    st.dataframe(pd.DataFrame([{"Division": d.name, "Starts at line": d.start_line} for d in p.divisions]),
                 hide_index=True, width="stretch")

    st.subheader("Sections")
    if p.sections:
        st.dataframe(pd.DataFrame([{"Section": s.name, "Division": s.division,
                                    "Starts at line": s.start_line,
                                    "Paragraphs": s.paragraph_count} for s in p.sections]),
                     hide_index=True, width="stretch")
    else:
        st.write("No sections found.")

    st.write(f"Source: {p.line_count} lines. Data items (level 01/77): {p.data_item_count}. "
             f"Procedure division starts at line {p.procedure_start_line}.")

    if a.never_called:
        st.warning("Never called: " + ", ".join(a.never_called))
    if a.unreachable:
        st.warning("Unreachable from the entry paragraph: " + ", ".join(a.unreachable))

    st.subheader("Export")
    c1, c2, c3, c4 = st.columns(4)
    c1.download_button("Excel report (.xlsx)", to_excel_bytes(a),
                       file_name=f"{p.name}_flow.xlsx")
    c2.download_button("Paragraphs (CSV)", to_csv_bytes(paragraphs_frame(a)),
                       file_name=f"{p.name}_paragraphs.csv", mime="text/csv")
    c3.download_button("Call sites (CSV)", to_csv_bytes(call_sites_frame(a)),
                       file_name=f"{p.name}_call_sites.csv", mime="text/csv")
    c4.download_button("Full analysis (JSON)", to_json_text(a),
                       file_name=f"{p.name}_analysis.json", mime="application/json")


# --------------------------------------------------------------------------- screen 3
def screen_explorer():
    st.header("Paragraph Explorer")
    if not _require_analysis():
        return
    a = st.session_state["analysis"]
    p = a.program

    query = st.text_input("Search paragraphs (name contains)", placeholder="e.g. ERROR-PARA")
    names = search_paragraphs(a, query)
    listing = pd.DataFrame([{
        "Paragraph": n,
        "Section": a.program.paragraph_map[n].section or "",
        "Lines": f"{a.program.paragraph_map[n].start_line}-{a.program.paragraph_map[n].end_line}",
        "Status": a.statuses[n].label,
        "Call sites in": a.statuses[n].call_count,
    } for n in names])
    if listing.empty:
        st.info("No paragraph matches that text.")
        return
    st.dataframe(listing, hide_index=True, width="stretch")

    selected = st.selectbox("Paragraph", names, index=0)
    detail = paragraph_detail(a, selected)

    st.subheader(f"{selected}")
    st.write(f"Defined at lines {detail['start_line']}-{detail['end_line']}"
             + (f", section {detail['section']}" if detail["section"] else "")
             + f". Status: **{detail['status']}**.")
    st.info(detail["after_completion"])

    left, right = st.columns(2)
    with left:
        st.markdown("**Called by (which paragraphs, and under what conditions)**")
        if detail["callers"]:
            st.dataframe(pd.DataFrame([{
                "Caller": c["caller"], "Kind": c["kind"], "Line": c["line"],
                "Conditions": " AND ".join(c["conditions"]) or "(unconditional)",
            } for c in detail["callers"]]), hide_index=True, width="stretch")
        else:
            st.write("No PERFORM or GO TO refers to this paragraph.")
    with right:
        st.markdown("**Calls out to**")
        if detail["outgoing"] or detail["external_calls"]:
            rows = [{"Target": o["target"], "Kind": o["kind"], "Line": o["line"],
                     "Conditions": " AND ".join(o["conditions"]) or "(unconditional)"}
                    for o in detail["outgoing"]]
            rows += [{"Target": f"CALL {c['program']} (external)", "Kind": "CALL", "Line": c["line"],
                      "Conditions": " AND ".join(c["conditions"]) or "(unconditional)"}
                     for c in detail["external_calls"]]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.write("No outgoing PERFORM, GO TO or CALL.")

    st.markdown("**Every mention in the PROCEDURE DIVISION**")
    if detail["occurrences"]:
        st.dataframe(pd.DataFrame(detail["occurrences"]), hide_index=True, width="stretch")

    st.markdown("**Source code**")
    st.code(detail["source"], language="cobol", line_numbers=True)


# --------------------------------------------------------------------------- screen 4
def screen_paragraph_flow():
    st.header("Paragraph Flow")
    if not _require_analysis():
        return
    a = st.session_state["analysis"]
    selected = st.selectbox("Paragraph", [p.name for p in a.program.paragraphs])
    detail = paragraph_detail(a, selected)

    st.subheader("Statement flow")
    st.caption("Indented rows are nested inside the branch or loop above them.")
    outline = pd.DataFrame([{
        "Line": row["line"],
        "Statement": ("    " * row["depth"]) + row["text"],
        "Kind": row["kind"],
    } for row in detail["outline"]])
    if outline.empty:
        st.write("This paragraph has no statements.")
    else:
        st.dataframe(outline, hide_index=True, width="stretch")

    st.subheader("What happens after it completes")
    st.info(detail["after_completion"])

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Execution reaches this paragraph from**")
        if detail["callers"]:
            st.dataframe(pd.DataFrame([{"From": c["caller"], "Kind": c["kind"], "Line": c["line"],
                                        "Conditions": " AND ".join(c["conditions"]) or "(unconditional)"}
                                       for c in detail["callers"]]), hide_index=True, width="stretch")
        else:
            st.write("No incoming PERFORM or GO TO.")
    with c2:
        st.markdown("**This paragraph transfers control to**")
        if detail["outgoing"]:
            st.dataframe(pd.DataFrame([{"To": o["target"], "Kind": o["kind"], "Line": o["line"],
                                        "Conditions": " AND ".join(o["conditions"]) or "(unconditional)"}
                                       for o in detail["outgoing"]]), hide_index=True, width="stretch")
        else:
            st.write("No outgoing PERFORM or GO TO.")

    st.subheader("Local flow")
    st.graphviz_chart(neighbourhood_dot(a.graph, a.statuses, selected))


# --------------------------------------------------------------------------- screen 5
def screen_flow_map():
    st.header("Program Flow Map")
    if not _require_analysis():
        return
    a = st.session_state["analysis"]

    show_ft = st.checkbox("Show fall-through edges (source order)", value=True)
    st.graphviz_chart(program_map_dot(a.graph, a.statuses, show_fall_through=show_ft))

    st.markdown(
        "**Legend** — node colour: green = entry point, blue = called, grey = fall-through only, "
        "red = never called; dashed border = unreachable from the entry point. "
        "Edges: solid blue = PERFORM, bold blue = PERFORM THRU, dashed red = GO TO, "
        "dotted grey = fall-through. A `?` label means the transfer is conditional."
    )

    st.subheader("Execution sequence (static, first pass)")
    st.caption("Walks from the entry paragraph: PERFORM returns to its caller, GO TO transfers control, "
               "IF/EVALUATE branches are listed with their conditions, and each paragraph is expanded once.")
    trace = execution_frame(a)
    kinds = sorted(trace["Event"].unique()) if not trace.empty else []
    chosen = st.multiselect("Show events", kinds, default=kinds)
    shown = trace[trace["Event"].isin(chosen)] if not trace.empty else trace
    if shown.empty:
        st.write("No execution events.")
    else:
        view = shown.copy()
        view["Detail"] = [("    " * d) + text for d, text in zip(view["Depth"], view["Detail"])]
        st.dataframe(view, hide_index=True, width="stretch")
        st.download_button("Download execution trace (CSV)", to_csv_bytes(execution_frame(a)),
                           file_name=f"{a.program.name}_trace.csv", mime="text/csv")

    with st.expander("Statement tree (all paragraphs)"):
        st.dataframe(statements_frame(a), hide_index=True, width="stretch")


# --------------------------------------------------------------------------- main
def main():
    _state()
    st.sidebar.title("COBOL Flow Analyzer")
    screen = st.sidebar.radio("Screen", SCREENS)
    if st.session_state["analysis"] is not None:
        st.sidebar.caption(f"Loaded: {st.session_state['analysis'].program.name}")

    handlers = {
        SCREENS[0]: screen_upload,
        SCREENS[1]: screen_overview,
        SCREENS[2]: screen_explorer,
        SCREENS[3]: screen_paragraph_flow,
        SCREENS[4]: screen_flow_map,
    }
    handlers[screen]()


main()
