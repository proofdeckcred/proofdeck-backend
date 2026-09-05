import base64
import pandas as pd
import uuid
from io import BytesIO
from datetime import datetime
from celery_app import celery
from ..models import db, Certificate, User, Template, Tenant, Group, BackgroundJob, Notification, QuotaTransaction
from ..extensions import mail
from ..services.pdf_service import generate_certificate_pdf
from ..services.email_service import create_certificate_email
from ..utils.helpers import parse_smart_date, normalize_email, normalize_headers


@celery.task(bind=True)
def process_bulk_upload_task(self, job_id, file_content_b64, filename, template_id, group_id, user_id, is_comp=False, company_id=None):
    """
    Celery task for processing bulk certificate uploads with incremental progress and live database commits.
    Runs inside Flask app context automatically via ContextTask.
    """
    job = BackgroundJob.query.get(job_id)
    if not job:
        print(f"Bulk Task Error: Job #{job_id} not found.")
        return

    job.status = 'processing'
    db.session.commit()

    user = User.query.get(user_id)
    template = Template.query.get(template_id)

    quota_holder = user
    tenant_name = None
    if is_comp and company_id:
        tenant = Tenant.query.get(company_id)
        if tenant:
            tenant_name = tenant.name
            quota_holder = tenant

    # 1. Read File
    try:
        file_content = base64.b64decode(file_content_b64)
        if filename.lower().endswith(('.xlsx', '.xls', '.ods')):
            df = pd.read_excel(BytesIO(file_content))
        else:
            df = pd.read_csv(BytesIO(file_content))
    except Exception as e:
        job.status = 'failed'
        job.result_summary = {"error": f"Failed to read file: {e}"}
        job.completed_at = datetime.utcnow()
        notif = Notification(
            user_id=user.id,
            title="Bulk upload failed",
            message=f"Could not read your file: {e}",
            type="error",
            category="bulk_complete",
            reference_id=job.id
        )
        db.session.add(notif)
        db.session.commit()
        return

    if df.empty:
        job.status = 'failed'
        job.result_summary = {"error": "File is empty"}
        job.completed_at = datetime.utcnow()
        notif = Notification(
            user_id=user.id,
            title="Bulk upload failed",
            message="The uploaded file is empty.",
            type="error",
            category="bulk_complete",
            reference_id=job.id
        )
        db.session.add(notif)
        db.session.commit()
        return

    # 2. Smart Normalization
    df = normalize_headers(df)

    # 3. Validation
    if 'recipient_name' not in df.columns:
        job.status = 'failed'
        job.result_summary = {"error": "Missing compulsory 'recipient_name' column"}
        job.completed_at = datetime.utcnow()
        notif = Notification(
            user_id=user.id,
            title="Bulk upload failed",
            message="Missing compulsory 'recipient_name' column in your file.",
            type="error",
            category="bulk_complete",
            reference_id=job.id
        )
        db.session.add(notif)
        db.session.commit()
        return

    # Update total items immediately so progress bar shows real total
    job.total_items = len(df)
    job.processed_items = 0
    job.failed_items = 0
    db.session.commit()

    # 4. Processing with incremental commits
    errors = []
    quota_left = quota_holder.cert_quota
    df = df.where(pd.notna(df), None)

    processed = 0
    failed = 0

    for idx, row in df.iterrows():
        row_num = idx + 2

        if quota_left <= 0:
            errors.append({"row": row_num, "msg": "Quota exhausted. Upgrade plan to continue."})
            failed += 1
            job.failed_items = failed
            db.session.commit()
            continue

        try:
            r_name = row.get('recipient_name')
            c_title = str(row.get('course_title')) if row.get('course_title') else ""
            i_date_raw = row.get('issue_date')

            if not r_name:
                errors.append({"row": row_num, "msg": "Missing compulsory recipient name."})
                failed += 1
                job.failed_items = failed
                db.session.commit()
                continue

            i_date = parse_smart_date(i_date_raw)
            r_email = normalize_email(row.get('recipient_email'))
            issuer = str(row.get('issuer_name')) if row.get('issuer_name') else (tenant_name if (is_comp and tenant_name) else user.name)
            sig = str(row.get('signature')) if row.get('signature') else None

            extra_fields = {}
            if row.get('amount'):
                extra_fields['amount'] = str(row.get('amount'))

            cert = Certificate(
                user_id=user.id,
                tenant_id=company_id if is_comp else None,
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

            db.session.add(cert)
            db.session.flush()

            # Record Quota deduction
            txn = QuotaTransaction(
                tenant_id=company_id if is_comp else None,
                user_id=user.id,
                certificate_id=cert.id,
                amount=-1
            )
            db.session.add(txn)

            quota_left -= 1
            quota_holder.cert_quota = quota_left
            processed += 1

            # Update job progress on every row
            job.processed_items = processed
            job.failed_items = failed
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            errors.append({"row": row_num, "msg": str(e)})
            failed += 1
            job.failed_items = failed
            db.session.commit()

    # 5. Mark completed
    job.status = 'completed'
    job.completed_at = datetime.utcnow()
    job.result_summary = {
        "created": processed,
        "errors": len(errors),
        "error_details": errors[:10]
    }

    notif = Notification(
        user_id=user.id,
        title="Bulk upload complete",
        message=f"{processed} certificates issued successfully." + (f" {len(errors)} rows had errors." if errors else ""),
        type="success",
        category="bulk_complete",
        reference_id=job.id
    )
    db.session.add(notif)
    db.session.commit()

    # 6. Email notification to issuer
    try:
        from ..routes.certificates import _send_issuer_notification_email

        summary_html = f"""
        <h3>Bulk Processing Complete</h3>
        <p><strong>{processed}</strong> documents have been successfully generated.</p>
        <p><strong>{len(errors)}</strong> rows had errors/warnings.</p>
        """

        if errors:
            summary_html += "<ul>"
            for err in errors[:10]:
                summary_html += f"<li>Row {err['row']}: {err['msg']}</li>"
            if len(errors) > 10:
                summary_html += f"<li>... and {len(errors) - 10} more errors.</li>"
            summary_html += "</ul>"

        summary_html += "<p>Please check your dashboard to view the new certificates.</p>"

        _send_issuer_notification_email(user, "Bulk Processing Complete — ProofDeck", summary_html)

    except Exception as e:
        print(f"Email Notification Error: {e}")


@celery.task(bind=True)
def process_bulk_email_task(self, job_id, group_id, user_id, is_comp=False, tenant_id=None):
    """
    Celery task for sending bulk emails to unsent certificates in a group with live progress tracking.
    """
    job = BackgroundJob.query.get(job_id)
    if not job:
        print(f"Bulk Email Task Error: Job #{job_id} not found.")
        return

    job.status = 'processing'
    db.session.commit()

    user = User.query.get(user_id)
    if is_comp and tenant_id:
        group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first()
    else:
        group = Group.query.filter_by(id=group_id, user_id=user_id).first()

    if not group:
        job.status = 'failed'
        job.result_summary = {"error": "Group not found"}
        job.completed_at = datetime.utcnow()
        db.session.commit()
        return

    certificates_to_send = [cert for cert in group.certificates if not cert.sent_at]
    job.total_items = len(certificates_to_send)
    job.processed_items = 0
    job.failed_items = 0
    db.session.commit()

    sent = 0
    failed = 0
    errors = []
    sent_certs = []

    for certificate in certificates_to_send:
        if not certificate.recipient_email:
            errors.append({"certificate_id": certificate.id, "msg": "No recipient email address"})
            failed += 1
            job.failed_items = failed
            db.session.commit()
            continue

        try:
            template = Template.query.get(certificate.template_id)
            pdf_buffer = generate_certificate_pdf(certificate, template, group.user)
            certificate.template = template

            msg = create_certificate_email(certificate, pdf_buffer)
            mail.send(msg)

            certificate.sent_at = datetime.utcnow()
            sent += 1
            sent_certs.append(certificate)

            job.processed_items = sent
            job.failed_items = failed
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            errors.append({"certificate_id": certificate.id, "msg": str(e)})
            failed += 1
            job.failed_items = failed
            db.session.commit()

    job.status = 'completed'
    job.completed_at = datetime.utcnow()
    job.result_summary = {
        "sent": sent,
        "failed": failed,
        "errors": errors[:10]
    }

    notif = Notification(
        user_id=user.id,
        title="Email dispatch complete",
        message=f"{sent} certificate emails sent successfully to group '{group.name}'." + (f" {failed} failed." if failed else ""),
        type="success",
        category="bulk_send",
        reference_id=job.id
    )
    db.session.add(notif)
    db.session.commit()

    try:
        from ..routes.certificates import _send_issuer_notification_email
        summary_html = f"""
        <h3>Bulk Email Dispatch Complete</h3>
        <p><strong>{sent}</strong> emails successfully delivered to group <strong>{group.name}</strong>.</p>
        <p><strong>{failed}</strong> errors encountered.</p>
        """
        _send_issuer_notification_email(user, "Bulk Emails Sent — ProofDeck", summary_html)
    except Exception as e:
        print(f"Summary email error: {e}")
