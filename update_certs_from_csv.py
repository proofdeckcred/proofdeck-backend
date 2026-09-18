import sys
import os
import pandas as pd
from pkg import create_app
from pkg.models import db, Certificate, Template, Group
from pkg.utils.helpers import normalize_headers, normalize_email

def update_group_custom_field(group_id_or_name, field_name, field_value):
    app = create_app()
    with app.app_context():
        if str(group_id_or_name).isdigit():
            group = Group.query.get(int(group_id_or_name))
        else:
            group = Group.query.filter_by(name=group_id_or_name).first()

        if not group:
            print(f"Group '{group_id_or_name}' not found.")
            return

        certs = Certificate.query.filter_by(group_id=group.id).all()
        print(f"Found {len(certs)} certificates in group '{group.name}' (ID: {group.id}).")
        
        for c in certs:
            extra = dict(c.extra_fields) if isinstance(c.extra_fields, dict) else {}
            extra[field_name] = str(field_value).strip()
            c.extra_fields = extra
            db.session.add(c)

        db.session.commit()
        print(f"Successfully updated {len(certs)} certificates with {field_name} = '{field_value}'.")

def update_from_csv(file_path, group_id=None):
    app = create_app()
    with app.app_context():
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            return

        if file_path.lower().endswith(('.xlsx', '.xls', '.ods')):
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path)

        df = normalize_headers(df)
        df = df.where(pd.notna(df), None)

        KNOWN_STANDARD_COLUMNS = {
            'recipient_name', 'recipient_email', 'course_title',
            'issuer_name', 'issue_date', 'signature'
        }

        updated_count = 0
        for _, row in df.iterrows():
            r_name = row.get('recipient_name')
            r_email = normalize_email(row.get('recipient_email'))

            if not r_name and not r_email:
                continue

            query = Certificate.query
            if group_id:
                query = query.filter_by(group_id=int(group_id))

            cert = None
            if r_email:
                cert = query.filter_by(recipient_email=r_email).order_by(Certificate.id.desc()).first()
            if not cert and r_name:
                cert = query.filter_by(recipient_name=str(r_name).strip()).order_by(Certificate.id.desc()).first()

            if cert:
                current_extra = dict(cert.extra_fields) if isinstance(cert.extra_fields, dict) else {}
                for col in df.columns:
                    if col not in KNOWN_STANDARD_COLUMNS:
                        val = row.get(col)
                        if val is not None and not (isinstance(val, float) and pd.isna(val)):
                            val_str = str(val).strip()
                            if val_str and val_str.lower() != 'nan':
                                current_extra[col] = val_str
                cert.extra_fields = current_extra
                db.session.add(cert)
                updated_count += 1

        db.session.commit()
        print(f"Successfully updated {updated_count} certificates with custom fields from {file_path}!")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage:')
        print('  1. From CSV: python update_certs_from_csv.py <path_to_csv> [group_id]')
        print('  2. Direct:   python update_certs_from_csv.py --set <group_id> <field_name> <field_value>')
        sys.exit(1)

    if sys.argv[1] == '--set' and len(sys.argv) >= 5:
        update_group_custom_field(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        file_arg = sys.argv[1]
        group_arg = sys.argv[2] if len(sys.argv) > 2 else None
        update_from_csv(file_arg, group_arg)
