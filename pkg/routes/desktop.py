import os
import re
import json
import uuid
import sqlite3
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from sqlalchemy import create_engine, text
from ..models import db, User, Tenant, Membership, Template, Group, Certificate, EnterpriseLicense, LicenseActivation
from ..services.pdf_service import generate_certificate_pdf, generate_certificate_png

desktop_bp = Blueprint('desktop', __name__)


def _get_desktop_config_path():
    instance_dir = os.path.abspath(os.path.join(current_app.root_path, '..', 'instance'))
    os.makedirs(instance_dir, exist_ok=True)
    return os.path.join(instance_dir, 'desktop_enterprise_config.json')


def _get_demo_sis_db_path():
    instance_dir = os.path.abspath(os.path.join(current_app.root_path, '..', 'instance'))
    os.makedirs(instance_dir, exist_ok=True)
    db_path = os.path.join(instance_dir, 'university_sis_demo.db')
    _ensure_demo_sis_populated(db_path)
    return db_path


def _ensure_demo_sis_populated(db_path):
    """
    Creates a realistic local University Student Information System (SIS) SQLite database
    with 25 sample student records so 'Pull by Student ID' works out-of-the-box offline.
    """
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
        return
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS student_records (
                student_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT,
                programme TEXT,
                department TEXT,
                faculty TEXT,
                level TEXT,
                cgpa TEXT,
                degree_class TEXT,
                graduation_date TEXT
            )
        """)
        sample_students = [
            ("20220001", "Aisha Mohammed Bello", "aisha.bello@campus.edu", "B.Sc. Software Engineering", "Software Engineering", "Computing Studies", "400", "4.82", "First Class Honours", "2026-10-30"),
            ("20220002", "Chukwuemeka David Okafor", "c.okafor@campus.edu", "B.Sc. Computer Science", "Computer Science", "Computing Studies", "400", "4.65", "First Class Honours", "2026-10-30"),
            ("20220003", "Fatima Zahra Ibrahim", "fatima.ibrahim@campus.edu", "B.Eng. Civil Engineering", "Civil Engineering", "Engineering", "500", "4.41", "Second Class Upper", "2026-10-30"),
            ("20220004", "Oluwaseun Toluwalase Adeyemi", "seun.adeyemi@campus.edu", "B.Sc. Economics", "Economics", "Management Sciences", "400", "4.55", "First Class Honours", "2026-10-30"),
            ("20220005", "Musa Abdullahi Danjuma", "musa.danjuma@campus.edu", "LL.B. Law", "Private & Islamic Law", "Law", "500", "4.18", "Second Class Upper", "2026-10-30"),
            ("20220006", "Zainab Abubakar Sadiq", "zainab.sadiq@campus.edu", "MBBS Medicine & Surgery", "Clinical Sciences", "College of Health Sciences", "600", "4.74", "Distinction", "2026-10-30"),
            ("20220007", "Kelechi Somtochukwu Nwosu", "kelechi.nwosu@campus.edu", "B.Sc. Cyber Security", "Cyber Security", "Computing Studies", "400", "4.38", "Second Class Upper", "2026-10-30"),
            ("20220008", "Halima Suleiman Lawal", "halima.lawal@campus.edu", "B.Sc. International Relations", "Political Science", "Arts & Social Sciences", "400", "4.60", "First Class Honours", "2026-10-30"),
            ("20220009", "Babajide Ayomide Ogunleye", "b.ogunleye@campus.edu", "B.Eng. Electrical & Electronics Engineering", "Electrical Engineering", "Engineering", "500", "3.92", "Second Class Upper", "2026-10-30"),
            ("20220010", "Amina Yusuf Maitama", "amina.maitama@campus.edu", "B.Sc. Business Administration", "Business Administration", "Management Sciences", "400", "4.29", "Second Class Upper", "2026-10-30"),
            ("20220011", "Tosin Emmanuel Adebayo", "tosin.adebayo@campus.edu", "B.Sc. Information Technology", "Information Technology", "Computing Studies", "400", "4.51", "First Class Honours", "2026-10-30"),
            ("20220012", "Hauwa Kabir Usman", "hauwa.usman@campus.edu", "B.Sc. Mass Communication", "Mass Communication", "Arts & Social Sciences", "400", "4.12", "Second Class Upper", "2026-10-30"),
            ("20220013", "Ibrahim Khalil Garba", "ibrahim.garba@campus.edu", "B.Eng. Petroleum & Gas Engineering", "Petroleum Engineering", "Engineering", "500", "4.68", "First Class Honours", "2026-10-30"),
            ("20220014", "Chiamaka Blessing Eze", "chiamaka.eze@campus.edu", "B.Sc. Accounting", "Accounting", "Management Sciences", "400", "4.79", "First Class Honours", "2026-10-30"),
            ("20220015", "Sadiq Aliyu Mustapha", "sadiq.mustapha@campus.edu", "B.Sc. Architecture", "Architecture", "Environmental Sciences", "400", "4.33", "Second Class Upper", "2026-10-30"),
            ("20220016", "Khadija Bashir Tukur", "khadija.tukur@campus.edu", "B.Sc. Biotechnology", "Biological Sciences", "Natural & Applied Sciences", "400", "4.47", "Second Class Upper", "2026-10-30"),
            ("20220017", "Daniel Oritseweyinmi Amusan", "daniel.amusan@campus.edu", "B.Sc. Software Engineering", "Software Engineering", "Computing Studies", "400", "4.91", "First Class Honours", "2026-10-30"),
            ("20220018", "Maryam Shehu Yaradua", "maryam.shehu@campus.edu", "B.Sc. Public Administration", "Public Administration", "Management Sciences", "400", "4.05", "Second Class Upper", "2026-10-30"),
            ("20220019", "Farouk Umar Abdulkadir", "farouk.umar@campus.edu", "B.Eng. Mechatronics Engineering", "Mechatronics Engineering", "Engineering", "500", "4.58", "First Class Honours", "2026-10-30"),
            ("20220020", "Ngozi Valerie Obi", "ngozi.obi@campus.edu", "B.Sc. Human Anatomy", "Basic Medical Sciences", "College of Health Sciences", "400", "4.22", "Second Class Upper", "2026-10-30"),
        ]
        cur.executemany("""
            INSERT OR IGNORE INTO student_records
            (student_id, full_name, email, programme, department, faculty, level, cgpa, degree_class, graduation_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, sample_students)
        conn.commit()
        conn.close()
    except Exception as e:
        current_app.logger.warning(f"Could not seed demo SIS database: {e}")


