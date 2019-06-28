#!/usr/bin/env python
# -*- coding: utf-8 -*-

from base64 import b64encode

class Mailgun(object):
    def __init__(self, config):
        self.api_url = config['api_url']
        self.api_key = config['api_key']
        self.sender_ui_name = config['sender_ui_name']
        self.sender_email = config['sender_email']

        # optional ${DOMAIN} replacement in api_url and sender_email
        self.domain = config.get('domain', '')
        self.domain_by_provider = config.get('domain_by_provider', {})

    def send(self, email, ui_subject, ui_body_plaintext, ui_body_html = None, tags = [],
             ui_sender_name = None, ui_sender_email = None, campaign = None,
             domain_override = None):
        assert isinstance(ui_subject, unicode)
        assert isinstance(ui_body_plaintext, unicode)
        assert ui_body_html is None or isinstance(ui_body_html, unicode)
        assert ui_sender_name is None or isinstance(ui_sender_name, unicode)

        if domain_override:
            domain = domain_override
        else:
            domain = self.domain

            # Ooverride sender domain depending on the email provider.
            # This allows us to work around spam blacklists.
            if not ('@' in email and len(email.split('@')) >= 2):
                raise Exception('invalid email address: %r' % email)

            provider = email.split('@')[1].lower()
            domain = self.domain_by_provider.get(provider, domain)

        sender_email = self.sender_email.replace('${DOMAIN}', domain)

        url = self.api_url.replace('${DOMAIN}', domain) + '/messages'
        headers = {'Authorization': 'Basic '+b64encode('api:'+self.api_key)}
        params = {'from': ('%s <%s>' % (ui_sender_name or self.sender_ui_name,
                                        ui_sender_email or sender_email)).encode('utf-8'),
                  'to': email.encode('utf-8'),
                  'subject': ui_subject.encode('utf-8'),
                  'text': ui_body_plaintext.encode('utf-8')}
        if ui_body_html: params['html'] = ui_body_html.encode('utf-8')
        for tag in tags:
            if 'o:tag' in params:
                raise Exception('only one tag allowed')
            params['o:tag'] = tag.encode('utf-8')
        if campaign:
            # assume this is for marketing, so it needs all kinds of tracking enabled
            params['o:campaign'] = campaign.encode('utf-8')
            params['o:tracking-clicks'] = u'yes'
            params['o:tracking-opens'] = u'yes'
        return {'method': 'POST', 'url': url, 'params': params, 'headers': headers}

# test code
if __name__ == '__main__':
    import json, sys, requests, time
    import SpinConfig
    email = sys.argv[1]
    mg = Mailgun(SpinConfig.config['mailgun_bulk'])
    time_now = int(time.time())
    req = mg.send(email, u'Sent at %d' % time_now, u'Body text \u9f13\u9f13 %d' % time_now,
                  ui_body_html = u'<html>HTML version test %d</html>' % time_now, tags = ['test'])
    if 0:
        response = getattr(requests, req['method'].lower())(req['url'], data = req['params'],
                                                            headers = req['headers'])
        print response.status_code
        print response.json()
    else:
        print json.dumps(req)
