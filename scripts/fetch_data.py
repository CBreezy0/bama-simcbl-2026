#!/usr/bin/env python3
"""
Fetch Alabama SimCBL data from SimSN API and write data/alabama.json.
Runs via GitHub Actions daily; also works locally.
"""
import json
import os
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

API   = "https://simbaseballapi-production.up.railway.app/api/v1"
ORG   = 34     # Alabama org_id
TEAM  = 184    # Alabama team_id
SEC   = "Southeastern Conference"
LEVEL = 3      # college level

YEAR_LABEL = {1: "FR", 2: "SO", 3: "JR", 4: "SR"}

def ovr_grade(n):
    if n is None: return "?"
    if n >= 90: return "A+"
    if n >= 85: return "A"
    if n >= 80: return "A-"
    if n >= 75: return "B+"
    if n >= 70: return "B"
    if n >= 65: return "B-"
    if n >= 60: return "C+"
    if n >= 55: return "C"
    if n >= 50: return "C-"
    if n >= 45: return "D+"
    if n >= 40: return "D"
    if n >= 35: return "D-"
    return "F"

def main():
    print("Fetching bootstrap data…")
    r = requests.get(f"{API}/bootstrap/landing/{ORG}?viewing_org_id={ORG}", timeout=30)
    r.raise_for_status()
    raw = r.json()

    # ── Roster ──────────────────────────────────────────────────────────────
    roster_raw = raw.get("RosterMap", {}).get(str(TEAM), [])
    roster = []
    for p in roster_raw:
        yr  = p.get("contract", {}).get("current_year", 4)
        pos = p.get("listed_position") or ("SP" if p.get("ptype") == "Pitcher" else "?")
        rat = p.get("ratings", {})
        pot = p.get("potentials", {})

        # best positional OVR for hitters, role OVR for pitchers
        if p.get("ptype") == "Pitcher":
            role_ovr = rat.get("sp_rating") if pos == "SP" else rat.get("rp_rating")
        else:
            candidates = [rat.get(k) for k in
                ("c_rating","1b_rating","2b_rating","3b_rating","ss_rating",
                 "lf_rating","cf_rating","rf_rating","dh_rating","fb_rating","sb_rating","tb_rating")
                if rat.get(k) is not None]
            role_ovr = max(candidates) if candidates else None

        roster.append({
            "id":          p.get("id"),
            "firstname":   p.get("firstname"),
            "lastname":    p.get("lastname"),
            "ptype":       p.get("ptype"),
            "pos":         pos,
            "ovr":         p.get("displayovr"),
            "ovr_grade":   ovr_grade(p.get("displayovr")),
            "role_ovr":    role_ovr,
            "role_grade":  ovr_grade(role_ovr),
            "year":        yr,
            "year_label":  YEAR_LABEL.get(yr, "SR"),
            "age":         p.get("age"),
            "bat_hand":    p.get("bat_hand"),
            "pitch_hand":  p.get("pitch_hand"),
            "height":      p.get("height"),
            "weight":      p.get("weight"),
            "recruit_stars": p.get("recruit_stars", 0),
            "is_injured":  p.get("is_injured", False),
            "injury_risk": p.get("injury_risk"),
            "signing_tendency": p.get("signing_tendency"),
            "pitch1_name": p.get("pitch1_name"),
            "pitch2_name": p.get("pitch2_name"),
            "pitch3_name": p.get("pitch3_name"),
            # current ratings (letter grades)
            "ratings": {
                "contact":    rat.get("contact_display"),
                "power":      rat.get("power_display"),
                "speed":      rat.get("speed_display"),
                "eye":        rat.get("eye_display"),
                "pendurance": rat.get("pendurance_display"),
                "pgenctrl":   rat.get("pgencontrol_display"),
                "throwpwr":   rat.get("pthrowpower_display"),
                "sequencing": rat.get("psequencing_display"),
                "pickoff":    rat.get("pickoff_display"),
                "sp_rating":  rat.get("sp_rating"),
                "rp_rating":  rat.get("rp_rating"),
            },
            # potentials
            "potentials": {
                "pendurance": pot.get("pendurance_pot"),
                "pgenctrl":   pot.get("pgencontrol_pot"),
                "throwpwr":   pot.get("pthrowpower_pot"),
                "sequencing": pot.get("psequencing_pot"),
                "pickoff":    pot.get("pickoff_pot"),
                "contact":    pot.get("contact_pot"),
                "power":      pot.get("power_pot"),
                "speed":      pot.get("speed_pot"),
            }
        })
    roster.sort(key=lambda p: (-(p["ovr"] or 0)))

    # ── Team map ─────────────────────────────────────────────────────────────
    team_map = {t["team_id"]: t for t in raw.get("AllTeams", [])}

    # ── Games ─────────────────────────────────────────────────────────────
    games = []
    for g in sorted(raw.get("AllGames", []), key=lambda x: (x["week"], x.get("game_day", ""))):
        ht = team_map.get(g["home_team_id"], {})
        at = team_map.get(g["away_team_id"], {})
        is_bama_home = g["home_team_id"] == TEAM
        opp_id  = g["away_team_id"] if is_bama_home else g["home_team_id"]
        opp     = team_map.get(opp_id, {})
        conf    = opp.get("conference", "")
        is_sec  = conf == SEC
        bama_score = g["home_score"] if is_bama_home else g["away_score"]
        opp_score  = g["away_score"] if is_bama_home else g["home_score"]

        games.append({
            "id":           g["id"],
            "week":         g["week"],
            "game_day":     g.get("game_day", "a"),
            "is_complete":  bool(g.get("is_complete")),
            "is_home":      is_bama_home,
            "bama_score":   bama_score,
            "opp_score":    opp_score,
            "won":          g.get("winning_team_id") == TEAM if g.get("is_complete") else None,
            "opp_id":       opp_id,
            "opp_abbrev":   opp.get("team_abbrev", "?"),
            "opp_name":     opp.get("team_full_name", "?"),
            "opp_conf":     conf,
            "is_sec":       is_sec,
            "game_type":    g.get("game_type", "regular"),
        })

    # ── Standings ────────────────────────────────────────────────────────────
    all_standings = raw.get("Standings", [])
    bama_st = next((s for s in all_standings if s["team_id"] == TEAM), {})
    sec_standings = sorted(
        [s for s in all_standings if s.get("conference") == SEC and s.get("team_level") == LEVEL],
        key=lambda s: (-s.get("wins", 0), s.get("losses", 0), s.get("games_back", 0))
    )

    ctx = raw.get("SeasonContext", {})

    # ── Output ────────────────────────────────────────────────────────────────
    out = {
        "updated_at":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "week":         ctx.get("current_week_index", 1),
        "season_year":  ctx.get("league_year", 2026),
        "record": {
            "wins":   bama_st.get("wins", 0),
            "losses": bama_st.get("losses", 0),
        },
        "conf_record": {
            "wins":   bama_st.get("conf_wins", 0),
            "losses": bama_st.get("conf_losses", 0),
        },
        "standing":      bama_st,
        "roster":        roster,
        "games":         games,
        "sec_standings": sec_standings,
    }

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", "alabama.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    w   = out["record"]["wins"]
    l   = out["record"]["losses"]
    cw  = out["conf_record"]["wins"]
    cl  = out["conf_record"]["losses"]
    print(f"✓ Written {out_path}")
    print(f"  Updated : {out['updated_at']}")
    print(f"  Week    : {out['week']}")
    print(f"  Record  : {w}–{l}  (SEC {cw}–{cl})")
    print(f"  Roster  : {len(roster)} players")
    print(f"  Games   : {len(games)}")
    print(f"  SEC     : {len(sec_standings)} teams")

if __name__ == "__main__":
    main()
