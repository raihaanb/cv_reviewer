import os
import re
import glob
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

# Dynamic loader: reads text samples from 'samples/' AND uploads your root scoring matrix PDF
def load_training_materials():
    extra_contents = []
    
    # 1. Load text files from the samples folder
    if not os.path.exists("samples"):
        os.makedirs("samples")
    
    sample_files = glob.glob("samples/*.txt")
    text_corpus = ""
    if sample_files:
        text_corpus += "\n--- EXEMPLAR CVs & COACH FEEDBACK ---\n"
        for filepath in sample_files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    text_corpus += f"\nFile ({os.path.basename(filepath)}):\n" + f.read() + "\n"
            except Exception:
                pass
        text_corpus += "--- END OF SAMPLES ---\n\n"
        if text_corpus.strip():
            extra_contents.append(text_corpus)

    # 2. Find and upload your scoring matrix PDF from the main folder
    matrix_pdfs = glob.glob("*scoring*matrix*.pdf") or glob.glob("*matrix*.pdf") or glob.glob("*.pdf")
    for pdf_path in matrix_pdfs:
        try:
            uploaded_pdf = client.files.upload(file=pdf_path)
            extra_contents.append(uploaded_pdf)
            break # Upload the first matching scoring matrix PDF found
        except Exception:
            pass
            
    return extra_contents

# Load training materials dynamically into context
training_materials = load_training_materials()

# System prompt incorporating style exemplars, scoring matrix PDF, and strict rules
system_prompt_content = (
    "You are an expert executive career coach reviewing student and professional CVs. "
    "Your tone must strictly match the style, warmth, and depth demonstrated in the sample feedback provided. "
    "You must rigorously evaluate the CV against the attached scoring matrix PDF, explicitly identifying what meets the criteria, what is strong/important, and what critical elements are lacking.\n\n"
    "Core Rules to Enforce Across the CV:\n"
    "1. Candidates must always keep GCSEs and A-levels on their CVs, restricted strictly to a single line.\n"
    "2. Your WhatsApp summary must be a warm, natural, conversational message (zero markdown asterisks, zero bolding, zero scores).\n"
    "3. Perform a comprehensive, deep-dive review across all sections (Education, Work Experience, Leadership, and Skills).\n"
    "4. Explicitly highlight matrix-driven strengths and missing criteria."
)

st.title("📱 WhatsApp & Docs CV Reviewer")
st.write("Upload a CV file or paste a native Google Doc link for a complete review driven by your scoring matrix PDF and training samples.")

# Input options
uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])
doc_url = st.text_input("Or paste native Google Doc Link (Optional - adds targeted inline comments)")

cv_target = None

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
            
            cv_text_content = ""
            doc_content = document.get('body').get('content')
            for element in doc_content:
                if 'paragraph' in element:
                    for elem in element['paragraph'].get('elements', []):
                        if 'textRun' in elem:
                            cv_text_content += elem['textRun'].get('content')
            cv_target = f"Review this complete CV text content extracted from a Google Doc:\n{cv_text_content}"
        except Exception as fetch_err:
            st.error(f"Failed to fetch Google Doc. Make sure it is a native Google Doc and shared with your service account email as an Editor! Details: {fetch_err}")
            st.stop()
    else:
        st.error("Google Service Account credentials missing in Streamlit secrets!")
        st.stop()

