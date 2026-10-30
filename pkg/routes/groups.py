from flask import Blueprint, request, jsonify, current_app, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Group, Certificate, Template, User
from ..utils.helpers import get_active_context
from ..extensions import mail
from datetime import datetime, timedelta
from io import BytesIO
import zipfile
import re

# --- CHANGED IMPORTS ---
from ..services.pdf_service import generate_certificate_pdf
from ..services.email_service import create_certificate_email

groups_bp = Blueprint('groups', __name__)

@groups_bp.route('/', methods=['POST'])
@jwt_required()
def create_group():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    data = request.get_json() or {}
    name = data.get('name')
    if not name: return jsonify({"msg": "Group name is required"}), 400
    description = data.get('description', '').strip() if data.get('description') else None
    is_comp, tenant_id, _, _ = get_active_context(user)
    new_group = Group(
        user_id=user_id,
        tenant_id=tenant_id if is_comp else None,
        name=name,
        description=description
    )
    db.session.add(new_group)
    db.session.commit()
    return jsonify({
        "msg": "Group created successfully",
        "group": {
            "id": new_group.id,
            "name": new_group.name,
            "description": new_group.description or "",
            "certificate_count": 0,
            "created_at": new_group.created_at.isoformat()
        }
    }), 201

@groups_bp.route('/', methods=['GET'])
@jwt_required()
def get_groups():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        pagination = Group.query.filter_by(tenant_id=tenant_id).order_by(Group.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    else:
        pagination = Group.query.filter_by(user_id=user_id, tenant_id=None).order_by(Group.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        
    groups_data = [{
        "id": group.id,
        "name": group.name,
        "description": group.description or "",
        "certificate_count": len(group.certificates),
        "created_at": group.created_at.isoformat()
    } for group in pagination.items]
    return jsonify({"groups": groups_data, "total": pagination.total, "pages": pagination.pages, "current_page": pagination.page}), 200

@groups_bp.route('/<int:group_id>', methods=['GET'])
@jwt_required()
def get_group_details(group_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first_or_404()
    else:
        group = Group.query.filter_by(id=group_id, user_id=user_id, tenant_id=None).first_or_404()
        
    certificates_data = [{
        'id': c.id,
        'template_id': c.template_id,
        'recipient_name': c.recipient_name,
        'recipient_email': c.recipient_email,
        'course_title': c.course_title,
        'issuer_name': c.issuer_name,
        'signature': c.signature,
        'extra_fields': c.extra_fields or {},
        'verification_id': c.verification_id,
        'issue_date': c.issue_date.isoformat() if c.issue_date else None,
        'sent_at': c.sent_at.isoformat() if c.sent_at else None,
        'view_count': c.view_count or 0,
        'status': c.status
    } for c in group.certificates]
    default_template_id = group.certificates[0].template_id if group.certificates else None
    group_meta = {
        "id": group.id,
        "name": group.name,
        "description": group.description or "",
        "template_id": default_template_id,
        "created_at": group.created_at.isoformat(),
    }
    return jsonify({
        **group_meta,
        "group": group_meta,
        "certificates": certificates_data
    }), 200

@groups_bp.route('/<int:group_id>/bulk-update', methods=['PUT', 'POST'])
@jwt_required()
def bulk_update_group_certificates(group_id):
    """
    Updates all certificates in a group from the Bulk Edit spreadsheet view.
    Supports updating existing rows (0 credit cost), creating new rows (1 credit each),
    removing deleted rows, and optionally triggering bulk email (re)send.
    """
    import uuid
    from ..models import Tenant, QuotaTransaction, BackgroundJob, Notification
    from ..utils.helpers import parse_smart_date, normalize_email
    from ..tasks.bulk_tasks import process_bulk_email_task

    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    is_comp, tenant_id, quota_holder, _ = get_active_context(user)

    if is_comp:
        group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first_or_404()
    else:
        group = Group.query.filter_by(id=group_id, user_id=user_id, tenant_id=None).first_or_404()

    data = request.get_json() or {}
    rows = data.get('rows') or data.get('certificates') or []
    template_id = data.get('template_id')
    batch_defaults = data.get('batch_defaults') or {}
    resend_emails = bool(data.get('resend_emails', False))
    delete_missing = bool(data.get('delete_missing', True))

    if not rows or not isinstance(rows, list):
        return jsonify({"msg": "Please provide at least one valid recipient row."}), 400

    template = None
    if template_id:
        template = Template.query.get(template_id)
        if not template:
            return jsonify({"msg": "Selected template not found."}), 404
        if not template.is_public:
            if is_comp and template.tenant_id != tenant_id:
                return jsonify({"msg": "Template permission denied"}), 403
            elif not is_comp and (template.user_id != user_id or template.tenant_id is not None):
                return jsonify({"msg": "Template permission denied"}), 403

    existing_certs_by_id = {c.id: c for c in group.certificates}

    # Count how many brand-new rows are being created so we can check credit balance
    new_rows_count = 0
    for r in rows:
        row_id = r.get('id')
        try:
            row_id = int(row_id) if row_id is not None and str(row_id).strip() != '' else None
        except (ValueError, TypeError):
            row_id = None
        if not row_id or row_id not in existing_certs_by_id:
            if str(r.get('recipient_name') or '').strip():
                new_rows_count += 1

    if new_rows_count > 0 and quota_holder.cert_quota < new_rows_count:
        return jsonify({
            "msg": f"Adding {new_rows_count} new recipient(s) requires {new_rows_count} credit(s), but you have {quota_holder.cert_quota} available."
        }), 403

    core_keys = {'id', 'recipient_name', 'recipient_email', 'course_title', 'issuer_name', 'issue_date', 'signature', 'verification_id'}
    seen_existing_ids = set()
    updated_count = 0
    created_count = 0
    deleted_count = 0

    default_issuer = batch_defaults.get('issuer_name')
    if not default_issuer:
        if is_comp:
            active_tenant = Tenant.query.get(tenant_id)
            default_issuer = active_tenant.name if active_tenant else user.name
        else:
            default_issuer = user.name

    use_uploaded_sig = batch_defaults.get('use_uploaded_signature', True)

    for r in rows:
        recipient_name = str(r.get('recipient_name') or '').strip()
        if not recipient_name:
            continue

        row_id = r.get('id')
        try:
            row_id = int(row_id) if row_id is not None and str(row_id).strip() != '' else None
        except (ValueError, TypeError):
            row_id = None

        recipient_email = normalize_email(r.get('recipient_email'))
        course_title = str(r.get('course_title') or batch_defaults.get('course_title') or '').strip()
        issuer_name = str(r.get('issuer_name') or default_issuer or '').strip()
        issue_date = parse_smart_date(r.get('issue_date') or batch_defaults.get('issue_date'))
        sig_val = str(r.get('signature') or batch_defaults.get('signature') or '').strip()
        if not sig_val:
            sig_val = None if (user.signature_image_url and use_uploaded_sig) else user.name

        # Collect custom column values
        row_custom_extras = {}
        for k, v in r.items():
            if k not in core_keys and v is not None and str(v).strip() != '':
                row_custom_extras[k] = str(v).strip()

        if row_id and row_id in existing_certs_by_id:
            cert = existing_certs_by_id[row_id]
            seen_existing_ids.add(row_id)
            cert.recipient_name = recipient_name
            cert.recipient_email = recipient_email
            cert.course_title = course_title
            cert.issuer_name = issuer_name
            cert.issue_date = issue_date
            cert.signature = sig_val
            if template:
                cert.template_id = template.id

            # Preserve internal settings like cert_styles while updating custom fields
            prev_extra = dict(cert.extra_fields) if isinstance(cert.extra_fields, dict) else {}
            preserved = {}
            for internal_k in ('cert_styles', 'use_uploaded_signature', 'amount'):
                if internal_k in prev_extra:
                    preserved[internal_k] = prev_extra[internal_k]
            if 'use_uploaded_signature' in batch_defaults or user.signature_image_url:
                preserved['use_uploaded_signature'] = bool(use_uploaded_sig)
            cert.extra_fields = {**preserved, **row_custom_extras}
            updated_count += 1
        else:
            target_template_id = template.id if template else (group.certificates[0].template_id if group.certificates else None)
            if not target_template_id:
                return jsonify({"msg": "Please select a certificate template."}), 400
            extra_fields = {**row_custom_extras}
            if 'use_uploaded_signature' in batch_defaults or user.signature_image_url:
                extra_fields['use_uploaded_signature'] = bool(use_uploaded_sig)
            new_cert = Certificate(
                user_id=user_id,
                tenant_id=tenant_id if is_comp else None,
                template_id=target_template_id,
                group_id=group.id,
                recipient_name=recipient_name,
                recipient_email=recipient_email,
                course_title=course_title,
                issuer_name=issuer_name,
                issue_date=issue_date,
                signature=sig_val,
                extra_fields=extra_fields,
                verification_id=str(uuid.uuid4())
            )
            quota_holder.cert_quota -= 1
            db.session.add(new_cert)
            db.session.flush()
            try:
                txn = QuotaTransaction(
                    tenant_id=tenant_id if is_comp else None,
                    user_id=user_id,
                    certificate_id=new_cert.id,
                    amount=-1
                )
                db.session.add(txn)
            except Exception:
                pass
            created_count += 1

    if delete_missing:
        for existing_id, existing_cert in list(existing_certs_by_id.items()):
            if existing_id not in seen_existing_ids:
                db.session.delete(existing_cert)
                deleted_count += 1

    db.session.commit()

    job_id = None
    if resend_emails:
        db.session.refresh(group)
        certs_with_email = [c for c in group.certificates if c.recipient_email]
        if certs_with_email:
            job = BackgroundJob(
                user_id=user.id,
                tenant_id=tenant_id if is_comp else None,
                job_type='bulk_send',
                status='pending',
                total_items=len(certs_with_email)
            )
            db.session.add(job)
            db.session.commit()
            try:
                if os.environ.get('PROOFDECK_DESKTOP') == '1':
                    raise RuntimeError("Use local thread in desktop mode")
                task = process_bulk_email_task.delay(
                    job.id, group.id, user.id, is_comp, tenant_id, True
                )
                job.celery_task_id = task.id
            except Exception:
                import threading
                app_obj = current_app._get_current_object()
                def _run_local_email():
                    with app_obj.app_context():
                        process_bulk_email_task(job.id, group.id, user.id, is_comp, tenant_id, True)
                threading.Thread(target=_run_local_email, daemon=True).start()
                job.celery_task_id = f"desktop-email-{job.id}"
            start_notif = Notification(
                user_id=user.id,
                title="Batch updated & email dispatch started",
                message=f"Saved changes to '{group.name}' and sending {len(certs_with_email)} emails in the background...",
                type="info",
                category="bulk_send",
                reference_id=job.id
            )
            db.session.add(start_notif)
            db.session.commit()
            job_id = job.id

    msg_parts = [f"Updated {updated_count} certificate{'s' if updated_count != 1 else ''}"]
    if created_count > 0:
        msg_parts.append(f"added {created_count} new")
    if deleted_count > 0:
        msg_parts.append(f"removed {deleted_count}")
    if resend_emails and job_id:
        msg_parts.append("and queued emails for delivery")

    return jsonify({
        "msg": ", ".join(msg_parts) + "!",
        "updated": updated_count,
        "created": created_count,
        "deleted": deleted_count,
        "job_id": job_id
    }), 200

@groups_bp.route('/<int:group_id>', methods=['PUT', 'PATCH'])
@jwt_required()
def update_group(group_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first_or_404()
    else:
        group = Group.query.filter_by(id=group_id, user_id=user_id, tenant_id=None).first_or_404()

    data = request.get_json() or {}
    if 'name' in data and data['name'].strip():
        group.name = data['name'].strip()
    if 'description' in data:
        group.description = data['description'].strip() if data['description'] else None

    db.session.commit()
    return jsonify({
        "msg": "Group updated successfully",
        "group": {
            "id": group.id,
            "name": group.name,
            "description": group.description or "",
            "certificate_count": len(group.certificates),
            "created_at": group.created_at.isoformat()
        }
    }), 200

@groups_bp.route('/<int:group_id>/analytics', methods=['GET'])
@jwt_required()
def get_group_analytics(group_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)

    # Gated to paid accounts
    if user.role == 'free':
        return jsonify({
            "upgrade_required": True,
            "msg": "Group performance analytics is available on Pro plans."
        }), 200

    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first_or_404()
    else:
        group = Group.query.filter_by(id=group_id, user_id=user_id, tenant_id=None).first_or_404()

    total_certs = len(group.certificates)
    total_sent = sum(1 for c in group.certificates if c.sent_at)
    total_views = sum(c.view_count or 0 for c in group.certificates)
    total_verified = sum(1 for c in group.certificates if (c.view_count or 0) > 0)
    active_valid = sum(1 for c in group.certificates if c.status == 'valid')

    # Build 7-day trend
    labels = []
    views_trend = []
    issuance_trend = []
    now = datetime.utcnow()
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        day_str = day.strftime("%b %d")
        labels.append(day_str)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
        issuance_trend.append(sum(1 for c in group.certificates if c.created_at and day_start <= c.created_at <= day_end))
        views_trend.append(sum(c.view_count or 0 for c in group.certificates if c.last_viewed_at and day_start <= c.last_viewed_at <= day_end))

    return jsonify({
        "upgrade_required": False,
        "stats": {
            "total_certs": total_certs,
            "total_sent": total_sent,
            "total_views": total_views,
            "total_verified": total_verified,
            "active_valid": active_valid,
            "send_rate": round((total_sent / total_certs * 100) if total_certs > 0 else 0, 1),
            "view_rate": round((total_verified / total_certs * 100) if total_certs > 0 else 0, 1)
        },
        "chart": {
            "labels": labels,
            "issuance": issuance_trend,
            "views": views_trend
        }
    }), 200

@groups_bp.route('/<int:group_id>/add-certificates', methods=['POST'])
@jwt_required()
def add_certificates_to_group(group_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)

    # Gated to paid accounts
    if user.role == 'free':
        return jsonify({
            "upgrade_required": True,
            "msg": "Adding certificates to existing groups is a Pro feature. Please upgrade your plan."
        }), 403

    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first_or_404()
    else:
        group = Group.query.filter_by(id=group_id, user_id=user_id, tenant_id=None).first_or_404()

    data = request.get_json() or {}
    cert_ids = data.get('certificate_ids', [])
    if not cert_ids or not isinstance(cert_ids, list):
        return jsonify({"msg": "Please select at least one certificate to add."}), 400

    # Ensure certificates belong to user/tenant context
    if is_comp:
        certs = Certificate.query.filter(Certificate.id.in_(cert_ids), Certificate.tenant_id == tenant_id).all()
    else:
        certs = Certificate.query.filter(Certificate.id.in_(cert_ids), Certificate.user_id == user_id, Certificate.tenant_id.is_(None)).all()

    if not certs:
        return jsonify({"msg": "No matching certificates found."}), 404

    added_count = 0
    for cert in certs:
        if cert.group_id != group.id:
            cert.group_id = group.id
            added_count += 1

    db.session.commit()
    return jsonify({
        "msg": f"Successfully added {added_count} certificate{'s' if added_count != 1 else ''} to '{group.name}'.",
        "added_count": added_count,
        "total_certificates": len(group.certificates)
    }), 200

@groups_bp.route('/<int:group_id>/remove-certificate/<int:cert_id>', methods=['POST', 'DELETE'])
@jwt_required()
def remove_certificate_from_group(group_id, cert_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first_or_404()
        cert = Certificate.query.filter_by(id=cert_id, group_id=group.id, tenant_id=tenant_id).first_or_404()
    else:
        group = Group.query.filter_by(id=group_id, user_id=user_id, tenant_id=None).first_or_404()
        cert = Certificate.query.filter_by(id=cert_id, group_id=group.id, user_id=user_id, tenant_id=None).first_or_404()

    cert.group_id = None
    db.session.commit()
    return jsonify({"msg": "Certificate removed from group successfully."}), 200

@groups_bp.route('/<int:group_id>', methods=['DELETE'])
@jwt_required()
def delete_group(group_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first_or_404()
        Certificate.query.filter_by(group_id=group.id, tenant_id=tenant_id).delete()
    else:
        group = Group.query.filter_by(id=group_id, user_id=user_id, tenant_id=None).first_or_404()
        Certificate.query.filter_by(group_id=group.id, user_id=user_id, tenant_id=None).delete()
        
    db.session.delete(group)
    db.session.commit()
    return jsonify({"msg": "Group and all associated certificates deleted successfully"}), 200

@groups_bp.route('/<int:group_id>/send-bulk-email', methods=['POST'])
@jwt_required()
def send_bulk_email_for_group(group_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    is_comp, tenant_id, _, _ = get_active_context(user)
    if is_comp:
        group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first_or_404()
    else:
        group = Group.query.filter_by(id=group_id, user_id=user_id, tenant_id=None).first_or_404()

    payload = request.get_json(silent=True) or {}
    force_resend = payload.get('resend', False)
    if force_resend:
        certificates_to_send = list(group.certificates)
    else:
        certificates_to_send = [cert for cert in group.certificates if not cert.sent_at]
        if not certificates_to_send and group.certificates:
            # If all are already sent, allow re-sending the whole group
            certificates_to_send = list(group.certificates)

    if not certificates_to_send:
        return jsonify({"msg": "No certificates found in this group to send."}), 400

    from ..models import BackgroundJob, Notification
    from ..tasks.bulk_tasks import process_bulk_email_task

    job = BackgroundJob(
        user_id=user.id,
        tenant_id=tenant_id if is_comp else None,
        job_type='bulk_send',
        status='pending',
        total_items=len(certificates_to_send)
    )
    db.session.add(job)
    db.session.commit()

    task = process_bulk_email_task.delay(
        job.id, group.id, user.id, is_comp, tenant_id, bool(force_resend)
    )
    job.celery_task_id = task.id

    start_notif = Notification(
        user_id=user.id,
        title="Email dispatch started",
        message=f"Sending {len(certificates_to_send)} certificate emails for '{group.name}' in the background...",
        type="info",
        category="bulk_send",
        reference_id=job.id
    )
    db.session.add(start_notif)
    db.session.commit()

    return jsonify({
        "msg": f"Dispatching {len(certificates_to_send)} certificate emails in the background.",
        "job_id": job.id,
        "count": len(certificates_to_send)
    }), 202

@groups_bp.route('/<int:group_id>/download-bulk-pdf', methods=['GET'], strict_slashes=False)
@jwt_required()
def download_bulk_pdf_for_group(group_id):
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        is_comp, tenant_id, _, _ = get_active_context(user)
        if is_comp:
            group = Group.query.filter_by(id=group_id, tenant_id=tenant_id).first_or_404()
        else:
            group = Group.query.filter_by(id=group_id, user_id=user_id, tenant_id=None).first_or_404()

        if not group.certificates:
            return jsonify({"msg": "This group contains no certificates to download."}), 404

        group_name = group.name or "group"
        issuer_user = group.user or user

        # Pre-cache templates to avoid redundant DB lookups
        templates_cache = {}

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for certificate in group.certificates:
                try:
                    tid = certificate.template_id
                    if tid not in templates_cache:
                        templates_cache[tid] = Template.query.get(tid)
                    template = templates_cache[tid]

                    pdf_buffer = generate_certificate_pdf(certificate, template, issuer_user)

                    # Sanitize recipient name for the filename
                    raw_name = certificate.recipient_name or "certificate"
                    sane_name = re.sub(r'[\W_]+', '_', raw_name).strip('_')
                    vid = (certificate.verification_id or "")[:8]
                    filename = f"certificate_{sane_name}_{vid}.pdf" if vid else f"certificate_{sane_name}_{certificate.id}.pdf"
                    zip_file.writestr(filename, pdf_buffer.getvalue())
                except Exception as e:
                    current_app.logger.error(f"Skipping PDF for cert {certificate.id} due to error: {e}")
                    zip_file.writestr(f"ERROR_cert_{certificate.id}.txt", f"Could not generate PDF. Error: {e}")

        zip_data = zip_buffer.getvalue()
        sane_group_name = re.sub(r'[\W_]+', '_', group_name).strip('_') or 'certificates'
        zip_filename = f"{sane_group_name}_certificates.zip"

        return Response(
            zip_data,
            mimetype='application/zip',
            headers={'Content-Disposition': f'attachment; filename="{zip_filename}"'}
        )
    except Exception as e:
        current_app.logger.error(f"Failed to generate group ZIP download: {e}", exc_info=True)
        return jsonify({"msg": f"Failed to generate ZIP archive: {str(e)}"}), 500