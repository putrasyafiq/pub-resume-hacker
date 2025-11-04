import os
import json
import uuid
from flask import (
    Flask, render_template, request, jsonify, redirect, 
    url_for, session, flash, send_from_directory,
    Response
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from weasyprint import HTML
from datetime import datetime, timedelta

# --- Google Cloud Imports ---
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
# --- REMOVED: from google.cloud import firestore ---
from google.cloud import storage

# --- Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-random-key-please-change-me' 

# --- !! REPLACE THESE !! ---
YOUR_PROJECT_ID = "johanesa-playground-326616"
YOUR_LOCATION = "us-central1"
YOUR_GCS_BUCKET_NAME = "putra_wpb_bucket" # The bucket you already created

# --- Initialize Cloud Clients ---
vertexai.init(project=YOUR_PROJECT_ID, location=YOUR_LOCATION)
# --- REMOVED: db = firestore.Client(project=YOUR_PROJECT_ID) ---
storage_client = storage.Client(project=YOUR_PROJECT_ID)
bucket = storage_client.bucket(YOUR_GCS_BUCKET_NAME)

# --- AI Model Config (Unchanged) ---
model = GenerativeModel("gemini-2.5-flash-lite")
generation_config = GenerationConfig(
    temperature=0.2,
    max_output_tokens=8192
)
DEFAULT_AI_PROMPT = """You are an expert HTML resume generator and a human resource specialist. Your *only* output must be a single, complete HTML file.
You will be given four inputs: a candidate's profile, a job application, an HTML template, and custom user instructions.
**Your Task:**
Generate a complete, tailored HTML resume by following these rules:
1.  **GENERATE SUMMARY:** You *must* write a new, compelling "Professional Summary" (3-5 sentences). This summary must be hyper-specific to the **{job_title}** role at **{company_name}**, using keywords from the **{job_description}**.
2.  **INJECT SUMMARY:** This new summary *must* be placed inside the `<section class="section">` with the `<h2>Professional Summary</h2>` heading in the final HTML.
3.  **TAILOR CONTENT:** The "Work Experience" and "Projects" sections *must* be tailored to fit the {job_description}. Rephrase bullet points to use action verbs and keywords from the **{job_description}** where relevant.
4.  **FOLLOW TEMPLATE:** You *must* use the exact HTML structure, class names, and CSS provided in the **{template_example}**.
5.  **FOLLOW CUSTOM INSTRUCTIONS:** You *must* obey all additional rules from the user, found here: {custom_instructions}
**Inputs:**
---
**1. PROFILE_DATA:**
{profile_json}
---
**2. JOB_APPLICATION:**
* Company Name: {company_name}
* Job Title: {job_title}
* Job Description: {job_description}
---
**3. HTML_TEMPLATE:**
{template_example}
---
**Output Format Rules (Most Important):**
Your response MUST be *only* the raw HTML code.
- DO NOT write *any* text, notes, explanations, or markdown (like "```html") before the `<!DOCTYPE html>` tag.
- Your entire response MUST start with `<!DOCTYPE html>` and end with `</html>`.
"""

# --- Default Profile Structure (Unchanged) ---
DEFAULT_PARTICULARS = {
    "name": "", "email": "", "languages": [], "country": ""
}
DEFAULT_PROFILE = {
    "particulars": DEFAULT_PARTICULARS.copy(),
    "experiences": [], "education": [], "projects": [], "awards": [],
    "ai_custom_prompt": ""
}

# --- NEW: GCS Helper Functions ---

def load_passwords():
    """Loads the password hash file from GCS."""
    try:
        blob_path = "passwords.json"
        blob = bucket.blob(blob_path)
        if blob.exists():
            return json.loads(blob.download_as_string())
    except Exception as e:
        print(f"Error loading passwords from GCS: {e}")
    return {} # Return empty if not found or error

def save_passwords(passwords):
    """Saves the password hash file to GCS."""
    blob_path = "passwords.json"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(passwords, indent=4),
        content_type="application/json"
    )

