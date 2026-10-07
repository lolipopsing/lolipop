"""Finance networking events: bank events (TrackR, career sites), Luma and Eventbrite in France.

Collected every few hours, kept in state["events"], shown in the dashboard "Events" tab, and sent on
Telegram once a day at most (config.json -> events_hour). Only upcoming events are kept.
"""
import concurrent.futures as cf
import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from .http import get_json, get_text

I = re.I

# What makes an event worth a student's evening: deal / finance careers, or where bankers and investors go.
FINANCE = re.compile(
    r"m ?& ?a\b|fusions?[- ]acquisitions?|mergers|investment bank|banque d.(affaires|investissement)|\bibd?\b"
    r"|private equity|capital[- ]investissement|\blbo\b|buy[- ]?out|venture capital|\bvc\b|capital[- ]risque|lev[ée]e de fonds"
    r"|fundraising|business angel|corporate finance|finance d.entreprise|dette priv|private (debt|credit|markets)|leveraged"
    r"|asset management|gestion d.actifs|investisseurs?|investors?|march[ée]s? (financiers|de capitaux)|capital markets"
    r"|\bcfa\b|fintech|restructuring|transaction services|due diligence|valuation|[ée]valuation d.entreprise|family office"
    r"|banking|banque|finance", I)
STRONG = re.compile(r"m ?& ?a\b|fusions?[- ]acquisitions?|investment bank|banque d.affaires|private equity|capital[- ]investissement"
                    r"|\blbo\b|venture capital|corporate finance|dette priv|private (debt|credit)|restructuring|banking", I)
NETWORKING = re.compile(r"network|r[ée]seau|afterwork|after[- ]work|ap[ée]ro|cocktail|rencontre|meet ?up|forum|salon|career|carri[eè]re"
                        r"|recrut|job ?dating|table ronde|panel|conf[ée]rence|summit|sommet|masterclass|insight|open (house|day)"
                        r"|coffee chat|petit[- ]d[ée]jeuner|breakfast|soir[ée]e|evening|workshop|atelier|webinar|students?|[ée]tudiants?", I)
OFF_TOPIC = re.compile(r"finance personnelle|personal finance|libert[ée] financi|financial freedom|ind[ée]pendance financi|crypto|bitcoin"
                       r"|forex|day ?trading|trading (de|pour) d[ée]butants|immobilier locatif|investissement locatif|retraite|patrimoine"
                       r"|d[ée]fiscalis|whisky|vin\b|wine|yoga|danse|dance|bar crawl|speed dating|comedy|spectacle|concert|vernissage"
                       r"|paie\b|payroll|comptabilit[ée] (de|pour) (tpe|ind[ée]pendant)|auto[- ]entrepreneur|micro[- ]entreprise"
                       r"|cr[ée]ation d.entreprise|pr[eê]t bancaire|mlm|marketing de r[ée]seau|scpi|financer (son|votre|ton) projet"
                       r"|budget|fiscalit|pr[ée]visionnel|d[ée]lais de paiement|mode d.emploi|surendett|tr[ée]sorerie (de|des) (tpe|pme)", I)
# Open platforms (Luma, Eventbrite): "finance" alone is too vague, the event must be about deals, investors or markets.
PRO = re.compile(r"investisseurs?|investors?|fintech|venture|\bvc\b|asset management|gestion d.actifs|march[ée]s financiers"
                 r"|capital markets|family office|\bcfa\b|dette|debt|banque d.affaires|finance (de march|d.entreprise)"
                 r"|place financi|fundrais|lev[ée]e de fonds|business angel", I)
OFF_ROLE = re.compile(r"\baudit|compliance|risk|technology|engineer|quant|software|\bhr\b|operations|actuar|insurance|consulting", I)
FAR = re.compile(r"chicago|toronto|menlo park|san francisco|new york|houston|los angeles|boston|atlanta|dallas|washington|minneapolis"
                 r"|universit|\bucla\b|\busc\b|\bnyu\b|wharton|harvard|columbia|stanford|cornell|upenn|notre dame|indiana|michigan"
                 r"|yale|princeton|georgetown|duke|veteran", I)

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _iso(s):
    return (s or "")[:10] or None


def _loose_date(txt):
    """TrackR free text: '20 Oct 26', '9 Oct 2026', 'April 2027' (-> 1st of month), 'Oct - Nov' -> None."""
    t = (txt or "").strip()
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{2,4})$", t)
    if m and m.group(2).lower()[:3] in MONTHS:
        y = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        try:
            return date(y, MONTHS[m.group(2).lower()[:3]], int(m.group(1))).isoformat()
        except ValueError:
            return None
    m = re.match(r"([A-Za-z]{3})[a-z]*\s+(\d{4})$", t)
    if m and m.group(1).lower()[:3] in MONTHS:
        return date(int(m.group(2)), MONTHS[m.group(1).lower()[:3]], 1).isoformat()
    return None


