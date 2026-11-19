import streamlit as st
import sqlite3
import pandas as pd
import urllib.parse
import re
import os
import requests

# ---- CONFIGURATION ----
DB_PATH = "resources/sunshine_records.db" if os.path.exists("resources/sunshine_records.db") else "sunshine_records.db"

# Fetch credentials securely from Streamlit Cloud Secrets
AUTH_USER = st.secrets["AUTH_USER"]
AUTH_PASS = st.secrets["AUTH_PASS"]
# -----------------------

st.set_page_config(page_title="Festus Sunshine Search", layout="wide")
st.title("Festus Sunshine Database Search")


def render_pdf_fetcher(file_list, key_prefix):
    """Reusable secure PDF fetcher component."""
    st.subheader("Secure Document Retrieval")
    col1, col2 = st.columns([2, 1])

    with col1:
        selected_file = st.selectbox(
            "Available Documents",
            file_list,
            label_visibility="collapsed",
            key=f"{key_prefix}_select"
        )
        target_filename = re.sub(r'[();]', '_', selected_file).replace('__', '_')

    with col2:
        if st.button("Fetch PDF", use_container_width=True, key=f"{key_prefix}_fetch"):
            with st.spinner("Retrieving..."):
                encoded_filename = urllib.parse.quote(target_filename)
                server_url = f"https://festus-records.duckdns.org/{encoded_filename}"

                try:
                    response = requests.get(server_url, auth=(AUTH_USER, AUTH_PASS), timeout=20)
                    if response.status_code == 200:
                        st.session_state[f'{key_prefix}_pdf_data'] = response.content
                        st.session_state[f'{key_prefix}_pdf_name'] = target_filename
                    elif response.status_code == 401:
                        st.error("Authentication failed. Check your DuckDNS username/password in Streamlit secrets.")
                    elif response.status_code == 404:
                        st.error(f"File not found on server. Looked for: {target_filename}")
                    else:
                        st.error(f"Server error: {response.status_code}")
                except Exception as e:
                    st.error(f"Connection failed: {e}")

    if (
        f'{key_prefix}_pdf_data' in st.session_state
        and st.session_state.get(f'{key_prefix}_pdf_name') == target_filename
    ):
        with col2:
            st.download_button(
                label="💾 Save PDF",
                data=st.session_state[f'{key_prefix}_pdf_data'],
                file_name=st.session_state[f'{key_prefix}_pdf_name'],
                mime="application/pdf",
                type="primary",
                use_container_width=True,
                key=f"{key_prefix}_save"
            )


if not os.path.exists(DB_PATH):
    st.error(f"Database not found at: {DB_PATH}. Please ensure the .db file is in this folder.")
    st.stop()

# Load summary stats for the header and directory tab
conn = sqlite3.connect(DB_PATH)
directory_df = pd.read_sql_query(
    """
    SELECT filename AS "Document Name", COUNT(*) AS "Indexed Pages"
    FROM documents
    GROUP BY filename
    ORDER BY filename ASC
    """,
    conn
)
conn.close()

total_docs = len(directory_df)
total_pages = int(directory_df["Indexed Pages"].sum()) if not directory_df.empty else 0
st.caption(f"Currently indexing **{total_docs} documents** ({total_pages:,} total pages) from the City of Festus Sunshine & Data Center records.")

tab_search, tab_directory = st.tabs(["🔍 Search Records", "📂 Full Document Rundown"])

# ---- TAB 1: KEYWORD SEARCH ----
with tab_search:
    search_query = st.text_input("Search documents, topics, or dates...")

    if search_query:
        conn = sqlite3.connect(DB_PATH)
        sql = """
            SELECT id, filename, page_number, content
            FROM documents
            WHERE filename LIKE ? OR content LIKE ?
            LIMIT 100
        """
        search_param = f"%{search_query}%"
        df = pd.read_sql_query(sql, conn, params=(search_param, search_param))
        conn.close()

        if df.empty:
            st.info("No matching records found.")
        else:
            st.success(f"Found {len(df)} matching record(s).")

            display_data = []
            for _, row in df.iterrows():
                content_str = str(row['content']) if pd.notna(row['content']) else ""

                idx = content_str.lower().find(search_query.lower())
                if idx != -1:
                    start = max(0, idx - 40)
                    end = min(len(content_str), idx + len(search_query) + 80)
                    snippet = f"...{content_str[start:end].replace(chr(10), ' ').strip()}..."
                else:
                    snippet = content_str[:100].replace(chr(10), ' ').strip() + "..." if content_str else "No text"

                display_data.append({
                    "ID": row['id'],
                    "Filename": row['filename'],
                    "Page Number": row['page_number'],
                    "Mention Snippet": snippet
                })

            results_df = pd.DataFrame(display_data)

            st.dataframe(results_df, hide_index=True, use_container_width=True)

            csv_data = results_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Export Search to CSV",
                data=csv_data,
                file_name='sunshine_results.csv',
                mime='text/csv'
            )

            st.divider()
            render_pdf_fetcher(results_df['Filename'].unique(), key_prefix="search")

# ---- TAB 2: FULL DOCUMENT DIRECTORY ----
with tab_directory:
    st.write("Browse every document currently indexed in the database and fetch any file directly.")
    st.dataframe(directory_df, hide_index=True, use_container_width=True)

    if not directory_df.empty:
        st.divider()
        render_pdf_fetcher(directory_df['Document Name'].tolist(), key_prefix="dir")