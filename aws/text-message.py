#!/usr/bin/python

# send an SMS text message (or just a regular email)!

import json
import smtplib
import sys, os, platform, getpass, time, getopt, cStringIO

# see http://stackoverflow.com/questions/3362600/how-to-send-email-attachments-with-python

from email.MIMEMultipart import MIMEMultipart
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email.Utils import COMMASPACE, formatdate
from email import Encoders

def pretty_receiver(r):
    if 'name' in r:
        return '"%s" <%s>' % (r['name'],r['email'])
    else:
        return r['email']

def compose_message(header_from, header_to, subject, body, attachments=[]):
    msg = MIMEMultipart()
    msg['From'] = header_from
    msg['To'] = header_to
    msg['Date'] = formatdate(localtime=False)
    msg['Subject'] = subject

    msg.attach( MIMEText(body) )

    for f in attachments:
        part = MIMEBase('application', "octet-stream")
        part.set_payload( open(f,"rb").read() )
        Encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="%s"' % os.path.basename(f))
        msg.attach(part)

    return msg.as_string()

if __name__ == "__main__":
    sender_email = getpass.getuser() + '@spinpunch.com' # + platform.node()
    sender_name = 'Valentina'
    subject = 'Auto'
    source = sys.stdin
    receivers = []
    attachments = []

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['sender-email=', 'sender-name=', 'recipient=', 'recipients-json=', 'subject=', 'body-from=', 'body=', 'attach='])

    for key, val in opts:
        if key == '--sender-email': sender_email = val
        elif key == '--sender-name': sender_name = val
        elif key == '--recipient': receivers.append({'email': val})
        elif key == '--recipients-json': receivers += json.loads(val) # format: [{'name': 'asdf', 'email': 'asdf@example.com'}, ...]
        elif key == '--subject': subject = val
        elif key == '--body-from': source = open(val)
        elif key == '--body': source = cStringIO.StringIO(val+'\n')
        elif key == '--attach': attachments.append(val)

    if not receivers:
        sys.stderr.write('no receivers specified')
        sys.exit(1)

    message = compose_message('"%s" <%s>' % (sender_name, sender_email),
                              ', '.join([pretty_receiver(r) for r in receivers]),
                              subject,
                              ''.join(source.readlines()),
                              attachments=attachments)

    smtplib.SMTP('localhost').sendmail(sender_email, [r['email'] for r in receivers], message)
