import streamlit as st
import requests
from scipy.stats import poisson
import pandas as pd
from datetime import datetime, timedelta, timezone
import io
from openpyxl.styles import PatternFill

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="GMAC V11.06 - Tam Donanımlı Analiz", page_icon="⚔️", layout="wide")

if "analiz_df" not in st.session_state:
    st.session_state.analiz_df = None

# Hedef Ligler
TARGET_IDS = [1, 2, 3, 5, 29, 30, 31, 32, 33, 34, 39, 40, 61, 62, 78, 79, 88, 89, 94, 98, 99, 100, 106, 119, 129, 135, 136, 140, 141, 144, 179, 197, 203, 206, 207, 210, 211, 218, 345, 848]

# --- YARDIMCI FONKSİYONLAR ---
def fix_timezone(date_str):
    try:
        if date_str.endswith('Z'): date_str = date_str.replace('Z', '+00:00')
        dt_obj = datetime.fromisoformat(date_str)
        tr_zone = timezone(timedelta(hours=3))
        dt_tr = dt_obj.astimezone(tr_zone)
        return dt_tr.strftime("%Y-%m-%d"), dt_tr.strftime("%H:%M") 
    except: return date_str[:10], date_str[11:16]

@st.cache_data(ttl=3600)
def get_league_standings(lig_id, season, api_key):
    headers = {"x-apisports-key": api_key}
    try:
        resp = requests.get("https://v3.football.api-sports.io/standings", headers=headers, params={"league": lig_id, "season": season})
        return {t['team']['id']: t['points'] for g in resp.json().get('response', [])[0]['league']['standings'] for t in g} if resp.json().get('response') else {}
    except: return {}

def get_odds(fixture_id, api_key):
    headers = {"x-apisports-key": api_key}
    url = "https://v3.football.api-sports.io/odds"
    odds_pool = {"MS1": [], "MSX": [], "MS2": [], "2.5U": [], "2.5A": [], "3.5U": [], "3.5A": [], "KGV": []}
    try:
        data = requests.get(url, headers=headers, params={"fixture": fixture_id}).json().get('response', [])
        if data:
            for bk in data[0].get('bookmakers', []):
                for bet in bk.get('bets', []):
                    if bet['id'] == 1: 
                        for v in bet['values']:
                            if v['value'] == "Home": odds_pool["MS1"].append(float(v['odd']))
                            elif v['value'] == "Draw": odds_pool["MSX"].append(float(v['odd']))
                            elif v['value'] == "Away": odds_pool["MS2"].append(float(v['odd']))
                    elif bet['id'] == 5: 
                        for v in bet['values']:
                            if v['value'] == "Over 2.5": odds_pool["2.5U"].append(float(v['odd']))
                            elif v['value'] == "Under 2.5": odds_pool["2.5A"].append(float(v['odd']))
                            elif v['value'] == "Over 3.5": odds_pool["3.5U"].append(float(v['odd']))
                            elif v['value'] == "Under 3.5": odds_pool["3.5A"].append(float(v['odd']))
                    elif bet['id'] == 8: 
                         for v in bet['values']:
                            if v['value'] == "Yes": odds_pool["KGV"].append(float(v['odd']))
    except: pass
    return {k: round(sum(v)/len(v), 2) if v else 0.0 for k, v in odds_pool.items()}

@st.cache_data(ttl=3600)
def get_team_form_6_months(team_id, api_key):
    headers = {"x-apisports-key": api_key}
    try:
        resp = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"team": team_id, "last": 6}).json().get('response', [])
        form_str = ""
        now = datetime.now(timezone.utc)
        for match in reversed(resp):
            if match['fixture']['status']['short'] not in ['FT', 'AET', 'PEN']: continue
            m_date = datetime.fromisoformat(match['fixture']['date'].replace('Z', '+00:00'))
            if (now - m_date).days <= 180:
                h_id, h_g, a_g = match['teams']['home']['id'], match['goals']['home'], match['goals']['away']
                if h_g == a_g: form_str += "D"
                elif (h_id == team_id and h_g > a_g) or (h_id != team_id and a_g > h_g): form_str += "W"
                else: form_str += "L"
        return form_str
    except: return ""

def get_stats(lig_id, team_id, season_year, api_key):
    headers = {"x-apisports-key": api_key}
    try:
        data = requests.get("https://v3.football.api-sports.io/teams/statistics", headers=headers, params={"league": lig_id, "team": team_id, "season": season_year}).json()
        s = data.get('response')
        if not s: return None
        return {
            "hf": float(s['goals']['for']['average']['home'] or 0.1),
            "ha": float(s['goals']['against']['average']['home'] or 0.1),
            "af": float(s['goals']['for']['average']['away'] or 0.1),
            "aa": float(s['goals']['against']['average']['away'] or 0.1)
        }
    except: return None

