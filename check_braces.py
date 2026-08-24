
def check_braces(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    in_style = False
    open_braces = 0
    style_start = 0
    
    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()
        
        if '<style>' in stripped:
            in_style = True
            style_start = line_num
            print(f"Style block starts at {line_num}")
            continue
            
        if '</style>' in stripped:
            in_style = False
            print(f"Style block ends at {line_num}")
            if open_braces != 0:
                print(f"ERROR: Style block ended with {open_braces} open braces!")
            else:
                print("Braces are balanced.")
            continue
            
        if in_style:
            # simple count, might be fooled by comments but let's try
            # strip comments first? simplified check
            content = line.split('/*')[0] # ignore comments roughly
            # this doesn't handle multi-line comments well if braces are inside
            
            open_braces += content.count('{')
            open_braces -= content.count('}')
            
            if open_braces < 0:
                print(f"ERROR: Negative brace count at line {line_num}")

check_braces(r'c:\Users\BOLAJI\OneDrive\Desktop\CertificateBadgeIssuer\backend\templates\certificates\creative_art.html')