def load_desktop_config():
    cfg_path = _get_desktop_config_path()
    demo_sis_path = _get_demo_sis_db_path()
    default_export_dir = os.path.join(os.path.expanduser("~"), "Documents", "ProofDeck_Exports")
    defaults = {
        "is_activated": False,
        "institution_name": "",
        "signatory_name": "",
        "license_key": "",
        "license_plan": "Enterprise Academic License",
        "license_status": "unactivated",
        "license_expires_at": "",
        "verification_mode": "university_portal",  # "university_portal", "no_qr", "proofdeck_cloud"
        "custom_verification_url": "",
        "default_export_folder": default_export_dir,
        "db_connector": {
            "engine": "sqlite_demo",  # "sqlite_demo", "mssql", "postgresql", "mysql", "sqlite_custom"
            "connection_uri": f"sqlite:///{demo_sis_path.replace(chr(92), '/')}",
            "table_or_view": "student_records",
            "id_column": "student_id",
            "field_map": {
                "student_id": "student_id",
                "recipient_name": "full_name",
                "recipient_email": "email",
                "course_title": "programme",
                "department": "department",
                "faculty": "faculty",
                "cgpa": "cgpa",
                "degree_class": "degree_class",
                "issue_date": "graduation_date"
            }
        }
    }
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                merged = {**defaults, **saved}
                if "db_connector" in saved and isinstance(saved["db_connector"], dict):
                    merged["db_connector"] = {**defaults["db_connector"], **saved["db_connector"]}
                return merged
        except Exception:
            pass
    return defaults


def save_desktop_config(new_cfg):
    cfg_path = _get_desktop_config_path()
    current = load_desktop_config()
    merged = {**current, **new_cfg}
    if "db_connector" in new_cfg and isinstance(new_cfg["db_connector"], dict):
        merged["db_connector"] = {**current.get("db_connector", {}), **new_cfg["db_connector"]}
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    return merged


