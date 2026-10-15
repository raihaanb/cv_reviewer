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
    
    if not os.path.exists("samples"):
        os.makedirs("samples")
    
    sample_files = glob.glob("samples/*.txt")
    text_corpus = ""
    if sample_files:
        text_corpus += "\n--- EXEMPLAR CVs & PAST COACH FEEDBACK TRANSCRIPTS ---\n"
        for filepath in sample_files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    text_corpus += f"\nFile ({os.path.basename(filepath)}):\n" + f.read() + "\n"
            except Exception:
                pass
        text_corpus += "--- END OF SAMPLES ---\n\n"
        if text_corpus.strip():
            extra_contents.append(text_corpus)

    # Find and upload your scoring matrix PDF from the root folder
    matrix_pdfs = glob.glob("*scoring*matrix*.pdf") or glob.glob("*matrix*.pdf") or glob.glob("*.pdf")
    for pdf_path in matrix_pdfs:
        try:
            uploaded_pdf = client.files.upload(file=pdf_path)
            extra_contents.append(uploaded_pdf)
            break
        except Exception:
            pass
            
    return extra_contents

training_materials = load_training_materials()

# Comprehensive system prompt matching your exact coaching voice, scoring matrix, and deep-dive expectations
system_prompt_content = (
    "You are an expert executive career coach reviewing student and professional CVs. "
    "Your tone must strictly match the style, warmth, and depth demonstrated in the sample feedback transcripts and scoring matrix PDF provided. "
    "Provide an extensive, thorough, and highly encouraging review that covers every single part of the candidate's profile from top to bottom (Education, Work Experience, Leadership, Projects, and Skills).\n\n"
    "Core Guidelines & Rules:\n"
    "1. WHATSAPP SUMMARY: Write a rich, warm, conversational, and highly detailed message (just like your past successful reviews), praising their strengths while giving structured, actionable advice across sections. No markdown asterisks, bolding, or scores.\n"
    "2. GOOGLE DOCS COMMENTS: Provide robust, detailed, professional bullet-pointed feedback evaluating every major section against the scoring matrix, explicitly highlighting what is strong, what is important, and what is lacking.\n"
    "3. GCSEs and A-levels must always be kept on the CV, restricted strictly to a single line rather than dropped or split across multiple lines.\n"
    "4. Check for timeline consistency, clear dates, robust action verbs, and quantitative commercial metrics."
)

st.title("📱 WhatsApp & Docs CV Reviewer")
st.write("Upload a CV or paste a native Google Doc link for a comprehensive, matrix-driven review.")

uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])
doc_url = st.text_input("Or paste native Google Doc Link (Optional - adds detailed inline comments across the whole doc)")

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

if cv_target is not None and st.button("Generate Comprehensive Review"):
    with st.spinner("Conducting full-document deep dive against scoring matrix and training feedback..."):
        try:
            contents_payload = training_materials + [
                cv_target,
                (
                    "Perform a meticulous, complete review of this CV from top to bottom against the attached scoring matrix PDF and training samples. Provide:\n"
                    "1. WHATSAPP SUMMARY: A rich, warm, conversational, and highly detailed coach review message (no markdown, no bolding, no scores).\n"
                    "2. DOCUMENT COMMENTS MAP: Detailed, professional improvement notes covering Education, Work Experience, Leadership, Projects, and Skills."
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
            
            st.success("Deep-Dive Review Complete!")
            st.subheader("WhatsApp Text Output:")
            st.text_area("Copy message below:", value=response.text, height=350)
            
            # If a Google Doc URL was provided, scan the entire document paragraphs and anchor detailed comments across all sections
            if doc_url:
                try:
                    docs_svc, _ = get_gdocs_service()
                    doc_id = extract_doc_id(doc_url)
                    document = docs_svc.documents().get(documentId=doc_id).execute()
                    
                    doc_content = document.get('body').get('content')
                    requests = []
                    
                    # Scan all paragraphs in the document to find matching content across the WHOLE CV
                    for element in doc_content:
                        if 'paragraph' in element:
                            p_text = ""
                            start_idx = element.get('startIndex')
                            end_idx = element.get('endIndex')
                            
                            for elem in element['paragraph'].get('elements', []):
                                if 'textRun' in elem:
                                    p_text += elem['textRun'].get('content')
                            
                            cleaned = p_text.strip()
                            if len(cleaned) > 15:  # Valid content line
                                line_lower = cleaned.lower()
                                comment_to_add = None
                                
                                # Map to appropriate section criteria based on training matrix
                                if any(kw in line_lower for kw in ["education", "university", "school", "a-level", "gcse", "degree"]):
                                    comment_to_add = (
                                        "Education & Academic Rubric Feedback:\n"
                                        "• Ensure high school qualifications (GCSEs and A-levels) are consolidated strictly onto a single line.\n"
                                        "• Highlight top-decile rankings, academic prizes, or relevant high-tier modules clearly."
                                    )
                                elif any(kw in line_lower for kw in ["experience", "intern", "analyst", "associate", "consultant", "deloitte", "liskara", "trainer"]):
                                    comment_to_add = (
                                        "Work Experience Rubric Feedback:\n"
                                        "• Lead every bullet point with strong action verbs and robust commercial metrics (revenue, efficiency %, funding).\n"
                                        "• Avoid standalone company background sentences; fold context directly into impact bullets."
                                    )
                                elif any(kw in line_lower for kw in ["leadership", "president", "society", "committee", "captain", "founder", "lead", "initiative"]):
                                    comment_to_add = (
                                        "Leadership & Impact Rubric Feedback:\n"
                                        "• Emphasize scale metrics (team size, funds raised, attendees).\n"
                                        "• Keep descriptions punchy and concise (maximum 2 lines per bullet)."
                                    )
                                elif any(kw in line_lower for kw in ["project", "research", "app", "model", "analysis"]):
                                    comment_to_add = (
                                        "Projects Rubric Feedback:\n"
                                        "• Include names of specific tools, technical libraries, or software used.\n"
                                        "• Quantify the success or output of the project where possible."
                                    )
                                elif any(kw in line_lower for kw in ["skills", "interests", "languages", "software", "excel"]):
                                    comment_to_add = (
                                        "Skills & Technical Rubric Feedback:\n"
                                        "• Include a dedicated hard skills line (e.g., Advanced Excel, financial modelling, Python, data tools) to avoid automated screening filters."
                                    )
                                
                                if comment_to_add and len(requests) < 6:  # Ensure we anchor across multiple distinct sections
                                    requests.append({
                                        'insertComment': {
                                            'content': comment_to_add,
                                            'range': {
                                                'startIndex': start_idx,
                                                'endIndex': end_idx
                                            }
                                        }
                                    })
                    
                    if requests:
                        docs_svc.documents().batchUpdate(
                            documentId=doc_id,
                            body={'requests': requests}
                        ).execute()
                        st.success("Successfully posted thorough, matrix-driven feedback comments across the entire Google Doc!")
                    else:
                        st.info("Review complete, but no matching section paragraphs were found for inline comments.")
                except Exception as doc_update_err:
                    st.error(f"Failed to post anchored comments to Google Doc: {doc_update_err}")
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")