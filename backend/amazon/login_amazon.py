# WHY: Single Responsibility Principle - Strictly manages Amazon Luna configuration and secure storage.
import os
from ViGaVault_utils import BASE_DIR, save_encrypted_json, load_encrypted_json

AMAZON_DIR = os.path.join(BASE_DIR, "backend", "amazon")
SESSION_FILE = os.path.join(AMAZON_DIR, "amazon_session.dat")

class AmazonRegionConfig:
    def __init__(self, retail_domain, luna_domain, tempo):
        self.retailDomain = retail_domain
        self.lunaDomain = luna_domain
        self.tempo = tempo

def get_region_config(code):
    mapping = {
        'AE': ('www.amazon.ae', 'luna.amazon.ae', 'tempo_ae'),
        'AU': ('www.amazon.com.au', 'luna.amazon.com.au', 'tempo_au'),
        'BE': ('www.amazon.com.be', 'luna.amazon.com.be', 'tempo_be'),
        'BR': ('www.amazon.com.br', 'luna.amazon.com.br', 'tempo_br'),
        'CA': ('www.amazon.ca', 'luna.amazon.ca', 'tempo_ca'),
        'DE': ('www.amazon.de', 'luna.amazon.de', 'tempo_de'),
        'EG': ('www.amazon.eg', 'luna.amazon.eg', 'tempo_eg'),
        'ES': ('www.amazon.es', 'luna.amazon.es', 'tempo_es'),
        'FR': ('www.amazon.fr', 'luna.amazon.fr', 'tempo_fr'),
        'IN': ('www.amazon.in', 'luna.amazon.in', 'tempo_in'),
        'IT': ('www.amazon.it', 'luna.amazon.it', 'tempo_it'),
        'JP': ('www.amazon.co.jp', 'luna.amazon.co.jp', 'tempo_jp'),
        'MX': ('www.amazon.com.mx', 'luna.amazon.com.mx', 'tempo_mx'),
        'NL': ('www.amazon.nl', 'luna.amazon.nl', 'tempo_nl'),
        'PL': ('www.amazon.pl', 'luna.amazon.pl', 'tempo_pl'),
        'SA': ('www.amazon.sa', 'luna.amazon.sa', 'tempo_sa'),
        'SE': ('www.amazon.se', 'luna.amazon.se', 'tempo_se'),
        'SG': ('www.amazon.sg', 'luna.amazon.sg', 'tempo_sg'),
        'TR': ('www.amazon.com.tr', 'luna.amazon.com.tr', 'tempo_tr'),
        'UK': ('www.amazon.co.uk', 'luna.amazon.co.uk', 'tempo_uk'),
        'US': ('www.amazon.com', 'luna.amazon.com', 'tempo_us')
    }
    retail, luna, tempo = mapping.get(code.upper(), ('www.amazon.com', 'luna.amazon.com', 'tempo_us'))
    return AmazonRegionConfig(retail, luna, tempo)

def get_login_url(region_code):
    config = get_region_config(region_code)
    return (f"https://{config.retailDomain}/ap/signin?openid.pape.max_auth_age=3600"
            f"&openid.return_to=https%3A%2F%2F{config.lunaDomain}%2Fclaims%2Fhome%3FsignedIn%3Dtrue"
            f"&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select"
            f"&openid.assoc_handle={config.tempo}&openid.mode=checkid_setup&language=en_US"
            f"&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select"
            f"&pageId={config.tempo}&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")

def is_amazon_connected():
    return os.path.exists(SESSION_FILE)

def disconnect_amazon():
    if os.path.exists(SESSION_FILE):
        try: os.remove(SESSION_FILE)
        except: pass

def save_amazon_session(cookie_value):
    os.makedirs(AMAZON_DIR, exist_ok=True)
    save_encrypted_json(SESSION_FILE, {"session_cookie": cookie_value})

def get_amazon_session():
    data = load_encrypted_json(SESSION_FILE)
    return data.get("session_cookie")
