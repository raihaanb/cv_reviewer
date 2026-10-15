import os
import tempfile
import streamlit as st
from google import genai

# ==========================================
# STREAMLIT PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="CV Reviewer AI",
    page_icon="📄",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ==========================================
# CUSTOM CSS FOR DARK MODE & MOBILE UI
# ==========================================
st.markdown("""
<style>
    /* Dark Theme Custom Styling */
    body {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    
    /* Smooth Container Styling */
    .stApp {
        background-color: #0E1117;
    }
    
    .css-card {
        background-color: #161B22;
        border: 1px solid #30363D;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }

    /* Primary Accent Styling */
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #4F46E5, #9333EA);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 0.5rem;
    }

    .sub-title {
        color: #8B949E;
        text-align: center;
        font-size: 1rem;
        margin-bottom: 2rem;
    }

    /* Custom File Uploader */
    .uploadedFile {
        border-radius: 8px;
    }

    /* Output Box Styling */
    .output-box {
        background-color: #161B22;
        border-left: 4px solid #10B981;
        padding: 16px;
        border-radius: 8px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        white-space: pre-wrap;
        color: #E6EDF3;
    }
</style>
""", unsafe_allow_html=unsafe_allow_html)

# ==========================================
# APP HEADER
# ==========================================
st.markdown('<div class="main-title">📄 CV Reviewer AI</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Instant, conversational WhatsApp-ready feedback for candidates</div>', unsafe_allow_html=True)

# ==========================================
# GEMINI API KEY SETUP
# ==========================================
# Tries to retrieve key from Streamlit Secrets or Environment Variable
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        api_key = None

# Sidebar for Setup & Information
with st.sidebar:
    st.header("⚙️ Configuration")
    
    if not api_key:
        api_key = st.text_input("Enter Gemini API Key", type="password", help="Enter your Google Gemini API Key here or set it in Streamlit Secrets.")
        if api_key:
            st.success("API Key saved for current session!")
    else:
        st.success("✅ Gemini API Key Connected")

    st.markdown("---")
    st.subheader("📚 Training Assets")
    st.markdown("""
    Ensure your reference documents are stored in the root directory:
    - `SYSTEM_PROMPT.md`
    - `Scoring matrix.pdf`
    - `exemplar_cv_1.pdf` & `exemplar_cv_2.pdf`
    - `sample_cv_1..4` (.pdf & .txt pairs)
    """)

# ==========================================
# MAIN CORE PROCESSOR FUNCTION
# ==========================================
def run_cv_review(cv_temp_path, api_key_value):
    """Handles uploading training files and candidate CV to Gemini and running analysis."""
    client = genai.Client(api_key=api_key_value)
    
    # Expected training files
    files_to_upload = [
        "SYSTEM_PROMPT.md",
        "Scoring matrix.pdf",
        "exemplar_cv_1.pdf",
        "exemplar_cv_2.pdf",
        "sample_cv_1.pdf",
        "sample_cv_1.txt",
        "sample_cv_2.pdf",
        "sample_cv_2.txt",
        "sample_cv_3.pdf",
        "sample_cv_3.txt",
        "sample_cv_4.pdf",
        "sample_cv_4.txt"
    ]

    uploaded_refs = []
    
    # Upload local context files if available
    for filename in files_to_upload:
        if os.path.exists(filename):
            ref = client.files.upload(file=filename)
            uploaded_refs.append(ref)

    # Upload target CV
    target_cv_ref = client.files.upload(file=cv_temp_path)
    uploaded_refs.append(target_cv_ref)

    # Prompt specification
    prompt = """
    Please review the newly uploaded target CV using `SYSTEM_PROMPT.md`, 
    `Scoring matrix.pdf`, both exemplar CVs, and all sample CVs with their corresponding `.txt` human feedback notes.
    
    Write out the feedback so it sounds completely natural, casual, and human—just like a relaxed WhatsApp text message you would type out yourself. 
    Do NOT use rigid robotic headings or structured corporate templates. Keep the feedback sharp, insightful, and accurate based on our standards, but make the tone conversational and fluid.
    
    CRITICAL: Do NOT use any asterisks (*) anywhere in your output text. Keep it completely plain text without markdown symbols. Do not include any estimated matrix scores.
    """
    
    uploaded_refs.append(prompt)

    # Generate content using gemini-3.8-flash
    response = client.models.generate_content(
        model='gemini-3.8-flash',
        contents=uploaded_refs
    )

    return response.text

# ==========================================
# UI FILE UPLOAD & PROCESSOR
# ==========================================
st.markdown('<div class="css-card">', unsafe_allow_html=True)
uploaded_file = st.file_uploader("Upload Candidate CV (PDF)", type=["pdf"])
st.markdown('</div>', unsafe_allow_html=True)

if uploaded_file is not None:
    if not api_key:
        st.error("⚠️ Please provide a Gemini API Key in the sidebar to proceed.")
    else:
        st.info(f"📄 Uploaded: **{uploaded_file.name}**")
        
        if st.button("🚀 Generate WhatsApp Feedback", use_container_width=True, type="primary"):
            with st.spinner("🤖 Analyzing CV against calibration history..."):
                try:
                    # Save PDF to temporary file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                        tmp_file.write(uploaded_file.getvalue())
                        temp_file_path = tmp_file.name

                    # Run model review
                    feedback_text = run_cv_review(temp_file_path, api_key)

                    # Clean up temporary file
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)

                    # Store output in session state
                    st.session_state['generated_feedback'] = feedback_text
                    st.success("✨ Analysis complete!")

                except Exception as e:
                    st.error(f"An error occurred during processing: {str(e)}")

# ==========================================
# DISPLAY RESULT & ONE-CLICK COPY
# ==========================================
if 'generated_feedback' in st.session_state:
    st.markdown("### 💬 WhatsApp Feedback Output")
    
    feedback = st.session_state['generated_feedback']

    # Display clean formatted box
    st.markdown(f'<div class="output-box">{feedback}</div>', unsafe_allow_html=True)
    st.write("") # Spacing

    # Code block display with built-in Streamlit top-right copy button for phone compatibility
    st.code(feedback, language=None)
    st.caption("📱 Tip: Tap the copy icon in the top right of the text block above to paste directly into WhatsApp!")