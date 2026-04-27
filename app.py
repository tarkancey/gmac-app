"""
CMAC - Futbol Mac Analiz ve Tahmin Araci
Versiyon : V1.18
Degisiklik: Lig listesi guncellendi (42 lig)
             LIG ID sutunu eklendi (LIG ile EV SAHIBI arasina)
             Deger sutunlarinda + isareti kaldirildi
             Negatif deger sutunlari kirmizi, pozitifler yesil renk
"""

import os, sys, time, datetime, math, requests
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ======================================================================
#  API ANAHTARI
# ======================================================================
APIFOOTBALL_KEY = "b577ac8215b05f6aed10d0aaa56dde3c"

AF_BOOKMAKERS = [8, 6, 4, 11, 7, 2]

# ======================================================================
#  TAKIP EDILECEK LIGLER
# ======================================================================
LIGLER = [
    (1,   "Dunya Kupasi"),
    (2,   "UEFA Sampiyonlar Ligi"),
    (3,   "UEFA Avrupa Ligi"),
    (5,   "UEFA Uluslar Ligi"),
    (29,  "DK Eleme - Afrika"),
    (30,  "DK Eleme - Asya"),
    (31,  "DK Eleme - CONCACAF"),
    (32,  "DK Eleme - UEFA"),
    (33,  "DK Eleme - Okyanusya"),
    (34,  "DK Eleme - G.Amerika"),
    (39,  "Ingiltere Premier League"),
    (40,  "Ingiltere Championship"),
    (61,  "Fransa Ligue 1"),
    (62,  "Fransa Ligue 2"),
    (78,  "Almanya Bundesliga"),
    (79,  "Almanya Bundesliga 2"),
    (88,  "Hollanda Eredivisie"),
    (89,  "Hollanda Eerste Divisie"),
    (94,  "Portekiz Primeira Liga"),
    (98,  "Japonya J1 League"),
    (99,  "Japonya J2/J3 League"),
    (100, "Japonya J3 League"),
    (106, "Polonya Ekstraklasa"),
    (119, "Danimarka Superliga"),
    (129, "Arjantin Primera Nacional"),
    (135, "Italya Serie A"),
    (136, "Italya Serie B"),
    (140, "Ispanya La Liga"),
    (141, "Ispanya La Liga 2"),
    (144, "Belcika Pro League"),
    (179, "Iskocya Premiership"),
    (197, "Yunanistan Super League"),
    (203, "Turkiye Super Lig"),
    (206, "Turkiye Kupası"),
    (207, "Isvicre Super League"),
    (210, "Hirvatistan HNL"),
    (211, "Hirvatistan HNL 2"),
    (218, "Avusturya Bundesliga"),
    (345, "Cek Cumhuriyeti Liga"),
    (848, "UEFA Konferans Ligi"),
]

AF_BASE = "https://v3.football.api-sports.io"
SEASON  = datetime.date.today().year - (1 if datetime.date.today().month < 7 else 0)


# ======================================================================
#  API-FOOTBALL
# ======================================================================

def af_get(endpoint, params=None):
    try:
        r = requests.get(f"{AF_BASE}/{endpoint}",
                         headers={"x-apisports-key": APIFOOTBALL_KEY},
                         params=params or {}, timeout=15)
        if r.status_code != 200:
            print(f"   x AF HTTP {r.status_code}")
            return None
        data = r.json()
        if data.get("errors"):
            print(f"   x AF hata: {data['errors']}")
            return None
        return data.get("response", [])
    except Exception as e:
        print(f"   x AF baglanti: {e}")
        return None


def fetch_fixtures(target_date):
    print(f"   Mac listesi cekiliyor: {target_date} ...")
    result = af_get("fixtures", {"date": target_date.isoformat(),
                                  "timezone": "Europe/Istanbul"})
    if not result:
        return []
    lid_set  = {l[0] for l in LIGLER}
    fixtures = [f for f in result if f["league"]["id"] in lid_set]
    print(f"   -> {len(fixtures)} mac bulundu")
    return fixtures


def fetch_team_stats(team_id, league_id):
    r = af_get("teams/statistics", {"team": team_id,
                                     "league": league_id,
                                     "season": SEASON})
    if not r: return {}
    return r[0] if isinstance(r, list) else r


def fetch_h2h(home_id, away_id):
    r = af_get("fixtures/headtohead", {"h2h": f"{home_id}-{away_id}", "last": 10})
    return r or []


def fetch_injuries(fixture_id):
    r = af_get("injuries", {"fixture": fixture_id})
    return r or []


def parse_form(stats):
    """Son 6 mac, son 3'e 2x agirlik verilmis form stringe donusturulur."""
    s = stats.get("form", "") or ""
    # Son 6 mac al
    recent = s[-6:] if len(s) >= 6 else s
    return recent


def weighted_form_score(form_str):
    """
    Son 6 mac, son 3 maca 2x agirlik.
    Ornek: WDLLWW → ilk3=WDL(4pt), son3=LWW(6pt)
    Agirlikli = ilk3*1 + son3*2, max = 15*1 + 15*2 = 45
    0-100 araligina normalize edilir.
    """
    if not form_str:
        return 50.0  # bilgi yoksa tarafsiz
    pts = {"W": 3, "D": 1, "L": 0}
    n = len(form_str)
    if n <= 3:
        # Sadece son 3 veya daha az mac var, normal hesap
        score = sum(pts.get(c, 0) for c in form_str)
        max_s = n * 3
        return score / max_s * 100 if max_s > 0 else 50.0
    # Son 3 ve oncesi
    split  = n - 3
    early  = form_str[:split]
    recent = form_str[split:]
    early_score  = sum(pts.get(c, 0) for c in early)
    recent_score = sum(pts.get(c, 0) for c in recent)
    # Agirlikli toplam: erken x1, son x2
    weighted = early_score * 1 + recent_score * 2
    max_w    = len(early) * 3 * 1 + 3 * 3 * 2   # 3*1 + 9*2 = 21 (3+3 mac icin)
    return min(100.0, weighted / max_w * 100) if max_w > 0 else 50.0


