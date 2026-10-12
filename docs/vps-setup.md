# Deploy the shared checklist on hadol.deydas.com

This runbook is intended for an agent with shell access to the VPS. It adds the checklist at **https://hadol.deydas.com/grocery/** to the existing Nginx installation. It does not replace the existing website, TLS configuration, or OpenClaw installation. The repository supplies the application and deployment templates; these instructions do not mean a remote deployment has already happened.

The example commands target a Linux VPS with systemd and Python 3.10 or newer. Adjust package-manager and service-discovery commands to the actual host. Use the release/commit containing this implementation, rather than assuming the VPS checkout is current.

## Target layout and behavior

| Component | Location |
| --- | --- |
| Public URL | `https://hadol.deydas.com/grocery/` |
| Existing HTTPS proxy | Nginx, serving `hadol.deydas.com` |
| Application listener | `127.0.0.1:8787`; never bind it publicly |
| Application checkout and virtualenv | `/opt/family-grocery`, `/opt/family-grocery/.venv` |
| Persistent local state | `/var/lib/family-grocery` |
| Environment file | `/etc/family-grocery.env` |
| systemd unit / service account | `family-grocery.service` / `grocery:grocery` |

The browser sends requests through Nginx. OpenClaw runs the `family-grocery` CLI locally against the same SQLite database. Both paths use the same transactional storage implementation. Keep the database on a local filesystem on this VPS, not NFS or a cloud-synced directory. Store metadata and safety notes remain in `config.json` and `safety.json`; `list.md` and `history.md` become import/export files, not live writable state.

There is one shared active link. Asking for it again returns the same link with its original expiry. Its deadline is four hours after creation, with no sliding renewal. Closing the page's **Close** button revokes that link and every session attached to it. Closing a browser tab does not revoke it. The next CLI `link` request after expiry/closure creates a fresh link. Link state persists across application restarts. There are no household accounts or individual attribution.

## 1. Inspect the VPS before changing it

Identify the actual OpenClaw operating-system account, how OpenClaw is started, its grocery data directory, and any existing grocery deployment. These examples discover services and listeners without printing process arguments that may contain secrets:

```sh
python3 --version
systemctl list-units --all --type=service
ps -eo user,pid,comm
sudo ss -ltnp
sudo nginx -t
```

If OpenClaw runs under a user-level systemd unit, inspect that user's units too. Record the actual unit name and restart procedure; do not assume the service is called `openclaw` or that its user has that name. Check that port 8787 is unused. If it is occupied, choose another free loopback port and change both the unit and Nginx snippet consistently.

Save Nginx's expanded configuration privately for inspection. It may contain unrelated credentials, so do not paste it into public logs or commit it:

```sh
GROCERY_DEPLOY_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
sudo sh -c 'umask 077; nginx -T > "$1" 2>&1' sh "/root/grocery-nginx-$GROCERY_DEPLOY_STAMP.txt"
```

Inspect that file on the host to find the **existing port-443 server block** whose `server_name` includes `hadol.deydas.com`, including its actual configuration file and any includes. Check existing `/grocery` locations, regex locations, authentication, caching, and server-level rewrites. A server-level unconditional `return` or rewrite can intercept the new locations. Preserve all unrelated routes and certificate settings. Do not create a second competing server block for this domain. If an existing grocery route is occupied, resolve its purpose before changing it.

Confirm DNS reaches this Nginx server and HTTPS already works for `hadol.deydas.com`. Retain the existing certificate-renewal arrangement. If TLS is missing or broken, repair the host's established TLS setup before exposing grocery links; do not disable secure cookies to work around it.

## 2. Install the application and service account

Use the existing checkout if suitable, or clone the repository into `/opt/family-grocery` and check out the intended release/commit. Do not overwrite an existing deployment directory blindly. For a new install:

```sh
sudo git clone https://github.com/adeydas/openclaw-family-grocery-skill.git /opt/family-grocery
GROCERY_RELEASE='replace-with-approved-release-or-commit-containing-this-change'
sudo git -C /opt/family-grocery checkout "$GROCERY_RELEASE"
```

