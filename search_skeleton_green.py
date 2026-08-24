import os

search_files = [
    r"c:\Users\BOLAJI\OneDrive\Desktop\CertificateBadgeIssuer\frontend\src\pages\GroupsPage.jsx",
    r"c:\Users\BOLAJI\OneDrive\Desktop\CertificateBadgeIssuer\frontend\src\pages\MyCertificatesPage.jsx",
    r"c:\Users\BOLAJI\OneDrive\Desktop\CertificateBadgeIssuer\frontend\src\pages\TemplatesPage.jsx",
    r"c:\Users\BOLAJI\OneDrive\Desktop\CertificateBadgeIssuer\frontend\src\pages\AnalyticsPage.jsx",
    r"c:\Users\BOLAJI\OneDrive\Desktop\CertificateBadgeIssuer\frontend\src\pages\SettingsPage.jsx"
]

for path in search_files:
    if os.path.exists(path):
        print(f"Searching {os.path.basename(path)}...")
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if any(x in line.lower() for x in ["green", "emerald", "teal", "glow"]):
                    # check if it's inside loading or skeleton
                    print(f"  Line {line_num}: {line.strip()}")