def ensure_desktop_default_data():
    """
    Ensures the local SQLite database has:
    1. A pre-activated Enterprise Desktop user (no cloud signup needed)
    2. Built-in templates (including both Certificate & Portrait A4 Academic Letter templates)
    3. A default Group folder so the user can start issuing offline immediately.
    """
    cfg = load_desktop_config()
    inst_name = cfg.get("institution_name") or "Apex Institute of Technology — Academic Division"

    user = User.query.filter_by(email="academic@desktop.local").first()
    if not user:
        user = User.query.first()

    if not user:
        from werkzeug.security import generate_password_hash
        user = User(
            name=inst_name,
            email="academic@desktop.local",
            password_hash=generate_password_hash("desktop-local-vault"),
            role="enterprise",
            cert_quota=999999,
            is_verified=True
        )
        db.session.add(user)
        db.session.commit()
    else:
        # Ensure Enterprise privileges and unlimited local quota in Desktop Mode
        if os.environ.get("PROOFDECK_DESKTOP") == "1":
            user.role = "enterprise"
            if (user.cert_quota or 0) < 100000:
                user.cert_quota = 999999
            user.is_verified = True
            db.session.commit()

    # Ensure Enterprise Business/Organization Tenant & Owner Membership exist automatically
    tenant = Tenant.query.filter_by(owner_id=user.id).first()
    if not tenant:
        tenant = Tenant.query.first()
    if not tenant:
        tenant = Tenant(
            name=inst_name,
            owner_id=user.id,
            cert_quota=999999
        )
        db.session.add(tenant)
        db.session.commit()
    else:
        if (tenant.cert_quota or 0) < 100000:
            tenant.cert_quota = 999999
        db.session.commit()

    membership = Membership.query.filter_by(user_id=user.id, tenant_id=tenant.id).first()
    if not membership:
        membership = Membership(
            user_id=user.id,
            tenant_id=tenant.id,
            role="owner",
            status="active"
        )
        db.session.add(membership)
        db.session.commit()
    elif membership.role != "owner" or membership.status != "active":
        membership.role = "owner"
        membership.status = "active"
        db.session.commit()

    # Ensure at least one default Group folder exists and belongs to the Tenant
    existing_group = Group.query.filter_by(user_id=user.id).first()
    if not existing_group:
        default_group = Group(
            name="2026 Academic Batch",
            description="Default local desktop batch folder",
            user_id=user.id,
            tenant_id=tenant.id
        )
        db.session.add(default_group)
        db.session.commit()

    # Ensure any existing local groups/templates/certificates without tenant_id are linked to tenant
    Group.query.filter_by(user_id=user.id, tenant_id=None).update({"tenant_id": tenant.id})
    Template.query.filter_by(user_id=user.id, tenant_id=None).update({"tenant_id": tenant.id})
    Certificate.query.filter_by(user_id=user.id, tenant_id=None).update({"tenant_id": tenant.id})
    db.session.commit()

    # Map any old experimental or department-themed titles to the authentic standard ProofDeck template names
    rename_map = {
        "University Degree & Graduation Certificate": ("Classic", "classic"),
        "Academic Excellence & Senate Honours": ("Modern", "modern"),
        "Official Statement of Result / Attestation": ("Minimalist Bold", "minimalist_bold"),
        "Executive Diploma & Post-Graduate Award": ("Diploma Classic", "diploma_classic"),
        "Gold Senate Distinction Award": ("Award Gold", "award_gold"),
        "Modern Academic Credential": ("Modern Landscape", "modern_landscape"),
        "Corporate Academic Fellowship": ("Corporate Blue", "corporate_blue"),
        "Elegant Serif Degree Certification": ("Elegant Serif", "elegant_serif"),
        "Faculty of Technology Dark Credential": ("Tech Dark", "tech_dark"),
        "Department of Arts & Creative Design": ("Creative Art", "creative_art"),
        "Academic Badge & Verified Accreditation": ("Badge Certificate", "badge_cert"),
        "Star of Achievement & Senate Valedictorian": ("Achievement Star", "achievement_star"),
        "Senate Commendation Star": ("Achievement Star", "achievement_star"),
        "Official Student Tuition & Academic Fee Receipt": ("Receipt", "receipt"),
    }
    for old_title, (new_title, style) in rename_map.items():
        for t in Template.query.filter_by(title=old_title).all():
            t.title = new_title
            t.layout_style = style
    db.session.commit()

    # Ensure the full suite of standard built-in templates exists in the local desktop library (exact same as web)
    all_starter_presets = [
        {"title": "Classic", "style": "classic", "primary": "#1e3a8a", "secondary": "#b45309", "font": "Cinzel"},
        {"title": "Modern", "style": "modern", "primary": "#0f172a", "secondary": "#0284c7", "font": "Playfair Display"},
        {"title": "Minimalist Bold", "style": "minimalist_bold", "primary": "#065f46", "secondary": "#d97706", "font": "Merriweather"},
        {"title": "Diploma Classic", "style": "diploma_classic", "primary": "#1e293b", "secondary": "#b45309", "font": "Cinzel"},
        {"title": "Award Gold", "style": "award_gold", "primary": "#78350f", "secondary": "#f59e0b", "font": "Cinzel"},
        {"title": "Modern Landscape", "style": "modern_landscape", "primary": "#1e3a8a", "secondary": "#3b82f6", "font": "Inter"},
        {"title": "Corporate Blue", "style": "corporate_blue", "primary": "#0f172a", "secondary": "#2563eb", "font": "Playfair Display"},
        {"title": "Elegant Serif", "style": "elegant_serif", "primary": "#1c1917", "secondary": "#78350f", "font": "Playfair Display"},
        {"title": "Tech Dark", "style": "tech_dark", "primary": "#030712", "secondary": "#06b6d4", "font": "Inter"},
        {"title": "Creative Art", "style": "creative_art", "primary": "#4c1d95", "secondary": "#ec4899", "font": "Playfair Display"},
        {"title": "Badge Certificate", "style": "badge_cert", "primary": "#1e3a8a", "secondary": "#d97706", "font": "Cinzel"},
        {"title": "Achievement Star", "style": "achievement_star", "primary": "#0f172a", "secondary": "#eab308", "font": "Cinzel"},
        {"title": "Receipt", "style": "receipt", "primary": "#1e293b", "secondary": "#64748b", "font": "Inter"},
    ]

    existing_titles = {t.title for t in Template.query.all()}
    missing_templates = []
    for p in all_starter_presets:
        if p["title"] not in existing_titles:
            missing_templates.append(
                Template(
                    title=p["title"],
                    layout_style=p["style"],
                    primary_color=p["primary"],
                    secondary_color=p["secondary"],
                    body_font_color="#1e293b",
                    font_family=p["font"],
                    is_public=True,
                    user_id=user.id,
                    tenant_id=tenant.id
                )
            )

    if missing_templates:
        db.session.add_all(missing_templates)
        db.session.commit()

    # Ensure official academic document presets exist in desktop vault
    existing_docs = {t.title for t in Template.query.filter_by(layout_style='document').all()}
    doc_presets = [
        ("Official Statement of Result", '''<div style="text-align: center; margin-bottom: 24px;">
        <h2 style="margin: 0; font-size: 22px; font-weight: 800; letter-spacing: 0.5px; color: #111827;">OFFICE OF THE ACADEMIC REGISTRAR</h2>
        <h3 style="margin: 4px 0 0 0; font-size: 15px; font-weight: 700; color: #374151;">EXAMINATIONS AND ACADEMIC RECORDS DIVISION</h3>
        <p style="margin: 4px 0 0 0; font-size: 12px; color: #6B7280;">Administrative Complex, University Main Campus</p>
      </div>
      <hr style="border: 0; border-top: 2px solid #111827; margin: 16px 0 24px 0;" />
      
      <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: 600; margin-bottom: 24px;">
        <div><strong>Ref:</strong> <span class="pd-chip" data-var="{{ref_number}}">{{ref_number}}</span></div>
        <div><strong>Date:</strong> <span class="pd-chip" data-var="{{issue_date}}">{{issue_date}}</span></div>
      </div>

      <div style="text-align: center; margin-bottom: 28px;">
        <h1 style="margin: 0; font-size: 19px; font-weight: 900; text-decoration: underline; letter-spacing: 0.5px; color: #111827;">
          OFFICIAL STATEMENT OF RESULT
        </h1>
      </div>

      <p style="font-size: 14px; line-height: 1.9; color: #1F2937; text-align: justify; margin-bottom: 18px;">
        This is to certify that <strong><span class="pd-chip" data-var="{{recipient_name}}">{{recipient_name}}</span></strong>, 
        with Registration Number <strong><span class="pd-chip" data-var="{{student_id}}">{{student_id}}</span></strong>, 
        having completed an approved course of study and passed the prescribed examinations, has on the recommendation of the Board of Studies of the Faculty of 
        <strong><span class="pd-chip" data-var="{{faculty}}">{{faculty}}</span></strong>, Department of 
        <strong><span class="pd-chip" data-var="{{department}}">{{department}}</span></strong>, been admitted on 
        <strong><span class="pd-chip" data-var="{{approval_date}}">{{approval_date}}</span></strong> to the Degree of:
      </p>

      <div style="text-align: center; margin: 24px 0; padding: 16px; background-color: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 8px;">
        <div style="font-size: 18px; font-weight: 800; color: #111827; margin-bottom: 6px;">
          <span class="pd-chip" data-var="{{course_title}}">{{course_title}}</span>
        </div>
        <div style="font-size: 15px; font-weight: 700; color: #374151;">
          With <span class="pd-chip" data-var="{{grade_or_honours}}">{{grade_or_honours}}</span> 
          (Cumulative Grade Point Average: <strong><span class="pd-chip" data-var="{{cgpa}}">{{cgpa}}</span></strong>)
        </div>
      </div>

      <p style="font-size: 13px; line-height: 1.8; color: #374151; text-align: justify; margin-bottom: 36px;">
        The official certificate will be issued to him/her in due course upon surrender of this Statement of Result and clearance from all Directorates.
      </p>

      <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 50px;">
        <div style="text-align: left; max-width: 250px;">
          <div style="font-family: 'Times New Roman', serif; font-size: 20px; font-style: italic; font-weight: bold; margin-bottom: 4px; color: #1E3A8A;">
            <span class="pd-chip" data-var="{{signatory_name}}">{{signatory_name}}</span>
          </div>
          <div style="border-top: 1.5px solid #374151; padding-top: 6px; font-size: 13px; font-weight: 700; color: #111827;">
            <span class="pd-chip" data-var="{{signatory_title}}">{{signatory_title}}</span>
          </div>
          <div style="font-size: 11px; color: #6B7280;">For: Academic Registrar & Secretary</div>
        </div>

        <div style="text-align: center; padding: 10px 18px; border: 2px dashed #9CA3AF; border-radius: 8px; font-size: 11px; color: #6B7280;">
          <div style="font-weight: 700; color: #374151; margin-bottom: 2px;">OFFICIAL SEAL</div>
          <div>Valid Only With Stamp</div>
        </div>
      </div>'''),
        ("Letter of English Proficiency", '''<div style="text-align: center; margin-bottom: 24px;">
        <h2 style="margin: 0; font-size: 20px; font-weight: 800; color: #111827;">DIRECTORATE OF ACADEMIC AFFAIRS</h2>
        <h3 style="margin: 4px 0 0 0; font-size: 14px; font-weight: 700; color: #374151;">OFFICE OF THE REGISTRAR</h3>
        <p style="margin: 4px 0 0 0; font-size: 12px; color: #6B7280;">Verification & International Credential Services</p>
      </div>
      <hr style="border: 0; border-top: 2px solid #111827; margin: 16px 0 24px 0;" />

      <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: 600; margin-bottom: 24px;">
        <div><strong>Ref:</strong> <span class="pd-chip" data-var="{{ref_number}}">{{ref_number}}</span></div>
        <div><strong>Date:</strong> <span class="pd-chip" data-var="{{issue_date}}">{{issue_date}}</span></div>
      </div>

      <div style="margin-bottom: 20px;">
        <p style="font-size: 13px; font-weight: 700; margin: 0; color: #111827;">TO WHOM IT MAY CONCERN</p>
      </div>

      <div style="text-align: center; margin-bottom: 24px;">
        <h2 style="margin: 0; font-size: 17px; font-weight: 800; text-decoration: underline; color: #111827;">
          ATTESTATION OF ENGLISH AS MEDIUM OF INSTRUCTION
        </h2>
      </div>

      <p style="font-size: 14px; line-height: 1.85; color: #1F2937; text-align: justify; margin-bottom: 18px;">
        This is to certify that <strong><span class="pd-chip" data-var="{{recipient_name}}">{{recipient_name}}</span></strong>, 
        bearing Registration Number <strong><span class="pd-chip" data-var="{{student_id}}">{{student_id}}</span></strong>, was a bona fide student in the 
        Department of <strong><span class="pd-chip" data-var="{{department}}">{{department}}</span></strong>, Faculty of 
        <strong><span class="pd-chip" data-var="{{faculty}}">{{faculty}}</span></strong>.
      </p>

      <p style="font-size: 14px; line-height: 1.85; color: #1F2937; text-align: justify; margin-bottom: 18px;">
        We confirm that English Language is the sole medium of instruction, examination, research, and general communication for all undergraduate and postgraduate academic programs.
      </p>

      <div style="margin-top: 48px;">
        <div style="font-family: 'Times New Roman', serif; font-size: 19px; font-style: italic; font-weight: bold; margin-bottom: 4px; color: #1E3A8A;">
          <span class="pd-chip" data-var="{{signatory_name}}">{{signatory_name}}</span>
        </div>
        <div style="border-top: 1.5px solid #374151; padding-top: 4px; font-size: 13px; font-weight: 700; color: #111827; display: inline-block;">
          <span class="pd-chip" data-var="{{signatory_title}}">{{signatory_title}}</span>
        </div>
        <div style="font-size: 11px; color: #6B7280; margin-top: 2px;">Director, Academic Planning & Records</div>
      </div>'''),
        ("Letter of Attestation", '''<div style="text-align: center; margin-bottom: 24px;">
        <h2 style="margin: 0; font-size: 20px; font-weight: 800; color: #111827;">OFFICE OF THE REGISTRAR</h2>
        <p style="margin: 4px 0 0 0; font-size: 12px; color: #6B7280;">Student Academic Verification Unit</p>
      </div>
      <hr style="border: 0; border-top: 2px solid #111827; margin: 16px 0 24px 0;" />

      <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: 600; margin-bottom: 24px;">
        <div><strong>Ref:</strong> <span class="pd-chip" data-var="{{ref_number}}">{{ref_number}}</span></div>
        <div><strong>Date:</strong> <span class="pd-chip" data-var="{{issue_date}}">{{issue_date}}</span></div>
      </div>

      <div style="text-align: center; margin-bottom: 24px;">
        <h2 style="margin: 0; font-size: 17px; font-weight: 800; text-decoration: underline; color: #111827;">
          LETTER OF ATTESTATION
        </h2>
      </div>

      <p style="font-size: 14px; line-height: 1.85; color: #1F2937; text-align: justify; margin-bottom: 16px;">
        This is to attest that <strong><span class="pd-chip" data-var="{{recipient_name}}">{{recipient_name}}</span></strong> 
        (Registration Number: <strong><span class="pd-chip" data-var="{{student_id}}">{{student_id}}</span></strong>) has satisfied all academic requirements for the award of 
        <strong><span class="pd-chip" data-var="{{course_title}}">{{course_title}}</span></strong>.
      </p>

      <p style="font-size: 14px; line-height: 1.85; color: #1F2937; text-align: justify; margin-bottom: 16px;">
        This letter is issued upon request pending the issuance of the substantive diploma certificate.
      </p>

      <div style="margin-top: 48px;">
        <div style="font-family: 'Times New Roman', serif; font-size: 19px; font-style: italic; font-weight: bold; margin-bottom: 4px; color: #1E3A8A;">
          <span class="pd-chip" data-var="{{signatory_name}}">{{signatory_name}}</span>
        </div>
        <div style="border-top: 1.5px solid #374151; padding-top: 4px; font-size: 13px; font-weight: 700; color: #111827; display: inline-block;">
          <span class="pd-chip" data-var="{{signatory_title}}">{{signatory_title}}</span>
        </div>
      </div>''')
    ]

    missing_docs = []
    for doc_title, doc_html in doc_presets:
        if doc_title not in existing_docs:
            missing_docs.append(
                Template(
                    title=doc_title,
                    layout_style="document",
                    layout_data={
                        "document_html": doc_html,
                        "qr_code_enabled": True,
                        "qr_position": "bottom-right",
                        "zoom": "100%"
                    },
                    primary_color="#1e3a8a",
                    secondary_color="#0284c7",
                    body_font_color="#1f2937",
                    font_family="Times New Roman",
                    is_public=False,
                    user_id=user.id,
                    tenant_id=tenant.id
                )
            )
    if missing_docs:
        db.session.add_all(missing_docs)
        db.session.commit()


    return user, tenant, cfg


