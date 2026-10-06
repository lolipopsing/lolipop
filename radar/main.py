"""Lolipop — scans career sites and job boards, stores postings, notifies on Telegram.

Usage:
  python3 -m radar scan            # one scan (what GitHub runs every 15 min)
  python3 -m radar test [NAME...]  # test sources without saving anything
  python3 -m radar digest          # send the morning digest now
  python3 -m radar telegram TOKEN  # find your chat id + send a test message
"""
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from . import notify
from .details import analyze, evaluate, fill_details
from .pages import for_dashboard, scan_pages
from .classify import STRONG_TARGET, classify, country
from .sources import FETCHERS, workday_posted

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "state.json")
DASH_PATH = os.path.join(ROOT, "docs", "jobs.json")
MISSING_BEFORE_CLOSED = 3     # scans in a row without the posting before we call it closed
KEEP_CLOSED_DAYS = 30
MAX_INSTANT = 10              # above this, new offers are grouped in one message
SCHEMA = 2                    # bump when sources change a lot, to re-seed silently once


def load_config():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("dashboard_url") and os.environ.get("GITHUB_REPOSITORY"):
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
        cfg["dashboard_url"] = f"https://{owner.lower()}.github.io/{repo}/"
    return cfg


def load_companies():
    with open(os.path.join(ROOT, "companies.csv"), encoding="utf-8") as f:
        firms = [r for r in csv.DictReader(f) if r.get("name") and not r["name"].startswith("#")]
    return firms + load_searches()


