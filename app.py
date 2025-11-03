import os
import json
import uuid
from flask import (
    Flask, render_template, request, jsonify, redirect, 
    url_for, session, flash, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- NEW: Vertex AI Imports ---
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig

# --- Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-random-key-please-change-me' 
PROFILE_DIR = "profiles"
PASSWORD_FILE = "passwords.json"
RESUME_DIR = "resumes"

# --- NEW: Vertex AI Setup ---
# !!! REPLACE WITH YOUR PROJECT DETAILS !!!
YOUR_PROJECT_ID = "johanesa-playground-326616"
YOUR_LOCATION = "us-central1"  # e.g., "us-central1"

vertexai.init(project=YOUR_PROJECT_ID, location=YOUR_LOCATION)

# Load the model (Using Flash as it's fast and cost-effective for this)
model = GenerativeModel("gemini-2.5-flash-lite")
generation_config = GenerationConfig(
    temperature=0.2,
    max_output_tokens=8192 # Increase token limit for full HTML
)

# --- Default Profile Structure (Unchanged) ---
DEFAULT_PARTICULARS = {
    "name": "", "email": "", "links": [], "languages": [], "country": ""
}
DEFAULT_PROFILE = {
    "particulars": DEFAULT_PARTICULARS.copy(),
    "experiences": [], "education": [], "projects": [], "awards": []
}

# --- (Password and Profile Data load/save functions are unchanged) ---
def load_passwords():
    if not os.path.exists(PASSWORD_FILE): return {}
    try:
        with open(PASSWORD_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_passwords(passwords):
    with open(PASSWORD_FILE, 'w', encoding='utf-8') as f:
        json.dump(passwords, f, indent=4)

def load_profile_data(profile_name):
    new_profile_data = DEFAULT_PROFILE.copy()
    new_profile_data['particulars'] = DEFAULT_PARTICULARS.copy()
    if not os.path.exists(PROFILE_DIR): os.makedirs(PROFILE_DIR)
    if ".." in profile_name or "/" in profile_name or "\\" in profile_name:
         return new_profile_data
    filepath = os.path.join(PROFILE_DIR, f"{profile_name}.json")
    if not os.path.exists(filepath):
        return new_profile_data
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                new_profile_data['experiences'] = data
                return new_profile_data
            elif isinstance(data, dict):
                new_profile_data.update(data)
                if 'particulars' not in new_profile_data:
                    new_profile_data['particulars'] = DEFAULT_PARTICULARS.copy()
                else:
                    default_particulars_copy = DEFAULT_PARTICULARS.copy()
                    default_particulars_copy.update(new_profile_data['particulars'])
                    new_profile_data['particulars'] = default_particulars_copy
                return new_profile_data
            else:
                return new_profile_data
    except (json.JSONDecodeError, IOError):
        return new_profile_data

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
            json.dump(full_data, f, indent=4)
        else:
            json.dump(DEFAULT_PROFILE, f, indent=4)


# --- Auth Routes (unchanged) ---
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

# --- Main Page (unchanged) ---
@app.route('/')
def index():
    if 'profile_name' not in session:
        return redirect(url_for('login'))
    profile_name = session['profile_name']
    profile_data = load_profile_data(profile_name)
    return render_template('index.html', 
                           profile_name=profile_name, 
                           profile_data=profile_data)

# --- NEW: Helper for Resume Routes ---
def get_user_resume_dir():
    """Helper to get the user's specific resume folder."""
    if 'profile_name' not in session:
        return None
    # Securely join paths
    profile_folder = secure_filename(session['profile_name'])
    profile_resume_dir = os.path.join(RESUME_DIR, profile_folder)
    if not os.path.exists(profile_resume_dir):
        os.makedirs(profile_resume_dir)
    return profile_resume_dir

# --- Resume Routes (MODIFIED) ---

@app.route('/resumes')
def resumes():
    """Shows the list of generated resumes."""
    if 'profile_name' not in session:
        return redirect(url_for('login'))
    
    profile_resume_dir = get_user_resume_dir()
    resume_files = []
    if profile_resume_dir:
        resume_files = [f for f in os.listdir(profile_resume_dir) if f.endswith('.html')]
        
    return render_template('resumes.html', resume_files=resume_files)

@app.route('/resumes/<filename>')
def view_resume(filename):
    """Securely serves a generated resume file."""
    if 'profile_name' not in session:
        return redirect(url_for('login'))
        
    profile_resume_dir = get_user_resume_dir()
    if not profile_resume_dir:
        return "Not found", 404
    
    secure_name = secure_filename(filename)
    if secure_name != filename:
        return "Invalid filename", 400

    return send_from_directory(profile_resume_dir, secure_name)

# --- THIS IS THE NEW, AI-POWERED ROUTE ---
@app.route('/add_resume', methods=['POST'])
def add_resume():
    """Generates a new resume using AI."""
    if 'profile_name' not in session:
        return redirect(url_for('login'))
        
    profile_name = session['profile_name']
    profile_resume_dir = get_user_resume_dir()
    
    # 1. Get data from the new form
    resume_name_base = request.form.get('resume_name', 'My Resume')
    job_description = request.form.get('job_description') # NEW
    
    if not job_description:
        flash('Job description cannot be empty.', 'error')
        return redirect(url_for('resumes'))
        
    resume_filename = secure_filename(resume_name_base) + '.html'
    
    # 2. Load the user's profile data
    profile_data = load_profile_data(profile_name)
    profile_json = json.dumps(profile_data)
    
    # 3. Load the HTML template to use as a style guide for the AI
    try:
        with open('templates/resume_template.html', 'r', encoding='utf-8') as f:
            template_example = f.read()
    except FileNotFoundError:
        flash('ERROR: resume_template.html not found.', 'error')
        return redirect(url_for('resumes'))

    # 4. Create the prompt
    prompt = f"""
    You are an expert resume writer and a front-end developer. Your task is to generate a professional, single-page HTML resume, tailored to a specific job description.

    You will be given:
    1.  **PROFILE_DATA:** A JSON object of the candidate's full profile.
    2.  **JOB_DESCRIPTION:** The text of the job description they are applying for.
    3.  **HTML_TEMPLATE:** An example HTML file to use for structure and CSS.

    Your task is to merge these three elements. You must:
    1.  Analyze the JOB_DESCRIPTION for key skills and requirements.
    2.  Analyze the PROFILE_DATA to find matching experiences, skills, and projects.
    3.  Using PROFILE_DATA, generate a new description for every experience, project and award to match the JOB_DESCRIPTION. Ensure that the description includes metrics of how the projects have improved the organizations. If no metrics are found in the original description, estimate the metrics. 
    4.  Write a new resume, using the newly generated descriptions. Rephrase bullet points to use keywords from the job description.
    5.  Format the *entire* output as a single, complete HTML file, using the exact structure, class names, and CSS from the HTML_TEMPLATE.
    6.  The final output must be *only* the HTML code. It must start with `<!DOCTYPE html>` and end with `</html>`. Do not include *any* other text, explanations, or markdown backticks.

    ---
    PROFILE_DATA:
    {profile_json}
    ---
    JOB_DESCRIPTION:
    {job_description}
    ---
    HTML_TEMPLATE:
    {template_example}
    ---

    Now, generate the tailored HTML resume.
    """
    
    try:
        # 5. Call the Vertex AI model
        response = model.generate_content(
            prompt,
            generation_config=generation_config
        )
        
        # 6. Clean and save the response
        ai_generated_html = response.text
        
        # Clean up potential markdown backticks (just in case)
        ai_generated_html = ai_generated_html.strip().replace("```html", "").replace("```", "").strip()
        
        if not ai_generated_html.startswith("<!DOCTYPE html>"):
            raise Exception("AI did not return valid HTML. Response: " + ai_generated_html[:200])

        # 7. Save the rendered HTML to a file
        filepath = os.path.join(profile_resume_dir, resume_filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(ai_generated_html)
            
        flash(f'Successfully generated AI-tailored resume "{resume_filename}"', 'success')
        
    except Exception as e:
        print(f"Error generating resume: {e}")
        flash(f'Error generating AI resume: {e}', 'error')
        
    return redirect(url_for('resumes'))


@app.route('/delete_resume', methods=['POST'])
def delete_resume():
    """Deletes a specific resume file."""
    if 'profile_name' not in session:
        return redirect(url_for('login'))
        
    profile_resume_dir = get_user_resume_dir()
    filename = request.form.get('filename')
    
    secure_name = secure_filename(filename)
    if not filename or secure_name != filename:
        flash('Invalid filename.', 'error')
        return redirect(url_for('resumes'))
        
    filepath = os.path.join(profile_resume_dir, secure_name)
    
    if os.path.exists(filepath):
        os.remove(filepath)
        flash(f'Successfully deleted "{secure_name}"', 'success')
    else:
        flash('File not found.', 'error')
        
    return redirect(url_for('resumes'))

# --- (All previous /update_item, /delete_item, etc. routes) ---
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