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
from datetime import datetime

# --- Vertex AI Imports ---
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig

# --- Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-random-key-please-change-me' 
PROFILE_DIR = "profiles"
PASSWORD_FILE = "passwords.json"
RESUME_DIR = "resumes"

# --- Vertex AI Setup ---
# !!! REPLACE WITH YOUR PROJECT DETAILS !!!
YOUR_PROJECT_ID = "johanesa-playground-326616"
YOUR_LOCATION = "us-central1"  # e.g., "us-central1"

vertexai.init(project=YOUR_PROJECT_ID, location=YOUR_LOCATION)

model = GenerativeModel("gemini-2.5-flash-lite")
generation_config = GenerationConfig(
    temperature=0.2,
    max_output_tokens=8192
)

# --- MODIFIED: Default AI Prompt is now a non-editable base ---
DEFAULT_AI_PROMPT = """You are a silent, expert HTML resume generator. Your *only* output must be a single, complete HTML file.
You will be given four inputs: a candidate's profile, a job application, an HTML template, and custom user instructions.

**Your Task:**
Generate a complete, tailored HTML resume by following these rules:

1.  **GENERATE SUMMARY:** You *must* write a new, compelling "Professional Summary" (3-5 sentences). This summary must be hyper-specific to the **{job_title}** role at **{company_name}**, using keywords from the **{job_description}**.
2.  **INJECT SUMMARY:** This new summary *must* be placed inside the `<section class="section">` with the `<h2>Professional Summary</h2>` heading in the final HTML.
3.  **TAILOR CONTENT:** The "Work Experience" and "Projects" sections must be tailored. Rephrase bullet points to use action verbs and keywords from the **{job_description}** where relevant.
4.  **FOLLOW TEMPLATE:** You *must* use the exact HTML structure, class names, and CSS provided in the **{template_example}**. If there are any blank sections, do **NOT** generate the HTML codes for that section.
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

# --- MODIFIED: Default Profile Structure ---
DEFAULT_PARTICULARS = {
    "name": "", "email": "", "languages": [], "country": ""
}
DEFAULT_PROFILE = {
    "particulars": DEFAULT_PARTICULARS.copy(),
    "experiences": [], "education": [], "projects": [], "awards": [],
    "ai_custom_prompt": ""  # NEW: For user's custom instructions
}

# --- (Password Load/Save unchanged) ---
def load_passwords():
    if not os.path.exists(PASSWORD_FILE): return {}
    try:
        with open(PASSWORD_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except (json.JSONDecodeError, IOError): return {}
def save_passwords(passwords):
    with open(PASSWORD_FILE, 'w', encoding='utf-8') as f: json.dump(passwords, f, indent=4)

# --- MODIFIED: load_profile_data ---
def load_profile_data(profile_name):
    new_profile_data = DEFAULT_PROFILE.copy()
    new_profile_data['particulars'] = DEFAULT_PARTICULARS.copy()

    if not os.path.exists(PROFILE_DIR): os.makedirs(PROFILE_DIR)
    if ".." in profile_name or "/" in profile_name or "\\" in profile_name:
         return new_profile_data
    filepath = os.path.join(PROFILE_DIR, f"{profile_name}.json")
    if not os.path.exists(filepath): return new_profile_data
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                new_profile_data['experiences'] = data
                return new_profile_data
            elif isinstance(data, dict):
                new_profile_data.update(data)
                if 'particulars' not in data:
                    new_profile_data['particulars'] = DEFAULT_PARTICULARS.copy()
                else:
                    default_particulars_copy = DEFAULT_PARTICULARS.copy()
                    default_particulars_copy.update(data['particulars'])
                    new_profile_data['particulars'] = default_particulars_copy
                
                # NEW: Ensure ai_custom_prompt exists
                if 'ai_custom_prompt' not in data:
                     new_profile_data['ai_custom_prompt'] = ""

                return new_profile_data
            else: return new_profile_data
    except (json.JSONDecodeError, IOError): return new_profile_data

# --- MODIFIED: save_profile_data ---
def save_profile_data(profile_name, profile_data):
    if not os.path.exists(PROFILE_DIR): os.makedirs(PROFILE_DIR)
    if ".." in profile_name or "/" in profile_name or "\\" in profile_name:
         raise ValueError("Invalid profile name")
    filepath = os.path.join(PROFILE_DIR, f"{profile_name}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        if isinstance(profile_data, dict):
            full_data = DEFAULT_PROFILE.copy()
            full_data['particulars'] = DEFAULT_PARTICULARS.copy()
            full_data.update(profile_data)
            
            if 'particulars' in profile_data:
                full_data['particulars'] = DEFAULT_PARTICULARS.copy()
                full_data['particulars'].update(profile_data['particulars'])
            
            # Ensure ai_custom_prompt is saved
            full_data['ai_custom_prompt'] = profile_data.get('ai_custom_prompt', "")

            json.dump(full_data, f, indent=4)
        else: json.dump(DEFAULT_PROFILE, f, indent=4)

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
            save_profile_data(profile_name, DEFAULT_PROFILE.copy()) # Will save default prompt
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

# --- Resume Metadata Functions (unchanged) ---
def get_user_resume_dir():
    if 'profile_name' not in session: return None
    profile_folder = secure_filename(session['profile_name'])
    profile_resume_dir = os.path.join(RESUME_DIR, profile_folder)
    if not os.path.exists(profile_resume_dir): os.makedirs(profile_resume_dir)
    return profile_resume_dir
def load_resume_metadata(profile_resume_dir):
    metadata_path = os.path.join(profile_resume_dir, 'resumes.json')
    if not os.path.exists(metadata_path): return []
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (json.JSONDecodeError, IOError): return []
def save_resume_metadata(profile_resume_dir, metadata_list):
    metadata_path = os.path.join(profile_resume_dir, 'resumes.json')
    with open(metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata_list, f, indent=4)

# --- Resume Routes (MODIFIED) ---

@app.route('/resumes')
def resumes():
    """Shows the list of resumes and passes the user's custom AI prompt."""
    if 'profile_name' not in session:
        return redirect(url_for('login'))
    
    profile_resume_dir = get_user_resume_dir()
    resume_metadata = load_resume_metadata(profile_resume_dir)
    resume_metadata.sort(key=lambda x: x.get('generation_date', ''), reverse=True)
    
    # NEW: Load profile to get the custom prompt
    profile_data = load_profile_data(session['profile_name'])
    current_custom_prompt = profile_data.get('ai_custom_prompt', "")
        
    return render_template('resumes.html', 
                           resume_files=resume_metadata, 
                           current_custom_prompt=current_custom_prompt) # Pass custom prompt

