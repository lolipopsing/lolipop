"""Investment banking news: deals (closed, signed, in process), senior moves (MD, partners, heads) and
policy / regulation that moves the banks.

Read every hour from Google News searches (topics + the firms followed by Lolipop) and a few free trade
feeds, kept 21 days in state["news"], written to docs/news.json for the dashboard "Actu" tab and sent on
Telegram once a day (config.json -> news_hour).
"""
import hashlib
import html
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from .http import get_text

I = re.I
KEEP_DAYS = 21
MAX_ITEMS = 1500


def gnews(q, lang="en"):
    loc = {"en": "hl=en-GB&gl=GB&ceid=GB:en", "us": "hl=en-US&gl=US&ceid=US:en", "fr": "hl=fr&gl=FR&ceid=FR:fr"}[lang]
    return f"https://news.google.com/rss/search?q={quote(q)}&{loc}"


# (topic, language, Google News query). "when:" keeps the feed fresh.
TOPICS = [
    ("deal", "en", '("financial adviser" OR "financial advisor" OR "advised by") (acquisition OR merger OR sale) when:2d'),
    ("deal", "us", '("financial advisor" OR "exclusive financial advisor") (acquire OR merger OR "definitive agreement") when:2d'),
    ("deal", "en", '("agreed to buy" OR "agreed to acquire" OR "takeover bid" OR "take private" OR "buyout") billion when:2d'),
    ("deal", "en", '("exploring a sale" OR "explores sale" OR "weighs sale" OR "in talks to buy" OR "sale process" OR "hires advisers") when:3d'),
    ("deal", "en", '("private equity" OR "buyout firm") (acquire OR "agreed to buy" OR "sells" OR "exit") when:2d'),
    ("deal", "en", '(IPO OR "initial public offering") (prices OR "files for" OR "plans") (London OR "New York" OR Paris OR Amsterdam) when:2d'),
    ("deal", "fr", '(rachat OR acquisition OR cession OR fusion) ("banque d\'affaires" OR "conseil financier" OR "conseillé par" OR "conseils") when:3d'),
    ("deal", "fr", '(LBO OR "fonds d\'investissement" OR "capital-investissement") (rachète OR "entre au capital" OR cède OR "prend le contrôle") when:3d'),
    ("deal", "fr", '("négociations exclusives" OR "offre publique d\'achat" OR "entre en négociations") (rachat OR cession OR acquisition) when:3d'),
    ("talent", "en", '("managing director" OR partner OR "co-head" OR "head of") (joins OR hires OR appoints OR poaches OR "named") ("investment bank" OR "M&A" OR "dealmaker") when:4d'),
    ("talent", "us", '(hires OR joins OR appoints OR promotes) ("managing director" OR "partner") ("investment banking" OR "M&A" OR restructuring OR "private equity") when:4d'),
    ("talent", "en", '(dealmaker OR banker OR "rainmaker") (leaves OR departs OR quits OR "steps down" OR poached) when:4d'),
    ("talent", "fr", '(nommé OR nommée OR rejoint OR recrute OR "nomination") ("banque d\'affaires" OR "fusions-acquisitions" OR "associé gérant" OR "managing director" OR "capital-investissement") when:7d'),
    ("policy", "en", '(banks OR "investment banks" OR lenders) (regulation OR "capital rules" OR "Basel" OR regulator OR supervisor) when:2d'),
    ("policy", "en", '("Federal Reserve" OR ECB OR "Bank of England") (banks OR rates OR "rate cut" OR "rate decision") when:1d'),
    ("policy", "en", '(antitrust OR "competition authority" OR CMA OR FTC OR "European Commission") (merger OR deal OR takeover) (blocks OR approves OR probe OR review) when:3d'),
    ("policy", "en", '(tariffs OR election OR government OR "tax") (dealmaking OR "M&A" OR "investment banks" OR "Wall Street") when:3d'),
    ("policy", "fr", '("banques françaises" OR "banques européennes" OR "secteur bancaire" OR "banques d\'affaires") (BCE OR régulation OR "Bâle" OR taxe OR surtaxe OR gouvernement OR ACPR OR AMF) when:3d'),
    ("policy", "fr", '("Autorité de la concurrence" OR "Commission européenne" OR "contrôle des investissements étrangers") (rachat OR fusion OR acquisition OR OPA) when:4d'),
]

