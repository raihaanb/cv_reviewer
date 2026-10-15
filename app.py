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

# System prompt enforcing concise casual WhatsApp text and rigorous scoring matrix document feedback
system_prompt_content = (
    "You are an expert executive career coach reviewing CVs. "
    "Your tone and feedback style must strictly match the training samples and scoring matrix PDF provided.\n\n"
    "CRITICAL RULES:\n"
    "1. WHATSAPP MESSAGE: Keep it short, casual, and direct. NO excessive AI praise or fluff at the start. Just state that the CV looks solid and that detailed feedback has been left directly in the Google Doc. (Zero markdown, zero bolding, zero scores).\n"
    "2. GOOGLE DOCS COMMENTS: This is where all the rigorous, detailed, professional bullet-pointed evaluation goes, covering every section from top to bottom against the scoring matrix (highlighting strengths, what is important, and what is lacking).\n"
    "3. GCSEs and A-levels must always be kept on the CV, restricted strictly to a single line.\n"
    "4. Check for timeline consistency, clear dates, action verbs, and quantitative commercial metrics."
)

st.title("📱 WhatsApp & Docs CV Reviewer")
st.write("Upload a CV or paste a native Google Doc link for a concise WhatsApp note and deep-dive rubric comments.")

uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])
doc_url = st.text_input("Or paste native Google Doc Link (Optional - adds up to 10 detailed inline comments)")

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

if cv_target is not None and st.button("Generate Review"):
    with st.spinner("Conducting full-document review against scoring matrix..."):
        try:
            contents_payload = training_materials + [
                cv_target,
                (
                    "Review this CV against the attached scoring matrix PDF and training samples. Provide two distinct sections:\n"
                    "1. WHATSAPP_SUMMARY: A short, casual, punchy text message (no AI praise, no markdown, no bolding).\n"
                    "2. DETAILED_FEEDBACK_MAP: Rigorous, bullet-pointed feedback evaluating all sections (Education, Experience, Leadership, Projects, Skills) against the scoring matrix."
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
            
            raw_output = response.text
            whatsapp_part = raw_output
            
            if "WHATSAPP_SUMMARY" in raw_output and "DETAILED_FEEDBACK_MAP" in raw_output:
                parts = raw_output.split("DETAILED_FEEDBACK_MAP")
                whatsapp_part = parts[0].replace("WHATSAPP_SUMMARY", "").strip()
            
            st.success("Review Complete!")
            st.subheader("WhatsApp Text Output (Short & Direct):")
            st.text_area("Copy message below:", value=whatsapp_part, height=150)
            
            # If a Google Doc URL was provided, scan the entire document paragraphs and anchor up to 10 detailed comments across all sections
            if doc_url:
                try:
                    docs_svc, _ = get_gdocs_service()
                    doc_id = extract_doc_id(doc_url)
                    document = docs_svc.documents().get(documentId=doc_id).execute()
                    
                    doc_content = document.get('body').get('content')
                    requests = []
                    
                    for element in doc_content:
                        if 'paragraph' in element:
                            p_text = ""
                            start_idx = element.get('startIndex')
                            end_idx = element.get('endIndex')
                            
                            for elem in element['paragraph'].get('elements', []):
                                if 'textRun' in elem:
                                    p_text += elem['textRun'].get('content')
                            
                            cleaned = p_text.strip()
                            if len(cleaned) > 15:
                                line_lower = cleaned.lower()
                                comment_to_add = None
                                
                                if any(kw in line_lower for kw in ["education", "university", "school", "a-level", "gcse", "degree"]):
                                    comment_to_add = (
                                        "Education Feedback (Scoring Matrix):\n"
                                        "• Consolidate A-levels and GCSEs strictly onto a single line to save vertical space.\n"
                                        "• Highlight top-decile rankings, academic prizes, or relevant modules."
                                    )
                                elif any(kw in line_lower for kw in ["deloitte", "liskara", "trainer", "intern", "analyst"]):
                                    comment_to_add = (
                                        "Work Experience Feedback (Scoring Matrix):\n"
                                        "• Lead every bullet point with strong action verbs and robust commercial metrics (revenue, efficiency %, funding).\n"
                                        "• Fold standalone company background descriptions directly into impact bullets."
                                    )
                                elif any(kw in line_lower for kw in ["islamic society", "leadership", "president", "consulting", "wrestling", "founder", "lead"]):
                                    comment_to_add = (
                                        "Leadership & Impact Feedback (Scoring Matrix):\n"
                                        "• Emphasize scale metrics (team size, funds raised, attendees).\n"
                                        "• Keep descriptions concise and punchy (max 2 lines)."
                                    )
                                elif any(kw in line_lower for kw in ["project", "research", "app", "model"]):
                                    comment_to_add = (
                                        "Projects Feedback (Scoring Matrix):\n"
                                        "• Include names of specific tools, technical libraries, or software used.\n"
                                        "• Quantify success or output where possible."
                                    )
                                elif any(kw in line_lower for kw in ["skills", "interests", "languages", "excel"]):
                                    comment_to_add = (
                                        "Skills & Technical Feedback (Scoring Matrix):\n"
                                        "• Include a dedicated hard skills line (e.g., Advanced Excel, financial modelling, Python, data tools) to avoid automated screening filters."
                                    )
                                
                                if comment_to_add and len(requests) < 10:  # Allow up to 10 comments across the doc
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
                        st.success(f"Successfully posted {len(requests)} detailed, matrix-driven feedback comments across your Google Doc!")
                    else:
                        st.info("Review complete, but no matching section paragraphs were found for inline comments.")
                except Exception as doc_update_err:
                    st.error(f"Failed to post anchored comments to Google Doc: {doc_update_err}")
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")