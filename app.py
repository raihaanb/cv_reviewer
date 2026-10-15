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

# Dynamic exemplar loader to read training files from the 'samples/' directory
def load_exemplars():
    exemplar_text = ""
    # Ensure samples directory exists locally so it doesn't throw errors
    if not os.path.exists("samples"):
        os.makedirs("samples")
    
    sample_files = glob.glob("samples/*.txt")
    if sample_files:
        exemplar_text += "\n--- EXEMPLAR CVs & SAMPLE COACH FEEDBACK FOR TRAINING ---\n"
        for filepath in sample_files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    exemplar_text += f"\nFile ({os.path.basename(filepath)}):\n"
                    exemplar_text += f.read() + "\n"
            except Exception:
                pass
        exemplar_text += "--- END OF EXAMPLES ---\n\n"
    return exemplar_text

# Load exemplars dynamically into context
exemplars_context = load_exemplars()

# System prompt combining style instructions, training exemplars, and strict core rules
system_prompt_content = (
    "You are an expert executive career coach reviewing student and professional CVs. "
    "Your tone must strictly match the style, warmth, and depth demonstrated in the sample feedback provided below.\n\n"
    f"{exemplars_context}"
    "Core Rules to Enforce Across the CV:\n"
    "1. Candidates must always keep GCSEs and A-levels on their CVs, restricted strictly to a single line rather than dropping them or splitting them across multiple lines[cite: 1, 2, 3].\n"
    "2. Your WhatsApp summary must be a warm, natural, conversational message (zero markdown asterisks, zero bolding, zero scores)[cite: 1, 2, 3].\n"
    "3. Review the entire CV comprehensively from top to bottom (Education, Work Experience, Leadership, and Skills).\n"
    "4. Check for timeline consistency, clear dates, hard skills (like Excel modelling or specific tools), and strong action verbs with commercial metrics[cite: 1, 2, 3]."
)

st.title("📱 WhatsApp & Docs CV Reviewer")
st.write("Upload a CV file or paste a native Google Doc link for a complete, deep-dive review powered by your training samples.")

# Input options
uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])
doc_url = st.text_input("Or paste native Google Doc Link (Optional - adds targeted inline comments)")

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
                    
                    cleaned_line = p_text.strip().lower()
                    cv_text_content += p_text
                    
                    # Track major sections across the entire CV for precise anchoring
                    if "education" in cleaned_line:
                        doc_sections['education'] = {'startIndex': start_idx, 'endIndex': end_idx}
                    elif "work experience" in cleaned_line:
                        doc_sections['work experience'] = {'startIndex': start_idx, 'endIndex': end_idx}
                    elif "leadership" in cleaned_line:
                        doc_sections['leadership'] = {'startIndex': start_idx, 'endIndex': end_idx}
                    elif "skills" in cleaned_line or "interests" in cleaned_line:
                        doc_sections['skills'] = {'startIndex': start_idx, 'endIndex': end_idx}

            cv_target = f"Review this complete CV text content extracted from a Google Doc:\n{cv_text_content}"
        except Exception as fetch_err:
            st.error(f"Failed to fetch Google Doc. Make sure it is a native Google Doc (not an Office file) and shared with your service account email as an Editor! Details: {fetch_err}")
            st.stop()
    else:
        st.error("Google Service Account credentials missing in Streamlit secrets!")
        st.stop()
else:
    cv_target = None

if cv_target is not None and st.button("Generate Comprehensive Review"):
    with st.spinner("Analyzing CV using training samples and deep-dive logic..."):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=[
                    cv_target,
                    (
                        "Perform a meticulous, complete review of this CV from top to bottom, matching the exact style and coaching depth of the training samples. Provide:\n"
                        "1. WHATSAPP SUMMARY: A warm, natural, conversational message (no markdown, no bolding, no scores).\n"
                        "2. SECTION COMMENTS: Specific, professional improvement notes for Education, Work Experience, Leadership, and Skills."
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt_content,
                    temperature=0.7
                )
            )
            
            st.success("Deep-Dive Review Complete!")
            st.subheader("WhatsApp Text Output:")
            st.text_area("Copy message below:", value=response.text, height=300)
            
            # If a Google Doc URL was provided, insert targeted anchored comments into matching sections
            if doc_url and doc_sections:
                try:
                    docs_svc, _ = get_gdocs_service()
                    doc_id = extract_doc_id(doc_url)
                    
                    requests = []
                    
                    if "education" in doc_sections:
                        edu = doc_sections["education"]
                        requests.append({
                            'insertComment': {
                                'content': "Education Feedback:\n• Consolidate A-levels and GCSEs strictly onto a single line to save vertical space[cite: 1, 2, 3].\n• Highlight top-decile rankings or specific academic prizes clearly[cite: 1, 2, 3].",
                                'range': {'startIndex': edu['startIndex'], 'endIndex': edu['endIndex']}
                            }
                        })
                    
                    if "work experience" in doc_sections:
                        work = doc_sections["work experience"]
                        requests.append({
                            'insertComment': {
                                'content': "Work Experience Feedback:\n• Ensure every bullet starts with a strong action verb and robust commercial metrics[cite: 1, 2, 3].\n• Keep corporate internship roles front and center; fold explanatory company descriptions directly into the lead bullet[cite: 1, 2, 3].",
                                'range': {'startIndex': work['startIndex'], 'endIndex': work['endIndex']}
                            }
                        })
                    
                    if "leadership" in doc_sections:
                        lead = doc_sections["leadership"]
                        requests.append({
                            'insertComment': {
                                'content': "Leadership Feedback:\n• Retain impressive sponsorship and attendance metrics[cite: 1, 2, 3].\n• Keep descriptions concise (max 2 lines per bullet)[cite: 1, 2, 3].",
                                'range': {'startIndex': lead['startIndex'], 'endIndex': lead['endIndex']}
                            }
                        })
                        
                    if "skills" in doc_sections:
                        skl = doc_sections["skills"]
                        requests.append({
                            'insertComment': {
                                'content': "Skills & Interests Feedback:\n• Add a dedicated line for technical/hard skills (e.g., Advanced Excel, financial modelling, Python) alongside your sports achievements[cite: 1, 2, 3].",
                                'range': {'startIndex': skl['startIndex'], 'endIndex': skl['endIndex']}
                            }
                        })
                    
                    if requests:
                        docs_svc.documents().batchUpdate(
                            documentId=doc_id,
                            body={'requests': requests}
                        ).execute()
                        st.success("Successfully posted targeted, section-specific bullet points onto your native Google Doc!")
                    else:
                        st.info("Review generated, but couldn't map specific section headers for anchoring.")
                except Exception as doc_update_err:
                    st.error(f"Failed to post anchored comments to Google Doc: {doc_update_err}")
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")