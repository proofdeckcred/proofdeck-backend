import os

search_dir = r"c:\Users\BOLAJI\OneDrive\Desktop\CertificateBadgeIssuer\frontend\src"

for root, dirs, files in os.walk(search_dir):
    for file in files:
        if file.endswith((".js", ".jsx", ".css")):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        if "pulse" in line.lower() and not "animate-pulse" in line:
                            # skip standard Tailwind class, look for custom styles
                            print(f"{file}:{line_num} -> {line.strip()}")
            except Exception as e:
                pass