def load_profile_data(profile_name):
    """Loads a single user's profile from GCS."""
    try:
        blob_path = f"{profile_name}/profile.json" # Standardized path
        blob = bucket.blob(blob_path)
        if blob.exists():
            data = json.loads(blob.download_as_string())
            
            # Merge with default to ensure all keys exist
            full_data = DEFAULT_PROFILE.copy()
            full_data['particulars'] = DEFAULT_PARTICULARS.copy()
            full_data.update(data)
            
            if 'particulars' in data:
                full_data['particulars'] = DEFAULT_PARTICULARS.copy()
                full_data['particulars'].update(data['particulars'])
            
            if 'ai_custom_prompt' not in data:
                 full_data['ai_custom_prompt'] = ""
            return full_data
    except Exception as e:
        print(f"Error loading profile {profile_name} from GCS: {e}")
        
    return DEFAULT_PROFILE.copy() # Return default if not found or error

def save_profile_data(profile_name, profile_data):
    """Saves a single user's profile to GCS."""
    blob_path = f"{profile_name}/profile.json" # Standardized path
    
    # Ensure all keys are present
    full_data = DEFAULT_PROFILE.copy()
    full_data['particulars'] = DEFAULT_PARTICULARS.copy()
    full_data.update(profile_data)
    
    if 'particulars' in profile_data:
        full_data['particulars'] = DEFAULT_PARTICULARS.copy()
        full_data['particulars'].update(profile_data['particulars'])
    
    full_data['ai_custom_prompt'] = profile_data.get('ai_custom_prompt', "")
    
    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(full_data, indent=4),
        content_type="application/json"
    )

def load_resume_metadata(profile_name):
    """Reads the resumes.json file from GCS."""
    try:
        blob_path = f"{profile_name}/resumes.json" # Path is in user's folder
        blob = bucket.blob(blob_path)
        if blob.exists():
            return json.loads(blob.download_as_string())
    except Exception as e:
        print(f"Error loading resume metadata: {e}")
    return []

def save_resume_metadata(profile_name, metadata_list):
    """Saves the metadata list to the resumes.json file in GCS."""
    blob_path = f"{profile_name}/resumes.json" # Path is in user's folder
    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(metadata_list, indent=4),
        content_type="application/json"
    )

# --- (Auth Routes & Main Page Route are unchanged) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        profile_name = request.form.get('profileName')
        password = request.form.get('password')
        if not profile_name or not password:
            flash('Please enter a profile name and password.', 'error')
            return redirect(url_for('login'))
        passwords = load_passwords()
        if profile_name in passwords:
            if check_password_hash(passwords[profile_name], password):
                session['profile_name'] = profile_name
                flash(f'Welcome back, {profile_name}!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Incorrect password.', 'error')
                return redirect(url_for('login'))
        else:
            hashed_password = generate_password_hash(password)
            passwords[profile_name] = hashed_password
            save_passwords(passwords)
            save_profile_data(profile_name, DEFAULT_PROFILE.copy()) 
            session['profile_name'] = profile_name
            flash(f'New profile "{profile_name}" created. Welcome!', 'success')
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('profile_name', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'profile_name' not in session:
        return redirect(url_for('login'))
    profile_name = session['profile_name']
    profile_data = load_profile_data(profile_name)
    return render_template('index.html', 
                           profile_name=profile_name, 
                           profile_data=profile_data)

# --- Resume Routes (MODIFIED for GCS) ---

@app.route('/resumes')
def resumes():
    if 'profile_name' not in session:
        return redirect(url_for('login'))
    profile_name = session['profile_name']
    resume_metadata = load_resume_metadata(profile_name)
    resume_metadata.sort(key=lambda x: x.get('generation_date', ''), reverse=True)
    profile_data = load_profile_data(profile_name)
    current_custom_prompt = profile_data.get('ai_custom_prompt', "")
    return render_template('resumes.html', 
                           resume_files=resume_metadata, 
                           current_custom_prompt=current_custom_prompt)

@app.route('/resumes/<filename>')
def view_resume(filename):
    if 'profile_name' not in session:
        return redirect(url_for('login'))
    profile_name = session['profile_name']
    secure_name = secure_filename(filename)
    if secure_name != filename: return "Invalid filename", 400
    
    blob_path = f"{profile_name}/{secure_name}" # Path is in user's folder
    blob = bucket.blob(blob_path)
    if not blob.exists():
        return "Not found", 404
    try:
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=15),
            method="GET"
        )
        return redirect(url)
    except Exception as e:
        print(f"Error generating signed URL: {e}")
        return "Error, could not view file", 500

