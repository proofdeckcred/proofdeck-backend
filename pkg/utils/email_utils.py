from flask_mail import Message
from flask import current_app
from ..extensions import mail
from datetime import datetime

def send_verification_email(user, code):
    """
    Sends a 6-digit verification code to a new user for account activation.
    """
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f4f4f4; }}
            .container {{ max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; }}
            .header {{ font-size: 24px; color: #333; text-align: center; padding: 10px; }}
            .code {{ font-size: 36px; font-weight: bold; color: #2563EB; text-align: center; margin: 20px 0; letter-spacing: 5px; }}
            .footer {{ font-size: 12px; text-align: center; color: #888; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">Welcome to ProofDeck!</div>
            <p>Hello {user.name},</p>
            <p>Thank you for signing up! To complete your registration and secure your account, please use the following verification code:</p>
            <div class="code">{code}</div>
            <p>This code is valid for the next 15 minutes. If you did not sign up for a ProofDeck account, you can safely ignore this email.</p>
            <div class="footer">
                This is an automated message from ProofDeck.
            </div>
        </div>
    </body>
    </html>
    """
    msg = Message(
        subject="Your ProofDeck Verification Code",
        sender=('ProofDeck', current_app.config.get('MAIL_USERNAME')),
        recipients=[user.email],
        html=html_body
    )
    try:
        mail.send(msg)
        current_app.logger.info(f"Verification email sent to: {user.email}")
    except Exception as e:
        current_app.logger.error(f"Failed to send verification email: {e}")
        raise


def send_admin_verification_email(admin_user):
    """
    Sends the 6-digit verification code to the pre-configured ADMIN_EMAIL
    to authorize the creation of a new admin account.
    """
    trusted_recipient = current_app.config.get('ADMIN_EMAIL')
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f4f4f4; }}
            .container {{ max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; }}
            .header {{ font-size: 24px; color: #333; text-align: center; padding: 10px; }}
            .code {{ font-size: 36px; font-weight: bold; color: #dc3545; text-align: center; margin: 20px 0; letter-spacing: 5px; }}
            .footer {{ font-size: 12px; text-align: center; color: #888; margin-top: 20px; }}
            .alert {{ border-left: 4px solid #ffc107; padding: 10px; background-color: #fff3cd; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">ProofDeck Admin Account Request</div>
            <div class="alert">
                <strong>Security Alert:</strong> A request has been made to create a new administrator account.
            </div>
            <p>Hello,</p>
            <p>
                An attempt to create a new admin account with the following details was made:
                <br>
                - <strong>Name:</strong> {admin_user.name}
                <br>
                - <strong>Email:</strong> {admin_user.email}
            </p>
            <p>To authorize this action, use the verification code below:</p>
            <div class="code">{admin_user.verification_code}</div>
            <p>This code will expire in 15 minutes. If you did not request this, you can safely ignore this email. No account will be created without this code.</p>
            <div class="footer">
                This is an automated security message from ProofDeck.
            </div>
        </div>
    </body>
    </html>
    """
    msg = Message(
        subject="[Action Required] New ProofDeck Admin Account Request",
        sender=('ProofDeck Security', current_app.config.get('MAIL_USERNAME')),
        recipients=[trusted_recipient],
        html=html_body
    )
    try:
        mail.send(msg)
        current_app.logger.info(f"Admin verification email sent to trusted address: {trusted_recipient}")
    except Exception as e:
        current_app.logger.error(f"Failed to send admin verification email: {e}")
        raise

def send_password_reset_email(user, reset_url):
    """
    Sends a password reset link to a user.
    """
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f4f4f4; }}
            .container {{ max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; }}
            .header {{ font-size: 24px; color: #333; text-align: center; padding: 10px; }}
            .button {{ display: inline-block; padding: 12px 25px; margin: 20px 0; font-size: 16px; color: #fff; background-color: #0d6efd; text-decoration: none; border-radius: 5px; }}
            .footer {{ font-size: 12px; text-align: center; color: #888; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">ProofDeck Password Reset Request</div>
            <div class="content">
                <p>Hello,</p>
                <p>We received a request to reset your password for your ProofDeck account.</p>
                <p>Please click the button below to reset your password:</p>
                <p style="text-align: center;">
                    <a href="{reset_url}" class="button">Reset Password</a>
                </p>
                <p>If you did not request a password reset, please ignore this email or contact support if you have questions.</p>
                <p>This link will expire in 1 hour.</p>
            </div>
            <div class="footer">
                This is an automated message from ProofDeck.
            </div>
        </div>
    </body>
    </html>
    """
    msg = Message(
        subject="Your ProofDeck Password Reset Link",
        sender=('ProofDeck Support', current_app.config.get('MAIL_USERNAME')),
        recipients=[user.email],
        html=html_body
    )
    try:
        mail.send(msg)
        current_app.logger.info(f"Password reset email sent to: {user.email}")
    except Exception as e:
        current_app.logger.error(f"Failed to send password reset email: {e}")
        raise

def send_bulk_email(users, subject, user_content, header_image_url=None):
    """
    Sends a personalized, professionally templated email to a list of user objects.
    - Personalizes content by replacing '{{ user_name }}' with the user's name.
    - Includes an optional header image with compact size and rounded corners.
    - Uses a robust, responsive HTML template.
    """
    social_links = {
        'instagram': current_app.config.get('SOCIAL_INSTAGRAM', '#'),
        'facebook': current_app.config.get('SOCIAL_FACEBOOK', '#'),
        'linkedin': 'https://www.linkedin.com/company/proofdeck',
        'twitter': 'https://x.com/proofdeck',
    }

    try:
        with mail.connect() as conn:
            for user in users:
                # Personalize the content for each user, default to 'User' if name is None
                personalized_content = user_content.replace('{{ user_name }}', user.name or 'User')

                html_body = f"""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>{subject}</title>
                    <style>
                        body {{ margin: 0; padding: 0; background-color: #f2f4f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol'; }}
                        .wrapper {{ width: 100%; table-layout: fixed; background-color: #f2f4f6; padding: 40px 0; }}
                        .main {{ margin: 0 auto; width: 100%; max-width: 600px; background-color: #ffffff; border-spacing: 0; border-radius: 8px; }}
                        .content {{ padding: 20px 40px; color: #333333; font-size: 16px; line-height: 1.6; }}
                        .footer {{ padding: 20px 40px; text-align: center; color: #6c757d; font-size: 12px; }}
                        .social-icons img {{ width: 24px; height: 24px; margin: 0 8px; }}
                        a {{ color: #2563EB; text-decoration: none; }}
                        .header-image {{ max-width: 600px; width: 100%; height: auto; display: block; border-radius: 8px; }}
                    </style>
                </head>
                <body>
                    <center class="wrapper">
                        <table class="main" width="100%">
                            <!-- HEADER IMAGE (OPTIONAL) -->
                            {f'<tr><td><img src="{header_image_url}" alt="Header" class="header-image"></td></tr>' if header_image_url else ''}
                            
                            <!-- MAIN CONTENT -->
                            <tr>
                                <td class="content">
                                    {personalized_content}
                                </td>
                            </tr>

                            <!-- FOOTER -->
                            <tr>
                                <td class="footer">
                                    <p style="margin-bottom: 20px;">Follow us on:</p>
                                    <p class="social-icons">
                                        <a href="{social_links['instagram']}"><img src="https://i.ibb.co/6rW8k04/instagram.png" alt="Instagram"></a>
                                        <a href="{social_links['facebook']}"><img src="https://i.ibb.co/d2r03s7/facebook.png" alt="Facebook"></a>
                                        <a href="{social_links['linkedin']}"><img src="https://i.ibb.co/xY7Xq65/linkedin.png" alt="LinkedIn"></a>
                                        <a href="{social_links['twitter']}"><img src="https://upload.wikimedia.org/wikipedia/commons/thumb/c/ce/X_logo_2023.svg/48px-X_logo_2023.svg.png" alt="X (Twitter)"></a>
                                    </p>
                                    <p style="margin-top: 20px;">ProofDeck: Digital Certificates Made Simple</p>
                                    <p>&copy; {datetime.now().year} ProofDeck. All rights reserved.</p>
                                </td>
                            </tr>
                        </table>
                    </center>
                </body>
                </html>
                """

                msg = Message(
                    subject=subject,
                    sender=('ProofDeck', current_app.config.get('MAIL_USERNAME')),
                    recipients=[user.email],
                    html=html_body
                )
                conn.send(msg)
        current_app.logger.info(f"Successfully sent bulk email to {len(users)} recipients.")
    except Exception as e:
        current_app.logger.error(f"Failed during bulk email sending: {e}")
        raise

def send_support_email(email, message):
    """
    Sends a support notification email to the admin.
    """
    trusted_recipient = current_app.config.get('MAIL_USERNAME') or current_app.config.get('ADMIN_EMAIL')
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .container {{ max-width: 600px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 8px; }}
            .header {{ background-color: #f8f9fa; padding: 10px; text-align: center; border-bottom: 1px solid #eee; }}
            .content {{ padding: 20px 0; }}
            .footer {{ font-size: 12px; color: #888; text-align: center; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h3>New Support Message</h3></div>
            <div class="content">
                <p><strong>From:</strong> {email}</p>
                <p><strong>Message:</strong></p>
                <div style="background-color: #f9f9f9; padding: 15px; border-radius: 4px; border-left: 4px solid #0d6efd;">
                    {message}
                </div>
            </div>
            <div class="footer">
                Sent from ProofDeck Support Widget
            </div>
        </div>
    </body>
    </html>
    """
    
    msg = Message(
        subject=f"Support Request from {email}",
        sender=('ProofDeck Support', current_app.config.get('MAIL_USERNAME')),
        recipients=[trusted_recipient],
        html=html_body,
        reply_to=email
    )
    
    try:
        mail.send(msg)
        current_app.logger.info(f"Support email sent from {email}")
    except Exception as e:
        current_app.logger.error(f"Failed to send support email: {e}")