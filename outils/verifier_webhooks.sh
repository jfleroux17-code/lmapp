#!/bin/sh
# Vérification de bout en bout des webhooks de Twilio, à travers Caddy (environnement de test).
# Usage : sh webhook_bout_en_bout.sh   (depuis /srv/lmapp/test)
H=test.ledeneigeur.com
U="https://$H/webhooks/twilio/textos/"
R="--resolve $H:443:127.0.0.1"
D='Body=Essai+de+signature&From=%2B15555550142&MessageSid=SMessai00000000000000000000000001&To=%2B15555550100'
SIG=$(docker compose exec -T app python -c "
import base64, hashlib, hmac, os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup()
from django.conf import settings
p = {'Body': 'Essai de signature', 'From': '+15555550142', 'MessageSid': 'SMessai00000000000000000000000001', 'To': '+15555550100'}
d = '$U' + ''.join(k + p[k] for k in sorted(p))
print('SIG=' + base64.b64encode(hmac.new(settings.TWILIO_AUTH_TOKEN.encode(), d.encode(), hashlib.sha1).digest()).decode())
" 2>/dev/null | sed -n 's/^SIG=//p')
printf "sans signature      : "; curl -s $R -o /dev/null -w "%{http_code}\n" -X POST -d "$D" "$U"
printf "signature fausse    : "; curl -s $R -o /dev/null -w "%{http_code}\n" -X POST -d "$D" -H "X-Twilio-Signature: AAAAAAAAAAAAAAAAAAAAAAAAAAA=" "$U"
printf "corps modifié       : "; curl -s $R -o /dev/null -w "%{http_code}\n" -X POST -d "$D&Extra=1" -H "X-Twilio-Signature: $SIG" "$U"
printf "signature valide    : "; curl -s $R -o /dev/null -w "%{http_code}\n" -X POST -d "$D" -H "X-Twilio-Signature: $SIG" "$U"
printf "GET                 : "; curl -s $R -o /dev/null -w "%{http_code}\n" "$U"
