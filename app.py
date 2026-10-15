import os
import re
import tempfile
import streamlit as st
from google import genai
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Page configuration
st.set_page_config(
    page_title="WhatsApp CV Reviewer",
    page_icon="📱",
    layout="centered"
)

# Initialize Gemini Client using Streamlit secrets
api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")

if not api_key:
    st.error("Missing Gemini API Key! Please configure it in your Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

# Helper function to initialize Google Docs/Drive API client from Streamlit secrets
def get_gdocs_service():
    if "gcp_service_account" not in st.secrets:
        return None
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"]
    )
    return build('docs', 'v1', credentials=creds), build('drive', 'v3', credentials=creds)

# Extract Google Doc ID from URL
def extract_doc_id(url_or_id):
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url_or_id)
    if match:
        return match.group(1)
    return url_or_id.strip()

# System prompt enforcing a natural, friendly, encouraging tone without forced bullet points
system_prompt_content = (
    "You are an expert executive career coach reviewing CVs. "
    "Provide constructive, encouraging feedback in a natural, conversational WhatsApp style. "
    "Remember that candidates should always keep GCSEs and A levels on their CVs, restricted strictly to a single line rather than dropping them. "
    "Never use markdown asterisks, bolding, formatting symbols, or estimated numerical scores."
)

st.title("📱 WhatsApp & Docs CV Reviewer")
st.write("Upload a CV file or paste a Google Doc link for encouraging, conversational feedback.")

# Input options
uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])
doc_url = st.text_input("Or paste Google Doc Link (Optional - posts comments directly)")

cv_text_content = ""

if uploaded_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_path = tmp_file.name

    uploaded_gemini_file = client.files.upload(file=tmp_path)
    os.unlink(tmp_path)
    cv_target = uploaded_gemini_file
elif doc_url:
    docs_service, drive_service = get_gdocs_service()
    if docs_service:
        doc_id = extract_doc_id(doc_url)
        doc = docs_service.documents().get(documentId=doc_id).execute()
        
        # Extract text from doc body
        doc_content = doc.get('body').get('content')
        for element in doc_content:
            if 'paragraph' in element:
                for elem in element['paragraph'].get('elements', []):
                    if 'textRun' in elem:
                        cv_text_content += elem['textRun'].get('content')
        cv_target = f"Review this CV text content extracted from a Google Doc:\n{cv_text_content}"
    else:
        st.error("Google Service Account credentials missing in Streamlit secrets!")
        st.stop()
else:
    cv_target = None

if cv_target is not None and st.button("Generate Review"):
    with st.spinner("Reviewing CV..."):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=[
                    cv_target,
                    "Review this CV naturally. Write in a helpful, conversational WhatsApp message style with zero markdown asterisks, zero bolding, and zero scores."
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt_content,
                    temperature=0.7
                )
            )
            
            st.success("Review Generated Successfully!")
            st.subheader("WhatsApp Text Output:")
            st.text_area("Copy message below:", value=response.text, height=300)
            
            # If a Google Doc URL was provided, also post comment via Drive API
            if doc_url:
                _, drive_svc = get_gdocs_service()
                doc_id = extract_doc_id(doc_url)
                
                comment_body = {
                    'content': f"🤖 AI CV Reviewer Feedback:\n\n{response.text}"
                }
                drive_svc.comments().create(
                    fileId=doc_id,
                    body=comment_body,
                    fields='id'
                ).execute()
                st.info("Successfully posted anchored comments directly onto your Google Doc!")
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")