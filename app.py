import streamlit as st
from typing import List
from rag import (
    process_urls_and_pdfs,
    generate_qa,
    generate_summary,
    generate_extract,
)
import tempfile

st.set_page_config(page_title="Healthcare Research Assistant", page_icon="🩺", layout="wide")

# ---------------------------------------------------
# Header
# ---------------------------------------------------
st.title("🩺 Healthcare Research Assistant")
st.markdown(
    """Use this tool to analyze healthcare documents using Retrieval-Augmented Generation (RAG).  
    You can instantly try the app with demo sources — no setup needed.
    """

)
# Compact instructions inside an expander
with st.expander("How to use this app 🔽"):
    st.markdown(
        """
**Quick Start Using Demo Data**
1. Demo URLs are already pre-filled in the sidebar.  
2. Click **Load Demo Data** to process them.  
3. Choose a mode (Q&A, Summarize, Extract).  
4. Use the pre-filled demo queries—or ask your own.

**What this app does**
- Loads healthcare webpages or PDFs  
- Splits content into chunks  
- Embeds + stores them in a vector database  
- Uses RAG to answer questions, summarize, or extract info  
- Shows evidence snippets for transparency  

**Important:**  
This tool is **not a medical device** and does **not** provide diagnosis or treatment.
"""
    )

# ---------------------------------------------------
# Sidebar — ingestion
# ---------------------------------------------------
with st.sidebar:
    st.header("📥 Step 1 - Provide Data Sources")

    # Prefilled demo URLs
    url1 = st.text_input(
        "URL 1",
        value="https://www.who.int/health-topics/clinical-trials#tab=tab_1",
    )
    url2 = st.text_input(
        "URL 2",
        value="https://www.cdc.gov/vaccines/basics/index.html",
    )
    url3 = st.text_input("URL 3 (optional)")

    uploaded_files = st.file_uploader(
        "Upload PDF(s)",
        type=["pdf"],
        accept_multiple_files=True
    )

    urls = [u.strip() for u in (url1, url2, url3) if u.strip()]

    # Buttons
    process_button = st.button("Process Sources", use_container_width=True)
    demo_button = st.button("Load Demo Data", use_container_width=True)

status = st.empty()


# Save PDF uploads
def _save_uploaded_pdfs(files) -> List[str]:
    paths = []
    for f in files:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(f.getbuffer())
        tmp.close()
        paths.append(tmp.name)
    return paths


# Process user sources
if process_button:
    status.info("Processing sources…")
    pdf_paths = _save_uploaded_pdfs(uploaded_files) if uploaded_files else []
    for msg in process_urls_and_pdfs(urls=urls, pdf_paths=pdf_paths):
        status.write("• " + msg)
    status.success("✅ Sources processed successfully.")

# Process demo sources
if demo_button:
    status.info("Loading demo data…")
    demo_urls = [
        "https://www.who.int/health-topics/clinical-trials#tab=tab_1",
        "https://www.cdc.gov/vaccines/basics/index.html",
    ]
    for msg in process_urls_and_pdfs(urls=demo_urls, pdf_paths=[]):
        status.write("• " + msg)
    status.success("✅ Demo data loaded successfully.")


# ---------------------------------------------------
# Step 2 — Analysis mode
# ---------------------------------------------------
st.subheader("🔎 Step 2 — Select Analysis Mode")

mode = st.radio(
    "Mode:",
    ["Q&A", "Summarize", "Extract"],
    horizontal=True,
)

# Pre-filled demo queries
demo_queries = {
    "Q&A": "What is a clinical trial and why is it important?",
    "Summarize": "Summarize the key information about clinical trials.",
    "Extract": "Briefly list the main phases of clinical trials.",
}

query = st.text_input(
    "Enter your query:",
    value=demo_queries.get(mode, ""),
)

run_button = st.button("Run analysis")


# ---------------------------------------------------
# Step 3 — Run pipeline
# ---------------------------------------------------
if run_button:
    try:
        if mode == "Q&A":
            answer, sources, snippets = generate_qa(query)
            tab1, tab2, tab3 = st.tabs(["Answer", "Evidence", "Sources"])

            with tab1:
                st.write(answer)

            with tab2:
                if snippets:
                    for i, (src, snip) in enumerate(snippets, 1):
                        with st.expander(f"Snippet {i} — {src}"):
                            st.write(snip)
                else:
                    st.info("No evidence snippets found.")

            with tab3:
                if sources:
                    for s in sources.split("\n"):
                        st.write("- " + s)
                else:
                    st.info("No sources returned.")

        elif mode == "Summarize":
            summary, snippets = generate_summary(query)
            tab1, tab2 = st.tabs(["Summary", "Evidence"])

            with tab1:
                st.write(summary)

            with tab2:
                for i, (src, snip) in enumerate(snippets, 1):
                    with st.expander(f"Snippet {i} — {src}"):
                        st.write(snip)

        elif mode == "Extract":
            out, snippets = generate_extract(query)
            tab1, tab2 = st.tabs(["Extracted Data", "Evidence"])

            with tab1:
                st.write(out)

            with tab2:
                for i, (src, snip) in enumerate(snippets, 1):
                    with st.expander(f"Snippet {i} — {src}"):
                        st.write(snip)

    except RuntimeError:
        st.error("⚠️ Please process or load data first.")

# ---------------------------------------------------
# Footer
# ---------------------------------------------------
st.markdown("---")
st.caption("⚠️ *This app is for educational purposes only and does not provide medical advice*.")