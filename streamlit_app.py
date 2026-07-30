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

search_query = st.text_input("Search documents, topics, or dates...")

if search_query:
    if not os.path.exists(DB_PATH):
        st.error(f"Database not found at: {DB_PATH}. Please ensure the .db file is in this folder.")
    else:
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

            # Render clean table
            st.dataframe(
                results_df,
                hide_index=True,
                use_container_width=True
            )

            # Render CSV Export button
            csv_data = results_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Export Search to CSV",
                data=csv_data,
                file_name='sunshine_results.csv',
                mime='text/csv'
            )

            st.divider()

            # ---- SECURE PDF DOWNLOADER (PROXY) ----
            st.subheader("Secure Document Retrieval")
            
            # Create a 2-column layout
            col1, col2 = st.columns([2, 1])
            
            with col1:
                unique_files = results_df['Filename'].unique()
                selected_file = st.selectbox("Available Documents", unique_files, label_visibility="collapsed")
                target_filename = re.sub(r'[();]', '_', selected_file).replace('__', '_')
            
            with col2:
                if st.button("Fetch PDF", use_container_width=True):
                    with st.spinner("Retrieving..."):
                        encoded_filename = urllib.parse.quote(target_filename)
                        server_url = f"https://festus-records.duckdns.org/{encoded_filename}"
                        
                        try:
                            response = requests.get(server_url, auth=(AUTH_USER, AUTH_PASS), timeout=20)
                            if response.status_code == 200:
                                st.session_state['pdf_data'] = response.content
                                st.session_state['pdf_name'] = target_filename
                            elif response.status_code == 401:
                                st.error("Authentication failed. Check your DuckDNS username/password in Streamlit secrets.")
                            elif response.status_code == 404:
                                st.error(f"File not found on server. Looked for: {target_filename}")
                            else:
                                st.error(f"Server error: {response.status_code}")
                        except Exception as e:
                            st.error(f"Connection failed: {e}")

            # Display the download button immediately below the fetch button if data exists
            if 'pdf_data' in st.session_state and st.session_state.get('pdf_name') == target_filename:
                with col2:
                    st.download_button(
                        label="💾 Save PDF",
                        data=st.session_state['pdf_data'],
                        file_name=st.session_state['pdf_name'],
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )