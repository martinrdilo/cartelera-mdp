"""Map a ticket URL host to the seller that owns it.

A collector that sees an outbound ticket link uses this map to fill `seller`;
subdomains inherit their parent domain's seller.
"""

from urllib.parse import urlparse

SELLERS = (
    ("venti.live", "Venti"),
    ("articket.com.ar", "Articket"),
    ("cultutickets.com", "CultuTickets"),
    ("ticketek.com.ar", "Ticketek"),
    ("plateanet.com", "Plateanet"),
    ("wearebombo.com", "Bombo"),
    ("tuentrada.com", "TuEntrada"),
    ("unica-cartelera.com.ar", "Única Cartelera"),
    ("passline.com", "Passline"),
    ("getdogma.app", "Dogma"),
    ("alpogo.com", "Alpogo"),
)


def seller_from_url(url):
    """Return the seller name for a ticket URL host, or None when unknown."""
    if not url:
        return None
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for domain, seller in SELLERS:
        if host == domain or host.endswith("." + domain):
            return seller
    return None
