import streamlit as st
import requests
from scipy.stats import poisson
import pandas as pd
import math
from datetime import datetime, timedelta, timezone
import io

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="GMAC V10.48", page_icon="⚔️", layout="wide")

# --- YARDIMCI FONKSİYONLAR ---
TARGET_IDS = [203, 204, 39, 40, 140, 141, 78, 79, 135, 136, 61, 62, 88, 89, 94, 144, 119, 179, 345, 197, 106, 210, 2, 3]

def fix_timezone(date_str):
    try:
        if date_str.endswith('Z'): date_str = date_str.replace('Z', '+00:00')
        dt_obj = datetime.fromisoformat(date_str)
        tr_zone = timezone(timedelta(hours=3))
        dt_tr = dt_obj.astimezone(tr_zone)
        return dt_tr.strftime("%d.%m.%Y"), dt_tr.strftime("%H:%M")
    except: return date_str[:10], date_str[11:16]

@st.cache_data(ttl=3600)
def get_league_standings(lig_id, season, api_key):
    headers = {"x-apisports-key": api_key}
    try:
        resp = requests.get("https://v3.football.api-sports.io/standings", headers=headers, params={"league": lig_id, "season": season})
        return {t['team']['id']: t['points'] for g in resp.json().get('response', [])[0]['league']['standings'] for t in g} if resp.json().get('response') else {}
    except: return {}

def get_matches_range(lig_id, season_year, start_date, end_date, api_key):
    headers = {"x-apisports-key": api_key}
    try:
        return requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"league": lig_id, "season": season_year, "from": start_date, "to": end_date, "timezone": "Europe/Istanbul"}).json().get('response', [])
    except: return []

def get_odds(fixture_id, api_key):
    headers = {"x-apisports-key": api_key}
    url = "https://v3.football.api-sports.io/odds"
    odds_pool = {"MS1": [], "MSX": [], "MS2": [], "1X": [], "X2": [], "2.5U": [], "2.5A": [], "3.5U": [], "3.5A": [], "KGV": []}
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
                    elif bet['id'] == 12: 
                        for v in bet['values']:
                            if v['value'] == "Home/Draw": odds_pool["1X"].append(float(v['odd']))
                            elif v['value'] == "Draw/Away": odds_pool["X2"].append(float(v['odd']))
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
    
    final_odds = {k: round(sum(v)/len(v), 2) if v else 0 for k, v in odds_pool.items()}
    if final_odds["1X"] == 0 and final_odds["MS1"] > 0 and final_odds["MSX"] > 0: final_odds["1X"] = round((final_odds["MS1"] * final_odds["MSX"]) / (final_odds["MS1"] + final_odds["MSX"]), 2)
    if final_odds["X2"] == 0 and final_odds["MS2"] > 0 and final_odds["MSX"] > 0: final_odds["X2"] = round((final_odds["MS2"] * final_odds["MSX"]) / (final_odds["MS2"] + final_odds["MSX"]), 2)
    return final_odds

def get_stats(lig_id, team_id, season_year, api_key):
    headers = {"x-apisports-key": api_key}
    try:
        s = requests.get("https://v3.football.api-sports.io/teams/statistics", headers=headers, params={"league": lig_id, "team": team_id, "season": season_year}).json().get('response')
        return {"form": s.get('form', "")[-5:], "hf": float(s['goals']['for']['average']['home']), "ha": float(s['goals']['against']['average']['home']), "af": float(s['goals']['for']['average']['away']), "aa": float(s['goals']['against']['average']['away'])} if s else None
    except: return None

# V10.48 GÜNCELLEMESİ: Puan Gücü (Power Balance) Eklendi
def calculate_momentum_xg(h_stats, a_stats, h_pts, a_pts):
    def form_multiplier(form_str):
        pts = (form_str.count('W') * 3) + (form_str.count('D') * 1)
        return 0.7 + (pts / 15.0) * 0.6 
    
    h_mom, a_mom = form_multiplier(h_stats['form']), form_multiplier(a_stats['form'])
    
    # Puan Gücü Çarpanı (Her 10 puan farkı %10 avantaj/dezavantaj sağlar, Max %30)
    diff = h_pts - a_pts
    h_pts_multiplier = 1.0 + max(min(diff * 0.01, 0.3), -0.3)
    a_pts_multiplier = 1.0 + max(min(-diff * 0.01, 0.3), -0.3)
    
    ev_xg = ((h_stats['hf'] + a_stats['aa']) / 2.0) * h_mom * h_pts_multiplier
    dep_xg = ((h_stats['ha'] + a_stats['af']) / 2.0) * a_mom * a_pts_multiplier
    
    return max(0.1, ev_xg), max(0.1, dep_xg)