def load_searches():
    """Job-board searches (LinkedIn, JobTeaser, WTTJ): one row = one query, results from many firms. See searches.csv."""
    path = os.path.join(ROOT, "searches.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("source") and not r["source"].startswith("#")]
    out = []
    for r in rows:
        query = r["query"] + (f'|{r["location"]}' if r.get("location") else "")
        label = r.get("label") or r["query"] + (f' ({r["location"]})' if r.get("location") else "")
        out.append({"name": f'{SOURCE_LABEL.get(r["source"], r["source"])} · {label}', "category": "Agrégateur", "tier": "",
                    "hq": "", "source": r["source"], "source_id": query, "source_url": "", "careers_url": "", "aggregator": True})
    return out


SOURCE_LABEL = {"linkedin": "LinkedIn", "jobteaser": "JobTeaser", "wttj": "Welcome to the Jungle"}
AGG_EVERY_MIN = {"linkedin": 60, "jobteaser": 120, "wttj": 60}  # job boards: no need to hit them every 15 min
AGG_CLOSE_DAYS = 10  # a job-board posting not seen for this long is considered closed


# ------------------------------------------------------------------ firm matching (job boards -> tracked firms)
FIRM_ALIASES = {"J.P. Morgan": ["jpmorgan", "jpmorganchase", "jpmorganchaseco"], "Bank of America": ["bankofamerica", "bofa", "bofasecurities", "merrilllynch"],
                "Citi": ["citigroup", "citibank", "citi"], "Société Générale": ["societegenerale", "sgcib", "societegeneralecib"],
                "Crédit Agricole CIB": ["creditagricolecib", "creditagricolecorporateandinvestmentbank", "cacib"], "BNP Paribas": ["bnpparibas"],
                "Natixis CIB": ["natixis", "natixiscib", "natixiscorporateinvestmentbanking"], "Rothschild & Co": ["rothschild", "rothschildco"],
                "EY": ["ey", "ernstyoung", "eyparthenon"], "PwC": ["pwc", "pricewaterhousecoopers"], "Goldman Sachs": ["goldmansachs"],
                "Morgan Stanley": ["morganstanley"], "Houlihan Lokey": ["houlihanlokey"], "Edmond de Rothschild Corporate Finance": ["edmondderothschild"],
                "Bpifrance": ["bpifrance", "bpi", "bpifrancedigital"]}
_FIRM_KEYS = None


def _compact(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s).replace("&", " ")
    s = re.sub(r"\b(and|co|the|group|groupe|sa|sas|inc|llc|ltd|limited|plc|lp|llp|ag|gmbh|se|nv|bv|corp|corporation|france|uk)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def match_firm(company, companies):
    """'BNP Paribas CIB' -> the BNP Paribas row of companies.csv (or None)."""
    global _FIRM_KEYS
    if _FIRM_KEYS is None:
        keys = []
        for c in companies:
            if not c.get("aggregator"):
                keys += [(k, c) for k in FIRM_ALIASES.get(c["name"], [_compact(c["name"])]) if len(k) >= 2]
        _FIRM_KEYS = sorted(keys, key=lambda x: -len(x[0]))
    comp, words = _compact(company), re.findall(r"[a-z0-9]+", (company or "").lower())
    for key, c in _FIRM_KEYS:
        if (comp == key or key in words) if len(key) < 5 else comp.startswith(key):
            return c
    return None


def norm_title(t):
    """'STAGE - Analyste private equity (F/H)' and 'Analyste Private Equity F/H' -> same key."""
    t = re.sub(r"\(?\b[hfm] ?/ ?[hfmx](?: ?/ ?[hfmx])?\b\)?|all genders", " ", (t or "").lower())  # H/F, (m/f/x)
    words = [w for w in re.findall(r"[a-z0-9]+", t) if w not in {"stage", "stagiaire", "internship", "intern", "cdi", "mois", "months"}]
    return " ".join(words)


def load_programmes():
    """Programmes to expect (springs...), with last year's opening date. See programmes.csv."""
    path = os.path.join(ROOT, "programmes.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("company") and not r["company"].startswith("#")]


def programme_status(programmes, jobs, companies, today, sources=None):
    """Is each expected programme open (seen by the radar), coming, or late?"""
    watched = {c["name"] for c in companies if c.get("source") in FETCHERS}
    out = []
    for p in programmes:
        rx = re.compile(p.get("keywords") or "spring|insight", re.I)
        want = "Spring / Insight" if p.get("type", "Spring") == "Spring" else p.get("type")

        def current_cycle(t):  # "2026 ... Insight Day" belongs to last year's cycle
            years = re.findall(r"20[2-3]\d", t)
            return not years or max(years) >= "2027"

        hits = [j for j in jobs.values() if j["company"] == p["company"] and not j.get("closed") and rx.search(j["title"])
                and current_cycle(j["title"]) and (j.get("cycle") == want or want == "Stage")]
        exp = _d(p.get("expected_open", ""))
        if hits:
            status = "ouverte"
        elif p["company"] not in watched:
            status = "non surveillée"
        elif exp and exp >= today:
            status = "à venir"
        elif any(v.get("fails") for k, v in (sources or {}).items() if k.split("#")[0] == p["company"]):
            status = "source indisponible"
        else:
            status = "en retard"
        best = sorted(hits, key=lambda j: j.get("posted") or j["first_seen"])[:1]
        out.append(dict(p, status=status, days=(exp - today).days if exp else None,
                        job_url=best[0]["url"] if best else "", job_title=best[0]["title"] if best else "",
                        opened=(best[0].get("posted") or (None if best[0].get("seed") else best[0]["first_seen"][:10])) if best else None))
    return out


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"initialized": False, "jobs": {}, "sources": {}, "last_digest": None}


def skey(c):
    """One firm can have several sources (e.g. Evercore US on Oleeo + Evercore London on SmartRecruiters)."""
    return f'{c["name"]}#{c["source"]}#{c.get("source_id") or c.get("source_url")}'


def source_states(state, name):
    return [v for k, v in state["sources"].items() if k.split("#")[0] == name]


def fingerprint(state):
    s = json.loads(json.dumps(state))
    for v in s["sources"].values():
        v.pop("last_ok", None)
        v.pop("raw", None)
        v.pop("suspect", None)
    return hashlib.sha1(json.dumps(s, sort_keys=True).encode()).hexdigest()


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_now(cfg):
    tz = ZoneInfo(cfg.get("timezone", "Europe/Paris")) if ZoneInfo else timezone.utc
    return datetime.now(tz)


# ------------------------------------------------------------------ fetching
def fetch_one(c):
    t0 = time.time()
    try:
        raw = FETCHERS[c["source"]](c)
        return c, True, raw, round(time.time() - t0, 1)
    except Exception as e:  # one broken site must never stop the others
        msg = f"{type(e).__name__}: {e}"[:160]
        return c, False, msg, round(time.time() - t0, 1)


def fetch_all(companies, state=None):
    """Career sites in parallel; job boards one query at a time per board (they rate-limit), and only when due."""
    active = [c for c in companies if c.get("source") in FETCHERS and not c.get("aggregator")]
    boards = {}
    for c in companies:
        if c.get("aggregator") and c.get("source") in FETCHERS:
            last = ((state or {}).get("sources", {}).get(skey(c)) or {}).get("last_ok")
            every = timedelta(minutes=AGG_EVERY_MIN.get(c["source"], 60) - 5)
            if state is None or not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - every:
                boards.setdefault(c["source"], []).append(c)

    def board_run(cs):
        out = []
        for c in cs:
            out.append(fetch_one(c))
            time.sleep(2)
        return out

    with cf.ThreadPoolExecutor(16) as ex:
        runs = [ex.submit(board_run, cs) for cs in boards.values()]
        results = list(ex.map(fetch_one, active))
        return results + [r for f in runs for r in f.result()]  # job boards last: direct sources win duplicates


# ------------------------------------------------------------------ scan
def scan():
    cfg = load_config()
    companies = load_companies()
    state = load_state()
    before = fingerprint(state)
    first_run = not state["initialized"]
    now = now_iso()
    jobs = state["jobs"]
    new = []
    primary = {}
    for c in companies:  # migrate old state keyed by firm name -> per-source key
        k = skey(c)
        primary.setdefault(c["name"], k)
        if k not in state["sources"] and primary[c["name"]] == k and c["name"] in state["sources"]:
            state["sources"][k] = state["sources"].pop(c["name"])
            state["sources"][k].pop("ever_ok", None)  # re-seed silently on its next successful scan

    # When sources change a lot (new boards, new sites), the first scan would flag old offers as new:
    # add them silently instead of flooding Telegram.
    reseed = state.get("schema") != SCHEMA
    state["schema"] = SCHEMA

    # Same posting seen on a career site and on LinkedIn / JobTeaser / WTTJ: keep one.
    titles = {(j["company"], norm_title(j["title"])): j["id"] for j in jobs.values() if not j.get("closed")}

    for c, ok, payload, secs in fetch_all(companies, state):
        name, sk = c["name"], skey(c)
        src = state["sources"].setdefault(sk, {"fails": 0})
        if not ok:
            src["fails"] = min(src.get("fails", 0) + 1, 99)
            src["error"] = payload
            print(f"  ✗ {name:40s} {payload}")
            continue
        prev = src.get("raw") or 0
        if not c.get("aggregator") and prev >= 10 and len(payload) < prev * 0.5 and src.get("suspect", 0) < 6:
            # Sudden drop (rate limit, half-loaded page...): don't trust this scan, retry next time.
            src["suspect"] = src.get("suspect", 0) + 1
            print(f"  ? {name:40s} {len(payload)} offres au lieu de ~{prev}, scan ignoré")
            continue
        src.pop("suspect", None)
        seeding = first_run or reseed or not src.get("ever_ok")
        src.update({"fails": 0, "error": None, "ever_ok": True, "last_ok": now, "raw": len(payload)})
        seen_now = set()
        agg = c.get("aggregator")
        for r in payload:
            firm = c
            if agg:  # job board: the employer is in the posting
                firm = match_firm(r.get("company", ""), companies) or {
                    "name": r.get("company") or "?", "category": "Autre", "tier": "3", "hq": ""}
            company = firm["name"]
            level, cycle, region = classify(r["title"], firm["category"], r.get("location", ""),
                                            internship=r.get("internship", False), strict=agg and firm["category"] == "Autre")
            if not level:
                continue
            jid = hashlib.sha1((f"{c['source']}|{r['key']}" if agg else f"{name}|{r['key']}").encode()).hexdigest()[:16]
            twin = titles.get((company, norm_title(r["title"])))
            if agg and twin and twin != jid:
                continue  # already known from the firm's own site (or another board)
            if not agg and twin and twin != jid and jobs.get(twin, {}).get("via"):
                jobs[twin]["closed"] = now  # the firm's own posting replaces the job-board copy
            titles[(company, norm_title(r["title"]))] = jid
            seen_now.add(jid)
            if jid in jobs:
                j = jobs[jid]
                j.update({"title": r["title"], "url": r["url"], "location": r.get("location", ""), "key": r["key"],
                          "level": level, "cycle": cycle, "region": region, "missing": 0, "last_seen": now})
                if not agg:
                    j["skey"] = sk
                if r.get("description") and "details" not in j:
                    j["details"] = analyze(clean_html(r["description"]), r["title"])
                for k in ("deadline", "event"):
                    if r.get(k):
                        j[k] = r[k]
                if r.get("posted") and not j.get("posted"):
                    j["posted"] = r["posted"]
                j.pop("closed", None)
                continue
            jobs[jid] = {
                "id": jid, "company": company, "category": firm["category"], "tier": firm["tier"], "hq": firm.get("hq", ""),
                "title": r["title"], "location": r.get("location", ""), "url": r["url"], "posted": r.get("posted"),
                "level": level, "cycle": cycle, "region": region, "source": c["source"],
                "first_seen": now, "last_seen": now, "seed": seeding, "missing": 0, "skey": sk, "key": r["key"],
            }
            if agg:
                jobs[jid]["via"] = SOURCE_LABEL.get(c["source"], c["source"])
            if r.get("description"):
                jobs[jid]["details"] = analyze(clean_html(r["description"]), r["title"])
            for k in ("deadline", "event"):
                if r.get(k):
                    jobs[jid][k] = r[k]
            if not seeding:
                new.append(jobs[jid])
        for j in jobs.values():
            if agg:
                break  # a search only shows recent postings: absence means nothing (see the job-board expiry below)
            if j.get("skey", primary.get(j["company"])) == sk and j["id"] not in seen_now and not j.get("closed"):
                j["missing"] = j.get("missing", 0) + 1
                if j["missing"] >= MISSING_BEFORE_CLOSED:
                    j["closed"] = now
        print(f"  ✓ {name:40s} {len(payload):4d} offres lues, {len(seen_now):3d} stages ({secs}s)")

    board_cutoff = (datetime.now(timezone.utc) - timedelta(days=AGG_CLOSE_DAYS)).isoformat()
    for j in jobs.values():
        if j.get("via") and not j.get("closed") and (j.get("last_seen") or j["first_seen"]) < board_cutoff:
            j["closed"] = now

    fill_posted_dates(jobs)
    fill_details(jobs)
    page_changes = scan_pages(state, now)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_CLOSED_DAYS)).isoformat()
    for jid in [k for k, j in jobs.items() if j.get("closed") and j["closed"] < cutoff]:
        del jobs[jid]
    known = {skey(c) for c in companies}
    for k in [k for k in state["sources"] if k not in known]:
        del state["sources"][k]

    if first_run:
        welcome(cfg, jobs)
        state["initialized"] = True
    else:
        instant(cfg, [j for j in new if fit(j, cfg)])
        notify_pages(cfg, page_changes)

    lt = local_now(cfg)
    if lt.hour >= cfg.get("digest_hour", 7) and state.get("last_digest") != lt.date().isoformat():
        digest(cfg, state, companies)
        state["last_digest"] = lt.date().isoformat()

    if fingerprint(state) != before or not os.path.exists(DASH_PATH):
        save(state, companies, cfg)
        print(f"État mis à jour ({len(new)} nouvelles offres).")
    else:
        print("Aucun changement.")


