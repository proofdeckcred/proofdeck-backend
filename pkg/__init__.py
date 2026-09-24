import os
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
from .extensions import db, migrate, mail, jwt
from .routes import register_blueprints
from .models import Admin, User
from celery_app import celery, make_celery

def create_app():
    # Templates are located in backend/templates, but this file is in backend/pkg/
    # So we need to point to '../templates' relative to this file's directory
    app = Flask(__name__, template_folder='../templates')

    # --- THIS IS THE DEFINITIVE CORS FIX ---
    # Allowed origins
    ALLOWED_ORIGINS = [
        "https://www.certifyme.com.ng",
        "https://certifyme.com.ng",
        "https://proofdeck.app",
        "https://www.proofdeck.app",
        "https://blog.proofdeck.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": ALLOWED_ORIGINS,
                "allow_headers": ["Content-Type", "Authorization", "X-Workspace-Context", "X-Requested-With", "Accept", "Origin"],
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
            },
            r"/uploads/*": {"origins": "*"}
        },
        supports_credentials=True
    )

    # Load configuration from environment variables
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'hbhfsgbhc67879732rgfguh378264idveydtc34')
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', '648gcvwcvotya87476fvghcjasd82784')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = 86400

    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'mysql+mysqlconnector://root@127.0.0.1/certifyme_db')
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_recycle": 280, "pool_pre_ping": True}
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    app.config['FRONTEND_URL'] = os.environ.get('FRONTEND_URL', 'https://proofdeck.app')
    app.config['PAYSTACK_SECRET_KEY'] = os.environ.get('PAYSTACK_SECRET_KEY', 'sk_test_bc2b10958c6b2ece0cab41fe4a9ebb56fff3d84f')
    app.config['PAYSTACK_PUBLIC_KEY'] = os.environ.get('PAYSTACK_PUBLIC_KEY', 'pk_test_e0d4baa25d66a069e4a300836f2f8fd04691b400')
    app.config['BACHS_SECRET_KEY'] = os.environ.get('BACHS_SECRET_KEY', 'sk_live_37743ffb_fY4qDHoKv5LUe0IEfYkZJ_o4vDbdwqvaFg9Y8QNDeqM')
    app.config['BACHS_WEBHOOK_SECRET'] = os.environ.get('BACHS_WEBHOOK_SECRET', '')
    
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'false').lower() in ['true', 'on', '1']
    app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'false').lower() in ['true', 'on', '1']
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'notifications@proofdeck.app')
    app.config['ADMIN_EMAIL'] = os.environ.get('ADMIN_EMAIL', 'omobolajidurojaiye57@gmail.com')

    upload_path = os.environ.get('UPLOAD_FOLDER') or os.path.abspath(os.path.join(app.root_path, '..', 'uploads'))
    os.makedirs(upload_path, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = upload_path
    
    # Initialize other extensions AFTER config and CORS
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    jwt.init_app(app)

    # Initialize Celery with Flask app settings if available
    if celery and hasattr(celery, 'conf'):
        redis_url = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/5')
        celery.conf.update(broker_url=redis_url, result_backend=redis_url)

    @jwt.user_lookup_loader
    def user_lookup_callback(_jwt_header, jwt_data):
        identity = jwt_data.get("sub")
        if not identity:
            return None
        try:
            uid = int(identity)
            if jwt_data.get("is_admin"):
                return Admin.query.get(uid)
            else:
                return User.query.get(uid)
        except (ValueError, TypeError, Exception):
            return None

    @jwt.invalid_token_loader
    def invalid_token_callback(error_string):
        return jsonify({"msg": f"Invalid token: {error_string}", "error": "invalid_token"}), 401

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_data):
        return jsonify({"msg": "Token has expired", "error": "token_expired"}), 401

    @app.route('/uploads/<path:filename>', methods=['GET', 'HEAD', 'OPTIONS'])
    def serve_upload(filename):
        from flask import make_response
        if request.method == 'OPTIONS':
            resp = make_response('', 204)
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
            resp.headers['Access-Control-Allow-Headers'] = '*'
            return resp
        upload_folder = app.config.get('UPLOAD_FOLDER', '')
        file_path = os.path.join(upload_folder, filename)
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            resp = jsonify({"msg": "Image not found", "error": "file_not_found"})
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp, 404
        response = send_from_directory(upload_folder, filename)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = '*'
        return response

    @app.after_request
    def add_cors_headers(response):
        from flask import request
        origin = request.headers.get('Origin')
        if origin and (origin in ALLOWED_ORIGINS or "proofdeck.app" in origin or "certifyme.com.ng" in origin):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            req_headers = request.headers.get('Access-Control-Request-Headers')
            response.headers['Access-Control-Allow-Headers'] = req_headers or 'Content-Type, Authorization, X-Workspace-Context, X-Requested-With, Accept, Origin'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, PATCH'
        return response

    register_blueprints(app)

    @app.errorhandler(404)
    def not_found(error):
        from flask import request
        origin = request.headers.get('Origin', '*')
        resp = jsonify({"msg": "Resource Not Found"})
        resp.headers['Access-Control-Allow-Origin'] = origin if origin else '*'
        resp.headers['Access-Control-Allow-Credentials'] = 'true'
        return resp, 404

    @app.errorhandler(500)
    def internal_error(error):
        from flask import request
        db.session.rollback()
        origin = request.headers.get('Origin', '*')
        resp = jsonify({"msg": "Internal Server Error", "error": str(error)})
        resp.headers['Access-Control-Allow-Origin'] = origin if origin else '*'
        resp.headers['Access-Control-Allow-Credentials'] = 'true'
        return resp, 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        from flask import request
        import traceback
        app.logger.error(f"Unhandled Exception: {e}\n{traceback.format_exc()}")
        db.session.rollback()
        origin = request.headers.get('Origin', '*')
        resp = jsonify({"msg": f"Server Error: {str(e)}", "error": str(e)})
        resp.headers['Access-Control-Allow-Origin'] = origin if origin else '*'
        resp.headers['Access-Control-Allow-Credentials'] = 'true'
        return resp, 500

    return app