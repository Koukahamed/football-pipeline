"""Generate a preview first; SMTP is invoked only without --preview-only."""
import argparse
import os
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from product import dataset, email_content, OUT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview-only', action='store_true')
    args = parser.parse_args()
    data = dataset()
    html, plain = email_content(data)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'email_preview.html').write_text(html, encoding='utf-8')
    if args.preview_only:
        print('Email preview generated; nothing sent.')
        return
    required = ['SMTP_HOST', 'SMTP_USER', 'SMTP_PASS', 'EMAIL_TO']
    if any(not os.environ.get(key) for key in required):
        raise SystemExit('Missing required SMTP configuration')
    recipients = [value.strip() for value in os.environ['EMAIL_TO'].split(',') if value.strip()]
    sender = os.environ.get('EMAIL_FROM') or os.environ['SMTP_USER']
    msg = EmailMessage()
    msg['Subject'] = f"⚽ Football Daily — {data['today']} : résultats et matchs du jour"
    msg['From'] = sender
    msg['To'] = ', '.join(recipients)
    msg.set_content(plain)
    msg.add_alternative(html, subtype='html')
    with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT') or '587'), timeout=30) as server:
        server.starttls()
        server.login(os.environ['SMTP_USER'], os.environ['SMTP_PASS'])
        server.send_message(msg, from_addr=parseaddr(sender)[1], to_addrs=recipients)
    print('Email sent successfully.')


if __name__ == '__main__':
    main()