def clean_html(s):
    from .details import clean
    return clean(s)


def notify_pages(cfg, changes):
    if not changes:
        return
    blocks = []
    for c in changes[:8]:
        lines = "\n".join("➕ " + notify.esc(l[:160]) for l in c["added"][:3])
        if not lines:
            lines = "➖ " + notify.esc(c["removed"][0][:160])
        badge = {"ouvert": " · 🟢 candidatures ouvertes", "bientôt": " · 🟡 bientôt", "fermé": " · 🔴 fermé"}.get(c.get("status"), "")
        blocks.append(f'📄 <b>{notify.esc(c["company"])}</b> — <a href="{notify.esc(c["url"])}">{notify.esc(c["label"])}</a>{badge}\n{lines}')
    notify.send("<b>Page étudiants modifiée</b>\n\n" + "\n\n".join(blocks) + dash_link(cfg))


def fill_posted_dates(jobs, budget=300):
    """Workday lists only say "Posted 30+ Days Ago": fetch the exact date once per posting."""
    todo = [j for j in jobs.values() if j["source"] == "workday" and not j.get("posted")
            and not j.get("posted_tried") and not j.get("closed")][:budget]
    if not todo:
        return

    def one(j):
        try:
            return j, workday_posted(j["url"])
        except Exception:
            return j, None

    with cf.ThreadPoolExecutor(12) as ex:
        for j, d in ex.map(one, todo):
            j["posted_tried"] = True
            if d:
                j["posted"] = d
    print(f"  Dates de publication récupérées pour {sum(1 for j in todo if j.get('posted'))}/{len(todo)} offres Workday.")


