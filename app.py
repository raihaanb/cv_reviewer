import os
import re
import json
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

# System prompt strictly enforcing your 6 CORE RULES
system_prompt_content = (
    "You are an expert executive career coach reviewing student and professional CVs.\n"
    "Your tone, rigor, and coaching style must strictly match the loaded training samples and scoring matrix PDF provided. Avoid all generic AI filler and corporate slop.\n\n"
    "CRITICAL CORE RULES:\n"
    "1. NEVER REPEAT ANY BULLET COMMENTS: Every comment must be 100% unique. Zero boilerplate or repeated feedback.\n"
    "2. ALL COMMENTS MUST BE CONTEXT-DEPENDENT: You MUST explicitly mention specific details, roles, companies, or projects (e.g., ISOC, Deloitte, Liskara, Wrestling, Forest School, GCSEs) in the text of each comment.\n"
    "3. READ AND COVER THE WHOLE CV: Review the candidate's document from top to bottom across all sections (Education, Work Experience, Leadership, Projects, and Skills).\n"
    "4. NOT GENERIC, BASED ON TRAINING: Feedback must align with the coaching philosophy and standards set out in the attached exemplars and scoring matrix.\n"
    "5. SPECIFIC POINTS (NO HEADINGS): Never comment on section titles or headers (e.g. 'Work Experience', 'Education'). Comments must anchor strictly to individual bullet points and specific achievement entries.\n"
    "6. NO LIMITS ON NUMBER OF COMMENTS: Every qualifying bullet point across the document should receive a dedicated comment.\n"
    "7. WHATSAPP SUMMARY: Keep it short, casual, and direct. NO excessive AI praise or fluff at the start. State that the CV looks solid and that detailed feedback has been left directly in the Google Doc. (Zero markdown asterisks, zero bolding, zero scores)."
)

st.title("📱 WhatsApp & Docs CV Reviewer")
st.write("Upload a CV or paste a native Google Doc link for a concise WhatsApp note and bespoke rubric comments.")

uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])
doc_url = st.text_input("Or paste native Google Doc Link (Optional - adds bespoke inline comments across the whole doc)")

cv_target = None
extracted_paragraphs = []

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
                    p_text = ""
                    start_idx = element.get('startIndex')
                    end_idx = element.get('endIndex')
                    for elem in element['paragraph'].get('elements', []):
                        if 'textRun' in elem:
                            p_text += elem['textRun'].get('content')
                    
                    cleaned = p_text.strip()
                    # Filter out short lines, headers, or empty spaces to isolate actual bullets and achievement entries
                    if len(cleaned) > 15:
                        lower_c = cleaned.lower()
                        # Strict rule 5: Filter out section titles and headers
                        is_header = cleaned.isupper() or (any(h in lower_c for h in ["education", "work experience", "leadership and impact", "skills and interests", "projects", "modules"]) and len(cleaned) < 35)
                        if not is_header:
                            extracted_paragraphs.append({
                                'text': cleaned,
                                'startIndex': start_idx,
                                'endIndex': end_idx
                            })
                            
                    cv_text_content += p_text + "\n"
                    
            cv_target = f"Review this complete CV text content extracted from a Google Doc:\n{cv_text_content}"
        except Exception as fetch_err:
            st.error(f"Failed to fetch Google Doc. Make sure it is a native Google Doc and shared with your service account email as an Editor! Details: {fetch_err}")
            st.stop()
    else:
        st.error("Google Service Account credentials missing in Streamlit secrets!")
        st.stop()

if cv_target is not None and st.button("Generate Matrix-Driven Review"):
    with st.spinner("Analyzing full CV against scoring matrix and training exemplars..."):
        try:
            # 1. Generate the concise WhatsApp summary message
            whatsapp_response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=training_materials + [
                    cv_target,
                    (
                        "Write a short, casual, direct WhatsApp message to the candidate stating their CV looks solid and that detailed feedback has been left directly on their Google Doc. "
                        "Do not include generic AI praise or fluff at the start. Do not use markdown, bolding, or scores."
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt_content,
                    temperature=0.7
                )
            )
            
            st.success("Review Complete!")
            st.subheader("WhatsApp Text Output (Short & Direct):")
            st.text_area("Copy message below:", value=whatsapp_response.text, height=150)
            
            # 2. Generate 100% bespoke, non-repeating comments for EVERY extracted bullet point across the document
            if doc_url and extracted_paragraphs:
                try:
                    docs_svc, _ = get_gdocs_service()
                    doc_id = extract_doc_id(doc_url)
                    
                    bullets_payload = ["Here are the specific bullet points and entry lines extracted across the entire CV:\n"]
                    for idx, ep in enumerate(extracted_paragraphs):
                        bullets_payload.append(f"[{idx}] {ep['text']}\n")
                    
                    bullets_payload.append(
                        "\nINSTRUCTIONS FOR COMMENTS:\n"
                        "For EVERY bullet point listed above, generate a completely unique, context-dependent coaching comment. "
                        "1. You MUST explicitly name the specific company, role, society, or qualification (e.g. ISOC, Deloitte, Liskara, Wrestling, Forest School, GCSEs) in the text of the comment.\n"
                        "2. Provide sharp, non-repeating feedback based on the attached scoring matrix PDF and training exemplars.\n"
                        "3. Return strictly a JSON array of objects with keys 'index' (int) and 'comment' (string)."
                    )
                    
                    comment_response = client.models.generate_content(
                        model='gemini-3.8-flash',
                        contents=training_materials + bullets_payload,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt_content,
                            response_mime_type="application/json",
                            temperature=0.7
                        )
                    )
                    
                    comment_data = json.loads(comment_response.text)
                    comment_map = {item['index']: item['comment'] for item in comment_data if 'index' in item and 'comment' in item}
                    
                    requests = []
                    for idx, ep in enumerate(extracted_paragraphs):
                        if idx in comment_map:
                            requests.append({
                                'insertComment': {
                                    'content': comment_map[idx],
                                    'range': {
                                        'startIndex': ep['startIndex'],
                                        'endIndex': ep['endIndex']
                                    }
                                }
                            })
                    
                    if requests:
                        docs_svc.documents().batchUpdate(
                            documentId=doc_id,
                            body={'requests': requests}
                        ).execute()
                        st.success(f"Successfully posted {len(requests)} 100% unique, bespoke comments across the entire Google Doc!")
                    else:
                        st.info("Review complete, but no comment mappings were returned.")
                except Exception as doc_update_err:
                    st.error(f"Failed to post anchored comments to Google Doc: {doc_update_err}")
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")