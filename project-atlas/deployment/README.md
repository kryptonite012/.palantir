# Deployment assets

| File | Purpose |
|---|---|
| `install.sh` / `install.ps1` | Offline installers shipped inside release bundles (venv + `pip install --no-index` from `wheelhouse/`) |
| `atlas-api.service` | systemd unit for the private-LAN profile |
| `nginx-atlas.conf` | TLS-terminating reverse proxy for the private-LAN profile |

See `docs/installation.md` for the three deployment profiles.
