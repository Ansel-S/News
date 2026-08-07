# geoip

Generates China IP routing lists (Clash ruleset + ipset rules) from
[misakaio/chnroutes2](https://github.com/misakaio/chnroutes2), for routing
traffic around China's network restrictions.

**Unrelated to the newsletter system in the rest of this repo** — no shared
code, schedule, or dependencies. It lives here for convenience (one repo,
one Actions dashboard), not because it's functionally part of dewsletter.

## Output

Running `generate.sh` writes to `dist/`:

| File | Format |
|------|--------|
| `cn-ipv4.txt` / `cn-ipv6.txt` | Raw CIDR list, one per line |
| `clash-ruleset.list` | `IP-CIDR,...` / `IP-CIDR6,...` rules for Clash |
| `chnroute.ipset` / `chnroute6.ipset` | `ipset` create + add commands |

`dist/` is gitignored — it's never committed to `main`. The
`geoip-update.yml` workflow runs hourly, regenerates it, and force-pushes
just those five files to a dedicated orphan `release` branch (wiping
whatever was there before) — so `release` always holds only the latest
snapshot, decoupled from this repo's actual commit history.

## Running locally

```bash
cd geoip
bash generate.sh
```

Requires `curl`. No other dependencies — this is a plain bash script,
unlike the rest of the repo (Python).