def _eid(source, key):
    return hashlib.sha1(f"{source}|{key}".encode()).hexdigest()[:16]


# ----------------------------------------------------------------- sources
def trackr_events(region="UK", season="2027"):
    d = get_json(f"https://api.the-trackr.com/programmes?region={region}&industry=Finance&season={season}&type=events")
    today = date.today().isoformat()
    out = []
    for p in d.get("programmes", []):
        closes = _iso(p.get("closingDate"))
        when = _loose_date(p.get("eventDate"))
        if (closes and closes < today) or (when and when < today):
            continue
        online = (p.get("format") or "").lower() in ("remote", "virtual", "online")
        out.append({"id": _eid("trackr", p["id"]), "source": "TrackR", "title": p.get("name", ""),
                    "org": (p.get("company") or {}).get("name") or p.get("companyId") or "",
                    "date": when, "date_text": p.get("eventDate") or "", "register_by": closes,
                    "city": "" if online else ("Londres" if region == "UK" else region), "country": "" if online else region,
                    "online": online, "free": True,  # firm-hosted student events are free
                    "url": re.sub(r"[?&]utm_[^&]+", "", p.get("url") or "") or "https://app.the-trackr.com/uk-finance/events",
                    "restriction": p.get("eligibility") or None, "kind": "Événement de recrutement"})
    return out


LUMA_PLACES = {"Paris": "discplace-NdLrh1xJfeotJZC"}
LUMA_QUERIES = ["finance", "private equity", "venture capital", "M&A", "investment banking", "fintech", "investisseurs"]


def luma():
    out = {}
    for city, place in LUMA_PLACES.items():
        for q in LUMA_QUERIES:
            d = get_json(f"https://api.lu.ma/discover/get-paginated-events?discover_place_api_id={place}"
                         f"&pagination_limit=50&query={quote(q)}")
            for e in d.get("entries", []):
                ev = e.get("event") or {}
                geo = ev.get("geo_address_info") or {}
                ticket = e.get("ticket_info") or {}
                hosts = ", ".join(h.get("name", "") for h in (e.get("hosts") or [])[:2] if h.get("name"))
                out[ev.get("api_id") or ev.get("url")] = {
                    "id": _eid("luma", ev.get("api_id") or ev.get("url")), "source": "Luma", "title": ev.get("name", ""),
                    "org": (e.get("calendar") or {}).get("name") or hosts, "date": _iso(ev.get("start_at")),
                    "time": (ev.get("start_at") or "")[11:16], "city": geo.get("city") or city, "country": "France",
                    "online": ev.get("location_type") == "online", "free": ticket.get("is_free"),
                    "url": "https://lu.ma/" + (ev.get("url") or ""), "summary": "", "kind": ""}
    return list(out.values())


EVENTBRITE_SLUGS = ["finance", "private-equity", "venture-capital", "fintech", "investment-banking"]


def eventbrite():
    out = {}
    for slug in EVENTBRITE_SLUGS:  # one at a time: Eventbrite answers 429 when hit in parallel
        for page in (1,):
            time.sleep(2)
            h = get_text(f"https://www.eventbrite.fr/d/france/{slug}--events/?page={page}")
            i = h.find("window.__SERVER_DATA__ = ")
            if i < 0:
                break
            d = json.JSONDecoder().raw_decode(h[i + len("window.__SERVER_DATA__ = "):])[0]
            for e in d["search_data"]["events"]["results"]:
                if e.get("is_cancelled"):
                    continue
                venue = (e.get("primary_venue") or {}).get("address") or {}
                tags = " ".join(t.get("display_name", "") for t in e.get("tags") or [])
                out[e["id"]] = {"id": _eid("eventbrite", e["id"]), "source": "Eventbrite", "title": e.get("name", ""),
                                "org": "", "date": e.get("start_date"), "time": (e.get("start_time") or "")[:5],
                                "city": venue.get("city") or "", "country": venue.get("country") or "FR",
                                "online": bool(e.get("is_online_event")), "free": None, "url": e.get("url", "").split("?")[0],
                                "summary": e.get("summary") or "", "kind": tags}
    return list(out.values())


def eventbrite_price(ev):
    """Free or not: only on the event page."""
    page = get_text(ev["url"])
    m = re.search(r'"isFree":\s*(true|false)', page)
    ev["free"] = (m.group(1) == "true") if m else None
    org = re.search(r'"organizer":\s*\{[^{}]*?"name":\s*"([^"]+)"', page)
    if org:
        ev["org"] = org.group(1)