def parse_goal_avg(stats):
    try:
        g  = stats.get("goals", {})
        sc = float(g.get("for",     {}).get("average", {}).get("total", 0) or 0)
        cn = float(g.get("against", {}).get("average", {}).get("total", 0) or 0)
        return round(sc, 2), round(cn, 2)
    except:
        return 0.0, 0.0


def parse_h2h_record(h2h_fixes, home_id):
    w = d = l = 0
    for fix in h2h_fixes:
        try:
            gh  = fix["goals"]["home"]
            ga  = fix["goals"]["away"]
            hid = fix["teams"]["home"]["id"]
            if gh is None or ga is None: continue
            if hid == home_id:
                if gh > ga: w += 1
                elif gh == ga: d += 1
                else: l += 1
            else:
                if ga > gh: w += 1
                elif ga == gh: d += 1
                else: l += 1
        except: continue
    return w, d, l


def count_injuries(injury_list, home_id, away_id):
    h_ids = set()
    a_ids = set()
    for p in injury_list:
        tid   = p.get("team",   {}).get("id")
        pid   = p.get("player", {}).get("id")
        ptype = (p.get("player", {}).get("type") or "").strip()
        if not pid: continue
        if ptype in ("Missing Fixture", "Suspended Fixture"):
            if tid == home_id:   h_ids.add(pid)
            elif tid == away_id: a_ids.add(pid)
    return len(h_ids), len(a_ids)


def fetch_all_stats(fixtures):
    stats_map = {}
    total = len(fixtures)
    print(f"\n   {total} mac icin istatistikler cekiliyor...")

    for i, fix in enumerate(fixtures, 1):
        fid     = fix["fixture"]["id"]
        home_id = fix["teams"]["home"]["id"]
        away_id = fix["teams"]["away"]["id"]
        lig_id  = fix["league"]["id"]
        home_nm = fix["teams"]["home"]["name"]
        away_nm = fix["teams"]["away"]["name"]
        print(f"  [{i:2d}/{total}] {home_nm} - {away_nm}")

        hs  = fetch_team_stats(home_id, lig_id); time.sleep(0.3)
        as_ = fetch_team_stats(away_id, lig_id); time.sleep(0.3)
        h2h = fetch_h2h(home_id, away_id);       time.sleep(0.3)
        inj = fetch_injuries(fid);               time.sleep(0.3)

        hgs, hgc = parse_goal_avg(hs)
        ags, agc = parse_goal_avg(as_)
        hw, hd, hl = parse_h2h_record(h2h, home_id)
        h_inj, a_inj = count_injuries(inj, home_id, away_id)

        stats_map[fid] = {
            "home_form": parse_form(hs),
            "away_form": parse_form(as_),
            "home_goals_scored_avg":   hgs,
            "home_goals_conceded_avg": hgc,
            "away_goals_scored_avg":   ags,
            "away_goals_conceded_avg": agc,
            "h2h": {"home_w": hw, "draw": hd, "away_w": hl},
            "home_injured": h_inj,
            "away_injured": a_inj,
        }
    return stats_map


# ======================================================================
#  API-FOOTBALL ODDS
# ======================================================================

def avg_odds(vals_list):
    """Liste halinde gelen oranların ortalamasını al."""
    clean = [v for v in vals_list if v and v > 1.0]
    return round(sum(clean) / len(clean), 2) if clean else None


def fetch_fixture_odds(fixture_id):
    """
    Tek bir mac icin API-Football /odds endpoint'inden oran cek.
    Donus: {ms1, msx, ms2, over25, under25, over35, under35, kg_yes, kg_no}
    """
    result = af_get("odds", {"fixture": fixture_id})
    if not result:
        return {}

    ms1_v = []; msx_v = []; ms2_v = []
    o25_v = []; u25_v = []; o35_v = []; u35_v = []
    kg_y  = []; kg_n  = []

    for bk in result[0].get("bookmakers", []):
        if bk.get("id") not in AF_BOOKMAKERS:
            continue
        for bet in bk.get("bets", []):
            name = bet.get("name", "")
            vals = {v["value"]: float(v["odd"]) for v in bet.get("values", [])}

            if name == "Match Winner":
                if "Home" in vals: ms1_v.append(vals["Home"])
                if "Draw" in vals: msx_v.append(vals["Draw"])
                if "Away" in vals: ms2_v.append(vals["Away"])

            elif name == "Goals Over/Under":
                for v in bet.get("values", []):
                    try:
                        pt  = float(v.get("value","").split(" ")[-1])
                        odd = float(v["odd"])
                        nm  = v.get("value","")
                        if pt == 2.5:
                            if nm.startswith("Over"):  o25_v.append(odd)
                            else:                       u25_v.append(odd)
                        elif pt == 3.5:
                            if nm.startswith("Over"):  o35_v.append(odd)
                            else:                       u35_v.append(odd)
                    except: continue

            elif name == "Both Teams Score":
                if "Yes" in vals: kg_y.append(vals["Yes"])
                if "No"  in vals: kg_n.append(vals["No"])

    return {
        "ms1":     avg_odds(ms1_v),
        "msx":     avg_odds(msx_v),
        "ms2":     avg_odds(ms2_v),
        "over25":  avg_odds(o25_v),
        "under25": avg_odds(u25_v),
        "over35":  avg_odds(o35_v),
        "under35": avg_odds(u35_v),
        "kg_yes":  avg_odds(kg_y),
        "kg_no":   avg_odds(kg_n),
    }