@desktop_bp.route('/bootstrap', methods=['GET', 'POST'])
def desktop_bootstrap():
    """
    Called by the Desktop App on startup to auto-authenticate into the local
    Enterprise Vault and return desktop configuration & license status.
    """
    user, tenant, cfg = ensure_desktop_default_data()
    access_token = create_access_token(identity=str(user.id))
    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    is_sqlite = db_uri.startswith("sqlite")

    return jsonify({
        "is_desktop": True,
        "token": access_token,
        "active_workspace_id": str(tenant.id),
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": "enterprise",
            "effective_role": "enterprise",
            "is_enterprise": True,
            "cert_quota": tenant.cert_quota,
            "personal_cert_quota": user.cert_quota,
            "signature_image_url": user.signature_image_url,
            "api_key": user.api_key,
            "company": {
                "id": tenant.id,
                "name": tenant.name,
                "owner_id": user.id,
                "active_role": "owner"
            },
            "workspaces": [
                {
                    "id": tenant.id,
                    "name": tenant.name,
                    "role": "owner",
                    "owner_id": user.id,
                    "cert_quota": tenant.cert_quota
                }
            ]
        },
        "config": cfg,
        "storage": {
            "engine": "Local SQLite Vault (Offline)" if is_sqlite else "University SQL Database",
            "database_uri_masked": re.sub(r':([^:@]+)@', ':***@', db_uri),
            "uploads_folder": current_app.config.get("UPLOAD_FOLDER")
        }
    }), 200