def get_h2h(ev_id, dep_id, api_key):
    headers = {"x-apisports-key": api_key}
    try:
        resp = requests.get("https://v3.football.api-sports.io/fixtures/headtohead", headers=headers, params={"h2h": f"{ev_id}-{dep_id}", "last": 5}).json().get('response', [])
        w, d, l = 0, 0, 0
        for m in resp:
            if m['fixture']['status']['short'] in ['FT', 'AET', 'PEN']:
                hg, ag = m['goals']['home'], m['goals']['away']
                if hg == ag: d += 1
                elif (m['teams']['home']['id'] == ev_id and hg > ag) or (m['teams']['away']['id'] == ev_id and ag > hg): w += 1
                else: l += 1
        return f"{w}-{d}-{l}"
    except: return "0-0-0"

def get_injuries(fixture_id, ev_id, dep_id, api_key):
    headers = {"x-apisports-key": api_key}
    try:
        resp = requests.get("https://v3.football.api-sports.io/injuries", headers=headers, params={"fixture": fixture_id}).json().get('response', [])
        ev_e = sum(1 for p in resp if p['team']['id'] == ev_id)
        dep_e = sum(1 for p in resp if p['team']['id'] == dep_id)
        return ev_e, dep_e
    except: return 0, 0

def calculate_momentum_xg(h_form, a_form, h_stats, a_stats, h_pts, a_pts):
    def weighted_form_multiplier(form_str):
        if not form_str: return 1.0
        t_pts, m_pts, length = 0, 0, len(form_str)
        for i, char in enumerate(form_str):
            is_recent = (i >= length - 3)
            wp, dp = (5, 2) if is_recent else (3, 1)
            m_pts += wp
            if char == 'W': t_pts += wp
            elif char == 'D': t_pts += dp
        return 0.7 + (t_pts / m_pts) * 0.6 if m_pts > 0 else 1.0
    
    h_mom, a_mom = weighted_form_multiplier(h_form), weighted_form_multiplier(a_form)
    diff = h_pts - a_pts
    h_mul = 1.0 + max(min(diff * 0.01, 0.3), -0.3)
    a_mul = 1.0 + max(min(-diff * 0.01, 0.3), -0.3)
    ex = ((h_stats['hf'] + a_stats['aa']) / 2.0) * h_mom * h_mul
    ax = ((h_stats['ha'] + a_stats['af']) / 2.0) * a_mom * a_mul
    return max(0.1, ex), max(0.1, ax)

def calculate_hybrid_probs(ex, ax):
    m1, mx, m2, kg, tot = 0, 0, 0, 0, 0
    for h in range(10):
        for a in range(10):
            p = poisson.pmf(h, ex) * poisson.pmf(a, ax)
            if h == a and h in [0, 1]: p *= 1.15
            tot += p
            if h > a: m1 += p
            elif h == a: mx += p
            else: m2 += p
            if h > 0 and a > 0: kg += p
    n = 100.0 / tot if tot > 0 else 0
    u25 = poisson.cdf(2, ex + ax) * 100
    u35 = poisson.cdf(3, ex + ax) * 100
    return {"1": m1*n, "X": mx*n, "2": m2*n, "KGV": kg*n, "2.5A": u25, "2.5U": 100-u25, "3.5A": u35, "3.5U": 100-u35}

def color_v(v):
    if isinstance(v, (int, float)):
        if v >= 1.20: return 'background-color: #ffe6cc; color: #cc6600;' 
        elif v >= 0.05: return 'background-color: #c6efce; color: #006100;' 
        elif v <= -0.15: return 'background-color: #ffc7ce; color: #9c0006;' 
    return ''

# --- UI ---
with st.sidebar:
    st.header("⚙️ GMAC V11.06")
    api_key = st.text_input("API Key:", type="password")
    menu = st.radio("İşlem Modu:", ["Bugün", "Yarın", "Tarih Gir", "Sonuçlar Bugün", "Sonuçlar Tarih Gir"])
    
    bdt = datetime.now()
    if "Bugün" in menu: s_tar = bdt.strftime("%Y-%m-%d")
    elif "Yarın" in menu: s_tar = (bdt + timedelta(days=1)).strftime("%Y-%m-%d")
    else: s_tar = st.date_input("Tarih Seç:", bdt).strftime("%Y-%m-%d")

    basla = st.button("🚀 Analizi Başlat", type="primary")

