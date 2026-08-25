# ?? ProofDeck Deployment & Operations Master Guide

This guide is the single source of truth for deploying, configuring, and maintaining the **ProofDeck** platform (`proofdeck-frontend` and `proofdeck-backend`).

---

## 1. ??? Architecture Overview

ProofDeck is structured as a **Poly-Repo**:

```
~/projects/proofdeck/
+-- frontend/                # React (Vite, TailwindCSS, Bootstrap, Lucide, Konva)
¦   +-- Git Remote: https://github.com/proofdeckcred/proofdeck-frontend.git
¦   +-- Production Host: Vercel (Auto-deploys from 'main' branch to https://www.proofdeck.app)
¦
+-- backend/                 # Python Flask (SQLAlchemy, Flask-JWT-Extended, Flask-Mail)
¦   +-- Git Remote: https://github.com/proofdeckcred/proofdeck-backend.git
¦   +-- Production Host: Hostinger Ubuntu 24.04 VPS (2.25.196.123) under Gunicorn + Systemd + Nginx
¦
+-- docs/                    # Architecture & operational guides
```

---

## 2. ?? Domains & DNS (Cloudflare)

* **Production Frontend**: `https://www.proofdeck.app` (Vercel)
* **Production API**: `https://api.proofdeck.app` (Points to VPS `2.25.196.123`)
* **Email Inbound Routing**:
  - `support@proofdeck.app` ? Cloudflare Email Routing forwards to `hello.certifyme@gmail.com`
* **Email Outbound (Resend SMTP)**:
  - `MAIL_DEFAULT_SENDER=ProofDeck <notifications@proofdeck.app>`
  - Domain verified in Resend via Cloudflare DKIM (`resend._domainkey`), SPF, and MX (`send.proofdeck.app`).

---

## 3. ?? Payment Gateways

ProofDeck supports dual checkout options for local and international users:

### A. Paystack (Nigeria & African Cards)
* **Mode**: Live
* **Callback URL**: `https://www.proofdeck.app/dashboard/settings`
* **Webhook URL**: `https://api.proofdeck.app/api/payments/webhook`
* **Currency**: NGN (Kobo: `amount * 100`)

### B. Bachs.io (Global Cards, International, Multi-Currency)
* **Mode**: Live / Sandbox
* **API Base URL**: `https://api.bachs.io` (or `https://sandbox-api.bachs.io` if test mode)
* **Webhook URL**: `https://api.proofdeck.app/api/payments/bachs/webhook`
* **Signature Verification**: `X-Bachs-Timestamp` and `X-Bachs-Signature` (HMAC SHA-256)

### Standard Pricing Tiers:
| Plan | NGN Price | USD Price | Credential Credits | Features |
| :--- | :--- | :--- | :--- | :--- |
| **Starter** | ?25,000 | $18.00 | 500 Credits | Unlimited templates, Email delivery, High-res PDF |
| **Growth** | ?60,000 | $42.00 | 2,000 Credits | All templates, Priority support |
| **Pro** | ?100,000 | $70.00 | 5,000 Credits | Developer API, Custom logo & branding, Custom domain |
| **Enterprise** | ?300,000 | $200.00 | 20,000 Credits | Dedicated manager, SLA, Unlimited API & Webhooks |

---

## 4. ??? VPS Production Deployment (Hostinger)

### Directory Structure on VPS:
* Application Path: `/var/www/proofdeck-backend/`
* Virtual Environment: `/var/www/proofdeck-backend/venv/`
* Uploads Directory: `/var/www/proofdeck-backend/uploads/`
* Environment Variables: `/var/www/proofdeck-backend/.env`
* Systemd Service: `/etc/systemd/system/proofdeck.service`
* Nginx Configuration: `/etc/nginx/sites-available/proofdeck-api`

---

### Step-by-Step Deploy / Update on VPS:

