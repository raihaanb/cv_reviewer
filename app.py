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
    page_title="WhatsApp & Docs CV Reviewer",
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
        return None, None
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

# System prompt enforcing natural tone + GCSE/A-level single line rule
system_prompt_content = (
    "You are an expert executive career coach reviewing CVs. "
    "Provide constructive, encouraging feedback in a natural, conversational WhatsApp style for the general overview. "
    "For specific sections (like Education and Work Experience), provide professional, concise, bullet-pointed improvement notes. "
    "Remember that candidates should always keep GCSEs and A levels on their CVs, restricted strictly to a single line rather than dropping them. "
    "Never use markdown asterisks or estimated numerical scores in your general feedback."
)

st.title("📱 WhatsApp & Docs CV Reviewer")
st.write("Upload a CV file or paste a Google Doc link for conversational summaries and inline anchored comments.")

# Input options
uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])
doc_url = st.text_input("Or paste Google Doc Link (Optional - adds inline anchored comments)")

cv_text_content = ""
doc_sections = {}

if uploaded_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_path = tmp_file.name

    uploaded_gemini_file = client.files.upload(file=tmp_path)
    os.unlink(tmp_path)
    cv_target = uploaded_gemini_file
elif doc_url:
    docs_service, _ = get_gdocs_service()
    if docs_service:
        try:
            doc_id = extract_doc_id(doc_url)
            document = docs_service.documents().get(documentId=doc_id).execute()
            
            # Extract text and track section positions for anchored comments
            doc_content = document.get('body').get('content')
            for element in doc_content:
                if 'paragraph' in element:
                    p_text = ""
                    start_idx = element.get('startIndex')
                    end_idx = element.get('endIndex')
                    for elem in element['paragraph'].get('elements', []):
                        if 'textRun' in elem:
                            p_text += elem['textRun'].get('content')
                    
                    cleaned_line = p_text.strip()
                    cv_text_content += p_text
                    
                    # Track major section headers for anchoring
                    if cleaned_line.lower() in ["education", "work experience", "leadership and impact", "skills and interests"]:
                        doc_sections[cleaned_line.lower()] = {'startIndex': start_idx, 'endIndex': end_idx}

            cv_target = f"Review this CV text content extracted from a Google Doc:\n{cv_text_content}"
        except Exception as fetch_err:
            st.error(f"Failed to fetch Google Doc. Make sure it is shared with your service account email as an Editor! Details: {fetch_err}")
            st.stop()
    else:
        st.error("Google Service Account credentials missing in Streamlit secrets!")
        st.stop()
else:
    cv_target = None

if cv_target is not None and st.button("Generate Review"):
    with st.spinner("Reviewing CV and preparing anchored feedback..."):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=[
                    cv_target,
                    (
                        "Provide two things:\n"
                        "1. GENERAL WHATSAPP REVIEW: A friendly, conversational WhatsApp summary message (no markdown asterisks or scores).\n"
                        "2. SECTION COMMENTS: Specific, professional, bullet-pointed feedback for 'Education' (e.g. academic prizes, modules) and 'Work Experience' (e.g. metrics, impact)."
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt_content,
                    temperature=0.7
                )
            )
            
            st.success("Review Generated Successfully!")
            st.subheader("WhatsApp Text Output:")
            st.text_area("Copy message below:", value=response.text, height=300)
            
            # If a Google Doc URL was provided, insert anchored comments into specific sections
            if doc_url and doc_sections:
                try:
                    docs_svc, _ = get_gdocs_service()
                    doc_id = extract_doc_id(doc_url)
                    
                    requests = []
                    
                    # Build anchored comment for Education if present
                    if "education" in doc_sections:
                        edu_range = doc_sections["education"]
                        requests.append({
                            'insertComment': {
                                'content': "Education Feedback:\n• Highlight specific academic prizes, honors, or top-decile rankings clearly.\n• Keep GCSEs and A levels strictly to a single line.",
                                'range': {
                                    'startIndex': edu_range['startIndex'],
                                    'endIndex': edu_range['endIndex']
                                }
                            }
                        })
                    
                    # Build anchored comment for Work Experience if present
                    if "work experience" in doc_sections:
                        work_range = doc_sections["work experience"]
                        requests.append({
                            'insertComment': {
                                'content': "Work Experience Feedback:\n• Emphasize quantitative business metrics and tangible outcomes.\n• Ensure strong action verbs start each bullet point.",
                                'range': {
                                    'startIndex': work_range['startIndex'],
                                    'endIndex': work_range['endIndex']
                                }
                            }
                        })
                    
                    if requests:
                        docs_svc.documents().batchUpdate(
                            documentId=doc_id,
                            body={'requests': requests}
                        ).execute()
                        st.success("Successfully posted professional, bullet-pointed anchored comments onto your Google Doc sections!")
                    else:
                        st.info("General review complete, but specific section headers weren't matched for inline anchoring.")
                except Exception as doc_update_err:
                    st.error(f"Failed to post anchored comments to Google Doc: {doc_update_err}")
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")