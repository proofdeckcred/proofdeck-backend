import pandas as pd
import uuid
from io import BytesIO
from ..models import db, Certificate, User, Template
from ..utils.helpers import parse_smart_date, normalize_email, normalize_headers
from ..services.email_service import create_certificate_email
from ..services.pdf_service import generate_certificate_pdf
from ..extensions import mail
from datetime import datetime

def process_bulk_upload(app, file_content, filename, template_id, group_id, user_id):
    """
    Reads file content (bytes), normalizes data, and creates certificates in bulk (Background Task).
    Sends an email summary to the issuer upon completion.
    """
    with app.app_context():
        user = User.query.get(user_id)
        template = Template.query.get(template_id)
        
        # 1. Read File
        try:
            if filename.lower().endswith(('.xlsx', '.xls', '.ods')):
                df = pd.read_excel(BytesIO(file_content))
            else:
                df = pd.read_csv(BytesIO(file_content))
        except Exception as e:
            # We can't return this error to the HTTP caller anymore, 
            # but we should log it or notify the user via email if possible.
            print(f"Background Upload Error: {e}")
            return

        if df.empty:
            print("Background Upload Error: File is empty")
            return

        # 2. Smart Normalization
        df = normalize_headers(df)

        # 3. Validation
        required_cols = {'recipient_name', 'course_title', 'issue_date'}
        missing = required_cols - set(df.columns)
        if missing:
            # Fallback detection could go here
            print(f"Background Upload Error: Missing columns {missing}")
            return

        # 4. Processing
        certs_to_add = []
        errors = []
        quota_left = user.cert_quota
        
        # Replace NaN with None
        df = df.where(pd.notna(df), None)

        for idx, row in df.iterrows():
            row_num = idx + 2 # Excel starts at 1, header is 1
            
            if quota_left <= 0:
                errors.append({"row": row_num, "msg": "Quota exhausted. Upgrade plan to continue."})
                continue

            try:
                # Data Extraction
                r_name = row.get('recipient_name')
                c_title = row.get('course_title')
                i_date_raw = row.get('issue_date')

                if not r_name or not c_title:
                    errors.append({"row": row_num, "msg": "Missing Name or Course Title."})
                    continue

                # Smart Date Parsing (Fixes the Excel 45587 error)
                i_date = parse_smart_date(i_date_raw)

                # Optional Fields
                r_email = normalize_email(row.get('recipient_email'))
                issuer = str(row.get('issuer_name')) if row.get('issuer_name') else (user.company.name if user.company else user.name)
                sig = str(row.get('signature')) if row.get('signature') else None
                
                # Extra Fields (Amount, etc)
                extra_fields = {}
                if row.get('amount'):
                    extra_fields['amount'] = str(row.get('amount'))

                # Create Object
                cert = Certificate(
                    user_id=user.id,
                    company_id=user.company_id,
                    template_id=template.id,
                    group_id=group_id,
                    recipient_name=str(r_name),
                    recipient_email=r_email,
                    course_title=str(c_title),
                    issuer_name=issuer,
                    issue_date=i_date,
                    signature=sig,
                    extra_fields=extra_fields,
                    verification_id=str(uuid.uuid4())
                )
                
                certs_to_add.append(cert)
                quota_left -= 1

            except Exception as e:
                errors.append({"row": row_num, "msg": str(e)})

        # 5. Commit to DB
        if certs_to_add:
            try:
                db.session.bulk_save_objects(certs_to_add)
                user.cert_quota = quota_left
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Background Upload DB Error: {e}")
                return

        # 6. Notification (Email Issuer)
        try:
            from ..routes.certificates import _send_issuer_notification_email
            
            created_count = len(certs_to_add)
            error_count = len(errors)
            
            summary_html = f"""
            <h3>Bulk Processing Complete</h3>
            <p><strong>{created_count}</strong> documents have been successfully generated.</p>
            <p><strong>{error_count}</strong> rows had errors/warnings.</p>
            """
            
            if errors:
                summary_html += "<ul>"
                for err in errors[:10]: # Limit error list in email
                    summary_html += f"<li>Row {err['row']}: {err['msg']}</li>"
                if len(errors) > 10:
                    summary_html += f"<li>... and {len(errors) - 10} more errors.</li>"
                summary_html += "</ul>"

            summary_html += "<p>Please check your dashboard to view the new certificates.</p>"

            _send_issuer_notification_email(user, "Bulk Processing Complete — ProofDeck", summary_html)
            
        except Exception as e:
            print(f"Notification Error: {e}")