def fetch_all_odds(fixtures):
    """Tum maclar icin odds cek, fixture_id -> odds_dict map'i donus."""
    odds_map = {}
    total = len(fixtures)
    print(f"\n   {total} mac icin oranlar cekiliyor...")
    for i, fix in enumerate(fixtures, 1):
        fid     = fix["fixture"]["id"]
        home_nm = fix["teams"]["home"]["name"]
        away_nm = fix["teams"]["away"]["name"]
        print(f"  [{i:2d}/{total}] {home_nm} - {away_nm}")
        odds_map[fid] = fetch_fixture_odds(fid)
        time.sleep(0.3)
    found = sum(1 for v in odds_map.values() if v.get("ms1"))
    print(f"   -> {found}/{total} macta oran bulundu")
    return odds_map


# ======================================================================
#  TAHMIN MOTORU
# ======================================================================

def form_score(form_str):
    return sum({"W": 3, "D": 1, "L": 0}.get(c, 0) for c in (form_str or ""))


def poisson_p(lam, k):
    return math.exp(-lam) * lam**k / math.factorial(k)


def predict(stats):
    hgs = stats.get("home_goals_scored_avg",   0) or 0
    hgc = stats.get("home_goals_conceded_avg", 0) or 0
    ags = stats.get("away_goals_scored_avg",   0) or 0
    agc = stats.get("away_goals_conceded_avg", 0) or 0
    h2h = stats.get("h2h", {})
    hw  = h2h.get("home_w", 0)
    hd  = h2h.get("draw",   0)
    hl  = h2h.get("away_w", 0)
    h2h_total = hw + hd + hl

    exp_home  = round((hgs + agc) / 2, 2) if (hgs + agc) > 0 else 1.2
    exp_away  = round((ags + hgc) / 2, 2) if (ags + hgc) > 0 else 1.0
    exp_total = exp_home + exp_away

    # Poisson simulasyon
    p1 = px = p2 = 0.0
    for i in range(8):
        for j in range(8):
            p = poisson_p(exp_home, i) * poisson_p(exp_away, j)
            if i > j:    p1 += p
            elif i == j: px += p
            else:         p2 += p

    # Form bileseni — agirlikli (son 3 maca 2x agirlik)
    hfp = weighted_form_score(stats.get("home_form",""))
    afp = weighted_form_score(stats.get("away_form",""))
    ft  = hfp + afp
    fh  = hfp / ft * 100 if ft > 0 else 50.0
    fa  = afp / ft * 100 if ft > 0 else 50.0

    # H2H bileseni
    if h2h_total >= 3:
        h2h_h = hw / h2h_total * 100
        h2h_d = hd / h2h_total * 100
        h2h_a = hl / h2h_total * 100
        h2h_w = 0.15   # H2H agirligi (onceki: 0.20)
    else:
        h2h_h = h2h_d = h2h_a = 0.0
        h2h_w = 0.0

    # Agirliklar: Poisson %60 + Form %25 + H2H %15
    # H2H yoksa: Poisson %70 + Form %30
    form_w = 0.25
    gw = 1.0 - form_w - h2h_w

    raw1 = p1*100*gw + fh*form_w + h2h_h*h2h_w
    rawx = px*100*gw + 25.0*form_w + h2h_d*h2h_w
    raw2 = p2*100*gw + fa*form_w  + h2h_a*h2h_w
    t    = raw1 + rawx + raw2

    ms1 = round(raw1 / t * 100, 1)
    msx = round(rawx / t * 100, 1)
    ms2 = round(raw2 / t * 100, 1)

    # Gol tahminleri
    lam = exp_total
    try:
        p0c = math.exp(-lam); p1c = lam*p0c
        p2c = lam**2/2*p0c;   p3c = lam**3/6*p0c
        po25 = round(min(92, max(8,  (1-p0c-p1c-p2c)     * 100)), 1)
        po35 = round(min(88, max(5,  (1-p0c-p1c-p2c-p3c) * 100)), 1)
    except:
        po25, po35 = 50.0, 30.0
    pu25 = round(100 - po25, 1)
    pu35 = round(100 - po35, 1)

    try:
        pkg = round((1-math.exp(-exp_home)) * (1-math.exp(-exp_away)) * 100, 1)
        pkg = min(90, max(5, pkg))
    except:
        pkg = 45.0

    return {
        "ms1": ms1, "msx": msx, "ms2": ms2,
        "kg":  pkg,
        "o25": po25, "u25": pu25,
        "o35": po35, "u35": pu35,
        "exp_home": exp_home, "exp_away": exp_away,
    }


# ======================================================================
#  STYLE HELPERS
# ======================================================================
C = {
    "dk_green":"1B5E20","green":"2E7D32","lt_green":"A5D6A7","lt_green2":"C8E6C9",
    "dk_blue":"0D47A1","blue":"1565C0","lt_blue":"BBDEFB",
    "gold":"F9A825","lt_gold":"FFF9C4",
    "red":"B71C1C","lt_red":"FFCDD2",
    "white":"FFFFFF","off_white":"F5F5F5","grey":"EEEEEE",
    "dk_text":"212121","mid_text":"757575",
    "purple":"6A1B9A","lt_purple":"E1BEE7",
    "teal":"00695C","lt_teal":"B2DFDB",
    "orange":"E65100","lt_orange":"FFE0B2",
}