@app.route('/download_resume/<filename>')
def download_resume(filename):
    if 'profile_name' not in session:
        return redirect(url_for('login'))
    profile_name = session['profile_name']
    secure_name = secure_filename(filename)
    if secure_name != filename: return "Invalid filename", 400
    
    blob_path = f"{profile_name}/{secure_name}" # Path is in user's folder
    blob = bucket.blob(blob_path)
    if not blob.exists():
        return "File not found", 404
    try:
        # Download HTML from GCS as string
        html_string = blob.download_as_string()
        
        # Render PDF in memory from the string
        html = HTML(string=html_string) 
        pdf_bytes = html.write_pdf()
        
        pdf_filename = os.path.splitext(secure_name)[0] + '.pdf'
        
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment;filename={pdf_filename}"}
        )
    except Exception as e:
        print(f"Error converting PDF: {e}")
        flash(f'Error converting file to PDF: {e}', 'error')
        return redirect(url_for('resumes'))

@app.route('/add_resume', methods=['POST'])
def add_resume():
    if 'profile_name' not in session: return redirect(url_for('login'))
    profile_name = session['profile_name']
    
    company_name = request.form.get('company_name')
    job_title = request.form.get('job_title')
    job_description = request.form.get('job_description')
    
    if not all([company_name, job_title, job_description]):
        flash('All fields are required to generate an AI resume.', 'error')
        return redirect(url_for('resumes'))
        
    now = datetime.now()
    datetime_str = now.strftime("%Y%m%d%H%M%S")
    safe_profile = secure_filename(profile_name)
    safe_job = secure_filename(job_title)
    safe_company = secure_filename(company_name)
    if not safe_job: safe_job = "job"
    if not safe_company: safe_company = "company"
    resume_filename = f"{safe_profile}_{datetime_str}_{safe_job}_{safe_company}.html"
    
    profile_data = load_profile_data(profile_name)
    profile_json = json.dumps(profile_data)
    
    try:
        with open('templates/resume_template.html', 'r', encoding='utf-8') as f:
            template_example = f.read()
    except FileNotFoundError:
        flash('ERROR: resume_template.html not found.', 'error')
        return redirect(url_for('resumes'))

    user_custom_prompt = profile_data.get('ai_custom_prompt', "")

    try:
        prompt_context = {
            "profile_json": profile_json, "job_title": job_title,
            "company_name": company_name, "job_description": job_description,
            "template_example": template_example, "custom_instructions": user_custom_prompt
        }
        prompt = DEFAULT_AI_PROMPT.format_map(prompt_context)
        
        response = model.generate_content(prompt, generation_config=generation_config)
        ai_generated_html = response.text
        ai_generated_html = ai_generated_html.strip().replace("```html", "").replace("```", "").strip()
        
        if not ai_generated_html.startswith("<!DOCTYPE html>"):
            error_snippet = ai_generated_html.replace('<', '&lt;').replace('>', '&gt;')
            raise Exception(f"AI did not return valid HTML. Response started with: {error_snippet[:300]}...")

        # Upload HTML to GCS
        blob_path = f"{profile_name}/{resume_filename}"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(
            ai_generated_html,
            content_type="text/html"
        )
            
        # Update metadata
        metadata_list = load_resume_metadata(profile_name)
        new_resume_entry = {
            "id": str(uuid.uuid4()), "filename": resume_filename,
            "name": f"{job_title} at {company_name}",
            "role": job_title, "company": company_name,
            "generation_date": now.strftime("%Y-%m-%d %H:%M:%S")
        }
        metadata_list.append(new_resume_entry)
        save_resume_metadata(profile_name, metadata_list)
        
        flash(f'Successfully generated AI-tailored resume for {job_title}', 'success')
        
    except KeyError as e:
        print(f"Prompt formatting error: {e}")
        flash(f'Error in your custom AI prompt: Missing variable {e}. Please edit the prompt and try again.', 'error')
    except Exception as e:
        print(f"Error generating resume: {e}")
        flash(f'Error generating AI resume: {e}', 'error')
        
    return redirect(url_for('resumes'))

