import google.generativeai as genai
from config import Config
import fitz  # PyMuPDF

genai.configure(api_key=Config.GEMINI_API_KEY)

configuration = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 8192,
    "response_mime_type": "text/plain"
}

model = genai.GenerativeModel(
    model_name="gemini-3-flash-preview",
    generation_config=configuration
)

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

def analyse_resume_gemini(resume_content, job_description):
    prompt = f"""
    You are a professional resume analyzer. Analyze the provided resume against the job description and provide a clean, structured analysis.

    Resume Content:
    {resume_content}

    Job Description:
    {job_description}

    Provide your analysis in this exact format without any special characters, symbols, or markdown:

    MATCH SCORE: [number]/100

    MISSING SKILLS:
    [List each missing skill on a new line]

    SUGGESTIONS:
    [List each suggestion on a new line]

    SUMMARY:
    [Provide a brief summary paragraph]

    Important: Use only plain text. No asterisks, hashtags, underscores, or other symbols. Keep the format exactly as shown above.
    """

    response = model.generate_content(prompt)

    return response.text