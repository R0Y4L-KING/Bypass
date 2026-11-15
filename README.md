# Bypass Bot

Ek chhota Telegram bot jo link-shortener links ko bypass karke direct link nikaal deta hai.

Koi bhi short link bhejo — bot API ko call karta hai, response parse karta hai, aur
original + bypassed link dono dikha deta hai.

Bot: [@KingBypassRobot](https://t.me/KingBypassRobot)

---

## Features

- Koi bhi `http://` / `https://` link bhejo, bypass ho jayega
- Original link, bypassed link, time aur credits — sab ek message me
- **Force-subscribe** (join channel check) — env se control hota hai
- API fail ho to saaf error message (bot crash nahi hota)
- Render ke liye built-in health endpoint (`/` pe `OK`)
- Saari settings environment variables se — code me kuch hardcoded nahi

---

## Environment variables

| Variable | Zaroori | Default | Kya hai |
|---|---|---|---|
| `BOT_TOKEN` | haan | — | @BotFather se mila token |
| `KEY` | haan | — | **Sirf API key** (poora URL nahi) |
| `BOT_USERNAME` | nahi | `KingBypassRobot` | Bot ka username, bina `@` ke |
| `FSUB_CHANNELS` | nahi | khali | Force-sub channels, comma separated |
| `FSUB_MSG` | nahi | built-in | Force-sub message ka custom text |
| `API_URL` | nahi | Altaf API endpoint | API ka base URL |
| `TOOL` | nahi | `nick-bypass` | Kaunsa bypass tool chalana hai |
| `TIMEOUT` | nahi | `45` | API call ka timeout (seconds) |
| `PORT` | nahi | `8080` | Render khud deta hai |

### `KEY` me kya daalna hai

Sirf **key** ki value, poora URL nahi:

```
KEY=Royalking
```

Poora endpoint pehle se code me default hai:

```
API_URL=https://altaf-api-maker.base44.app/functions/lookup
```

Agar kabhi endpoint badle to `API_URL` alag se set kar dena.

> `KEY` kabhi repo me commit na karo. `.env` local ke liye hai aur woh `.gitignore`
> me already hai.

---

## Force-subscribe (join channel check)

`FSUB_CHANNELS` me channel list do — comma se separate, `@username` ya `-100...` id:

```
FSUB_CHANNELS=@mychannel,-1001234567890
```

Kaam kaise karta hai:

1. User jab bhi link bhejta hai, bot `get_chat_member` se check karta hai ki woh
   sab channels me hai ya nahi.
2. Agar nahi hai, to join buttons + **🔄 Try Again** wala message chala jaata hai.
3. Join karke Try Again dabane par verification ho jaati hai aur user ko bata
   diya jaata hai ki ab link bhej sakta hai.
4. Khali chhodne par force-sub poori tarah **off** rehta hai.

**Zaroori:** bot ko in channels me **admin** banana padega, warna Telegram
`get_chat_member` allow nahi karta. Private channel ho to bot ko admin banane par
invite link khud mil jaata hai; public channel ka `t.me/<username>` link use hota hai.

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
   - `BOT_USERNAME` = `KingBypassRobot`
   - `FSUB_CHANNELS` = `@yourchannel` (agar force-sub chahiye)
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
                 ├─ force-sub check (FSUB_CHANNELS)
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