@app.route('/resumes/<filename>')
def view_resume(filename):
    if 'profile_name' not in session: return redirect(url_for('login'))
    profile_resume_dir = get_user_resume_dir()
    if not profile_resume_dir: return "Not found", 404
    secure_name = secure_filename(filename)
    if secure_name != filename: return "Invalid filename", 400
    return send_from_directory(profile_resume_dir, secure_name)

@app.route('/download_resume/<filename>')
def download_resume(filename):
    if 'profile_name' not in session: return redirect(url_for('login'))
    profile_resume_dir = get_user_resume_dir()
    if not profile_resume_dir: return "Not found", 404
    secure_name = secure_filename(filename)
    if secure_name != filename: return "Invalid filename", 400
    filepath = os.path.join(profile_resume_dir, secure_name)
    if not os.path.exists(filepath): return "File not found", 404
    try:
        html = HTML(filename=filepath) 
        pdf_bytes = html.write_pdf()
        pdf_filename = os.path.splitext(secure_name)[0] + '.pdf'
        return Response(pdf_bytes, mimetype="application/pdf",
                        headers={"Content-Disposition": f"attachment;filename={pdf_filename}"})
    except Exception as e:
        print(f"Error converting PDF: {e}")
        flash(f'Error converting file to PDF: {e}', 'error')
        return redirect(url_for('resumes'))