@desktop_bp.route('/verify-key', methods=['POST'])
def desktop_verify_key():
    """
    Called live as the user types or pastes a license key in the activation modal.
    Queries the cloud / local registry and returns the registered institution name,
    contact person, and expiry so the form autofills automatically.
    """
    data = request.get_json() or {}
    license_key = (data.get("license_key") or "").strip().upper()

    if not license_key:
        return jsonify({"valid": False, "msg": "License key required."}), 400

    # 1. Check local/cloud license registry
    lic = EnterpriseLicense.query.filter_by(license_key=license_key).first()
    if lic:
        if lic.status != 'active':
            return jsonify({
                "valid": False,
                "msg": f"This license key is currently {lic.status}."
            }), 403
        if lic.expires_at and datetime.utcnow() > lic.expires_at:
            return jsonify({
                "valid": False,
                "msg": "This license key has expired."
            }), 403

        return jsonify({
            "valid": True,
            "institution_name": lic.institution_name,
            "signatory_name": lic.contact_person or "Prof. Academic Registrar",
            "plan_tier": lic.plan_tier,
            "expires_at": lic.expires_at.strftime("%Y-%m-%d") if lic.expires_at else "",
            "max_workstations": lic.max_workstations
        }), 200

    # 2. Try online cloud API validation if internet is reachable
    try:
        import requests
        cloud_url = "https://api.proofdeck.app/api/licenses/activate"
        resp = requests.post(
            cloud_url,
            json={"license_key": license_key, "app_version": "1.0.0"},
            timeout=3.5
        )
        if resp.status_code == 200:
            c_data = resp.json().get("license", {})
            return jsonify({
                "valid": True,
                "institution_name": c_data.get("institution_name", ""),
                "signatory_name": c_data.get("contact_person") or c_data.get("signatory_name") or "Prof. Academic Registrar",
                "plan_tier": c_data.get("plan_tier", "Enterprise Academic License"),
                "expires_at": c_data.get("expires_at", "")
            }), 200
        elif resp.status_code in (403, 404):
            err_msg = resp.json().get("msg", "Invalid license key.")
            return jsonify({"valid": False, "msg": err_msg}), resp.status_code
    except Exception:
        pass

    # 3. Fallback for offline parsed keys (PD-ENT-<NAME>-...)
    parts = license_key.split('-')
    if len(parts) >= 3 and parts[0] == "PD" and parts[1] == "ENT":
        inferred = f"{parts[2]} Academic Division"
        return jsonify({
            "valid": True,
            "institution_name": inferred,
            "signatory_name": "Prof. Academic Registrar",
            "plan_tier": "Enterprise Academic License",
            "expires_at": (datetime.utcnow() + timedelta(days=365)).strftime("%Y-%m-%d")
        }), 200

    return jsonify({"valid": False, "msg": "License key not recognized."}), 404


