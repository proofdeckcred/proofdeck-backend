import os
import jinja2

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates', 'certificates')

def check_templates():
    env = jinja2.Environment()
    
    if not os.path.exists(TEMPLATE_DIR):
        print(f"Directory not found: {TEMPLATE_DIR}")
        return

    files = [f for f in os.listdir(TEMPLATE_DIR) if f.endswith('.html')]
    print(f"Found {len(files)} templates in {TEMPLATE_DIR}")

    has_error = False
    for filename in files:
        path = os.path.join(TEMPLATE_DIR, filename)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            env.parse(content)
            print(f"[OK] {filename}: Syntax OK")
        except jinja2.TemplateSyntaxError as e:
            print(f"[FAIL] {filename}: SYNTAX ERROR at line {e.lineno}")
            print(f"   {e.message}")
            has_error = True
        except Exception as e:
            print(f"[FAIL] {filename}: ERROR {e}")
            has_error = True

    if not has_error:
        print("\nAll templates passed Jinja2 syntax check.")
    else:
        print("\nFound errors in templates.")

if __name__ == "__main__":
    check_templates()
