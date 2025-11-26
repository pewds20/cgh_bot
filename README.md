# 🏥 CGH Sustainability Redistribution Bot  
Telegram Bot for Staff-to-Staff Redistribution of Surplus Consumables  
Built with python-telegram-bot, Firebase Realtime Database, and Render

---

## Overview
The CGH Sustainability Redistribution Bot automates the external sharing of excess medical consumables.  
It allows staff to post items via Telegram, automatically publishes posts to a redistribution channel, and records all data in Firebase for audit and reporting.

This repository contains the full bot source code, deployment configuration, and setup instructions.

---

## Features
- Post new items directly into the Telegram Channel via Telebot 
- Photo support for listings  
- Reply buttons + inline claiming system  
- Automatic updates to channel posts (remaining qty, status, etc.)  
- Firebase-backed database for reliability  
- Auto-expiry of old listings (7-day rule)  
- Custom error handler and logging  
- Keep-alive HTTP endpoint for uptime monitoring  
- Hosted on Render (free tier)

---

## 🧱 System Architecture

```
       Nurse / CGH Staff
               │
               ▼
        Telegram Bot UI
               │
               ▼
    Bot Code (Python on Render)
               │
               ▼
     Firebase Realtime Database
               │
               ▼
        JSON export → CSV (for reports)

     GitHub Repo → Render → Deployment
```

---

## Tech Stack
- **Python 3.10**
- **python-telegram-bot v20+**
- **Firebase Realtime Database (REST + Admin SDK)**
- **Render Web Service**
- **Waitress (Production WSGI Server for keep-alive endpoint)**
- **Flask (keep-alive endpoint only)**

---

## Setup Instructions

### 1. Clone the repository
```bash
git clone https://github.com/<your-org>/<your-repo>.git
cd <your-repo>
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment Variables  
These must be set in Render **Environment → Secrets**:

| Variable | Description |
|---------|-------------|
| `BOT_TOKEN` | Telegram bot API token |
| `CHANNEL_ID` | Telegram channel username or numeric ID |
| `FIREBASE_CREDENTIALS` | Full JSON service account credentials (stringified) |

Example format for `FIREBASE_CREDENTIALS`:
```json
{"type": "service_account", "project_id": "...", ...}
```

---

## Deployment (Render)

The bot is deployed as a **Render Web Service**:

### Build Command
```
pip install -r requirements.txt
```

### Start Command
```
python main.py
```

Render auto-deploys on every GitHub push.

---

## Project Structure
```
/main.py               → main bot logic
/requirements.txt      → Python dependencies
/README.md             → documentation
```

---

## 🗄 Data Storage (Firebase)
The bot reads/writes these nodes:

```
/listings
    <listing_id>
        item:
        qty:
        remaining:
        size:
        expiry:
        location:
        photo_id:
        status:
        claims: []

/user_listings
    <user_id>:
        <listing_id>: {...}
```

Use Firebase UI → Export JSON to download all data.

---

## Year-End Reporting  
At year-end:

1. Go to Firebase Realtime Database  
2. Click **Export JSON**  
3. Upload JSON to: https://json-csv.com/  
4. Download CSV for Excel analysis  

No cost involved.

---

## Debugging & Troubleshooting

### Bot not responding?
- Visit Render → Service → Logs  
- Check for Python exceptions  

### Bot cannot post to Telegram channel?
- Ensure bot is **admin** in the Telegram channel  
- Check `CHANNEL_ID` value  

### Firebase errors?
- Confirm `FIREBASE_CREDENTIALS` is correct JSON  
- Check database rules  

---

## 👩‍⚕️ Ownership
This bot is maintained by:  
CGH Nursing Sustainability 

---

## 📄 License
Internal CGH project — not for public distribution.