@desktop_bp.route('/activate-license', methods=['POST'])
def desktop_activate_license():
    """
    Activates the Desktop workstation either directly against the local DB
    (if offline/air-gapped) or via cloud handshake when internet is available.
    """
    data = request.get_json() or {}
    license_key = (data.get("license_key") or "").strip().upper()
    institution_name = (data.get("institution_name") or "").strip()
    signatory_name = (data.get("signatory_name") or "").strip()

    if not license_key:
        return jsonify({"msg": "License key is required."}), 400

    # 1. Check local/cloud license registry
    lic = EnterpriseLicense.query.filter_by(license_key=license_key).first()
    
    expires_at = (datetime.utcnow() + timedelta(days=365)).strftime("%Y-%m-%d")
    plan_tier = "Enterprise Academic Annual License"
    
    if lic:
        if lic.status != 'active':
            return jsonify({"msg": f"This license is currently {lic.status}. Contact ProofDeck."}), 403
        if lic.expires_at and datetime.utcnow() > lic.expires_at:
            return jsonify({"msg": "This license has expired. Please renew."}), 403
        institution_name = lic.institution_name or institution_name
        expires_at = lic.expires_at.strftime("%Y-%m-%d") if lic.expires_at else expires_at
        plan_tier = lic.plan_tier or plan_tier
    else:
        # If offline air-gapped activation or custom key format
        if not institution_name:
            # Try to infer institution from key format: PD-ENT-<INST>-...
            parts = license_key.split('-')
            if len(parts) >= 3:
                institution_name = f"{parts[2]} Academic Division"
            else:
                institution_name = "Enterprise Institution"

    # Save to local desktop configuration
    updated_cfg = save_desktop_config({
        "is_activated": True,
        "license_key": license_key,
        "institution_name": institution_name,
        "signatory_name": signatory_name or "Authorized Registrar",
        "license_status": "active",
        "license_plan": plan_tier,
        "license_expires_at": expires_at,
        "activated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    })

    # Update local User & Tenant records to match the activated school
    user, tenant, _ = ensure_desktop_default_data()
    user.name = institution_name
    if tenant:
        tenant.name = institution_name
    db.session.commit()

    return jsonify({
        "success": True,
        "msg": f"ProofDeck Enterprise activated successfully for {institution_name}!",
        "config": updated_cfg
    }), 200


@desktop_bp.route('/settings', methods=['GET', 'PUT', 'POST'])
@jwt_required(optional=True)
def desktop_settings():
    if request.method == 'GET':
        _, _, cfg = ensure_desktop_default_data()
        return jsonify({"config": cfg}), 200

    data = request.get_json() or {}
    updated = save_desktop_config(data)

    # Also sync institution_name to local user & company tenant profile if updated
    if data.get("institution_name"):
        user, tenant, _ = ensure_desktop_default_data()
        new_inst_name = data["institution_name"].strip()
        user.name = new_inst_name
        if tenant:
            tenant.name = new_inst_name
        db.session.commit()

    return jsonify({
        "msg": "Enterprise Desktop settings saved locally.",
        "config": updated
    }), 200


@desktop_bp.route('/pick-folder', methods=['POST'])
@jwt_required(optional=True)
def pick_local_folder():
    """
    Opens the native Windows Folder Picker dialog so the user can choose where
    to save generated PDFs/PNGs on their computer.
    """
    cfg = load_desktop_config()
    initial_dir = cfg.get("default_export_folder") or os.path.expanduser("~")
    if not os.path.exists(initial_dir):
        initial_dir = os.path.expanduser("~")

    selected_folder = None
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        selected_folder = filedialog.askdirectory(
            initialdir=initial_dir,
            title="Select Folder to Save Generated Documents"
        )
        root.destroy()
    except Exception as e:
        current_app.logger.warning(f"Native folder picker fallback: {e}")

    if not selected_folder:
        return jsonify({"cancelled": True, "folder": cfg.get("default_export_folder")}), 200

    selected_folder = os.path.normpath(selected_folder)
    save_desktop_config({"default_export_folder": selected_folder})
    return jsonify({"cancelled": False, "folder": selected_folder}), 200


@desktop_bp.route('/open-folder', methods=['POST'])
@jwt_required(optional=True)
def open_local_folder():
    """
    Opens the specified local folder in Windows File Explorer.
    """
    data = request.get_json() or {}
    cfg = load_desktop_config()
    folder = data.get("folder") or cfg.get("default_export_folder")
    if not folder or not os.path.exists(folder):
        return jsonify({"msg": "Folder does not exist yet."}), 404

    try:
        if os.name == 'nt':
            os.startfile(folder)
        return jsonify({"msg": "Opened folder in File Explorer.", "folder": folder}), 200
    except Exception as e:
        return jsonify({"msg": f"Could not open folder: {e}"}), 500


@desktop_bp.route('/export-group-to-folder/<int:group_id>', methods=['POST'])
@jwt_required()
def export_group_to_local_folder(group_id):
    """
    Renders all certificates/documents in a Group directly to a local folder on the user's PC
    (100% offline, naming files by student_id + recipient_name when available).
    """
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    group = Group.query.get_or_404(group_id)

    data = request.get_json() or {}
    cfg = load_desktop_config()
    base_folder = data.get("folder") or cfg.get("default_export_folder") or os.path.join(os.path.expanduser("~"), "Documents", "ProofDeck_Exports")
    file_format = (data.get("format") or "pdf").lower()  # "pdf", "png", or "both"
    open_when_done = bool(data.get("open_folder", True))

    safe_group_name = re.sub(r'[<>:"/\\|?*]+', '_', group.name).strip() or f"Batch_{group.id}"
    target_dir = os.path.join(base_folder, safe_group_name)
    os.makedirs(target_dir, exist_ok=True)

    exported_files = []
    errors = []

    for cert in group.certificates:
        try:
            template = Template.query.get(cert.template_id)
            if not template:
                continue

            extra = cert.extra_fields or {}
            student_id = extra.get("student_id") or extra.get("matric_number") or extra.get("matric_no") or ""
            clean_student_id = re.sub(r'[^a-zA-Z0-9_-]+', '_', str(student_id)).strip('_')
            clean_name = re.sub(r'[^a-zA-Z0-9_-]+', '_', cert.recipient_name or "Recipient").strip('_')

            if clean_student_id:
                base_filename = f"{clean_student_id}_{clean_name}"
            else:
                base_filename = f"{clean_name}_{cert.verification_id[:6]}"

            if file_format in ("pdf", "both"):
                pdf_buf = generate_certificate_pdf(cert, template, user)
                pdf_path = os.path.join(target_dir, f"{base_filename}.pdf")
                with open(pdf_path, "wb") as f:
                    f.write(pdf_buf.getvalue())
                exported_files.append(pdf_path)

            if file_format in ("png", "both"):
                png_buf = generate_certificate_png(cert, template, user)
                png_path = os.path.join(target_dir, f"{base_filename}.png")
                with open(png_path, "wb") as f:
                    f.write(png_buf.getvalue())
                exported_files.append(png_path)
        except Exception as e:
            errors.append(f"{cert.recipient_name}: {str(e)}")

    if open_when_done and os.name == 'nt' and exported_files:
        try:
            os.startfile(target_dir)
        except Exception:
            pass

    return jsonify({
        "msg": f"Exported {len(exported_files)} files to {target_dir}",
        "folder": target_dir,
        "exported_count": len(exported_files),
        "errors": errors
    }), 200


@desktop_bp.route('/db-connector/pull', methods=['POST'])
@jwt_required(optional=True)
def pull_from_university_database():
    """
    Queries the connected University SQL Database (or the built-in Demo University SIS DB)
    by a list of Student IDs, faculty, department, or search filter, and returns standardized
    spreadsheet rows ready for bulk issuance.
    """
    data = request.get_json() or {}
    cfg = load_desktop_config()
    db_cfg = cfg.get("db_connector", {})

    conn_uri = data.get("connection_uri") or db_cfg.get("connection_uri")
    table_name = re.sub(r'[^a-zA-Z0-9_]', '', data.get("table_or_view") or db_cfg.get("table_or_view") or "student_records")
    id_col = re.sub(r'[^a-zA-Z0-9_]', '', data.get("id_column") or db_cfg.get("id_column") or "student_id")
    field_map = data.get("field_map") or db_cfg.get("field_map") or {}

    student_ids = data.get("student_ids") or []
    if isinstance(student_ids, str):
        student_ids = [s.strip() for s in re.split(r'[\s,;]+', student_ids) if s.strip()]

    department_filter = (data.get("department") or "").strip()
    faculty_filter = (data.get("faculty") or "").strip()
    limit = min(int(data.get("limit") or 500), 5000)

    try:
        engine = create_engine(conn_uri)
        with engine.connect() as conn:
            where_clauses = []
            params = {}

            if student_ids:
                placeholders = []
                for idx, sid in enumerate(student_ids):
                    key = f"sid_{idx}"
                    placeholders.append(f":{key}")
                    params[key] = str(sid).strip()
                where_clauses.append(f"{id_col} IN ({', '.join(placeholders)})")

            if department_filter:
                where_clauses.append("LOWER(department) LIKE :dept")
                params["dept"] = f"%{department_filter.lower()}%"

            if faculty_filter:
                where_clauses.append("LOWER(faculty) LIKE :fac")
                params["fac"] = f"%{faculty_filter.lower()}%"

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            query_sql = f"SELECT * FROM {table_name} {where_sql} LIMIT {limit}"

            result = conn.execute(text(query_sql), params)
            columns = list(result.keys())
            raw_rows = [dict(zip(columns, row)) for row in result.fetchall()]

        # Map DB columns to ProofDeck spreadsheet columns + custom columns
        mapped_rows = []
        custom_columns_detected = set()
        core_keys = {"recipient_name", "recipient_email", "course_title", "issuer_name", "issue_date", "signature"}

        for r in raw_rows:
            row_obj = {
                "recipient_name": "",
                "recipient_email": "",
                "course_title": "",
                "issuer_name": cfg.get("institution_name") or "",
                "issue_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "signature": cfg.get("signatory_name") or ""
            }
            # Apply configured field_map first
            for target_key, source_col in field_map.items():
                if source_col in r and r[source_col] is not None:
                    row_obj[target_key] = str(r[source_col]).strip()
                    if target_key not in core_keys:
                        custom_columns_detected.add(target_key)

            # Also include any unmapped columns (like student_id, cgpa, degree_class, department)
            for col_name, val in r.items():
                if val is None:
                    continue
                clean_key = col_name.lower().strip()
                if clean_key not in row_obj or not row_obj[clean_key]:
                    row_obj[clean_key] = str(val).strip()
                if clean_key not in core_keys and clean_key not in ("full_name", "email", "programme", "graduation_date"):
                    custom_columns_detected.add(clean_key)

            if row_obj.get("recipient_name"):
                mapped_rows.append(row_obj)

        return jsonify({
            "msg": f"Pulled {len(mapped_rows)} student records from database.",
            "rows": mapped_rows,
            "custom_columns": [
                {"key": k, "label": k.replace("_", " ").upper() if k in ("cgpa", "id") else k.replace("_", " ").title()}
                for k in sorted(custom_columns_detected)
            ],
            "total_pulled": len(mapped_rows)
        }), 200

    except Exception as e:
        return jsonify({
            "msg": f"Database query failed: {str(e)}",
            "error": str(e)
        }), 400