# Free trade feeds (RSS) that do not need a subscription.
FEEDS = [
    ("PE Hub", "https://www.pehub.com/feed/"),
    ("Private Equity Wire", "https://www.privateequitywire.co.uk/feed"),
    ("finews", "https://www.finews.com/news/english-news?format=feed&type=rss"),
]

# How firms are written in headlines (when the companies.csv name is not how the press says it).
ALIASES = {
    "J.P. Morgan": [r"J\.? ?P\.? ?Morgan", r"JPMorgan"], "Bank of America": [r"Bank of America", r"BofA", r"Merrill Lynch"],
    "Citi": [r"Citi(group|bank)?"], "Société Générale": [r"Soci[ée]t[ée] G[ée]n[ée]rale", r"SocGen", r"SG CIB"],
    "Crédit Agricole CIB": [r"Cr[ée]dit Agricole", r"CA[- ]CIB"], "BNP Paribas": [r"BNP( Paribas)?"], "Natixis CIB": [r"Natixis"],
    "Rothschild & Co": [r"(?<!de )Rothschild"], "Goldman Sachs": [r"Goldman( Sachs)?"], "Morgan Stanley": [r"Morgan Stanley"],
    "Deutsche Bank": [r"Deutsche Bank"], "Houlihan Lokey": [r"Houlihan"], "Perella Weinberg Partners": [r"Perella( Weinberg)?"],
    "Moelis & Company": [r"Moelis"], "PJT Partners": [r"PJT"], "Centerview Partners": [r"Centerview"], "Zaoui & Co": [r"Zaoui"],
    "Messier & Associés": [r"Messier (& Associ|et Associ|Maris)"], "Apollo": [r"Apollo (Global|Management|-backed|Funds)", r"Apollo's"],
    "Ares Management": [r"Ares (Management|Capital|-backed)"], "Advent International": [r"Advent International", r"Advent-backed"],
    "Bain Capital": [r"Bain Capital"], "CVC Capital Partners": [r"\bCVC\b"], "Edmond de Rothschild Corporate Finance": [r"Edmond de Rothschild"],
    "EY": [r"\bEY\b", r"Ernst & Young", r"EY-Parthenon"], "PwC": [r"\bPwC\b"], "KPMG": [r"\bKPMG\b"], "Deloitte": [r"Deloitte"],
    "General Atlantic": [r"General Atlantic"], "Hg": [r"\bHg(Capital)?\b(?! ?\d)"], "ICG": [r"\bICG\b", r"Intermediate Capital"],
    "TPG": [r"\bTPG\b"], "EQT": [r"\bEQT\b(?! Corp)"], "Blue Owl": [r"Blue Owl"], "Sixth Street": [r"Sixth Street"],
    "Oaktree Capital": [r"Oaktree"], "HPS Investment Partners": [r"\bHPS\b"], "Brookfield": [r"Brookfield"],
}
# Names too generic to be matched on their own.
GENERIC = {"citi", "ey", "apollo", "advent", "ares", "hg", "icg", "tpg", "eqt", "hps", "partners", "capital", "group", "bank", "advisory",
           "investment", "investments", "finance", "corporate", "equity", "global", "first", "national", "royal",
           # common words, places or surnames: "Lincoln City", "Cathay Pacific", "Elliott"... need the full firm name
           "allen", "antares", "atout", "cambon", "carmine", "cathay", "cavendish", "clearwater", "crescent", "eight", "elliott", "evelyn",
           "exponent", "fidelity", "hahn", "impulse", "inspirit", "invest", "latour", "lexington", "lincoln", "linkers", "matin", "monroe",
           "montfort", "nordic", "ohana", "omnes", "raine", "reggio", "rochefort", "solomon", "spin-off", "trianon", "trium", "verdier",
           "wagram", "weinberg", "samsung", "twinl", "adviso", "activa", "chami", "montefiore", "searchlight", "arma", "ondra"}
