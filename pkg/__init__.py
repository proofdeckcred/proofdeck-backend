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
    # We are explicitly defining all allowed origins and resource paths.
    # This removes any ambiguity.
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": ["https://www.certifyme.com.ng", "https://proofdeck.app", "https://www.proofdeck.app", "http://localhost:5173"]
            },
            r"/uploads/*": {
                "origins": ["https://www.certifyme.com.ng", "https://proofdeck.app", "https://www.proofdeck.app", "http://localhost:5173"]
            }
        },
        supports_credentials=True
    )
    # --- END OF FIX ---

    # Load configuration from environment variables
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_default_secret_key')
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'a_default_jwt_key')
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

    # Initialize Celery with Flask app context
    celery.conf.update(broker_url=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))
    celery.conf.update(result_backend=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    @jwt.user_lookup_loader
    def user_lookup_callback(_jwt_header, jwt_data):
        identity = jwt_data["sub"]
        if jwt_data.get("is_admin"):
            return Admin.query.get(int(identity))
        else:
            return User.query.get(int(identity))

    @app.route('/uploads/<path:filename>')
    def serve_upload(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    register_blueprints(app)

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"msg": "Resource Not Found"}), 404

    return app