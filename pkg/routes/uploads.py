import os
import uuid
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from flask_jwt_extended import jwt_required

# Create a new blueprint for upload-related routes
uploads_bp = Blueprint('uploads', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    """Checks if the file's extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@uploads_bp.route('/editor-images', methods=['POST'])
@jwt_required()
def upload_editor_image():
    """
    Handles image uploads from the ReactQuill editor.
    It saves the image to the pre-configured UPLOAD_FOLDER and returns
    a full, absolute public URL that will work in any email client.
    """
    if 'image' not in request.files:
        return jsonify({"msg": "No image part in the request"}), 400
    
    file = request.files['image']
    
    if file.filename == '':
        return jsonify({"msg": "No image selected for uploading"}), 400

    if file and allowed_file(file.filename):
        # Sanitize the original filename for security
        original_filename = secure_filename(file.filename)
        extension = original_filename.rsplit('.', 1)[1].lower()
        
        # Generate a unique filename to prevent overwrites
        unique_filename = f"{uuid.uuid4()}.{extension}"
        
        # Get the upload path from your app's config
        upload_path = current_app.config['UPLOAD_FOLDER']
        
        # Save the file to your 'Uploads' directory
        file.save(os.path.join(upload_path, unique_filename))
        

        base_url = request.host_url
        image_url = f"{base_url}uploads/{unique_filename}"
        
        # Return the full URL to the frontend
        return jsonify({"imageUrl": image_url}), 201
    else:
        return jsonify({"msg": "Allowed image types are: png, jpg, jpeg, gif"}), 400