from pkg import create_app
from pkg.extensions import db
from pkg.models import User, Payment, Certificate, SupportTicket, SupportMessage, Group, Template
from sqlalchemy import or_

app = create_app()

def cleanup_mock_data():
    with app.app_context():
        print("Starting cleanup...")

        # 1. Delete Mock Payments
        # Identify by 'stripe' provider (since app uses paystack) OR 'tx_mock_' ref
        payments = Payment.query.filter(
            or_(
                Payment.provider == 'stripe',
                Payment.transaction_ref.like('tx_mock_%')
            )
        ).all()
        
        print(f"Found {len(payments)} mock payments.")
        for p in payments:
            # print(f"Deleting payment: {p.transaction_ref}")
            db.session.delete(p)
        db.session.commit()
        print("Mock payments deleted.")

        # 2. Find Mock Users
        mock_users = User.query.filter(
            or_(
                User.email.like('user%@example.com'),
                User.name.like('Mock User%'),
                User.email == 'test@certifyme.io'
            )
        ).all()
        
        print(f"Found {len(mock_users)} mock users.")
        for u in mock_users:
            print(f"Deleting user: {u.email}")
            
            # Delete certificates issued by this user
            Certificate.query.filter_by(user_id=u.id).delete()
            
            # Delete groups
            Group.query.filter_by(user_id=u.id).delete()
            
            # Delete templates owned by this user
            Template.query.filter_by(user_id=u.id).delete()

            # Delete tickets
            SupportTicket.query.filter_by(user_id=u.id).delete()

            # Finally delete user
            db.session.delete(u)
        
        db.session.commit()
        print("Mock users deleted.")
        
        # 3. FIX Main User Account (if corrupted)
        # User reported Enterprise plan issues. Ensure case consistency.
        target_email = 'omobolajidurojaiye57@gmail.com'
        user = User.query.filter_by(email=target_email).first()
        if user:
            print(f"Fixing account for: {user.email}")
            user.role = 'enterprise' # Force lowercase
            if user.cert_quota < 1000:
                user.cert_quota = 20000 
            db.session.commit()
            print("Account repaired.")
        else:
            print(f"User {target_email} not found. Skipping fix.")

        print("Cleanup complete!")

if __name__ == '__main__':
    cleanup_mock_data()
