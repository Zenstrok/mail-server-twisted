# Mail Server with Twisted — SMTP, POP3, TLS & XMPP Notifications

Individual project for the Computer Networks course at Instituto Tecnológico de Costa Rica. A complete email system written in **Python** with the **Twisted** networking framework: it receives, stores, sends and delivers email, and notifies users in real time over XMPP.

## Components

| File | Description |
|------|-------------|
| `smtpserver.py` | SMTP server that validates recipient domains, stores each message as `.eml` and triggers an XMPP notification. |
| `pop3server.py` | POP3 server with authentication (Twisted Cred) so clients like Thunderbird can download messages; deletes them on `QUIT`. |
| `smtpclient.py` | Bulk email client that reads recipients from a CSV, personalizes messages with `{{column}}` variables and attaches files (MIME). |
| `xmpp_notifier.py` | XMPP bot (slixmpp) that sends "new email" alerts in a separate thread, so the server is never blocked. |

## Features

- SMTP and POP3 over plain TCP and **SSL/TLS** (PyOpenSSL).
- Recipient domain validation and per-user mailbox storage.
- Personalized bulk email with MIME attachments.
- Real-time new-mail notifications via XMPP.

**Tech:** Python 3.12 · Twisted (SMTP, POP3, Cred) · PyOpenSSL · slixmpp · asyncio · OpenSSL · Linux

## Quick start

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configuration: add your own users and XMPP bot credentials
cp config.example.json config.json

# Optional: self-signed certificate for the SSL ports
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout certs/server.key -out certs/server.crt
```

Start the servers in separate terminals:

```bash
python smtpserver.py -d mariojimenez.tech -s ./mailstorage -p 2525
python pop3server.py -d mariojimenez.tech -s ./mailstorage -p 1100
```

Send personalized emails to everyone in `destinatarios.csv` using the `mensaje.txt` template:

```bash
python smtpclient.py --host 127.0.0.1 --port 2525 \
  -c destinatarios.csv -m mensaje.txt --sender sender@mariojimenez.tech
```

Run any script with `-h` to see all options. Tested with `telnet`, `openssl s_client`, Thunderbird and Gajim.

## Documentation

Full technical documentation, including architecture, ports and test evidence (in Spanish): [documentacion.md](documentacion.md)