def _fill(h):  return PatternFill("solid", fgColor=h)
def _border():
    s = Side(style="thin", color="BDBDBD")
    return Border(left=s, right=s, top=s, bottom=s)
def _align(h="center", wrap=True):
    return Alignment(horizontal=h, vertical="center", wrap_text=wrap)

def sc(cell, bold=False, size=9, fg="212121", bg=None,
       align="center", italic=False, border=True, wrap=True):
    cell.font      = Font(name="Arial", bold=bold, size=size, color=fg, italic=italic)
    cell.alignment = _align(align, wrap)
    if bg:     cell.fill   = _fill(bg)
    if border: cell.border = _border()

def pct_bg(val):
    if val is None: return C["grey"]
    if val >= 65:   return C["lt_green"]
    if val >= 50:   return C["lt_green2"]
    if val >= 38:   return C["lt_gold"]
    return C["lt_red"]

def oran_bg(v):
    if v is None:  return C["grey"]
    if v <= 1.50:  return C["lt_green"]
    if v <= 2.20:  return C["lt_green2"]
    if v <= 3.50:  return C["lt_gold"]
    return C["lt_red"]

def form_bg(s):
    sc_ = form_score(s)
    if sc_ >= 10: return C["lt_green"]
    if sc_ >= 6:  return C["lt_green2"]
    if sc_ >= 3:  return C["lt_gold"]
    return C["lt_red"]

def fmt_pct(v):  return f"{v:.2f}"  if v is not None else ""
def fmt_or(v):   return f"{v:.2f}"  if v is not None else "-"
def fmt_xg(v):   return f"{v:.2f}"  if v and v > 0   else "-"


# ======================================================================
#  EXCEL
# ======================================================================