Install Python's `venv` support using the host's package manager if needed. On Debian/Ubuntu this is typically `python3-venv`. Nginx is already installed and should not be reinstalled or reset. Create the account/group only if they do not already exist; inspect any existing account before reusing it:

```sh
getent group grocery
getent passwd grocery
# Run these two commands only for a new group/account:
sudo groupadd --system grocery
sudo useradd --system --gid grocery --home-dir /var/lib/family-grocery --no-create-home --shell /usr/sbin/nologin grocery

sudo install -d -o grocery -g grocery -m 2770 /var/lib/family-grocery
sudo python3 -m venv /opt/family-grocery/.venv
sudo /opt/family-grocery/.venv/bin/python -m pip install '/opt/family-grocery[server]'
sudo /opt/family-grocery/.venv/bin/python -m pip check
```

The checkout and virtualenv should remain writable only by the deployment administrator, and readable/executable by `grocery` and OpenClaw. The `[server]` extra installs the pinned Gunicorn runtime. Gunicorn accepts the application's factory target `grocery_service.web:create_app()`. [Gunicorn application-factory documentation](https://gunicorn.org/run/)

Give the **actual OpenClaw account** shared state access:

```sh
GROCERY_AGENT_USER='replace-with-the-actual-openclaw-os-user'
id "$GROCERY_AGENT_USER"
sudo usermod -a -G grocery "$GROCERY_AGENT_USER"
```

Existing OpenClaw processes will not acquire new supplementary groups until restarted. Arrange that restart together with the skill migration below. Do not grant `www-data` or every local user database access; Nginx only needs access to the loopback listener. For rootless/containerized OpenClaw, explicitly arrange the corresponding group ID and local-state mount instead of assuming host group membership reaches the container.

## 3. Migrate data with legacy writers paused

Pause grocery writes in OpenClaw before copying or importing data. Deploy the updated skill instructions before allowing writes again: the old instructions write `list.md` directly and would otherwise create two inconsistent lists. If OpenClaw is a dedicated service, stop the discovered unit during this step; if it also handles unrelated work, use the host's established maintenance mechanism to pause grocery operations.

Take a private backup of the original directory outside the web root. Do not remove the originals. Example, with the real source path substituted:

```sh
GROCERY_OLD_DATA='/absolute/path/to/existing/grocery-data'
sudo install -d -m 0700 /var/backups/family-grocery
sudo tar -C "$GROCERY_OLD_DATA" -czf "/var/backups/family-grocery/legacy-$GROCERY_DEPLOY_STAMP.tar.gz" .
sudo chmod 0600 "/var/backups/family-grocery/legacy-$GROCERY_DEPLOY_STAMP.tar.gz"
```

For a first install, copy the existing `list.md`, `history.md`, `config.json`, and `safety.json`, if present, into `/var/lib/family-grocery` with ownership `grocery:grocery` and mode `0660`. Do not replace files in an already initialized state directory. For each existing source file, use:

```sh
sudo install -o grocery -g grocery -m 0660 "$GROCERY_OLD_DATA/list.md" /var/lib/family-grocery/list.md
sudo install -o grocery -g grocery -m 0660 "$GROCERY_OLD_DATA/history.md" /var/lib/family-grocery/history.md
sudo install -o grocery -g grocery -m 0660 "$GROCERY_OLD_DATA/config.json" /var/lib/family-grocery/config.json
sudo install -o grocery -g grocery -m 0660 "$GROCERY_OLD_DATA/safety.json" /var/lib/family-grocery/safety.json
```

Skip commands for absent source files. An empty/new household does not need a legacy directory or copies. Initialize/import using the CLI:

