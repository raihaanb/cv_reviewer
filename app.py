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

# Strict system prompt embodying your exact rules
system_prompt_content = (
    "You are an expert executive career coach reviewing student and professional CVs.\n"
    "Your tone, rigor, and coaching style must strictly match the loaded training samples provided. Avoid all generic AI filler and corporate slop.\n\n"
    "CRITICAL GUIDELINES:\n"
    "1. NEVER MENTION THE MATRIX: Under no circumstances should you ever mention the words 'matrix', 'scoring matrix', or 'rubric'. All feedback must feel like personal, expert human coaching.\n"
    "2. NO REPEATED COMMENTS: Every single comment must be 100% unique and bespoke.\n"
    "3. CONTEXT-DEPENDENT: You MUST explicitly mention specific details, roles, companies, or projects (e.g., ISOC, Deloitte, Liskara, Wrestling, Forest School, GCSEs) in the text of each comment.\n"
    "4. NO HEADINGS ALLOWED: Never comment on section titles or headers. Comments must anchor strictly to individual bullet points, specific achievement entries, or specific target words/phrases.\n"
    "5. SELECTIVE HIGH-IMPACT COVERAGE: Aim for roughly 40-75% of the most impactful bullet points across the document from top to bottom.\n"
    "6. WHATSAPP SUMMARY FORMAT:\n"
    "   - Must start with a bland, generic opening line (e.g., 'It looks really good overall!'). No super positive or over-the-top summary praise.\n"
    "   - Provide a concise medium-level overview of key areas to refine.\n"
    "   - Must end with: 'Let me know if you have any questions and feel free to send a re-drafted version.'\n"
    "   - Zero markdown asterisks, zero bolding, zero scores."
)

st.title("📱 WhatsApp & Docs CV Reviewer")
st.write("Upload a CV or paste a native Google Doc link for a warm WhatsApp review and targeted inline comments.")

uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])
doc_url = st.text_input("Or paste native Google Doc Link (Optional - adds targeted inline comments across key bullet points)")

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
                    if len(cleaned) > 15:
                        lower_c = cleaned.lower()
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
            st.error(f"Failed to fetch Google Doc: {fetch_err}")
            st.stop()
    else:
        st.error("Google Service Account credentials missing in Streamlit secrets!")
        st.stop()

if cv_target is not None and st.button("Generate Review"):
    with st.spinner("Analyzing full CV and generating bespoke coaching review..."):
        try:
            # 1. WhatsApp summary with bland opening and standard sign-off
            whatsapp_response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=training_materials + [
                    cv_target,
                    (
                        "Write a WhatsApp review message following these exact rules:\n"
                        "1. Start with a bland, generic opening line (e.g., 'It looks really good overall!'). Do not include over-the-top praise.\n"
                        "2. Provide a medium-level overview of key areas to refine.\n"
                        "3. End with exactly: 'Let me know if you have any questions and feel free to send a re-drafted version.'\n"
                        "4. Do NOT mention the word matrix or rubric. Do NOT use markdown asterisks, bolding, or numerical scores."
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt_content,
                    temperature=0.7
                )
            )
            
            st.success("Review Complete!")
            st.subheader("WhatsApp Text Output:")
            st.text_area("Copy message below:", value=whatsapp_response.text, height=250)
            
            # 2. Generate selective (~40-75% coverage) word-focused inline comments
            if doc_url and extracted_paragraphs:
                try:
                    docs_svc, _ = get_gdocs_service()
                    doc_id = extract_doc_id(doc_url)
                    
                    bullets_payload = ["Here are bullet points and entries extracted across the candidate's CV:\n"]
                    for idx, ep in enumerate(extracted_paragraphs):
                        bullets_payload.append(f"[{idx}] {ep['text']}\n")
                    
                    bullets_payload.append(
                        "\nINSTRUCTIONS FOR INLINE COMMENTS:\n"
                        "1. Select the most impactful bullet points (aim for roughly 50% to 75% of the total entries list, skipping less critical lines).\n"
                        "2. For each selected entry, identify a specific target phrase or key word within that line (e.g., 'A-Levels', 'Deloitte', 'LiDAR', 'Islamic Society', or a specific metric) to highlight.\n"
                        "3. Write a completely unique, context-dependent coaching comment. NEVER mention the word 'matrix' or 'rubric'.\n"
                        "4. Return strictly a JSON array of objects with keys: "
                        "'index' (int), 'target_phrase' (string - exact snippet from the text to highlight), and 'comment' (string)."
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
                    requests = []
                    
                    for item in comment_data:
                        if 'index' in item and 'comment' in item:
                            idx = item['index']
                            if 0 <= idx < len(extracted_paragraphs):
                                ep = extracted_paragraphs[idx]
                                full_text = ep['text']
                                target_phrase = item.get('target_phrase', '')
                                
                                start_offset = 0
                                end_offset = len(full_text)
                                
                                if target_phrase and target_phrase in full_text:
                                    match_start = full_text.find(target_phrase)
                                    start_offset = match_start
                                    end_offset = match_start + len(target_phrase)
                                else:
                                    end_offset = min(25, len(full_text))
                                
                                anchor_start = ep['startIndex'] + start_offset
                                anchor_end = ep['startIndex'] + end_offset
                                
                                requests.append({
                                    'insertComment': {
                                        'content': item['comment'],
                                        'range': {
                                            'startIndex': anchor_start,
                                            'endIndex': anchor_end
                                        }
                                    }
                                })
                    
                    if requests:
                        docs_svc.documents().batchUpdate(
                            documentId=doc_id,
                            body={'requests': requests}
                        ).execute()
                        st.success(f"Successfully posted {len(requests)} targeted, word-highlighted inline comments on your Google Doc!")
                    else:
                        st.info("Review complete, but no comments were returned.")
                except Exception as doc_update_err:
                    st.error(f"Failed to post anchored comments to Google Doc: {doc_update_err}")
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")