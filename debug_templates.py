from pkg import create_app
from pkg.models import Template

app = create_app()

with app.app_context():
    templates = Template.query.all()
    print(f"{'ID':<5} {'Title':<30} {'Style':<20} {'Premium':<10}")
    print("-" * 70)
    for t in templates:
        print(f"{t.id:<5} {t.title[:28]:<30} {t.layout_style:<20} {t.is_premium:<10}")