def calculate_hybrid_probabilities(ev_xg, dep_xg):
    ms1, msx, ms2, kg_var = 0, 0, 0, 0
    total_prob = 0
    for h in range(10):
        for a in range(10):
            p = poisson.pmf(h, ev_xg) * poisson.pmf(a, dep_xg)
            total_prob += p
            if h > a: ms1 += p
            elif h == a: msx += p
            else: ms2 += p
            if h > 0 and a > 0: kg_var += p
    norm = 100.0 / total_prob if total_prob > 0 else 0
    total_xg = ev_xg + dep_xg
    prob_under_25 = poisson.cdf(2, total_xg) * 100
    prob_under_35 = poisson.cdf(3, total_xg) * 100
    if total_xg > 2.2: prob_under_35 *= 0.85 
    return {"1": ms1 * norm, "X": msx * norm, "2": ms2 * norm, "1X": (ms1 + msx) * norm, "X2": (msx + ms2) * norm, "KGV": kg_var * norm, "2.5A": prob_under_25, "2.5U": 100 - prob_under_25, "3.5A": prob_under_35, "3.5U": 100 - prob_under_35}

# V10.48 GÜNCELLEMESİ: Value Trap (Değer Tuzağı) Filtresi Eklendi
def true_val(odd, pct, is_side_bet=False): 
    if odd <= 0 or pct <= 0: return -1.0
    val = round((odd * (pct/100)) - 1, 2)
    
    # Eğer Taraf Bahsi ise ve Value %35'ten fazlaysa, bu büyük ihtimalle bir tuzaktır (Eksik kadro vb.)
    if is_side_bet and val > 0.35:
        return -0.99 # Tuzak olarak işaretle ve yeşil listeye almasını engelle
    
    return val

# --- ARAYÜZ (UI) ---
st.title("⚔️ GMAC V10.48 - Anti-Trap Engine")
st.caption("Puan Gücü Algoritması ve Değer Tuzağı (Value Trap) Filtresi Aktif")

with st.sidebar:
    st.header("⚙️ Ayarlar")
    api_key = st.text_input("API Key Giriniz:", type="password")
    
    st.header("📅 Tarih Seçimi")
    now = datetime.now()
    bugun_str = now.strftime("%Y-%m-%d")
    yarin_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    
    secim = st.radio("Taramak İstediğiniz Gün:", ["Bugün", "Yarın"])
    hedef_tarih = bugun_str if secim == "Bugün" else yarin_str
    
    baslat = st.button("🚀 Analizi Başlat", type="primary", use_container_width=True)