@app.route('/delete_resume', methods=['POST'])
def delete_resume():
    if 'profile_name' not in session:
        return redirect(url_for('login'))
    profile_name = session['profile_name']
    resume_id = request.form.get('resume_id')
    if not resume_id:
        flash('Invalid request.', 'error')
        return redirect(url_for('resumes'))
        
    metadata_list = load_resume_metadata(profile_name)
    item_to_delete = next((item for item in metadata_list if item.get('id') == resume_id), None)
    
    if item_to_delete:
        filename = item_to_delete.get('filename')
        if filename:
            # Delete from GCS
            try:
                blob_path = f"{profile_name}/{secure_filename(filename)}"
                blob = bucket.blob(blob_path)
                if blob.exists():
                    blob.delete()
            except Exception as e:
                print(f"Error deleting file from GCS: {e}")
        
        new_metadata_list = [item for item in metadata_list if item.get('id') != resume_id]
        save_resume_metadata(profile_name, new_metadata_list)
        flash(f'Successfully deleted resume', 'success')
    else:
        flash('File not found.', 'error')
        
    return redirect(url_for('resumes'))

@app.route('/update_custom_prompt', methods=['POST'])
def update_custom_prompt():
    if 'profile_name' not in session: 
        return jsonify({"status": "error", "message": "Not logged in"}), 401
    
    try:
        new_prompt = request.json.get('prompt')
        if new_prompt is None:
            return jsonify({"status": "error", "message": "No prompt provided"}), 400
            
        profile_name = session['profile_name']
        profile_data = load_profile_data(profile_name)
        
        profile_data['ai_custom_prompt'] = new_prompt
        
        save_profile_data(profile_name, profile_data) # Save to GCS
        
        return jsonify({"status": "success", "message": "Custom prompt updated."})
        
    except Exception as e:
        print(f"Error in /update_custom_prompt: {e}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

# --- (All other routes: /update_particulars, /add, /add_education, etc. are unchanged) ---
@app.route('/update_particulars', methods=['POST'])
def update_particulars():
    if 'profile_name' not in session: return jsonify({"status": "error", "message": "Not logged in"}), 401
    profile_name = session['profile_name']
    try:
        new_particulars = request.json.get('particulars')
        if not new_particulars: return jsonify({"status": "error", "message": "Missing particulars data"}), 400
        profile_data = load_profile_data(profile_name)
        profile_data['particulars'] = new_particulars
        save_profile_data(profile_name, profile_data)
        return jsonify({"status": "success", "message": "Particulars updated successfully."})
    except Exception as e:
        print(f"Error in /update_particulars: {e}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

@app.route('/add', methods=['POST'])
def add_experience():
    if 'profile_name' not in session: return jsonify({"status": "error", "message": "Not logged in"}), 401
    profile_name = session['profile_name']
    try:
        new_experience = request.json.get('experience')
        if not new_experience: return jsonify({"status": "error", "message": "Missing experience data"}), 400
        new_experience['id'] = str(uuid.uuid4())
        profile_data = load_profile_data(profile_name)
        profile_data["experiences"].append(new_experience)
        save_profile_data(profile_name, profile_data)
        return jsonify({"status": "success", "newItem": new_experience})
    except Exception as e:
        print(f"Error in /add: {e}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

@app.route('/add_education', methods=['POST'])
def add_education():
    if 'profile_name' not in session: return jsonify({"status": "error", "message": "Not logged in"}), 401
    profile_name = session['profile_name']
    try:
        new_education = request.json.get('education')
        if not new_education: return jsonify({"status": "error", "message": "Missing education data"}), 400
        new_education['id'] = str(uuid.uuid4())
        profile_data = load_profile_data(profile_name)
        profile_data["education"].append(new_education)
        save_profile_data(profile_name, profile_data)
        return jsonify({"status": "success", "newItem": new_education})
    except Exception as e:
        print(f"Error in /add_education: {e}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

@app.route('/add_project', methods=['POST'])
def add_project():
    if 'profile_name' not in session: return jsonify({"status": "error", "message": "Not logged in"}), 401
    profile_name = session['profile_name']
    try:
        new_project = request.json.get('project')
        if not new_project: return jsonify({"status": "error", "message": "Missing project data"}), 400
        new_project['id'] = str(uuid.uuid4())
        profile_data = load_profile_data(profile_name)
        profile_data["projects"].append(new_project)
        save_profile_data(profile_name, profile_data)
        return jsonify({"status": "success", "newItem": new_project})
    except Exception as e:
        print(f"Error in /add_project: {e}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

@app.route('/add_award', methods=['POST'])
def add_award():
    if 'profile_name' not in session: return jsonify({"status": "error", "message": "Not logged in"}), 401
    profile_name = session['profile_name']
    try:
        new_award = request.json.get('award')
        if not new_award: return jsonify({"status": "error", "message": "Missing award data"}), 400
        new_award['id'] = str(uuid.uuid4())
        profile_data = load_profile_data(profile_name)
        profile_data["awards"].append(new_award)
        save_profile_data(profile_name, profile_data)
        return jsonify({"status": "success", "newItem": new_award})
    except Exception as e:
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

@app.route('/update_item', methods=['POST'])
def update_item():
    if 'profile_name' not in session: return jsonify({"status": "error", "message": "Not logged in"}), 401
    profile_name = session['profile_name']
    try:
        data = request.json
        item_type = data.get('itemType')
        updated_item = data.get('item')
        item_id = updated_item.get('id')
        if not all([item_type, updated_item, item_id]):
            return jsonify({"status": "error", "message": "Missing data"}), 400
        profile_data = load_profile_data(profile_name)
        if item_type not in profile_data:
            return jsonify({"status": "error", "message": "Invalid item type"}), 400
        item_list = profile_data[item_type]
        index_to_update = next((i for i, item in enumerate(item_list) if item.get('id') == item_id), None)
        if index_to_update is not None:
            item_list[index_to_update] = updated_item
            save_profile_data(profile_name, profile_data)
            return jsonify({"status": "success", "message": "Item updated."})
        else:
            return jsonify({"status": "error", "message": "Item not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

@app.route('/delete_item', methods=['POST'])
def delete_item():
    if 'profile_name' not in session: return jsonify({"status": "error", "message": "Not logged in"}), 401
    profile_name = session['profile_name']
    try:
        data = request.json
        item_type = data.get('itemType')
        item_id = data.get('id')
        if not all([item_type, item_id]):
            return jsonify({"status": "error", "message": "Missing data"}), 400
        profile_data = load_profile_data(profile_name)
        if item_type not in profile_data:
            return jsonify({"status": "error", "message": "Invalid item type"}), 400
        item_list = profile_data[item_type]
        new_list = [item for item in item_list if item.get('id') != item_id]
        if len(new_list) < len(item_list):
            profile_data[item_type] = new_list
            save_profile_data(profile_name, profile_data)
            return jsonify({"status": "success", "message": "Item deleted."})
        else:
            return jsonify({"status": "error", "message": "Item not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500
        
# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True, port=8080)