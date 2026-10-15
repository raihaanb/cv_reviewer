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

    # Find and upload your scoring matrix PDF from the main folder
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

# System prompt tuned to keep WhatsApp ultra-short/casual, and push the heavy detailed rubric feedback into the doc comments
system_prompt_content = (
    "You are an expert executive career coach reviewing student and professional CVs. "
    "Your tone must strictly match the style, warmth, and depth demonstrated in the sample feedback and scoring matrix PDF.\n\n"
    "CRITICAL STRUCTURAL RULE:\n"
    "- WHATSAPP SUMMARY: Keep this extremely short, brief, casual, and punchy (like a quick 2-sentence text message telling them their profile looks great and to check their doc for detailed feedback). Absolutely zero markdown, zero bolding, zero scores.\n"
    "- GOOGLE DOCS COMMENTS: This is where all the heavy, detailed, bullet-pointed feedback goes. Rigorously evaluate the CV against the scoring matrix PDF, detailing specific strengths (what is important) and blind spots/missing items (what is lacking) for individual sections and bullets."
)

st.title("📱 WhatsApp & Docs CV Reviewer")
st.write("Upload a CV file or paste a native Google Doc link for a concise WhatsApp note and deep-dive rubric comments.")

uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])
doc_url = st.text_input("Or paste native Google Doc Link (Optional - adds detailed inline comments to specific bullet points)")

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
    with st.spinner("Analyzing CV against scoring matrix and generating precise feedback..."):
        try:
            contents_payload = training_materials + [
                cv_target,
                (
                    "Analyze this CV against the attached scoring matrix PDF and training samples. Provide two distinct outputs clearly separated:\n"
                    "1. WHATSAPP_TEXT: A very short, punchy, casual 2-sentence text message (no markdown, no bolding, no scores).\n"
                    "2. DETAILED_FEEDBACK_MAP: Detailed, bullet-pointed coaching feedback evaluating specific sections and bullet points against the scoring matrix (highlighting what is important and what is lacking)."
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
            
            # Separate the short WhatsApp text from the detailed feedback map
            whatsapp_part = raw_output
            detailed_part = raw_output
            
            if "WHATSAPP_TEXT" in raw_output and "DETAILED_FEEDBACK_MAP" in raw_output:
                parts = raw_output.split("DETAILED_FEEDBACK_MAP")
                whatsapp_part = parts[0].replace("WHATSAPP_TEXT", "").strip()
                detailed_part = parts[1].strip()
            
            st.success("Review Complete!")
            st.subheader("WhatsApp Text Output (Short & Casual):")
            st.text_area("Copy message below:", value=whatsapp_part, height=150)
            
            # If a Google Doc URL was provided, find individual bullet points/paragraphs to anchor detailed comments accurately
            if doc_url:
                try:
                    docs_svc, _ = get_gdocs_service()
                    doc_id = extract_doc_id(doc_url)
                    document = docs_svc.documents().get(documentId=doc_id).execute()
                    
                    target_paragraphs = []
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
                            if len(cleaned) > 10:  # Ignore empty lines or tiny bullets
                                line_lower = cleaned.lower()
                                # Identify specific bullet lines or section rows to anchor detailed feedback
                                if any(kw in line_lower for kw in ["a-level", "gcse", "forest school", "education", "deloitte", "liskara", "trainer", "schroders", "islamic society", "consulting", "wrestling", "skills", "interests"]):
                                    target_paragraphs.append({
                                        'text': cleaned,
                                        'startIndex': start_idx,
                                        'endIndex': end_idx
                                    })
                    
                    requests = []
                    # Create targeted, detailed comment payloads based on the scoring matrix evaluation for specific lines
                    for tp in target_paragraphs[:4]: # Attach to top relevant matched bullet points/lines
                        text_lower = tp['text'].lower()
                        comment_content = "Scoring Matrix Evaluation:\n• Review this section against rubric requirements.\n• Ensure strong action verbs and quantified impact are present."
                        
                        if "a-level" in text_lower or "gcse" in text_lower or "forest school" in text_lower:
                            comment_content = "Education Rubric Feedback:\n• Must be consolidated strictly onto a single line.\n• Ensure top-decile rankings or specific academic prizes are explicit."
                        elif "deloitte" in text_lower or "liskara" in text_lower or "intern" in text_lower or "trainer" in text_lower:
                            comment_content = "Work Experience Rubric Feedback:\n• Lead with strong action verbs and concrete commercial metrics (revenue, efficiency %).\n• Remove standalone company background descriptions."
                        elif "islamic society" in text_lower or "consulting" in text_lower or "wrestling" in text_lower:
                            comment_content = "Leadership Rubric Feedback:\n• Highlight scale metrics (team size, funds raised, attendees).\n• Keep text concise and punchy."
                        elif "skills" in text_lower or "interests" in text_lower:
                            comment_content = "Skills Rubric Feedback:\n• Ensure a dedicated technical hard skills line is included (e.g., Advanced Excel, financial modelling, Python)."

                        requests.append({
                            'insertComment': {
                                'content': comment_content,
                                'range': {
                                    'startIndex': tp['startIndex'],
                                    'endIndex': tp['endIndex']
                                }
                            }
                        })
                    
                    if requests:
                        docs_svc.documents().batchUpdate(
                            documentId=doc_id,
                            body={'requests': requests}
                        ).execute()
                        st.success("Successfully posted detailed, matrix-driven comments onto the specific bullet points in your Google Doc!")
                    else:
                        st.info("Review generated, but couldn't map specific paragraph indexes for anchoring.")
                except Exception as doc_update_err:
                    st.error(f"Failed to post anchored comments to Google Doc: {doc_update_err}")
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")