def from_postings(jobs):
    """Events posted on the banks' own career sites (Oleeo open houses, coffee chats, webinars...)."""
    from .classify import EVENT
    out = []
    today = date.today().isoformat()
    for j in jobs.values():
        if j.get("closed") or j.get("via") or not EVENT.search(j.get("title", "")):
            continue
        when = j.get("event")
        if when and when < today:
            continue
        loc = j.get("location", "")
        online = bool(re.search(r"virtual|virtuel|online|en ligne|remote|webinar", j["title"] + " " + loc, I))
        out.append({"id": _eid("posting", j["id"]), "source": "Site de la boîte", "title": j["title"], "org": j["company"],
                    "date": when, "register_by": j.get("deadline"), "city": loc, "country": "", "online": online,
                    "free": True, "url": j["url"], "kind": "Événement de recrutement"})
    return out


# ----------------------------------------------------------------- scoring
def score(ev, firms):
    """Relevance for an M&A / PE student: deal words, a tracked firm, networking format, France / online, free."""
    text = f'{ev["title"]} {ev.get("summary", "")} {ev.get("kind", "")} {ev.get("org", "")}'
    s = 0
    if STRONG.search(text):
        s += 3
    elif FINANCE.search(text):
        s += 1
    if ev.get("org") in firms or ev["source"] in ("TrackR", "Site de la boîte"):
        s += 3
    if NETWORKING.search(text):
        s += 2
    if ev.get("free"):
        s += 1
    if ev.get("online") or (ev.get("country") or "").upper() in ("FR", "FRANCE"):
        s += 1
    if OFF_ROLE.search(ev["title"]):
        s -= 3
    return s


def relevant(ev):
    text = f'{ev["title"]} {ev.get("summary", "")} {ev.get("kind", "")}'
    if ev["source"] == "TrackR":
        return True
    if ev["source"] == "Site de la boîte":  # US campus coffee chats are not for me; virtual sessions are
        return not FAR.search(ev["title"] + " " + ev.get("city", "")) and bool(
            ev.get("online") or re.search(r"paris|france|london|londres", ev.get("city", ""), I))
    return bool(STRONG.search(text) or PRO.search(text)) and not OFF_TOPIC.search(text)


def reachable(ev):
    """Somewhere I can go: in France, or online."""
    return ev.get("online") or (ev.get("country") or "").upper() in ("FR", "FRANCE")


# ----------------------------------------------------------------- collect / store
def collect(state, firms, now_iso):
    """Refresh state["events"]. Returns the number of events read (for the log)."""
    store = state.setdefault("events", {})
    found, errors = [], []
    jobs = [("TrackR", trackr_events), ("Luma", luma), ("Eventbrite", eventbrite)]
    with cf.ThreadPoolExecutor(3) as ex:
        for name, res in zip([n for n, _ in jobs], ex.map(lambda f: _safe(f[1]), jobs)):
            if isinstance(res, Exception):
                errors.append(f"{name}: {type(res).__name__}: {res}"[:160])
            else:
                found += res
    found += from_postings(state.get("jobs", {}))
    fresh = [e for e in found if relevant(e) and e["id"] not in store]
    todo = [e for e in fresh if e["source"] == "Eventbrite"][:25]
    for e in todo:  # price is only on the event page; new events only, gently
        _safe(lambda: eventbrite_price(e))
        time.sleep(1.5)
    seen = {e["id"] for e in found}
    for e in found:
        if not relevant(e):
            continue
        old = store.get(e["id"])
        e["score"] = score(e, firms)
        e["first_seen"] = old["first_seen"] if old else now_iso
        if old and e.get("free") is None:
            e["free"] = old.get("free")
            e["org"] = e.get("org") or old.get("org", "")
        store[e["id"]] = e
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    for k in [k for k, e in store.items() if (e.get("date") and e["date"] < yesterday)
              or (e.get("register_by") and e["register_by"] < yesterday and k not in seen)]:
        del store[k]
    state["events_errors"] = errors
    for err in errors:
        print("  ✗ événements", err)
    print(f"  Événements : {len(found)} lus, {len(store)} à venir gardés.")
    return len(found)


def _safe(f):
    try:
        return f()
    except Exception as e:  # one broken site must never stop the others
        return e


NOTIFY_MIN_SCORE = 5


def worth_notifying(ev):
    return reachable(ev) and ev.get("score", 0) >= NOTIFY_MIN_SCORE and ev.get("free") is not False


def upcoming(state):
    out = [e for e in state.get("events", {}).values()]
    return sorted(out, key=lambda e: (e.get("date") or "9999", -e.get("score", 0)))