```sh
sudo -u grocery sh -c 'umask 0007; exec /opt/family-grocery/.venv/bin/family-grocery --data-dir /var/lib/family-grocery init'
sudo -u grocery /opt/family-grocery/.venv/bin/family-grocery --data-dir /var/lib/family-grocery list
sudo -u grocery /opt/family-grocery/.venv/bin/family-grocery --data-dir /var/lib/family-grocery history
```

Compare imported names, stores, quantities, timestamps, count, and historical entries with the originals. Date-only item entries retain their calendar dates. Legacy timestamps with a time but no timezone are interpreted as UTC; retain the originals if those times were recorded in a different local timezone. Initialization must finish successfully before starting the web service. If strict Markdown parsing rejects legacy content, resolve the reported lines in the working copy and retry; do not discard or silently skip those rows. Keep the backed-up originals unchanged. An already initialized database must not be reimported to repair an unrelated startup problem.

Check ownership/modes of the state directory, database, and supporting files, including any SQLite `-wal` and `-shm` files. The directory's setgid bit keeps new files in the `grocery` group. Both the service and OpenClaw must be able to use that directory; other users must have no access. Confirm access with a new process running as the actual agent user:

```sh
sudo -u "$GROCERY_AGENT_USER" /opt/family-grocery/.venv/bin/family-grocery --data-dir /var/lib/family-grocery list
```

Do not solve permission failures with world-writable permissions or by running the web application as root.

## 4. Start the loopback service

For a new deployment, install the supplied environment file and systemd unit. If either destination already exists, back it up and reconcile the differences before replacing it:

```sh
sudo install -o root -g grocery -m 0640 /opt/family-grocery/deploy/family-grocery.env.example /etc/family-grocery.env
sudo install -o root -g root -m 0644 /opt/family-grocery/deploy/family-grocery.service /etc/systemd/system/family-grocery.service
sudo systemd-analyze verify /etc/systemd/system/family-grocery.service
sudo systemctl daemon-reload
sudo systemctl enable --now family-grocery.service
sudo systemctl status family-grocery.service --no-pager
curl --fail --silent --show-error http://127.0.0.1:8787/grocery/healthz
sudo ss -ltnp
```

Verify the application only listens on `127.0.0.1:8787`. The health endpoint contains no grocery data. Confirm the env file contains these exact production settings:

```dotenv
GROCERY_DATA_DIR=/var/lib/family-grocery
GROCERY_PUBLIC_URL=https://hadol.deydas.com/grocery/
GROCERY_COOKIE_SECURE=1
```

`GROCERY_PUBLIC_URL` determines the expected browser origin and path; an incorrect value breaks authenticated requests. Do not remove the `/grocery/` suffix. Never set `GROCERY_COOKIE_SECURE=0` for public deployment. There is no separate signing-key environment variable to invent: persistent link/session material is managed in the database.

The supplied unit runs two Gunicorn workers with four threads each, uses `UMask=0007`, and permits persistent writes only under the state directory. `ProtectSystem=strict` and `ReadWritePaths` apply the filesystem restriction; the SQLite directory needs write access for its database, WAL, and shared-memory files. [systemd execution settings](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml)

## 5. Add the Nginx location to the existing HTTPS site

Back up the actual configuration file you identified in step 1. Substitute that path below; do not edit a guessed `sites-enabled/default` file. Keep backups outside Nginx's included directories so a wildcard include cannot load a second copy of the site. `cp -pL` backs up the contents even when the selected path is a symlink:

```sh
GROCERY_NGINX_SITE='/actual/path/to/existing/hadol-nginx-config'
sudo install -d -m 0700 /var/backups/family-grocery
sudo cp -pL "$GROCERY_NGINX_SITE" "/var/backups/family-grocery/nginx-site-$GROCERY_DEPLOY_STAMP.conf"
sudo install -d -o root -g root -m 0755 /etc/nginx/snippets
sudo install -o root -g root -m 0644 /opt/family-grocery/deploy/nginx-grocery.conf /etc/nginx/snippets/family-grocery.conf
```

If `/etc/nginx/snippets/family-grocery.conf` already exists, inspect and back it up outside Nginx's include paths before replacing it.