@app.route('/add_resume', methods=['POST'])
def add_resume():
    if 'profile_name' not in session: return redirect(url_for('login'))
    profile_name = session['profile_name']
    profile_resume_dir = get_user_resume_dir()
    
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

    # --- MODIFIED: Use the user's custom prompt ---
    user_custom_prompt = profile_data.get('ai_custom_prompt', "")

    try:
        # Create context dictionary to format the prompt
        prompt_context = {
            "profile_json": profile_json,
            "job_title": job_title,
            "company_name": company_name,
            "job_description": job_description,
            "template_example": template_example,
            "custom_instructions": user_custom_prompt  # Inject custom instructions
        }
        
        # Format the main prompt with the context
        prompt = DEFAULT_AI_PROMPT.format_map(prompt_context)
        
        # Call Vertex AI
        response = model.generate_content(prompt, generation_config=generation_config)
        
        ai_generated_html = response.text
        ai_generated_html = ai_generated_html.strip().replace("```html", "").replace("```", "").strip()
        
        if not ai_generated_html.startswith("<!DOCTYPE html>"):
            error_snippet = ai_generated_html.replace('<', '&lt;').replace('>', '&gt;')
            raise Exception(f"AI did not return valid HTML. Response started with: {error_snippet[:300]}...")

        filepath = os.path.join(profile_resume_dir, resume_filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(ai_generated_html)
            
        metadata_list = load_resume_metadata(profile_resume_dir)
        new_resume_entry = {
            "id": str(uuid.uuid4()),
            "filename": resume_filename,
            "name": f"{job_title} at {company_name}",
            "role": job_title,
            "company": company_name,
            "generation_date": now.strftime("%Y-%m-%d %H:%M:%S")
        }
        metadata_list.append(new_resume_entry)
        save_resume_metadata(profile_resume_dir, metadata_list)
        
        flash(f'Successfully generated AI-tailored resume for {job_title}', 'success')
        
    except KeyError as e:
        # This catches if the main prompt has a missing variable (our error)
        print(f"Prompt formatting error: {e}")
        flash(f'Critical prompt error: Missing variable {e}.', 'error')
    except Exception as e:
        print(f"Error generating resume: {e}")
        flash(f'Error generating AI resume: {e}', 'error')
        
    return redirect(url_for('resumes'))

@app.route('/delete_resume', methods=['POST'])
def delete_resume():
    if 'profile_name' not in session:
        return redirect(url_for('login'))
    profile_resume_dir = get_user_resume_dir()
    resume_id = request.form.get('resume_id')
    if not resume_id:
        flash('Invalid request.', 'error')
        return redirect(url_for('resumes'))
    metadata_list = load_resume_metadata(profile_resume_dir)
    item_to_delete = next((item for item in metadata_list if item.get('id') == resume_id), None)
    if item_to_delete:
        filename = item_to_delete.get('filename')
        if filename:
            filepath = os.path.join(profile_resume_dir, secure_filename(filename))
            if os.path.exists(filepath):
                os.remove(filepath)
        new_metadata_list = [item for item in metadata_list if item.get('id') != resume_id]
        save_resume_metadata(profile_resume_dir, new_metadata_list)
        flash(f'Successfully deleted resume', 'success')
    else:
        flash('File not found.', 'error')
    return redirect(url_for('resumes'))

# --- NEW: Route to update the CUSTOM AI prompt ---
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
        
        save_profile_data(profile_name, profile_data)
        
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
    if not os.path.exists(PROFILE_DIR): os.makedirs(PROFILE_DIR)
    if not os.path.exists(RESUME_DIR): os.makedirs(RESUME_DIR)
    app.run(debug=True)