# ------------------------------------------------------------------ messages
def dash_link(cfg):
    return f'\n\n📊 <a href="{cfg["dashboard_url"]}">Tableau de bord</a>' if cfg.get("dashboard_url") else ""


PREFERRED_REGIONS = {"Paris / France": 2, "London / UK": 2, "New York / US": 2, "Suisse": 1, "Corée / Asie": 1}


def relevance(j):
    """Higher = more interesting. Used to order messages."""
    s = {"1": 3, "2": 1}.get(j["tier"], 0) + PREFERRED_REGIONS.get(j.get("region"), 0)
    if STRONG_TARGET.search(j["title"]):
        s += 3
    if j.get("cycle") == "Spring / Insight":
        s += 2
    return s


def fit(j, cfg):
    """Does this target offer match what I'm looking for right now (config.json -> targets)?
    Springs: any country by default. Internships: chosen cycles and countries, start date in my window."""
    t = cfg.get("targets")
    if not t:
        return j["level"] in cfg.get("instant_levels", ["A"])
    if j["level"] != "A" or j.get("closed"):
        return False
    where = country(j.get("location", ""), j["title"])
    if j.get("cycle") == "Spring / Insight":
        ok = (t.get("spring") or {}).get("enabled", True)
        places = (t.get("spring") or {}).get("countries") or []
    else:
        ok = j.get("cycle") in (t.get("internship") or {}).get("cycles", ["Off-cycle", "Stage"])
        places = (t.get("internship") or {}).get("countries") or []
    if not ok or (places and where and where not in places and where != "Plusieurs pays"):
        return False
    return evaluate(dict(j, country=where), cfg.get("profile", {}))["status"] != "no"


