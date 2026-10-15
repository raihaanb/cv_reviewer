import os
import sys
from google import genai

def review_cv(cv_file_path: str):
    # Initialize the Gemini client (reads GEMINI_API_KEY from environment variables)
    client = genai.Client()
    
    print("🚀 Initializing CV Reviewer Agent...")
    print("📦 Uploading full context, exemplars, all calibration pairs, and scoring matrix to Gemini...")

    # Matches your exact file names in the CV_Reviewer folder
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
    
    # Upload training files if they exist locally
    for filename in files_to_upload:
        if os.path.exists(filename):
            print(f"   -> Uploading: {filename}")
            ref = client.files.upload(file=filename)
            uploaded_refs.append(ref)
        else:
            print(f"   [!] Warning: Optional/Training file '{filename}' not found locally. Skipping.")

    # Upload the target CV to be reviewed
    if not os.path.exists(cv_file_path):
        print(f"❌ Error: Target CV '{cv_file_path}' not found.")
        sys.exit(1)
        
    print(f"   -> Uploading Target CV: {cv_file_path}")
    target_cv_ref = client.files.upload(file=cv_file_path)
    uploaded_refs.append(target_cv_ref)

    # Construct the instruction prompt utilizing all historical context and constraints
    prompt = f"""
    Please review the newly uploaded target CV (`{cv_file_path}`) using `SYSTEM_PROMPT.md`, 
    `Scoring matrix.pdf`, both exemplar CVs, and all four sample CVs with their corresponding `.txt` human feedback notes.
    
    Write out the feedback so it sounds completely natural, casual, and human—just like a relaxed WhatsApp text message you would type out yourself. 
    Do NOT use rigid robotic headings or structured corporate templates. Keep the feedback sharp, insightful, and accurate based on our standards, but make the tone conversational and fluid.
    CRITICAL: Do NOT use any asterisks (*) anywhere in your output text. Keep it completely plain text without markdown symbols. Do not include any estimated matrix scores.
    """

    uploaded_refs.append(prompt)

    print("🤖 Analyzing candidate against your full calibration history (using gemini-3.8-flash)...")

    # Call Gemini model
    response = client.models.generate_content(
        model='gemini-3.8-flash',
        contents=uploaded_refs
    )

    print("\n" + "="*50)
    print("📋 GENERATED CV FEEDBACK (READY FOR WHATSAPP):")
    print("="*50 + "\n")
    print(response.text)
    print("\n" + "="*50)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_cv_reviewer.py <path_to_candidate_cv.pdf>")
        sys.exit(1)
        
    cv_path = sys.argv[1]
    review_cv(cv_path)