SUFFIX = re.compile(r"\s*(&\s*(co\.?|company|cie|associés)|partners|capital( partners| management)?|group|groupe|international"
                    r"|management|investment partners|investments?|cib|corporate finance|securities|advisors?|advisory|sa|ag|plc|llc|inc\.?)$", I)

KIND_WORDS = {
    "talent": re.compile(r"\b(hires?|hired|hiring|joins?|joined|appoint|appoints|appointed|names?|named|promot\w+|poach\w*|recruit\w*"
                         r"|departs?|leaves|quits|exits|steps? down|retires?|nomm[ée]e?s?|nomination|rejoint|recrute|arriv[ée]e|quitte"
                         r"|co-head|new head|chairman of)\b", I),
    "policy": re.compile(r"\b(regulat\w+|regulators?|basel|b[âa]le|capital rules|capital requirements?|stress tests?|supervis\w+"
                         r"|federal reserve|\bfed\b|ecb|bce|bank of england|boe|rate (cut|hike|decision)|interest rates?|taux"
                         r"|tariffs?|droits de douane|antitrust|competition (authority|watchdog)|autorit[ée] de la concurrence"
                         r"|\bcma\b|\bftc\b|\bdoj\b|\bsec\b|\bfca\b|\bamf\b|\bacpr\b|european commission|commission europ[ée]enne"
                         r"|brussels|bruxelles|tax|taxe|imp[ôo]t|budget|government|gouvernement|minist\w+|law|loi|sanctions?"
                         r"|election|[ée]lection|white house|treasury|congress|parliament|parlement|trump|mifid|ban on)\b", I),
    "deal": re.compile(r"\b(acqui\w+|merg\w+|buys?|bought|buyout|takeover|take[- ]private|bid|bids|offer for|deal|stake|sale|sells?|sold"
                       r"|divest\w*|spin[- ]?off|carve[- ]?out|ipo|listing|flotation|lbo|rach[eè]te|rachat|c[èe]de|cession|fusion"
                       r"|prise de (participation|contr[ôo]le)|entre au capital|opa|introduction en bourse|refinanc\w+|financing"
                       r"|raises?|fund close|closes fund|valuation|advis\w+|conseil\w*|mandat\w*|exit|strategic review|transaction|m ?& ?a|scoops? up|snaps? up|swoops?|rach[eè]te|s.offre)\b", I),
}
STAGE = [  # deals only: where the deal stands
    ("Abouti", re.compile(r"\b(complete[sd]?|completion|closes|closed|closing of|finalis\w+|finaliz\w+|r[ée]alis[ée]e?|wraps up|seals?|sealed"
                          r"|conclut|boucl[ée]e?|concluded|autorise|approves?|cleared|feu vert)\b", I)),
    ("En process", re.compile(r"\b(talks|explor\w+|weighs?|weighing|consider\w*|mulls?|mulling|sale process|auction|shortlist\w*|bidders?"
                              r"|hires? (advisers|advisors|banks)|taps|mandate[sd]?|could|may|might|plans?|prepar\w+|seeks?|sounding|eyes|preliminary"
                              r"|race for|crumbles|collapses?|en discussions?|pourparlers|[ée]tudie|envisage\w*|cherche|r[ée]fl[ée]chit|pourrait"
                              r"|en vue de|sur le point|s.appr[êe]te)\b", I)),
    ("Signé / annoncé", re.compile(r"\b(agree[sd]?|agreement|to (acquire|buy|merge|sell)|signs?|signed|announces?|annonce|unveils?|offered|offers? for"
                                   r"|takeover bid|bid for|n[ée]gociations exclusives|exclusive talks|definitive|accepts?|recommended (offer|bid)"
                                   r"|launch(es)? (a |an )?(bid|offer)|rach[eè]te|acquires|buys|sells|c[èe]de|acquiert|s'offre|met la main|strikes)\b", I)),
]
FINANCE = re.compile(r"\b(bank\w*|banque\w*|m ?& ?a|merger|acqui\w+|deal\w*|private equity|buyout|lbo|capital|fund\w*|fonds|invest\w+"
                     r"|ipo|bourse|stock exchange|financ\w+|lender|credit|cr[ée]dit|dette|debt|advis\w+|conseil|wall street|city of london"
                     r"|regulat\w+|takeover|stake|valuation|rachat|cession|fusion)\b", I)
