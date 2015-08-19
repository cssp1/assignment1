#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Fix out-of-the-box misconfiguration of sendmail on Amazon Linux so
# that it can actually send mail.

# This is an IMPERFECT solution - it is good enough to get critical
# system mails out to admin staff, but it is definitely NOT reliable
# enough to use for customer-facing email. There is no good way to get
# customer-facing email delivered reliably from ANY server in EC2 due
# to spam-blocker issues. You MUST use either Amazon SES or a
# third-party SMTP system (Gmail for low volume,
# http://www.authsmtp.com/ for high volume).

# Note: spinpunch.com SPF record needs to allow, at the very minimum,
# forums and www hosts to send mail directly. It may help, but it's
# not essential, to also include analytics/prod/mongo hosts.

import sys, os, socket, subprocess, getopt

# edit "filename", making sure it has all lines in "include" and no lines in "exclude"
def fix_file(filename, include = [], exclude = []):
    newpath = filename+'.inprogress'
    newfile = open(newpath, 'w')
    exclude_set = set(exclude)
    try:
        seen = set()
        for line in open(filename).xreadlines():
            line = line.strip()
            if line in exclude_set:
                print '%s: removing unwanted line "%s"' % (filename, line)
                continue
            seen.add(line)
            newfile.write(line+'\n')
        for line in include:
            if line not in seen:
                print '%s: adding missing line "%s"' % (filename, line)
                newfile.write(line+'\n')
    except:
        os.unlink(newpath)
        raise
    os.rename(newpath, filename)

def fix_sendmail_mc():
    return fix_file('/etc/mail/sendmail.mc',
                    exclude = [
        "EXPOSED_USER(`root')dnl",
        "dnl MASQUERADE_AS(`mydomain.com')dnl",
        "dnl FEATURE(masquerade_envelope)dnl",
        "dnl FEATURE(masquerade_entire_domain)dnl",
        "dnl MASQUERADE_DOMAIN(localhost)dnl",
        "dnl MASQUERADE_DOMAIN(localhost.localdomain)dnl",
        "dnl MASQUERADE_DOMAIN(mydomainalias.com)dnl",
        "dnl MASQUERADE_DOMAIN(mydomain.lan)dnl",
        # these belong at the end of the file, after "FEATURE" lines (otherwise it's a syntax error)
        # so remove them first, then add back later
        "MAILER(smtp)dnl",
        "MAILER(procmail)dnl",
        "dnl MAILER(cyrusv2)dnl",
        ],
                    include = [
        "dnl EXPOSED_USER(`root')dnl",
        "MASQUERADE_AS(`spinpunch.com')dnl",
        "FEATURE(masquerade_envelope)dnl",
        "FEATURE(masquerade_entire_domain)dnl",
        "MASQUERADE_DOMAIN(`spinpunch.com')dnl",
        "MASQUERADE_DOMAIN(`amazonaws.com')dnl",
        "MASQUERADE_DOMAIN(localhost)dnl",
        "MASQUERADE_DOMAIN(localhost.localdomain)dnl",
        "MASQUERADE_DOMAIN(mydomainalias.com)dnl",
        "MASQUERADE_DOMAIN(mydomain.lan)dnl",
        # add these back at the end, after "FEATURE" lines
        "MAILER(smtp)dnl",
        "MAILER(procmail)dnl",
        "dnl MAILER(cyrusv2)dnl",
        ],
                    )

def fix_submit_mc(myhost):
    return fix_file('/etc/mail/submit.mc',
                    include = ["define(`confDOMAIN_NAME', `"+myhost+"')dnl",
                               "define(`_USE_CT_FILE_',`1')dnl",
                               "define(`confCT_FILE',`/etc/mail/trusted-users')dnl"],
                    )

def fix_trusted_users():
    return fix_file('/etc/mail/trusted-users', include = ['apache'])

#def fix_trusted_users():
if __name__ == "__main__":
    myhost = socket.gethostname()

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])

    for key, val in opts:
        if key == '--sender-email': pass

    fix_sendmail_mc()
    fix_submit_mc(myhost)
    fix_trusted_users()
    os.chdir('/etc/mail')
    subprocess.check_call(['make'])

    print "Mail config should be fixed now! Restarting sendmail!"
    subprocess.check_call(['/etc/init.d/sendmail', 'restart'])
