# Live Deploy Guide

## Kyun artifact link kaam nahi karega
Claude ke artifact page ek sandboxed browser mein chalta hai jo sirf
Anthropic ke apne script hosts se connect kar sakta hai — aapke apne
backend server se WebSocket jodna wahan allow nahi hai. Isliye real admin
panel (`static/index.html`) yahi backend serve karega, jo neeche ke
kisi bhi server par deploy hoga.

## Sabse aasaan: Railway / Render (free tier se shuru)

1. `server/` folder ko GitHub repo bana ke push karein.
2. Railway.app ya Render.com par "New Web Service" → us repo ko connect karein.
3. Build command: `pip install -r requirements.txt`
   Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Deploy hote hi aapko ek URL milega, jaise `https://your-app.up.railway.app`
5. Browser mein wahi URL kholne se admin panel dikhega (abhi khaali, kyunki
   koi agent connect nahi hua).
6. `agent.py` mein `SERVER_URL` ko is URL ke `wss://` version se set karein:
   `wss://your-app.up.railway.app/ws/agent`
7. Agent ko `.exe` banayein (`BUILD_AND_AUTOSTART.md` dekhein) aur kisi bhi
   PC par chalayein — uski screen admin panel mein turant dikhni chahiye.

## Apna VPS (DigitalOcean / AWS / company server)

```
sudo apt update && sudo apt install python3-pip nginx -y
pip3 install -r requirements.txt
# background mein chalayein (ya systemd service banayein):
uvicorn main:app --host 127.0.0.1 --port 8000 &
```
Fir nginx ko reverse proxy + SSL (Certbot) ke saath apne domain
(`monitor.yourcompany.com`) par point karein. Isse aapko HTTPS/WSS milega,
jo zaroori hai taaki browsers WebSocket block na karein.

## Checklist before "live"
- [ ] Backend deployed, HTTPS/WSS working (plain `ws://` sirf testing ke liye)
- [ ] `agent.py` mein `SERVER_URL` final domain se set, phir `.exe` banaya
- [ ] CORS (`main.py` mein `allow_origins`) ko `"*"` se apne admin domain tak limit kiya
- [ ] Employees ko written notice di gayi monitoring ke baare mein
- [ ] `.exe` test kiya ek PC par — tray icon dikhta hai, "Start" dabane par
      admin panel mein live image aati hai