JUNK = re.compile(r"price target|shares? (of|rise|rises|fall|falls|jump|jumps|drop|drops|gain|gains|slide|slides|sink|surge)"
                  r"|stock (rises|falls|jumps|drops|price)|should you buy|buy rating|sell rating|upgrade[sd]? |downgrade[sd]? "
                  r"|(acquires|buys|sells|trims|boosts|lifts|cuts|raises) (new )?(position|stake|holdings?) in|position in|holdings in"
                  r"|shares sold by|shares bought by|insider|13f|dividend|earnings (call|preview|beat|miss)|quarterly results?"
                  r"|\bq[1-4]\b (results|earnings)|crypto|bitcoin|ethereum|horoscope|football|soccer|nba|nfl|transfer window|mercato"
                  r"|real estate agent|mortgage rates today|savings account|cd rates|credit card|comment acheter|how to buy|que faire ?\?"
                  r"|faut-il (acheter|vendre)|investir dans|taux d.(int[ée]r[êe]t|emprunt)s? (sur|des|en)|cr[ée]dit immobilier|[ée]pargne|livret"
                  r"|comptes? (courant|d.[ée]pargne)|vietnam|recommandation .?acheter|objectif de cours|city fc|defender|striker|midfielder", I)
# Untagged headlines must be clearly about deals, dealmakers or bank policy.
STRONG = re.compile(r"\b(m ?& ?a|mergers? and acquisitions|fusions?[- ]acquisitions?|private equity|capital[- ]investissement|buyout|lbo"
                    r"|takeover|take[- ]private|acqui\w+|rachat|rach[eè]te|c[èe]de|cession|opa|offre publique|investment bank\w*"
                    r"|banque d.affaires|dealmak\w+|bankers?|banquiers?|wall street|the city|banks?|banques?|lenders?|private credit"
                    r"|dette priv[ée]e|leveraged|refinanc\w+|advis(er|or)s?|conseils?)\b", I)
JUNK_SOURCES = re.compile(r"marketbeat|defense world|etf daily news|the motley fool|zacks|simply wall st|ainvest|tickerreport"
                          r"|stocktitan|modern readers|the lincolnian|thecerbatgem|baseball|sports", I)
BIG = re.compile(r"\b\d+([.,]\d+)? ?(bn|billion|milliards?|md ?€|mds?|trillion)\b|\$\d+([.,]\d+)? ?b\b|€\d+([.,]\d+)? ?b\b", I)
SENIOR = re.compile(r"managing director|\bmd\b|partner|associ[ée]|co-head|head of|chair|ceo|vice[- ]chair|president|global head|directeur", I)