def sort_key(j):
    return (-relevance(j), j["company"], j["title"])


def diverse(jobs, n, per_company=2):
    out, seen = [], {}
    for j in sorted(jobs, key=sort_key):
        if seen.get(j["company"], 0) < per_company:
            out.append(j)
            seen[j["company"]] = seen.get(j["company"], 0) + 1
        if len(out) == n:
            break
    return out


def welcome(cfg, jobs):
    mine = [j for j in jobs.values() if fit(j, cfg)]
    n_a = sum(1 for j in jobs.values() if j["level"] == "A" and not j.get("closed"))
    msg = (f"🍭 <b>Lolipop est activé !</b>\n{len(mine)} offres correspondent déjà à ce que tu cherches "
           f"(sur {n_a} offres ciblées ouvertes). À partir de maintenant, tu reçois chacune de ces offres dès sa publication.")
    if mine:
        msg += "\n\n<b>Déjà ouvertes (extrait) :</b>\n\n" + "\n\n".join(notify.job_line(j) for j in diverse(mine, 25))
    notify.send(msg + dash_link(cfg))


def instant(cfg, new):
    if not new:
        return
    new = sorted(new, key=sort_key)
    if len(new) <= MAX_INSTANT:
        for j in new:
            notify.send("🔥 <b>Nouvelle offre</b>\n" + notify.job_line(j))
    else:
        body = "\n\n".join(notify.job_line(j) for j in new[:30])
        more = f"\n\n… et {len(new) - 30} autres." if len(new) > 30 else ""
        notify.send(f"🔥 <b>{len(new)} nouvelles offres ciblées</b>\n\n{body}{more}{dash_link(cfg)}")


