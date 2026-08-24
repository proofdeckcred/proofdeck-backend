from pkg import create_app, db
from pkg.models import Template
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("Attempting to fix layout_style values...")
    
    # Map of Title -> Layout Style
    updates = {
        "Modern Landscape": "modern_landscape",
        "Elegant Serif": "elegant_serif",
        "Minimalist Bold": "minimalist_bold",
        "Corporate Blue": "corporate_blue",
        "Tech Dark": "tech_dark",
        "Creative Art": "creative_art",
        "Badge Certificate": "badge_cert",
        "Award Gold": "award_gold",
        "Diploma Classic": "diploma_classic",
        "Achievement Star": "achievement_star"
    }

    for title, style in updates.items():
        # Try updating using SQLAlchemy ORM
        t = Template.query.filter_by(title=title).first()
        if t:
            print(f"Updating {title} to {style}...")
            t.layout_style = style
            try:
                db.session.commit()
                print("  -> Success")
            except Exception as e:
                print(f"  -> Failed: {e}")
                db.session.rollback()
                
                # Fallback: Raw SQL might bypass some Python-level enum checks if that's the issue,
                # BUT if it's a DB constraint, it will still fail.
                # However, if the issue was silently ignored during seed (e.g. non-strict), maybe explicit update helps.
                try:
                    query = text("UPDATE templates SET layout_style = :style WHERE id = :id")
                    db.session.execute(query, {"style": style, "id": t.id})
                    db.session.commit()
                    print("  -> SQL Update Success")
                except Exception as ex:
                    print(f"  -> SQL Update Failed: {ex}")

    print("Fix attempt complete.")
