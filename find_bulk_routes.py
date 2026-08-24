import os

search_dir = r"c:\Users\BOLAJI\OneDrive\Desktop\CertificateBadgeIssuer\frontend\src"

for root, dirs, files in os.walk(search_dir):
    for file in files:
        if file.endswith((".js", ".jsx")):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        if "bulk-create" in line.lower() or "bulkcreate" in line.lower():
                            print(f"{os.path.basename(path)}:{line_num} -> {line.strip()}")
            except Exception as e:
                pass