def build_excel(fixtures, stats_map, odds_map, target_date):
    wb = Workbook()
    ws = wb.active
    ws.title = "Tahminler"
    ws.sheet_view.showGridLines = False

    date_str = target_date.strftime("%d.%m.%Y")
    FINISHED = {"FT","AET","PEN","AWD","WO"}

    # -- On islem --
    processed = []
    for fix in fixtures:
        fid     = fix["fixture"]["id"]
        home_nm = fix["teams"]["home"]["name"]
        away_nm = fix["teams"]["away"]["name"]
        league  = fix["league"]["name"]
        status  = fix["fixture"]["status"]["short"]

        try:
            dt        = datetime.datetime.fromisoformat(fix["fixture"]["date"])
            date_cell = dt.strftime("%d.%m.%Y")
            time_str  = dt.strftime("%H:%M")
        except:
            date_cell = date_str; time_str = "?"

        gh = fix["goals"].get("home")
        ga = fix["goals"].get("away")
        skor = f"{gh}-{ga}" if status in FINISHED and gh is not None else ""

        stats = stats_map.get(fid, {})
        pred  = predict(stats)
        odds  = odds_map.get(fid, {})

        processed.append({
            "date": date_cell, "time": time_str, "league": league,
            "league_id": fix["league"]["id"],
            "home": home_nm, "away": away_nm, "skor": skor,
            "stats": stats, "pred": pred, "odds": odds,
        })

    processed.sort(key=lambda p: (p["date"], p["time"]))
    N = len(processed)

    # -- Sutun tanimlari --
    # Toplam: 32 sutun
    COLS = [
        # (baslik,          genislik, grup_rengi_hex)
        ("TARIH",                10, "0D47A1"),   #  1
        ("SAAT",                  7, "0D47A1"),   #  2
        ("LIG",                  14, "0D47A1"),   #  3
        ("LIG\nID",               6, "0D47A1"),   #  4  YENİ
        ("EV SAHIBI",            18, "0D47A1"),   #  5
        ("DEPLASMAN",            18, "0D47A1"),   #  6
        ("SKOR",                  8, "0D47A1"),   #  7
        ("Ev\nEksik",             7, "E65100"),   #  8
        ("Dep\nEksik",            7, "E65100"),   #  9
        ("Ev\nxG",                7, "E65100"),   # 10
        ("Dep\nxG",               7, "E65100"),   # 11
        ("FORM\nEv",              8, "1A237E"),   # 12
        ("FORM\nDep",             8, "1A237E"),   # 13
        ("H2H\nW-D-L",            9, "1A237E"),   # 14
        ("MS1\nOran",             8, "1B5E20"),   # 15
        ("MS1\n(%)",              8, "1B5E20"),   # 16
        ("MS1\nDeger",            7, "1B5E20"),   # 17
        ("MSX\nOran",             8, "1B5E20"),   # 18
        ("MSX\n(%)",              8, "1B5E20"),   # 19
        ("MSX\nDeger",            7, "1B5E20"),   # 20
        ("MS2\nOran",             8, "1B5E20"),   # 21
        ("MS2\n(%)",              8, "1B5E20"),   # 22
        ("MS2\nDeger",            7, "1B5E20"),   # 23
        ("KG\nOran",              8, "00695C"),   # 24
        ("KG\n(%)",               8, "00695C"),   # 25
        ("KG\nDeger",             7, "00695C"),   # 26
        ("2.5U\nOran",            8, "00695C"),   # 27
        ("2.5U\n(%)",             8, "00695C"),   # 28
        ("2.5U\nDeger",           7, "00695C"),   # 29
        ("2.5A\nOran",            8, "00695C"),   # 30
        ("2.5A\n(%)",             8, "00695C"),   # 31
        ("2.5A\nDeger",           7, "00695C"),   # 32
        ("3.5U\nOran",            8, "00695C"),   # 33
        ("3.5U\n(%)",             8, "00695C"),   # 34
        ("3.5U\nDeger",           7, "00695C"),   # 35
        ("3.5A\nOran",            8, "00695C"),   # 36
        ("3.5A\n(%)",             8, "00695C"),   # 37
        ("3.5A\nDeger",           7, "00695C"),   # 38
    ]
    NCOLS = len(COLS)

    # Grup tanimlari
    GRP = [
        (1,  7,  "MACLAR",            "0D47A1"),
        (8,  11, "EKSIK & xG",        "E65100"),
        (12, 14, "FORM & H2H",        "1A237E"),
        (15, 23, "MAC SONUCU",        "1B5E20"),
        (24, 38, "GOL TAHMINLERI",    "00695C"),
    ]

    # -- Satır 1: Grup baslikları --
    for s, e, lbl, clr in GRP:
        ws.merge_cells(f"{get_column_letter(s)}1:{get_column_letter(e)}1")
        cell = ws.cell(row=1, column=s, value=lbl)
        cell.font = Font(name="Arial", bold=True, size=8, color="FFFFFF")
        cell.fill = _fill(clr)
        cell.alignment = _align()
        cell.border = _border()
    ws.row_dimensions[1].height = 16

    # -- Satır 2: Sutun baslikları --
    for ci, (h, w, clr) in enumerate(COLS, 1):
        cell = ws.cell(row=2, column=ci, value=h)
        sc(cell, bold=True, size=8, fg="FFFFFF", bg=clr)
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.row_dimensions[2].height = 30
    ws.freeze_panes = "A3"

    # -- Lig renk paleti --
    palettes  = ["BBDEFB","C8E6C9","FFF9C4","E1BEE7","B2DFDB","FFCDD2"]
    lig_color = {}

    # -- Veri satırları --
    for ri, p in enumerate(processed, 3):
        st = p["stats"]; pr = p["pred"]; od = p["odds"]
        league = p["league"]

        if league not in lig_color:
            lig_color[league] = palettes[len(lig_color) % len(palettes)]
        lig_bg = lig_color[league]
        rb = "F5F5F5" if ri % 2 == 0 else "FFFFFF"

        hform   = st.get("home_form", "")
        aform   = st.get("away_form", "")
        h2h_d   = st.get("h2h", {})
        h2h_str = f'{h2h_d.get("home_w",0)}-{h2h_d.get("draw",0)}-{h2h_d.get("away_w",0)}'
        h_inj   = st.get("home_injured", 0) or 0
        a_inj   = st.get("away_injured", 0) or 0

        ms1_or = od.get("ms1");    msx_or = od.get("msx");    ms2_or = od.get("ms2")
        o25_or = od.get("over25"); u25_or = od.get("under25")
        o35_or = od.get("over35"); u35_or = od.get("under35")
        kg_or  = od.get("kg_yes")  # Both Teams Score - Yes orani

        ms_max = max(pr["ms1"], pr["msx"], pr["ms2"])

        # Deger farki: CMAC ihtimali - oranin ima ettigi ihtimal
        # Oran yoksa None
        def deger(cmac_pct, oran):
            if oran is None or oran <= 1.0: return None
            oran_pct = round(1 / oran * 100, 1)
            return round(cmac_pct - oran_pct, 1)

        ms1_dg = deger(pr["ms1"], ms1_or)
        msx_dg = deger(pr["msx"], msx_or)
        ms2_dg = deger(pr["ms2"], ms2_or)
        kg_dg  = deger(pr["kg"],  kg_or)
        o25_dg = deger(pr["o25"], o25_or)
        u25_dg = deger(pr["u25"], u25_or)
        o35_dg = deger(pr["o35"], o35_or)
        u35_dg = deger(pr["u35"], u35_or)

        def fmt_deger(v):
            if v is None: return ""
            return f"{v:.1f}" if v >= 0 else f"{v:.1f}"  # artik + yok

        row_vals = [
            p["date"],                  #  1 TARIH
            p["time"],                  #  2 SAAT
            p["league"],                #  3 LIG
            p["league_id"],             #  4 LIG ID
            p["home"],                  #  5 EV SAHIBI
            p["away"],                  #  6 DEPLASMAN
            p["skor"],                  #  7 SKOR
            h_inj if h_inj else "",     #  8 Ev Eksik
            a_inj if a_inj else "",     #  9 Dep Eksik
            fmt_xg(pr["exp_home"]),     # 10 Ev xG
            fmt_xg(pr["exp_away"]),     # 11 Dep xG
            hform,                      # 12 FORM Ev
            aform,                      # 13 FORM Dep
            h2h_str,                    # 14 H2H
            fmt_or(ms1_or),             # 15 MS1 Oran
            fmt_pct(pr["ms1"]),         # 16 MS1%
            fmt_deger(ms1_dg),          # 17 MS1 Deger
            fmt_or(msx_or),             # 18 MSX Oran
            fmt_pct(pr["msx"]),         # 19 MSX%
            fmt_deger(msx_dg),          # 20 MSX Deger
            fmt_or(ms2_or),             # 21 MS2 Oran
            fmt_pct(pr["ms2"]),         # 22 MS2%
            fmt_deger(ms2_dg),          # 23 MS2 Deger
            fmt_or(kg_or),              # 24 KG Oran
            fmt_pct(pr["kg"]),          # 25 KG%
            fmt_deger(kg_dg),           # 26 KG Deger
            fmt_or(o25_or),             # 27 2.5U Oran
            fmt_pct(pr["o25"]),         # 28 2.5U%
            fmt_deger(o25_dg),          # 29 2.5U Deger
            fmt_or(u25_or),             # 30 2.5A Oran
            fmt_pct(pr["u25"]),         # 31 2.5A%
            fmt_deger(u25_dg),          # 32 2.5A Deger
            fmt_or(o35_or),             # 33 3.5U Oran
            fmt_pct(pr["o35"]),         # 34 3.5U%
            fmt_deger(o35_dg),          # 35 3.5U Deger
            fmt_or(u35_or),             # 36 3.5A Oran
            fmt_pct(pr["u35"]),         # 37 3.5A%
            fmt_deger(u35_dg),          # 38 3.5A Deger
        ]

        for ci, val in enumerate(row_vals, 1):
            cell = ws.cell(row=ri, column=ci, value=val)

            def dg_style(dg):
                """Pozitif: yesil ton, negatif: kirmizi ton, None: sade"""
                if dg is None:    return {"fg": "BDBDBD", "bg": rb}
                if dg >=  5:      return {"fg": "1B5E20", "bg": "A5D6A7"}
                if dg >=  2:      return {"fg": "2E7D32", "bg": "C8E6C9"}
                if dg >=  0:      return {"fg": "388E3C", "bg": rb}
                if dg >= -2:      return {"fg": "E65100", "bg": "FFE0B2"}
                if dg >= -5:      return {"fg": "C62828", "bg": "FFCDD2"}
                return             {"fg": "B71C1C", "bg": "EF9A9A"}

            if ci == 1:                  # TARIH
                sc(cell, size=9, bg=rb, align="left", wrap=False)
            elif ci == 3:                # LIG
                sc(cell, bold=True, size=8, fg="212121", bg=lig_bg, align="left", wrap=False)
            elif ci == 4:                # LIG ID
                sc(cell, size=8, fg="757575", bg=lig_bg, align="center", wrap=False)
            elif ci in (5, 6):           # EV/DEP
                sc(cell, size=10, bg=rb, align="left", wrap=False)
            elif ci == 7:                # Skor
                sc(cell, size=9, bold=bool(p["skor"]), bg=rb)
            elif ci in (8, 9):           # Eksik
                v = h_inj if ci == 8 else a_inj
                bg_ = "FFCDD2" if v >= 3 else ("FFE0B2" if v >= 1 else rb)
                sc(cell, bold=(v > 0), size=9, bg=bg_)
            elif ci in (10, 11):         # xG
                sc(cell, size=9, italic=True, fg="757575", bg=rb)
            elif ci in (12, 13):         # Form Ev/Dep
                sc(cell, size=9, bg=rb)
            elif ci in (15, 18, 21):     # MS Oran
                sc(cell, size=9, bg=rb)
            elif ci in (16, 19, 22):     # MS %
                v = pr["ms1"] if ci==16 else (pr["msx"] if ci==19 else pr["ms2"])
                bold_ = (v == ms_max)
                sc(cell, bold=bold_, size=9, bg=pct_bg(v) if bold_ else rb)
            elif ci in (17, 20, 23):     # MS Deger
                dg = ms1_dg if ci==17 else (msx_dg if ci==20 else ms2_dg)
                s  = dg_style(dg)
                sc(cell, bold=(dg is not None and abs(dg)>=5), size=9, **s)
            elif ci == 24:               # KG Oran
                sc(cell, size=9, bg=rb)
            elif ci == 25:               # KG%
                sc(cell, size=9, bg=pct_bg(pr["kg"]))
            elif ci == 26:               # KG Deger
                s = dg_style(kg_dg)
                sc(cell, bold=(kg_dg is not None and abs(kg_dg)>=5), size=9, **s)
            elif ci in (27, 30, 33, 36): # Gol Oran
                sc(cell, size=9, bg=rb)
            elif ci in (28, 31, 34, 37): # Gol %
                v = (pr["o25"] if ci==28 else pr["u25"] if ci==31 else
                     pr["o35"] if ci==34 else pr["u35"])
                sc(cell, size=9, bg=pct_bg(v))
            elif ci in (29, 32, 35, 38): # Gol Deger
                dg = (o25_dg if ci==29 else u25_dg if ci==32 else
                      o35_dg if ci==35 else u35_dg)
                s  = dg_style(dg)
                sc(cell, bold=(dg is not None and abs(dg)>=5), size=9, **s)
            else:
                sc(cell, size=9, bg=rb)

        ws.row_dimensions[ri].height = 22

    # -- Lejant --
    leg_row = N + 4
    ws.row_dimensions[leg_row].height = 5
    leg_row += 1
    ws.merge_cells(f"A{leg_row}:{get_column_letter(NCOLS)}{leg_row}")
    lc = ws.cell(row=leg_row, column=1,
        value="Eksik: Sakat+Cezali (Missing/Suspended Fixture).  "
              "xG: Beklenen gol (Poisson).  "
              "Oran: Bahis sitesi ortalamasi (The Odds API) — yok ise '-'.  "
              "Deger = CMAC ihtimali - oranin ima ettigi ihtimal: "
              "Koy Yesil>=+5 · Acik Yesil>=+2 · Sari -2/+2 · Turuncu<=-2 · Kirmizi<=-5.  "
              "MS%: Poisson %60 + Form %20 + H2H %20.  "
              "Oran renk: <=1.50 Yesil · <=2.20 Acik Yesil · <=3.50 Sari · >3.50 Kirmizi.  "
              "Yuzde renk: >=65 Yesil · >=50 Acik Yesil · >=38 Sari · <38 Kirmizi.")
    lc.font = Font(name="Arial", italic=True, size=7, color="757575")
    lc.fill = _fill("EEEEEE"); lc.alignment = _align("left")
    ws.row_dimensions[leg_row].height = 14

    return wb, processed