def _clean(s):
    s = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", s or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def norm(s):
    s = re.sub(r"[^a-z0-9àâäçéèêëîïôöûüœ ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def tokens(s):
    return {w for w in norm(s).split() if len(w) > 2}


STOP_PROPER = {"the", "to", "for", "in", "of", "and", "deal", "deals", "billion", "million", "buy", "buys", "acquire", "acquires", "agrees",
               "agreed", "sale", "update", "report", "reports", "exclusive", "breaking", "market", "chatter", "new", "how", "why", "what",
               "with", "from", "after", "its", "his", "her", "joins", "hires", "names", "appoints", "says", "group", "partners", "capital",
               "bank", "banks", "fund", "funds", "les", "des", "une", "pour", "dans", "sur", "avec", "rachat", "rachète",
               "senior", "managing", "director", "directors", "head", "heads", "chief", "officer", "president", "presidents", "chair",
               "chairman", "vice", "global", "team", "group", "investment", "banking", "join", "joining", "former", "veteran", "expand",
               "expands", "names", "named", "appointed", "partner", "co-head", "europe", "european", "london", "paris", "york", "billion"}


def proper(title, firms):
    """Distinctive names in a headline (targets, people), minus the firms already tagged."""
    firm_words = {w for f in firms for w in norm(f).split()}
    return {w for w in (norm(x) for x in re.findall(r"\b[A-Z][\w'’.-]{2,}", title))
            if w not in STOP_PROPER and w not in firm_words and w not in FIRST_NAMES and len(w) >= 4}


def same_story(a, b):
    if a["firms"] and set(a["firms"]) & set(b["firms"]):
        shared = a["proper"] & b["proper"]
        if shared:
            return True
    if len(a["proper"] & b["proper"]) >= 2 and len(a["tk"] & b["tk"]) / max(1, len(a["tk"] | b["tk"])) >= 0.35:
        return True
    return a["tk"] and len(a["tk"] & b["tk"]) / len(a["tk"] | b["tk"]) >= 0.6


def parse_rss(text, default_source=""):
    out = []
    for it in re.findall(r"<item\b.*?</item>", text, re.S):
        g = lambda tag: (re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1]
        title, link, pub = _clean(g("title")), _clean(g("link")), _clean(g("pubDate"))
        source = _clean(g("source")) or default_source
        if source and title.endswith(" - " + source):  # Google News: "Headline - Publisher"
            title = title[: -len(source) - 3].strip()
        elif not source and " - " in title:
            title, source = title.rsplit(" - ", 1)
        try:
            when = parsedate_to_datetime(pub).astimezone(timezone.utc).replace(microsecond=0).isoformat()
        except Exception:
            when = None
        if title and link:
            out.append({"title": title, "url": link, "source": source, "published": when})
    return out


def firm_patterns(companies):
    """[(firm name, tier, category, compiled regex)] for every firm followed by Lolipop."""
    rows, seen = [], set()
    for c in companies:
        if not c.get("aggregator") and c["name"] not in seen:
            seen.add(c["name"])
            rows.append(c)
    taken = {norm(re.sub(r"[\\()?|]", "", p)) for c in rows for p in ALIASES.get(c["name"], [])} | {norm(c["name"]) for c in rows}
    out = []
    for c in rows:
        name = c["name"]
        pats = ALIASES.get(name)
        if not pats:
            core = SUFFIX.sub("", name).strip() or name
            # too short, ambiguous, or another firm's name ("Natixis Partners" vs Natixis): full name only
            if core.lower() in GENERIC or len(core) < 4 or (core != name and norm(core) in taken):
                core = name
            pats = [re.escape(core)]
        out.append((name, c.get("tier", "3"), c.get("category", ""), re.compile(r"(?<![\w-])(" + "|".join(pats) + r")(?![\w])")))
    return out


FIRST_NAMES = set("""robert david john michael james william richard thomas charles daniel matthew mark paul steven andrew peter george
edward chris christopher brian kevin jason jeff jeffrey scott eric stephen tim timothy ryan jacob gary nicholas jonathan larry frank
henry patrick jack dennis jerry tyler aaron adam nathan douglas zach peter harry oliver alex alexander sam samuel ben benjamin luke
tom simon martin philip phil anthony tony joe joseph max lucas hugo louis jean pierre jacques michel françois francois nicolas antoine
olivier philippe alain bernard christophe laurent julien sébastien sebastien guillaume thierry vincent mary patricia jennifer linda
elizabeth barbara susan jessica sarah karen nancy lisa emma emily anna sophie marie claire julie camille laura anne catherine""".split())


def _person(title, start):
    """'Robert Carlyle', 'David Wendel': the firm name is someone's surname."""
    prev = re.search(r"([A-Za-zÀ-ÿ]+) $", title[:start])
    return bool(prev) and prev.group(1).lower() in FIRST_NAMES


def tag_firms(title, patterns):
    hits = [(n, t, cat, m.span()) for n, t, cat, rx in patterns for m in [rx.search(title)] if m and not _person(title, m.start())]
    # "Weinberg Capital" inside "Perella Weinberg": keep the longer match only
    keep = [h for h in hits if not any(o is not h and o[3][0] <= h[3][0] and h[3][1] <= o[3][1] and o[3] != h[3] for o in hits)]
    return [(n, t, cat) for n, t, cat, _ in keep]


HIRE_VERB = re.compile(r"\b(hires?|hired|appoints?|appointed|names|named|joins?|joined|poach\w*|promot\w+|taps \w+ \w+ (to|as)|welcomes"
                       r"|nomm[ée]e?s?|rejoint|recrute|accueille|arriv[ée]e)\b", I)
ADVISER_HIRE = re.compile(r"\b(hires?|taps|mandates?|picks|appoints?) (advisers|advisors|banks|bankers|[A-Z][\w.&]+( Sachs| Stanley| Lokey)?"
                          r" (to|for) (review|explore|advise|sell|run|lead|weigh|help))", I)


def kind_of(title, hint):
    if ADVISER_HIRE.search(title):
        return "deal"
    if HIRE_VERB.search(title) and not KIND_WORDS["deal"].search(re.sub(r"(?i)dealmak\w+|deals? team", "", title)):
        return "talent"
    if KIND_WORDS["talent"].search(title) and SENIOR.search(title):
        return "talent"
    if hint == "talent" and KIND_WORDS["talent"].search(title):
        return "talent"
    if KIND_WORDS["policy"].search(title) and (hint == "policy" or not KIND_WORDS["deal"].search(title)):
        return "policy"
    if KIND_WORDS["deal"].search(title):
        return "deal"
    return hint if hint in ("policy", "talent") else "other"


def stage_of(title):
    for label, rx in STAGE:
        if rx.search(title):
            return label
    return None


def score(n):
    s = 0
    tiers = [t for _, t, _ in n["firm_meta"]]
    s += 5 if "1" in tiers else 3 if "2" in tiers else 1 if tiers else 0
    s += 2 if any(cat in ("Banque BB", "Boutique M&A", "M&A Mid-Market") for _, _, cat in n["firm_meta"]) else 0
    s += 2 if n["kind"] == "talent" and SENIOR.search(n["title"]) else 0
    s += 1 if n["kind"] == "deal" and n.get("stage") else 0
    s += 2 if BIG.search(n["title"]) else 0
    s += 1 if n["kind"] == "policy" and re.search(r"bank|banque", n["title"], I) else 0
    return s


QUERY_NAME = {"J.P. Morgan": "JPMorgan", "Citi": "Citigroup", "Crédit Agricole CIB": "Credit Agricole CIB", "Apollo": "Apollo Global",
              "Hg": "Hg Capital", "Rothschild & Co": "Rothschild & Co", "Bank of America": "Bank of America", "Messier & Associés": "Messier",
              "Moelis & Company": "Moelis", "Zaoui & Co": "Zaoui"}


def firm_queries(patterns):
    """Google News searches on the firms that matter most (tier 1 and 2), a few names per query."""
    names = set()
    for n, t, cat, _ in patterns:
        if t in ("1", "2") and cat in ("Banque BB", "Boutique M&A", "M&A Mid-Market", "Private Equity", "Dette Privée", "Corporate Finance"):
            core = SUFFIX.sub("", n).strip()
            names.add(QUERY_NAME.get(n) or (n if core.lower() in GENERIC or len(core) < 4 else core))
    names = sorted(names)
    words = '(deal OR acquisition OR advised OR hires OR appoints OR joins OR "managing director" OR rachat OR nommé)'
    return [("firm", "en", "(" + " OR ".join(f'"{x}"' for x in names[i:i + 7]) + f") {words} when:2d") for i in range(0, len(names), 7)]


def _days(a, b):
    try:
        return (datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds() / 86400
    except Exception:
        return 0


def collect(state, companies, now):
    """Read every feed and merge the new headlines into state["news"]."""
    patterns = firm_patterns(companies)
    store = state.setdefault("news", {})
    errors, raw = [], []
    for kind, lang, q in TOPICS + firm_queries(patterns):
        try:
            raw += [dict(x, hint=kind, lang="fr" if lang == "fr" else "en") for x in parse_rss(get_text(gnews(q, lang)))]
        except Exception as e:
            errors.append(f"Google News ({kind}) : {str(e)[:80]}")
        time.sleep(0.6)
    for name, url in FEEDS:
        try:
            raw += [dict(x, hint="feed", lang="en") for x in parse_rss(get_text(url), name)]
        except Exception as e:
            errors.append(f"{name} : {str(e)[:80]}")

    def sig(n):
        return {"firms": n["firms"], "proper": proper(n["title"], n["firms"]), "tk": tokens(n["title"]), "when": n.get("published") or n["first_seen"]}
    recent = [(sig(n), nid) for nid, n in store.items()]
    added = 0
    for x in raw:
        title = x["title"]
        if JUNK.search(title) or JUNK_SOURCES.search(x["source"] or ""):
            continue
        firms = tag_firms(title, patterns)
        if not firms and not (FINANCE.search(title) and STRONG.search(title)):
            continue
        if x["published"] and _days(now, x["published"]) > 7:  # Google News sometimes returns old stories
            continue
        if x["hint"] in ("firm", "feed") and not firms and not re.search(r"bank|banque|m ?& ?a|private equity|buyout|lbo|deal|advis", title, I):
            continue
        nid = hashlib.sha1(norm(title)[:90].encode()).hexdigest()[:12]
        if nid in store:
            continue
        me = sig({"title": title, "firms": [f for f, _, _ in firms], "published": x["published"], "first_seen": now})
        twin = next((oid for o, oid in recent if abs(_days(o["when"], me["when"])) <= 3 and same_story(me, o)), None)
        if twin:  # same story from another publisher: keep the first, remember the other source
            srcs = store[twin].setdefault("also", [])
            if x["source"] and x["source"] != store[twin]["source"] and x["source"] not in srcs and len(srcs) < 5:
                srcs.append(x["source"])
            continue
        kind = kind_of(title, x["hint"])
        if kind == "other" and not firms:
            continue
        n = {"id": nid, "title": title, "url": x["url"], "source": x["source"], "published": x["published"] or now,
             "first_seen": now, "kind": kind, "lang": x["lang"], "firm_meta": firms}
        n["stage"] = stage_of(title) if kind == "deal" else None
        n["score"] = score(n)
        n["firms"] = [f for f, _, _ in firms]
        del n["firm_meta"]
        store[nid] = n
        recent.append((me, nid))
        added += 1

    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    for nid in [k for k, n in store.items() if (n.get("published") or n["first_seen"]) < cutoff]:
        del store[nid]
    if len(store) > MAX_ITEMS:
        for nid in sorted(store, key=lambda k: store[k].get("published") or "")[: len(store) - MAX_ITEMS]:
            del store[nid]
    state["news_errors"] = errors
    print(f"  Actu : {added} nouvelle(s), {len(store)} gardée(s), {len(errors)} flux en panne")
    return added


def items(state):
    return sorted(state.get("news", {}).values(), key=lambda n: n.get("published") or "", reverse=True)


KIND_LABEL = {"deal": "🤝 Deals", "talent": "👔 Mouvements (MD, partners, heads)", "policy": "🏛️ Politique & régulation", "other": "📰 Autres"}