def _d(s):
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def digest(cfg, state, companies):
    lt = local_now(cfg)
    today = lt.date()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    fresh = [j for j in state["jobs"].values() if not j.get("seed") and j["first_seen"] >= since]
    mine = sorted([j for j in fresh if fit(j, cfg)], key=sort_key)
    a = sorted([j for j in fresh if j["level"] == "A" and j not in mine], key=sort_key)
    b = sorted([j for j in fresh if j["level"] == "B"], key=sort_key)
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    msg = f"🍭 <b>Lolipop du {jours[today.weekday()]} {today.strftime('%d/%m')}</b>\n"
    if mine or a or b:
        msg += f"{len(mine)} nouvelle(s) offre(s) pour toi, {len(a)} autre(s) ciblée(s) et {len(b)} autre(s) stage(s) en 24 h."
    else:
        msg += "Rien de nouveau ces dernières 24 h."
    if mine:
        msg += "\n\n<b>🎯 Pour toi</b>\n\n" + "\n\n".join(notify.job_line(j) for j in mine[:20])
    if a:
        msg += "\n\n<b>Autres offres ciblées</b> (pays, période ou cycle hors de tes critères)\n" + "\n".join("• " + notify.job_line(j, False) for j in a[:10])
    if b:
        msg += f"\n\n<i>+ {len(b)} stage(s) hors cible, visibles dans le tableau de bord.</i>"

    soon = []
    for p in programme_status(load_programmes(), state["jobs"], companies, today, state["sources"]):
        closes = _d(p.get("closes", ""))
        label = f'<b>{notify.esc(p["company"])}</b> — {notify.esc(p["program"])}'
        link = p.get("job_url") or p.get("url")
        if link:
            label = f'<a href="{notify.esc(link)}">{label}</a>'
        if closes and 0 <= (closes - today).days <= 14:
            soon.append(((closes - today).days, f"⏰ J-{(closes - today).days} · ferme le {closes.strftime('%d/%m')} · {label}"))
        elif p["status"] in ("à venir", "non surveillée") and p["days"] is not None and 0 <= p["days"] <= 7:
            soon.append((p["days"], f"🟡 attendue vers le {_d(p['expected_open']).strftime('%d/%m')} (l'an dernier : {_d(p['last_open']).strftime('%d/%m/%Y')}) · {label}"))
    for j in state["jobs"].values():
        dl = _d(j.get("deadline") or "")
        if j["level"] == "A" and not j.get("closed") and dl and 0 <= (dl - today).days <= 7:
            soon.append(((dl - today).days, f"⏰ J-{(dl - today).days} · {notify.job_line(j, False)}"))
    if soon:
        msg += "\n\n<b>Deadlines & ouvertures attendues</b>\n" + "\n".join(s for _, s in sorted(soon)[:20])

    broken = sorted({k.split("#")[0] for k, s in state["sources"].items() if s.get("fails", 0) >= 4 and not k.startswith("Nomura#")})
    if broken:
        msg += f"\n\n⚠️ {len(broken)} source(s) en panne : " + notify.esc(", ".join(broken[:12])) + ("…" if len(broken) > 12 else "")
    notify.send(msg + dash_link(cfg))