if baslat:
    if not api_key:
        st.error("Lütfen sol menüden API Key giriniz!")
    else:
        all_excel_data = []
        headers = {"x-apisports-key": api_key}
        
        with st.status("Veriler çekiliyor ve Tuzak Taraması yapılıyor...", expanded=True) as status:
            try:
                resp = requests.get("https://v3.football.api-sports.io/leagues", headers=headers, params={"current": "true"})
                valid_leagues = [{"id": i['league']['id'], "name": i['league']['name'], "year": i['seasons'][0]['year']} for i in resp.json().get('response', []) if i['league']['id'] in TARGET_IDS]
                
                progress_bar = st.progress(0)
                total_leagues = len(valid_leagues)
                
                for i, l in enumerate(valid_leagues):
                    st.write(f"⏳ Taranıyor: {l['name']}")
                    maclar = get_matches_range(l['id'], l['year'], hedef_tarih, hedef_tarih, api_key)
                    
                    for mac in maclar:
                        try:
                            tr_tarih, saat = fix_timezone(mac['fixture']['date'])
                            ev_ad, dep_ad = mac['teams']['home']['name'], mac['teams']['away']['name']
                            ev_id, dep_id, lig_id, sezon = mac['teams']['home']['id'], mac['teams']['away']['id'], mac['league']['id'], mac['league']['season']
                            
                            points_map = get_league_standings(lig_id, sezon, api_key)
                            ev_puan, dep_puan = points_map.get(ev_id, 0), points_map.get(dep_id, 0)
                            
                            ms_durumu = mac['fixture']['status']['short']
                            skor = f"{mac['goals']['home']}-{mac['goals']['away']}" if ms_durumu in ['FT', 'AET', 'PEN'] else ms_durumu

                            h_s = get_stats(lig_id, ev_id, sezon, api_key)
                            a_s = get_stats(lig_id, dep_id, sezon, api_key)
                            
                            if h_s and a_s:
                                # Yeni Puanlı xG Hesaplaması
                                ev_xg, dep_xg = calculate_momentum_xg(h_s, a_s, ev_puan, dep_puan)
                                probs = calculate_hybrid_probabilities(ev_xg, dep_xg)
                                odds = get_odds(mac['fixture']['id'], api_key)
                                
                                all_excel_data.append({
                                    "Tarih": tr_tarih, "Saat": saat, "Lig": mac['league']['name'],
                                    "Ev": ev_ad, "Ev Form": h_s['form'], "Ev Puan": ev_puan,
                                    "Dep": dep_ad, "Dep Form": a_s['form'], "Dep Puan": dep_puan,
                                    "Skor": skor, "Ev xG": round(ev_xg, 2), "Dep xG": round(dep_xg, 2),
                                    "MS1 Oran": odds["MS1"], "MS1 %": round(probs['1']), "VAL MS1": true_val(odds["MS1"], probs['1'], True),
                                    "MSX Oran": odds["MSX"], "MSX %": round(probs['X']), "VAL MSX": true_val(odds["MSX"], probs['X'], True),
                                    "MS2 Oran": odds["MS2"], "MS2 %": round(probs['2']), "VAL MS2": true_val(odds["MS2"], probs['2'], True),
                                    "1X Oran": odds["1X"], "1X %": round(probs['1X']), "VAL 1X": true_val(odds["1X"], probs['1X'], True),
                                    "X2 Oran": odds["X2"], "X2 %": round(probs['X2']), "VAL X2": true_val(odds["X2"], probs['X2'], True),
                                    "KG Var Oran": odds["KGV"], "KG Var %": round(probs['KGV']), "VAL KG": true_val(odds["KGV"], probs['KGV']),
                                    "2.5 Üst Oran": odds["2.5U"], "2.5 Üst %": round(probs['2.5U']), "VAL 2.5Ü": true_val(odds["2.5U"], probs['2.5U']),
                                    "2.5 Alt Oran": odds["2.5A"], "2.5 Alt %": round(probs['2.5A']), "VAL 2.5A": true_val(odds["2.5A"], probs['2.5A']),
                                    "3.5 Üst Oran": odds["3.5U"], "3.5 Üst %": round(probs['3.5U']), "VAL 3.5Ü": true_val(odds["3.5U"], probs['3.5U']),
                                    "3.5 Alt Oran": odds["3.5A"], "3.5 Alt %": round(probs['3.5A']), "VAL 3.5A": true_val(odds["3.5A"], probs['3.5A'])
                                })
                        except: pass
                    progress_bar.progress((i + 1) / total_leagues)
                status.update(label="Tuzak Taraması ve Analiz Tamamlandı!", state="complete", expanded=False)
            except Exception as e:
                st.error(f"Bir hata oluştu: {e}")

        if all_excel_data:
            df = pd.DataFrame(all_excel_data)
            
            st.success(f"✅ {len(df)} adet maç analiz edildi. Değer tuzakları temizlendi.")
            
            # --- TELEFONA VE WEB'E ÖZEL KART GÖRÜNÜMÜ ---
            st.markdown("### 🎯 Güvenli Fırsatlar (Tuzaksız | Value > 0.10 & Olasılık > %50)")
            
            for index, row in df.iterrows():
                firsatlar = []
                
                bahis_tipleri = [
                    ("MS 1", "MS1 %", "VAL MS1", "MS1 Oran"), ("MS X", "MSX %", "VAL MSX", "MSX Oran"), ("MS 2", "MS2 %", "VAL MS2", "MS2 Oran"),
                    ("1X ÇŞ", "1X %", "VAL 1X", "1X Oran"), ("X2 ÇŞ", "X2 %", "VAL X2", "X2 Oran"),
                    ("KG Var", "KG Var %", "VAL KG", "KG Var Oran"),
                    ("2.5 Üst", "2.5 Üst %", "VAL 2.5Ü", "2.5 Üst Oran"), ("2.5 Alt", "2.5 Alt %", "VAL 2.5A", "2.5 Alt Oran"),
                    ("3.5 Üst", "3.5 Üst %", "VAL 3.5Ü", "3.5 Üst Oran"), ("3.5 Alt", "3.5 Alt %", "VAL 3.5A", "3.5 Alt Oran")
                ]
                
                for isim, yuzde_col, val_col, oran_col in bahis_tipleri:
                    # Değerli ve %50 üstü bahisleri bul (Tuzaklanıp -0.99 olanlar otomatik elenecek)
                    if row[val_col] >= 0.10 and row[yuzde_col] >= 50:
                        firsatlar.append(f"✅ **{isim}** | %{row[yuzde_col]} | Oran: {row[oran_col]} | **Val: +{row[val_col]}**")

                if len(firsatlar) > 0:
                    with st.expander(f"⚽ {row['Ev']} - {row['Dep']}  | 🕒 {row['Saat']}"):
                        st.caption(f"🏆 {row['Lig']} | Skor: {row['Skor']}")
                        st.markdown(f"**Puan:** {row['Ev']} ({row['Ev Puan']}p) - {row['Dep']} ({row['Dep Puan']}p)")
                        st.markdown(f"**Form:** {row['Ev']} ({row['Ev Form']}) - {row['Dep']} ({row['Dep Form']})")
                        st.divider()
                        st.markdown("🎯 **Güvenilir Bahisler:**")
                        for firsat in firsatlar:
                            st.success(firsat)

            # Bilgisayar için Excel İndirme Butonu ve Tablo
            st.divider()
            st.markdown("### 💻 Tüm Veriler (Detaylı Analiz İçin)")
            st.dataframe(df)
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            
            st.download_button(
                label="📥 Tüm Verileri Excel Olarak İndir",
                data=buffer.getvalue(),
                file_name=f"GMAC_v10.48_{secim}_{datetime.now().strftime('%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("Seçilen tarihte taranacak maç bulunamadı.")
