from flask_mail import Message
from flask import current_app

def create_certificate_email(certificate, pdf_buffer):
    verification_url = f"{current_app.config['FRONTEND_URL']}/verify/{certificate.verification_id}"
    
    # Determine wording based on type (Receipt vs Certificate)
    is_receipt = hasattr(certificate, 'template') and certificate.template.layout_style == 'receipt'
    subject = f"Payment Receipt: {certificate.course_title}" if is_receipt else f"Your Certificate: {certificate.course_title}"
    
    header_text = "Payment Receipt" if is_receipt else f"Congratulations, {certificate.recipient_name}!"
    body_text = f"Please find attached your payment receipt for <strong>{certificate.course_title}</strong>." if is_receipt else f"You have been awarded a certificate for successfully completing: <strong>{certificate.course_title}</strong>"
    button_text = "Verify Receipt" if is_receipt else "View & Verify Certificate"

    html_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: sans-serif; background-color: #f4f7f6; padding: 20px; }}
            .container {{ width: 100%; max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.05); }}
            .header {{ text-align: center; border-bottom: 1px solid #eee; padding-bottom: 20px; margin-bottom: 20px; }}
            .content {{ text-align: center; color: #333; }}
            .button {{ background-color: #2563EB; color: #ffffff !important; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block; margin-top: 20px; }}
            .footer {{ text-align: center; font-size: 12px; color: #999; margin-top: 30px; border-top: 1px solid #eee; padding-top: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>{header_text}</h2>
            </div>
            <div class="content">
                <p>Hello {certificate.recipient_name},</p>
                <p>{body_text}</p>
                <p>Your document is attached to this email.</p>
                <a href="{verification_url}" class="button" target="_blank">{button_text}</a>
            </div>
            <div class="footer">
                <p>Issued by {certificate.issuer_name} via ProofDeck</p>
                <p>Verification ID: {certificate.verification_id}</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    msg = Message(
        subject=subject,
        sender=('ProofDeck', current_app.config.get('MAIL_USERNAME')),
        recipients=[certificate.recipient_email],
        html=html_body
    )
    
    # Attach PDF
    filename = "receipt.pdf" if is_receipt else "certificate.pdf"
    msg.attach(filename, "application/pdf", pdf_buffer.getvalue())
    
    return msg