# Bypass Bot

Ek chhota Telegram bot jo link-shortener links ko bypass karke direct link nikaal deta hai.

Koi bhi short link bhejo — bot API ko call karta hai, response parse karta hai, aur
original + bypassed link dono dikha deta hai.

---

## Features

- Koi bhi `http://` / `https://` link bhejo, bypass ho jayega
- Original link, bypassed link, time aur credits — sab ek message me
- API fail ho to saaf error message (bot crash nahi hota)
- Render ke liye built-in health endpoint (`/` pe `OK`)
- Saari settings environment variables se — code me kuch hardcoded nahi

---

## Environment variables

| Variable | Zaroori | Default | Kya hai |
|---|---|---|---|
| `BOT_TOKEN` | haan | — | @BotFather se mila token |
| `KEY` | haan | — | API key |
| `BOT_USERNAME` | nahi | `Your_Bypass_Bot` | Bot ka username, bina `@` ke |
| `API_URL` | nahi | Altaf API endpoint | API ka base URL |
| `TOOL` | nahi | `nick-bypass` | Kaunsa bypass tool chalana hai |
| `TIMEOUT` | nahi | `45` | API call ka timeout (seconds) |
| `PORT` | nahi | `8080` | Render khud deta hai |

> `KEY` kabhi repo me commit na karo. `.env` local ke liye hai aur woh `.gitignore`
> me already hai.

---

## Local par chalana

```bash
git clone https://github.com/R0Y4L-KING/Bypass.git
cd Bypass

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env             # phir .env me BOT_TOKEN aur KEY bharo
export $(grep -v '^#' .env | xargs)   # Windows: manually set karo

python bot.py
```

Terminal me `bot starting (long polling)` dikhe to bot chalu hai. Telegram pe jaake
`/start` bhejo.

---

## Render par deploy

1. [Render](https://render.com) pe login karo → **New +** → **Web Service**
2. Apna GitHub repo `Bypass` connect karo
3. Settings:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Instance Type:** Free
4. **Environment** tab me variables add karo:
   - `BOT_TOKEN` = aapka token
   - `KEY` = API key
   - `BOT_USERNAME` = bot ka username
5. **Create Web Service** dabao. Logs me `bot starting (long polling)` aane par ho gaya.

`render.yaml` bhi repo me hai, to **New + → Blueprint** se ek click me bhi deploy ho sakta hai.

> Free instance 15 minute inactivity ke baad sleep ho jaata hai. Health endpoint
> isliye hai ki Render ko ek open port mile; pehla message aane par service
> phir se jag jaati hai (thoda delay ho sakta hai).

---

## Kaam kaise karta hai

```
User → link → bot.py
                 │
                 ├─ GET API_URL ?tool=nick-bypass&key=KEY&q=<link>
                 │
                 ├─ JSON: {success, result: "Original Link ... Bypassed Link ..."}
                 │
                 └─ result (text) se URL parse → formatted reply
```

API ka `result` field plain text hota hai, is liye `pick_url()` usme se
`Bypassed Link` wali line ka URL nikaalta hai. Agar label badal jaye to fallback
ke taur par result ka aakhri URL use hota hai.

---

## Files

```
bot.py            poora bot
requirements.txt  dependencies
render.yaml       Render blueprint
Procfile          Heroku/worker ke liye
runtime.txt       Python version
.env.example      env variables ka sample
```

---

## Note

Yeh bypass services ad-supported shorteners ke ads skip karti hain. Personal
testing ke liye theek hai — public bot me daalne se pehle us site ki terms
dekh lena.
