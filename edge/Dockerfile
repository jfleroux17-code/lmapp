# Caddy 2.11 avec le module caddy-dns/cloudflare, pour obtenir les certificats
# Let's Encrypt par validation DNS (aucun port 80 ouvert, accès filtré par IP).
FROM caddy:2.11-builder AS construction
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2.11
COPY --from=construction /usr/bin/caddy /usr/bin/caddy
