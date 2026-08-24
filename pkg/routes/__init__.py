from .auth import auth_bp
from .templates import template_bp
from .certificates import certificate_bp
from .payments import payments_bp
from .users import users_bp
from .groups import groups_bp
from .support import support_bp
from .api_v1 import api_v1_bp
from .analytics import analytics_bp
from .canva import canva_bp
from .contact import contact_bp
from .referrals import referrals_bp

#Standalones
from .uploads import uploads_bp

# Admin blueprints
from .admin_auth import admin_auth_bp
from .admin_users import admin_users_bp
from .admin_payments import admin_payments_bp
from .admin_certificates import admin_certificates_bp
from .admin_analytics import admin_analytics_bp
from .admin_support import admin_support_bp
from .admin_companies import admin_companies_bp
from .admin_companies import admin_companies_bp
from .admin_messaging import admin_messaging_bp
from .admin_team import admin_team_bp
from .admin_system import admin_system_bp

def register_blueprints(app):
    """
    Registers all imported blueprints with the Flask application.
    """
    # Public/User-facing blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(template_bp, url_prefix='/api/templates')
    app.register_blueprint(certificate_bp, url_prefix='/api/certificates')
    app.register_blueprint(payments_bp, url_prefix='/api/payments')
    app.register_blueprint(users_bp, url_prefix='/api/users')
    app.register_blueprint(groups_bp, url_prefix='/api/groups')
    app.register_blueprint(support_bp, url_prefix='/api/support')
    app.register_blueprint(api_v1_bp, url_prefix='/api/v1')
    app.register_blueprint(analytics_bp, url_prefix='/api/analytics')
    app.register_blueprint(canva_bp, url_prefix='/api/canva')
    app.register_blueprint(contact_bp, url_prefix='/api/contact')
    app.register_blueprint(referrals_bp, url_prefix='/api/referrals')
    
    # All admin blueprints are grouped under a single, consistent prefix.
    app.register_blueprint(admin_auth_bp, url_prefix='/api/admin/auth')
    app.register_blueprint(admin_users_bp, url_prefix='/api/admin')
    app.register_blueprint(admin_payments_bp, url_prefix='/api/admin')
    app.register_blueprint(admin_certificates_bp, url_prefix='/api/admin')
    app.register_blueprint(admin_analytics_bp, url_prefix='/api/admin')
    app.register_blueprint(admin_support_bp, url_prefix='/api/admin')
    app.register_blueprint(admin_companies_bp, url_prefix='/api/admin')
    app.register_blueprint(admin_messaging_bp, url_prefix='/api/admin')
    app.register_blueprint(admin_team_bp, url_prefix='/api/admin')
    app.register_blueprint(admin_system_bp, url_prefix='/api/admin')

    #Standalones
    app.register_blueprint(uploads_bp, url_prefix='/api/uploads')

    @app.route('/api/health')
    def health_check():
        return {"status": "ok"}