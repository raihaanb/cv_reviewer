import os
import tempfile
import streamlit as st
from google import genai
from google.genai import types

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

# Updated system prompt enforcing friendly, professional bullet points without markdown
system_prompt_content = (
    "You are an expert executive career coach reviewing CVs. "
    "Provide constructive, encouraging feedback organized into clean bullet points. "
    "Maintain a friendly yet professional tone. "
    "Never use markdown asterisks, bolding, formatting symbols, or estimated numerical scores."
)

st.title("📱 WhatsApp CV Reviewer")
st.write("Drop a candidate's CV below to generate direct, structured bullet-point feedback.")

# File uploader for candidate CVs (supports PDF or text)
uploaded_file = st.file_uploader("Upload Candidate CV (PDF or TXT)", type=["pdf", "txt"])

if uploaded_file is not None:
    with st.spinner("Reviewing CV..."):
        try:
            # Save the uploaded file temporarily so the SDK can read it securely from disk
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name

            # Upload the temporary file using the File API
            uploaded_gemini_file = client.files.upload(file=tmp_path)
            
            # Clean up the local temporary file
            os.unlink(tmp_path)
            
            # Prompt the model using your updated instructions and the uploaded file
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=[
                    uploaded_gemini_file,
                    "Review this CV following your master prompt guidelines. Output only clean, friendly bullet points with zero markdown asterisks, zero bolding, and zero scores."
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt_content,
                    temperature=0.7
                )
            )
            
            st.success("Review Generated Successfully!")
            st.subheader("WhatsApp Text Output:")
            
            # Display plain text cleanly
            st.text_area("Copy message below:", value=response.text, height=300)
            
        except Exception as e:
            st.error(f"An error occurred during generation: {e}")