# ======================================================================
#  MAIN
# ======================================================================

# ======================================================================
#  LIG / TAKIM ARAMA (Lig_Id entegrasyonu)
# ======================================================================

def search_leagues_by_keyword(keyword):
    results = af_get("leagues", {"search": keyword})
    ligler  = []
    for item in results or []:
        ligler.append({
            "id":      item["league"]["id"],
            "name":    item["league"]["name"],
            "type":    item["league"]["type"],
            "country": item["country"]["name"],
        })
    return sorted(ligler, key=lambda x: (x["country"], x["name"]))


def search_leagues_by_team(keyword):
    teams = af_get("teams", {"search": keyword})
    results = []
    for t in (teams or [])[:5]:
        team_id   = t["team"]["id"]
        team_name = t["team"]["name"]
        leagues   = af_get("leagues", {"team": team_id, "current": "true"})
        for item in (leagues or []):
            results.append({
                "takim":  team_name,
                "lig_id": item["league"]["id"],
                "lig":    item["league"]["name"],
                "tip":    item["league"]["type"],
            })
    return results


def run_lig_search():
    """Interaktif lig/takim arama modu."""
    print()
    print("  ╔════════════════════════════════════════╗")
    print("  ║     Lig / Takim ID Arama               ║")
    print("  ║     Cikis icin bos birakip Enter'a bas ║")
    print("  ╚════════════════════════════════════════╝")
    while True:
        try:
            keyword = input("\n  Arama (ulke / lig / takim): ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not keyword:
            break

        print(f"\n  Araniyor: '{keyword}' ...")
        ligler = search_leagues_by_keyword(keyword)
        if ligler:
            print(f"\n  {'ID':<8} {'Ulke':<22} {'Lig Adi':<40} {'Tip'}")
            print("  " + "-" * 80)
            for l in ligler:
                print(f"  {l['id']:<8} {l['country']:<22} {l['name']:<40} {l['type']}")
            print(f"\n  {len(ligler)} sonuc.")
        else:
            print("  Lig/ulke bulunamadi, takim olarak aranıyor...")
            tl = search_leagues_by_team(keyword)
            if tl:
                print(f"\n  {'Takim':<25} {'Lig ID':<8} {'Lig Adi':<35} {'Tip'}")
                print("  " + "-" * 75)
                for r in tl:
                    print(f"  {r['takim']:<25} {r['lig_id']:<8} {r['lig']:<35} {r['tip']}")
                print(f"\n  {len(tl)} sonuc.")
            else:
                print(f"  '{keyword}' icin sonuc bulunamadi.")

    print("\n  Ana menüye donuluyor...")


def show_results(target_date=None):
    """
    Sadece bitmis mac sonuclarini goster.
    Tek API istegi - istatistik/odds cekilmez.
    """
    if target_date is None:
        target_date = datetime.date.today()

    print(f"\n  Sonuclar: {target_date.strftime('%d.%m.%Y')} tarihli bitmis maclar")
    print("  " + "─" * 70)

    result = af_get("fixtures", {
        "date":     target_date.isoformat(),
        "timezone": "Europe/Istanbul",
    })

    if not result:
        print("  Veri alinamadi veya mac bulunamadi.")
        input("\n  Devam etmek icin Enter'a basin...")
        return

    FINISHED = {"FT", "AET", "PEN", "AWD", "WO"}
    lid_set   = {l[0] for l in LIGLER}
    lig_adi   = {l[0]: l[1] for l in LIGLER}

    # Sadece bitmis ve takip edilen ligler
    bitmis = [
        f for f in result
        if f["fixture"]["status"]["short"] in FINISHED
        and f["league"]["id"] in lid_set
    ]

    if not bitmis:
        print(f"  Bu tarihte bitmis mac bulunamadi.")
        input("\n  Devam etmek icin Enter'a basin...")
        return

    # Lig bazinda grupla ve sirala
    bitmis.sort(key=lambda f: (
        lig_adi.get(f["league"]["id"], f["league"]["name"]),
        f["fixture"]["date"]
    ))

    # Terminal ciktisi
    onceki_lig = None
    toplam     = 0
    for f in bitmis:
        lig_id  = f["league"]["id"]
        lig_nm  = lig_adi.get(lig_id, f["league"]["name"])
        home    = f["teams"]["home"]["name"]
        away    = f["teams"]["away"]["name"]
        gh      = f["goals"].get("home", "?")
        ga      = f["goals"].get("away", "?")
        skor    = f"{gh} - {ga}"
        durum   = f["fixture"]["status"]["short"]

        if lig_nm != onceki_lig:
            print(f"\n  [{lig_nm}]")
            onceki_lig = lig_nm

        print(f"  {home:<28} {skor:^7} {away}")
        toplam += 1

    print(f"\n  {'─'*70}")
    print(f"  Toplam {toplam} mac sonucu  |  "
          f"Takip edilen liglerin disindaki maclar gosterilmedi.")
    input("\n  Ana menuye donmek icin Enter'a basin...")


def select_date():
    """
    Tarih secim menusu.
    - Komut satirindan tarih verildiyse direkt kullan: python CMAC_V1.16.py 2026-03-20
    - Verildiyse interaktif menu goster.
    """
    today = datetime.date.today()

    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        try:
            d = datetime.date.fromisoformat(arg)
            print(f"   Tarih (komut satirindan): {d.strftime('%d.%m.%Y')}")
            return d
        except ValueError:
            print(f"   Gecersiz tarih formati '{arg}'. Beklenen: YYYY-MM-DD")
            print("   Interaktif menu aciliyor...")

    # Interaktif menu
    tomorrow  = today + datetime.timedelta(days=1)
    day_after = today + datetime.timedelta(days=2)
    yesterday = today - datetime.timedelta(days=1)

    while True:
        print()
        print("  ┌─────────────────────────────────────────┐")
        print("  │          CMAC - Ana Menu  V1.17         │")
        print("  ├─────────────────────────────────────────┤")
        print(f"  │  1  Bugun          ({today.strftime('%d.%m.%Y')})         │")
        print(f"  │  2  Yarin          ({tomorrow.strftime('%d.%m.%Y')})         │")
        print(f"  │  3  Obur gun       ({day_after.strftime('%d.%m.%Y')})         │")
        print(f"  │  4  Dun            ({yesterday.strftime('%d.%m.%Y')})         │")
        print("  │  5  Ozel tarih gir (YYYY-MM-DD)         │")
        print("  │  6  Lig / Takim ID ara                  │")
        print(f"  │  7  Sonuclar - Bugun ({today.strftime('%d.%m.%Y')})       │")
        print("  │  8  Sonuclar - Tarih sec                │")
        print("  └─────────────────────────────────────────┘")
        print()

        try:
            secim = input("  Seciminiz (1-8): ").strip()
            if secim == "1":
                return today
            elif secim == "2":
                return tomorrow
            elif secim == "3":
                return day_after
            elif secim == "4":
                return yesterday
            elif secim == "5":
                tarih_str = input("  Tarih girin (YYYY-MM-DD): ").strip()
                return datetime.date.fromisoformat(tarih_str)
            elif secim == "6":
                run_lig_search()
            elif secim == "7":
                show_results()
            elif secim == "8":
                try:
                    tarih_str = input("  Tarih girin (YYYY-MM-DD): ").strip()
                    show_results(datetime.date.fromisoformat(tarih_str))
                except ValueError:
                    print("  Gecersiz tarih. Ornek: 2026-03-20")
            else:
                print("  Gecersiz secim. 1-8 arasi bir sayi girin.")
        except ValueError:
            print("  Gecersiz tarih formati. Ornek: 2026-03-20")
        except (KeyboardInterrupt, EOFError):
            print("\n  Iptal edildi.")
            sys.exit(0)


def main():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   CMAC - Mac Analiz ve Tahmin V1.18  ║")
    print("  ╚══════════════════════════════════════╝")

    if not APIFOOTBALL_KEY or APIFOOTBALL_KEY == "BURAYA_ANAHTAR_GIRIN":
        print("\n  HATA: APIFOOTBALL_KEY girilmemis!")
        return

    target_date = select_date()
    today       = datetime.date.today()
    is_past     = target_date < today

    print(f"\n   Tarih : {target_date.strftime('%d.%m.%Y')}", end="")
    if is_past:
        print("  [GECMIS - istatistik/odds atlanacak]")
    elif target_date == today:
        print("  [BUGUN]")
    else:
        days_ahead = (target_date - today).days
        print(f"  [GELECEK +{days_ahead} gun]")
    print("=" * 60)

    fixtures = fetch_fixtures(target_date)
    if not fixtures:
        print("   Mac bulunamadi.")
        return

    # Gecmis tarih: istatistik ve odds cekme, bos map gonder
    if is_past:
        print("\n   Gecmis tarih — istatistik ve oranlar atlanıyor.")
        stats_map = {}
        odds_map  = {}
    else:
        stats_map = fetch_all_stats(fixtures)
        odds_map  = fetch_all_odds(fixtures)

    print(f"\n   Excel olusturuluyor ({len(fixtures)} mac)...")
    wb, processed = build_excel(fixtures, stats_map, odds_map, target_date)

    now      = datetime.datetime.now()
    date_tag = target_date.strftime("%Y%m%d")
    time_tag = now.strftime("%H%M")
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"CMAC_V1.18_{date_tag}_{time_tag}.xlsx"
    )
    wb.save(out_path)
    print(f"\n   Kaydedildi: {out_path}")

    print(f"\n{'─'*90}")
    print(f"{'TARIH':<11}{'SAAT':<6}{'LIG':<18}{'MAC':<30}{'SKOR':>8}{'MS1%':>6}{'MSX%':>6}{'MS2%':>6}")
    print("─" * 90)
    for p in processed:
        pr   = p["pred"]
        mac  = f"{p['home'][:13]} - {p['away'][:13]}"
        skor = p["skor"] if p["skor"] else "-"
        print(f"{p['date']:<11}{p['time']:<6}{p['league'][:16]:<18}{mac:<30}"
              f"{skor:>8}{pr['ms1']:>5.1f}%{pr['msx']:>5.1f}%{pr['ms2']:>5.1f}%")
    print("─" * 90)
    print(f"   Toplam {len(processed)} mac")


if __name__ == "__main__":
    main()

