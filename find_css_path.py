import os

search_dir = r"c:\Users\BOLAJI\OneDrive\Desktop\CertificateBadgeIssuer\frontend\src"

for root, dirs, files in os.walk(search_dir):
    if "SupportPage.css" in files:
        print(os.path.join(root, "SupportPage.css"))
