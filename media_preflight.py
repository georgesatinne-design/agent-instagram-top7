"""Contrôle HTTPS gratuit et borné avant tout arbitrage de publication."""
from urllib.parse import urlparse
import time
import requests

def verify_public_assets(assets, *, getter=requests.get, attempts=3, pause=time.sleep):
    if not isinstance(assets,list) or not 1<=len(assets)<=10:
        raise ValueError('Nombre de médias invalide')
    for item in assets:
        url=item['image']['url']
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!='raw.githubusercontent.com' or parsed.username or parsed.password:
            raise ValueError('Média GitHub public HTTPS obligatoire')
        for attempt in range(attempts):
            ok=False
            try:
                response=getter(url,timeout=12,stream=True,allow_redirects=False)
                try:
                    response.raise_for_status()
                    ok=response.status_code==200 and response.headers.get('Content-Type','').lower().startswith('image/')
                finally:
                    response.close()
            except requests.RequestException:
                pass
            if ok:break
            if attempt+1<attempts:pause(3)
        else:
            raise RuntimeError('Média non accessible : aucun arbitrage Buffer '+url)
    return True