if basla:
    if not api_key: st.error("API Key girilmedi!")
    else:
        headers = {"x-apisports-key": api_key}
        is_results = "Sonuçlar" in menu
        all_res = []

        with st.status(f"{s_tar} verileri toplanıyor...") as status:
            l_resp = requests.get("https://v3.football.api-sports.io/leagues", headers=headers, params={"current": "true"}).json()
            v_leagues = [i for i in l_resp.get('response', []) if i['league']['id'] in TARGET_IDS]
            
            for l in v_leagues:
                lid, lyr = l['league']['id'], l['seasons'][0]['year']
                f_resp = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, 
                                      params={"league": lid, "season": lyr, "from": s_tar, "to": s_tar, "timezone": "Europe/Istanbul"}).json().get('response', [])
                
                for f in f_resp:
                    trd, trt = fix_timezone(f['fixture']['date'])
                    skor = f"{f['goals']['home']}-{f['goals']['away']}" if f['fixture']['status']['short'] in ['FT', 'AET', 'PEN'] else ""
                    fid = f['fixture']['id']
                    ev_id, dep_id = f['teams']['home']['id'], f['teams']['away']['id']
                    
                    row = {"Tarih": datetime.strptime(trd, "%Y-%m-%d").strftime("%d.%m.%Y"), "Saat": trt, "Lig": l['league']['name'], 
                           "Lig ID": lid, "Ev": f['teams']['home']['name'], "Dep": f['teams']['away']['name'], "Skor": skor, "Sort": trd}
                    
                    if not is_results:
                        # Full Analiz Bloğu
                        ev_e, dep_e = get_injuries(fid, ev_id, dep_id, api_key)
                        h2h = get_h2h(ev_id, dep_id, api_key)
                        h_form, a_form = get_team_form_6_months(ev_id, api_key), get_team_form_6_months(dep_id, api_key)
                        pts = get_league_standings(lid, lyr, api_key)
                        h_s, a_s = get_stats(lid, ev_id, lyr, api_key), get_stats(lid, dep_id, lyr, api_key)
                        
                        if h_s and a_s:
                            exg, axg = calculate_momentum_xg(h_form, a_form, h_s, a_s, pts.get(ev_id, 0), pts.get(dep_id, 0))
                            p = calculate_hybrid_probs(exg, axg)
                            o = get_odds(fid, api_key)
                            
                            row.update({
                                "Ev Eksik": ev_e, "Dep Eksik": dep_e, "Ev xG": round(exg, 2), "Dep xG": round(axg, 2),
                                "Ev Form": h_form, "Dep Form": a_form, "H2H W-D-L": h2h,
                                "MS1 Oran": o["MS1"], "MS1 %": round(p['1']), "MS1 VAL": round(((p['1']/100)*o["MS1"])-1, 2) if o["MS1"]>0 else 0,
                                "MSX Oran": o["MSX"], "MSX %": round(p['X']), "MSX VAL": round(((p['X']/100)*o["MSX"])-1, 2) if o["MSX"]>0 else 0,
                                "MS2 Oran": o["MS2"], "MS2 %": round(p['2']), "MS2 VAL": round(((p['2']/100)*o["MS2"])-1, 2) if o["MS2"]>0 else 0,
                                "KG Var Oran": o["KGV"], "KG Var %": round(p['KGV']), "KGV VAL": round(((p['KGV']/100)*o["KGV"])-1, 2) if o["KGV"]>0 else 0,
                                "2.5Ü Oran": o["2.5U"], "2.5Ü %": round(p['2.5U']), "2.5Ü VAL": round(((p['2.5U']/100)*o["2.5U"])-1, 2) if o["2.5U"]>0 else 0,
                                "2.5A Oran": o["2.5A"], "2.5A %": round(p['2.5A']), "2.5A VAL": round(((p['2.5A']/100)*o["2.5A"])-1, 2) if o["2.5A"]>0 else 0,
                                "3.5Ü Oran": o["3.5U"], "3.5Ü %": round(p['3.5U']), "3.5Ü VAL": round(((p['3.5U']/100)*o["3.5U"])-1, 2) if o["3.5U"]>0 else 0,
                                "3.5A Oran": o["3.5A"], "3.5A %": round(p['3.5A']), "3.5A VAL": round(((p['3.5A']/100)*o["3.5A"])-1, 2) if o["3.5A"]>0 else 0
                            })
                    all_res.append(row)
            status.update(label="Analiz Hazır!", state="complete")
        
        if all_res:
            st.session_state.analiz_df = pd.DataFrame(all_res).sort_values(by=["Sort", "Saat"]).drop(columns=["Sort"])
        else:
            st.warning("Veri bulunamadı.")

if st.session_state.analiz_df is not None:
    df = st.session_state.analiz_df
    v_cols = [c for c in df.columns if 'VAL' in c]
    st.dataframe(df.style.map(color_v, subset=v_cols) if v_cols else df, use_container_width=True, hide_index=True)

    # XLSX
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as wr:
        df.to_excel(wr, index=False, sheet_name="Analiz")
        ws = wr.sheets['Analiz']
        f_o, f_g, f_r = PatternFill("solid", "FFE6CC"), PatternFill("solid", "C6EFCE"), PatternFill("solid", "FFC7CE")
        v_idx = [i + 1 for i, c in enumerate(df.columns) if 'VAL' in c]
        for r_idx, row in enumerate(df.itertuples(index=False), 2):
            for c_idx in v_idx:
                val = row[c_idx - 1]
                if isinstance(val, (int, float)):
                    cell = ws.cell(r_idx, c_idx)
                    if val >= 1.20: cell.fill = f_o
                    elif val >= 0.05: cell.fill = f_g
                    elif val <= -0.15: cell.fill = f_r
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 15

    st.download_button("📥 GMAC V11.06 XLSX İndir", buf.getvalue(), f"GMAC_V11.06_{s_tar}.xlsx", type="primary")