```bash
# 1. SSH into the VPS
ssh root@2.25.196.123

# 2. Navigate to backend repo & pull changes
cd /var/www/proofdeck-backend
git pull origin main

# 3. If requirements were updated:
/var/www/proofdeck-backend/venv/bin/pip install -r requirements.txt

# 4. If database schema changed:
/var/www/proofdeck-backend/venv/bin/python sync_db.py

# 5. Ensure upload directory permissions:
mkdir -p /var/www/proofdeck-backend/uploads
chown -R www-data:www-data /var/www/proofdeck-backend/uploads
chmod -R 755 /var/www/proofdeck-backend/uploads

# 6. Restart the backend service
systemctl restart proofdeck

# 7. Check service status
systemctl status proofdeck --no-pager
```

---

## 5. ?? Production Configurations

### A. Environment Variables (`/var/www/proofdeck-backend/.env`)
```ini
FLASK_APP=run.py
FLASK_DEBUG=0

DATABASE_URL=mysql+mysqlconnector://proofdeck_user:YOUR_DB_PASSWORD@127.0.0.1:3306/proofdeck_db
FRONTEND_URL=https://www.proofdeck.app
SECRET_KEY=YOUR_APP_SECRET_KEY
JWT_SECRET_KEY=YOUR_JWT_SECRET_KEY

# Paystack
PAYSTACK_SECRET_KEY=sk_live_YOUR_PAYSTACK_SECRET_KEY
PAYSTACK_PUBLIC_KEY=pk_live_YOUR_PAYSTACK_PUBLIC_KEY

# Bachs.io
BACHS_SECRET_KEY=sk_live_YOUR_BACHS_SECRET_KEY
BACHS_WEBHOOK_SECRET=whsec_YOUR_BACHS_WEBHOOK_SECRET

# Resend SMTP
MAIL_SERVER=smtp.resend.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=resend
MAIL_PASSWORD=re_YOUR_RESEND_API_KEY
MAIL_DEFAULT_SENDER=ProofDeck <notifications@proofdeck.app>
ADMIN_EMAIL=omobolajidurojaiye57@gmail.com
```

### B. Systemd Service (`/etc/systemd/system/proofdeck.service`)
```ini
[Unit]
Description=Gunicorn instance to serve ProofDeck Backend
After=network.target

[Service]
User=root
Group=www-data
WorkingDirectory=/var/www/proofdeck-backend
Environment="PATH=/var/www/proofdeck-backend/venv/bin"
ExecStart=/var/www/proofdeck-backend/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5005 run:app

[Install]
WantedBy=multi-user.target
```

### C. Nginx Reverse Proxy & Dynamic CORS (`/etc/nginx/sites-available/proofdeck-api`)
```nginx
map $http_origin $cors_origin {
    default "";
    "~^https?://(www\.)?proofdeck\.app$" "$http_origin";
    "~^http://localhost(:[0-9]+)?$" "$http_origin";
}

server {
    listen 80;
    server_name api.proofdeck.app;

    client_max_body_size 50M;

    # Static uploads with CORS headers
    location /uploads/ {
        alias /var/www/proofdeck-backend/uploads/;
        add_header Access-Control-Allow-Origin $cors_origin always;
        add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type, Authorization, Range" always;
        add_header Access-Control-Expose-Headers "Content-Length, Content-Range" always;

        if ($request_method = OPTIONS) {
            return 204;
        }
    }

    # Flask Gunicorn backend proxy
    location / {
        proxy_pass http://127.0.0.1:5005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 6. ??? Useful Maintenance & Debugging Commands

* **Live API Logs**:
  `journalctl -u proofdeck -f`
* **Restart Backend**:
  `systemctl restart proofdeck`
* **Test Email Delivery**:
  `/var/www/proofdeck-backend/venv/bin/python test_email.py`
* **Verify Database Schema**:
  `/var/www/proofdeck-backend/venv/bin/python sync_db.py`