Add this one line **inside the existing HTTPS `server { ... }` block for `hadol.deydas.com`**:

```nginx
include /etc/nginx/snippets/family-grocery.conf;
```

Do not add it at `http` scope, inside another `location`, or to the HTTP redirect server. Leave the site's other locations and TLS directives in place. The snippet's `location ^~ /grocery/` ensures unrelated regex handlers do not capture checklist assets. Its `proxy_pass http://127.0.0.1:8787;` deliberately has **no trailing slash/URI** so the application receives `/grocery/...` unchanged. Nginx documents the different URI-replacement behavior when `proxy_pass` includes a URI. [Nginx proxy_pass documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)

The snippet disables caching and access logging for checklist requests, caps request bodies at 16 KiB, and preserves application error status codes. The application supplies `Cache-Control: no-store`. If the domain sits behind a CDN or another reverse proxy, exempt `/grocery/` from caching there too. Do not enable request-body/cookie/debug logging: the key is exchanged in a POST body and cookies carry browser access. Do not use Nginx `alias` or `root` to expose the checkout or state directory.

Validate before reloading. If validation fails, fix or restore the changed configuration without reloading:

```sh
sudo nginx -t
sudo systemctl reload nginx
curl --fail --silent --show-error https://hadol.deydas.com/grocery/healthz
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' https://hadol.deydas.com/grocery
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' https://hadol.deydas.com/grocery/api/list
```

Expected results: healthy JSON, `308` for `/grocery`, and `401` for the unauthenticated list endpoint. Confirm `/grocery/` loads the generic page and the existing site's other routes still work. A generic shell must not reveal grocery items. No public firewall rule for port 8787 is needed; leave external access to the existing HTTPS port.

## 6. Connect OpenClaw and verify the complete flow

Install/update the root skill files from this same release in OpenClaw's configured skill location. Do not install the obsolete untracked `family-grocery/` folder if it exists in a development checkout. Set these OpenClaw memory values, following the current `SKILL.md` and `memory-template.md`:

| Memory key | Value |
| --- | --- |
| `family_grocery_path` | `/var/lib/family-grocery` |
| `family_grocery_cli` | `/opt/family-grocery/.venv/bin/family-grocery` |
| `family_grocery_public_url` | `https://hadol.deydas.com/grocery/` |

Restart or resume the previously identified OpenClaw service/process so its new group membership and skill instructions take effect. Verify its actual runtime can invoke the CLI. A successful administrator-run command alone does not prove that OpenClaw's runtime/container has the required executable and state access.

Generate a link as the agent account:

```sh
sudo -u "$GROCERY_AGENT_USER" /opt/family-grocery/.venv/bin/family-grocery --data-dir /var/lib/family-grocery link --base-url https://hadol.deydas.com/grocery/
```

The result is private: send the full `#key=...` link only to the intended WhatsApp conversation. Do not copy it into an issue, screenshot, command-line argument, or deployment log. Everyone with the link can view/remove groceries and close access for everyone. Nginx cannot see the fragment in the initial page URL; JavaScript exchanges it for an HttpOnly session cookie, then removes it from the address bar. A bare URL and a WhatsApp preview reveal no list data. Sessions do not outlive the link's deadline or revocation.

Run the application's automated suite against temporary directories before production cutover; it should cover concurrent removals, stale versions, expiry, revocation, and retry behavior without waiting four hours. The source checkout's test command is:

```sh
cd /opt/family-grocery
.venv/bin/python -m unittest discover -s tests -v
```

For interactive checks that remove items or close links, use a **separate temporary data directory and service instance** with an unused loopback port. For example, a local-only instance on port 8788 can use `GROCERY_PUBLIC_URL=http://127.0.0.1:8788/grocery/` and `GROCERY_COOKIE_SECURE=0`; issue its link using the same `--base-url`. These insecure-cookie settings are supported only for loopback HTTP development and must never replace the production environment file. Do not add sample groceries to the live household or press its Close button during a passive health check. For phone testing of that temporary instance, use an SSH tunnel or a separately scoped temporary HTTPS route, removing it afterward.