if cv_target is not None and st.button("Generate Matrix-Driven Review"):
    with st.spinner("Analyzing CV against your scoring matrix PDF and training exemplars..."):
        try:
            # Bundle training materials (PDF scoring matrix + text exemplars) + CV target
            contents_payload = training_materials + [
                cv_target,
                (
                    "Perform a meticulous review of this CV against the attached scoring matrix PDF and training samples. Provide:\n"
                    "1. WHATSAPP SUMMARY: A warm, natural, conversational message highlighting key strengths, importance, and what's lacking according to the matrix (no markdown, no bolding, no scores).\n"
                    "2. SECTION COMMENTS: Targeted, professional improvement notes for Education, Work Experience, Leadership, and Skills based on the rubric criteria."
                )
            ]
            
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=contents_payload,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt_content,
                    temperature=0.7
                )
            )
            
            st.success("Matrix-Driven Review Complete!")
            st.subheader("WhatsApp Text Output:")
            st.text_area("Copy message below:", value=response.text, height=300)
            
            # If a Google Doc URL was provided, re-fetch section positions and insert comments
            if doc_url:
                try:
                    docs_svc, _ = get_gdocs_service()
                    doc_id = extract_doc_id(doc_url)
                    document = docs_svc.documents().get(documentId=doc_id).execute()
                    
                    doc_sections = {}
                    doc_content = document.get('body').get('content')
                    for element in doc_content:
                        if 'paragraph' in element:
                            p_text = ""
                            start_idx = element.get('startIndex')
                            end_idx = element.get('endIndex')
                            for elem in element['paragraph'].get('elements', []):
                                if 'textRun' in elem:
                                    p_text += elem['textRun'].get('content')
                            cleaned_line = p_text.strip().lower()
                            
                            if "education" in cleaned_line:
                                doc_sections['education'] = {'startIndex': start_idx, 'endIndex': end_idx}
                            elif "work experience" in cleaned_line:
                                doc_sections['work experience'] = {'startIndex': start_idx, 'endIndex': end_idx}
                            elif "leadership" in cleaned_line:
                                doc_sections['leadership'] = {'startIndex': start_idx, 'endIndex': end_idx}
                            elif "skills" in cleaned_line or "interests" in cleaned_line:
                                doc_sections['skills'] = {'startIndex': start_idx, 'endIndex': end_idx}
                    
                    requests = []
                    if "education" in doc_sections:
                        edu = doc_sections["education"]
                        requests.append({
                            'insertComment': {
                                'content': "Education Feedback (Matrix Rubric):\n• Consolidate A-levels and GCSEs strictly onto a single line.\n• Highlight top-decile rankings or specific academic prizes.",
                                'range': {'startIndex': edu['startIndex'], 'endIndex': edu['endIndex']}
                            }
                        })
                    if "work experience" in doc_sections:
                        work = doc_sections["work experience"]
                        requests.append({
                            'insertComment': {
                                'content': "Work Experience Feedback (Matrix Rubric):\n• Ensure bullets lead with strong action verbs and quantitative metrics.\n• Remove standalone company descriptions.",
                                'range': {'startIndex': work['startIndex'], 'endIndex': work['endIndex']}
                            }
                        })
                    if "leadership" in doc_sections:
                        lead = doc_sections["leadership"]
                        requests.append({
                            'insertComment': {
                                'content': "Leadership Feedback (Matrix Rubric):\n• Verify scale metrics (team size, funding figures, attendance).\n• Keep descriptions punchy and concise.",
                                'range': {'startIndex': lead['startIndex'], 'endIndex': lead['endIndex']}
                            }
                        })
                    if "skills" in doc_sections:
                        skl = doc_sections["skills"]
                        requests.append({
                            'insertComment': {
                                'content': "Skills & Interests Feedback (Matrix Rubric):\n• Add a dedicated hard skills line (e.g., Advanced Excel, financial modelling, Python) to fill missing technical competencies.",
                                'range': {'startIndex': skl['startIndex'], 'endIndex': skl['endIndex']}
                            }
                        })
                    
                    if requests:
                        docs_svc.documents().batchUpdate(
                            documentId=doc_id,
                            body={'requests': requests}
                        ).execute()
                        st.success("Successfully posted matrix-driven anchored comments onto your Google Doc!")
                except Exception as doc_update_err:
                    st.error(f"Failed to post anchored comments to Google Doc: {doc_update_err}")
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")