# ------------------------------------------------------------------ files
def save(state, companies, cfg):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(DASH_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=0, sort_keys=True)
    recent = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    jobs = [j for j in state["jobs"].values() if not j.get("closed") or j["closed"] >= recent]
    comp, by_name, searches = [], {}, []
    for c in companies:
        s = state["sources"].get(skey(c), {})
        if c.get("aggregator"):
            searches.append({"name": c["name"], "source": c["source"], "status": "ok" if s.get("ever_ok") and not s.get("fails")
                             else "en panne" if s.get("fails") else "en attente", "error": s.get("error"), "last_ok": s.get("last_ok"),
                             "found": sum(1 for j in jobs if j.get("skey") == skey(c) and not j.get("closed"))})
            continue
        status = ("manuel" if c.get("source") not in FETCHERS else
                  "ok" if s.get("ever_ok") and not s.get("fails") else
                  "en panne" if s.get("fails") else "en attente")
        if c["name"] in by_name:  # second source of the same firm
            e = by_name[c["name"]]
            e["source"] += " + " + c["source"]
            if status == "en panne" or e["status"] == "manuel":
                e["status"], e["error"] = status, s.get("error") or e["error"]
            continue
        e = {"name": c["name"], "category": c["category"], "tier": c["tier"], "hq": c.get("hq", ""),
             "source": c.get("source", ""), "careers_url": c.get("careers_url", ""), "status": status,
             "error": s.get("error"), "country": country(c.get("hq", "")),
             "open": sum(1 for j in jobs if j["company"] == c["name"] and not j.get("closed"))}
        by_name[c["name"]] = e
        comp.append(e)
    out = []
    for j in jobs:
        j = {k: v for k, v in j.items() if k not in ("missing", "posted_tried", "details_tried", "source", "skey", "key")}
        j["score"] = relevance(j)
        j["country"] = country(j.get("location", ""), j["title"])
        j["elig"] = evaluate(j, cfg.get("profile", {}))
        j["fit"] = fit(j, cfg)
        j["score"] += 4 if j["fit"] else 0
        # Publication date: the site's own date if known, else when the radar first saw it (unknown for launch-day offers).
        j["published"] = j.get("posted") or (None if j.get("seed") else j["first_seen"][:10])
        out.append(j)
    out.sort(key=lambda j: (j["published"] or "", j["score"]), reverse=True)
    today = local_now(cfg).date()
    with open(DASH_PATH, "w", encoding="utf-8") as f:
        json.dump({"updated": now_iso(), "jobs": out, "companies": comp, "searches": searches, "targets": cfg.get("targets"),
                   "profile": {k: v for k, v in cfg.get("profile", {}).items() if k != "nationality"},
                   "programmes": programme_status(load_programmes(), state["jobs"], companies, today, state["sources"]),
                   "pages": for_dashboard(state)},
                  f, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------ CLI helpers
def test(names):
    companies = [c for c in load_companies() if not names or any(n.lower() in c["name"].lower() for n in names)]
    results = fetch_all(companies)
    ok = 0
    for c, good, payload, secs in sorted(results, key=lambda r: r[0]["name"]):
        if not good:
            print(f"✗ {c['name']:38s} [{c['source']}] {payload}")
            continue
        ok += 1
        cls = [(classify(r["title"], c["category"], r.get("location", "")), r) for r in payload]
        a = [r for (lv, _, _), r in cls if lv == "A"]
        b = [r for (lv, _, _), r in cls if lv == "B"]
        print(f"✓ {c['name']:38s} [{c['source']}] {len(payload):4d} lues · {len(a)} ciblées · {len(b)} autres ({secs}s)")
        for r in a[:3]:
            print(f"      🎯 {r['title'][:90]}  ({r.get('location', '')[:30]})")
    print(f"\n{ok}/{len(results)} sources OK")


def telegram_setup(token):
    from .http import get_json
    me = get_json(f"https://api.telegram.org/bot{token}/getMe")["result"]
    print(f"Bot trouvé : @{me['username']}")
    ups = get_json(f"https://api.telegram.org/bot{token}/getUpdates")["result"]
    chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "") for u in ups if "message" in u}
    if not chats:
        print("Aucun message reçu : ouvre ton bot dans Telegram, appuie sur « Démarrer » (ou envoie-lui « salut »), puis relance cette commande.")
        return
    for cid, who in chats.items():
        print(f"\n➡️  TELEGRAM_CHAT_ID = {cid}   ({who})")
        os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"] = token, str(cid)
        notify.send("✅ Lolipop est bien connecté à ton Telegram !")
    print("\nMessage de test envoyé. Copie ce numéro, il servira pour GitHub.")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "scan"
    if cmd == "scan":
        scan()
    elif cmd == "test":
        test(argv[2:])
    elif cmd == "digest":
        cfg, state = load_config(), load_state()
        digest(cfg, state, load_companies())
    elif cmd == "telegram" and len(argv) > 2:
        telegram_setup(argv[2])
    else:
        print(__doc__)