Before declaring the deployment complete, verify these behaviors in that disposable instance:

1. Two separate browsers using the same link see the same list, grouped by store.
2. Checking different items concurrently removes both, and checking the same item twice creates one removal/history entry.
3. A changed item quantity causes an outdated checkbox action to refresh instead of removing the revised row.
4. Remove/re-add yields a new item ID; an older browser cannot remove the replacement.
5. A retry after a dropped connection does not duplicate history. Disconnected pages recover current state after reconnecting.
6. Repeated `link` calls reuse the key and original deadline. Restarting the service does not extend or revoke it.
7. Close revokes the link for both browsers. Subsequent reads and writes fail; a new link works and the saved list remains intact.
8. The automated expiry test proves both reads and writes are rejected at the fixed four-hour deadline, including with a previously valid cookie. Do not change the VPS clock to test expiry.

Finally, ask OpenClaw over WhatsApp to show the actual grocery list and confirm its link opens the imported list. Record the deployed commit, service name, state path, exact Nginx file changed, test results, and backup path. Record no private link/session value.

## Backups, upgrades, and rollback

Use the CLI's SQLite online backup operation for database backups. A live database can have committed data in `grocery.sqlite3-wal`; copying `grocery.sqlite3` alone is not a reliable backup. Also back up `config.json` and `safety.json`, and keep all backups private because the database contains link/session state and household history. This example lets the service account create a backup in the state directory, then moves it into the administrator's private backup directory:

```sh
GROCERY_BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
sudo -u grocery /opt/family-grocery/.venv/bin/family-grocery --data-dir /var/lib/family-grocery backup --output "/var/lib/family-grocery/backup-$GROCERY_BACKUP_STAMP.sqlite3"
sudo mv "/var/lib/family-grocery/backup-$GROCERY_BACKUP_STAMP.sqlite3" /var/backups/family-grocery/
sudo install -m 0600 -o root -g root /var/lib/family-grocery/config.json "/var/backups/family-grocery/config-$GROCERY_BACKUP_STAMP.json"
sudo install -m 0600 -o root -g root /var/lib/family-grocery/safety.json "/var/backups/family-grocery/safety-$GROCERY_BACKUP_STAMP.json"
```

If you need a consistent snapshot across metadata and the database, pause metadata writers for all three operations. Schedule private backups using the host's established backup system and test restoration to a disposable directory. An export uses `family-grocery --data-dir /var/lib/family-grocery export --output-dir /path/to/new-export-directory`; the output directory must differ from the live state directory and contain no existing list/history files. Markdown exports are for inspection/interchange and are not complete database backups.

Before an upgrade, take a database backup, record the current commit, and preserve the environment/unit/Nginx files being changed. Install the approved version into the virtualenv, run the tests, restart only `family-grocery`, and repeat readiness, unauthenticated-access, and existing-route checks. The persistent state directory stays outside the checkout. Do not run legacy Markdown writers alongside the new service.

If a proxy change breaks the site, restore the saved Nginx configuration, run `nginx -t`, then reload Nginx. If the service fails, inspect `journalctl -u family-grocery.service` privately, correct the issue, and restart it. A `502` commonly means the listener is down, bound to a different port, or blocked by host security policy; check local health and logs before altering unrelated settings. An Origin error usually means the configured public URL, browser URL, or forwarded route is inconsistent.

Rollback application code to the recorded compatible release and reinstall its dependencies before restarting. If database restoration is needed, first pause **all** writers, stop the service, preserve the failed current database/WAL files, and restore the verified backup with correct ownership and permissions. Do not roll back to the Markdown-only skill against stale exports: first export the current data while writes are paused and explicitly reconcile that storage change. Restoring an old database also restores old link/session state; close any restored still-active link before reopening public access.
