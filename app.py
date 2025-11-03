import os
import json
import uuid
from flask import (
    Flask, render_template, request, jsonify, redirect, 
    url_for, session, flash, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename # NEW

# --- Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-random-key-please-change-me' 
PROFILE_DIR = "profiles"
PASSWORD_FILE = "passwords.json"
RESUME_DIR = "resumes" # NEW

# --- Default Profile Structure ---
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

# --- (Data Endpoints: /update_particulars, /add, /update_item, etc. are unchanged) ---
# ... (all the add, update, delete endpoints from previous step go here) ...
# (routes /update_particulars, /add, /add_education, /add_project, /add_award)
# (routes /update_item, /delete_item)
# ... (omitted for brevity, but they must be present) ...

# --- NEW: Resume Routes ---

def get_user_resume_dir():
    """Helper to get the user's specific resume folder."""
    if 'profile_name' not in session:
        return None
    profile_resume_dir = os.path.join(RESUME_DIR, session['profile_name'])
    if not os.path.exists(profile_resume_dir):
        os.makedirs(profile_resume_dir)
    return profile_resume_dir

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
    
    # Securely check filename
    secure_name = secure_filename(filename)
    if secure_name != filename:
        return "Invalid filename", 400

    return send_from_directory(profile_resume_dir, secure_name)

@app.route('/add_resume', methods=['POST'])
def add_resume():
    """Generates a new resume from current data."""
    if 'profile_name' not in session:
        return redirect(url_for('login'))
        
    profile_name = session['profile_name']
    profile_resume_dir = get_user_resume_dir()
    
    resume_name_base = request.form.get('resume_name', 'My Resume')
    # Make sure it's a safe HTML filename
    resume_filename = secure_filename(resume_name_base) + '.html'
    
    # 1. Load the user's data
    profile_data = load_profile_data(profile_name)
    
    # 2. Render the resume template with the data
    # We pass the data in a 'data' variable to the template
    rendered_html = render_template('resume_template.html', data=profile_data)
    
    # 3. Save the rendered HTML to a file
    filepath = os.path.join(profile_resume_dir, resume_filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(rendered_html)
        
    flash(f'Successfully generated "{resume_filename}"', 'success')
    return redirect(url_for('resumes'))

@app.route('/delete_resume', methods=['POST'])
def delete_resume():
    """Deletes a specific resume file."""
    if 'profile_name' not in session:
        return redirect(url_for('login'))
        
    profile_resume_dir = get_user_resume_dir()
    filename = request.form.get('filename')
    
    # Security: Ensure filename is safe and exists
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

# --- (all the add, update, delete endpoints from previous step go here) ---
# (routes /update_particulars, /add, /add_education, /add_project, /add_award)
# (routes /update_item, /delete_item)
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
    if not os.path.exists(RESUME_DIR): os.makedirs(RESUME_DIR) # NEW
    app.run(debug=True)