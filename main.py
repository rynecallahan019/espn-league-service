import os
from fastapi import FastAPI, HTTPException, Header, Query
from espn_api.football import League

app = FastAPI(title="ESPN League Service")

LEAGUE_ID = int(os.environ.get("ESPN_LEAGUE_ID", "1754323"))
API_KEY   = os.environ.get("ESPN_API_KEY", "")   # optional; must match the x-api-key in WordPress
ESPN_S2   = os.environ.get("ESPN_S2", "")         # only needed for PRIVATE leagues
SWID      = os.environ.get("ESPN_SWID", "")       # only needed for PRIVATE leagues


def check_key(x_api_key: str):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def get_league(year: int) -> League:
    kwargs = {"league_id": LEAGUE_ID, "year": year}
    if ESPN_S2 and SWID:
        kwargs["espn_s2"] = ESPN_S2
        kwargs["swid"] = SWID
    return League(**kwargs)


def owner_name(team) -> str:
    owners = getattr(team, "owners", None)
    if not owners:
        return ""
    o = owners[0]
    if isinstance(o, dict):
        return (o.get("firstName", "") + " " + o.get("lastName", "")).strip()
    return str(o)


@app.get("/")
def health():
    return {"ok": True, "league_id": LEAGUE_ID}


@app.get("/teams")
def teams(year: int = Query(...), x_api_key: str = Header(default="")):
    check_key(x_api_key)
    try:
        league = get_league(year)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ESPN fetch failed for {year}: {e}")

    out = []
    for t in league.teams:
        out.append({
            "id":             t.team_id,
            "name":           t.team_name,
            "abbrev":         getattr(t, "team_abbrev", ""),
            "wins":           t.wins,
            "losses":         t.losses,
            "ties":           t.ties,
            "points_for":     t.points_for,
            "points_against": t.points_against,
            "standing":       getattr(t, "standing", 0),
            "final_standing": getattr(t, "final_standing", 0),
            "division_id":    getattr(t, "division_id", ""),
            "owner":          owner_name(t),
        })
    return out


@app.get("/draft")
def draft(year: int = Query(...), x_api_key: str = Header(default="")):
    check_key(x_api_key)
    try:
        league = get_league(year)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ESPN fetch failed for {year}: {e}")

    out = []
    for p in league.draft:
        team = getattr(p, "team", None)
        out.append({
            "round":         getattr(p, "round_num", 0),
            "pick_in_round": getattr(p, "round_pick", 0),
            "team_id":       team.team_id if team else 0,
            "team":          team.team_name if team else "",
            "player":        getattr(p, "playerName", ""),
            "player_id":     getattr(p, "playerId", 0),
        })
    return out


@app.get("/current-week")
def current_week(year: int = Query(...), x_api_key: str = Header(default="")):
    check_key(x_api_key)
    try:
        league = get_league(year)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ESPN fetch failed for {year}: {e}")
    return {"current_week": getattr(league, "current_week", 1)}


@app.get("/matchups")
def matchups(year: int = Query(...), week: int = Query(...), x_api_key: str = Header(default="")):
    check_key(x_api_key)
    try:
        league = get_league(year)
        board = league.scoreboard(week)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ESPN fetch failed for {year} week {week}: {e}")

    out = []
    for m in board:
        home = getattr(m, "home_team", None)
        away = getattr(m, "away_team", None)
        out.append({
            "week":          week,
            "home_team_id":  home.team_id if home else 0,
            "home_team":     home.team_name if home else "BYE",
            "home_score":    getattr(m, "home_score", 0),
            "away_team_id":  away.team_id if away else 0,
            "away_team":     away.team_name if away else "BYE",
            "away_score":    getattr(m, "away_score", 0),
        })
    return out


# ---------------------------------------------------------------------------
# Box scores: every player on each team's roster for one week (ESPN has these from 2019 on)
# ---------------------------------------------------------------------------
NON_STARTER_SLOTS = {"BE", "IR"}


def real_team(t):
    return t if hasattr(t, "team_id") else None


def num(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def player_row(p) -> dict:
    slot = str(getattr(p, "slot_position", "") or "")
    return {
        "player_id":     getattr(p, "playerId", 0),
        "name":          getattr(p, "name", ""),
        "position":      getattr(p, "position", ""),
        "slot":          slot,
        "starter":       slot not in NON_STARTER_SLOTS,
        "points":        num(getattr(p, "points", 0)),
        "projected":     num(getattr(p, "projected_points", 0)),
        "pro_team":      getattr(p, "proTeam", "") or "",
        "pro_opponent":  getattr(p, "pro_opponent", "") or "",
        "injury_status": str(getattr(p, "injuryStatus", "") or ""),
        "on_bye":        bool(getattr(p, "on_bye_week", False)),
    }


@app.get("/boxscores")
def boxscores(year: int = Query(...), week: int = Query(...), x_api_key: str = Header(default="")):
    check_key(x_api_key)
    if year < 2019:
        raise HTTPException(status_code=400, detail="ESPN has no box scores before 2019")
    try:
        league = get_league(year)
        boxes = league.box_scores(week)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ESPN box scores failed for {year} week {week}: {e}")

    out = []
    for b in boxes:
        home = real_team(getattr(b, "home_team", None))
        away = real_team(getattr(b, "away_team", None))
        out.append({
            "week":           week,
            "home_team_id":   home.team_id if home else 0,
            "home_team":      home.team_name if home else "BYE",
            "home_score":     num(getattr(b, "home_score", 0)),
            "home_projected": num(getattr(b, "home_projected", 0)),
            "home_lineup":    [player_row(p) for p in (getattr(b, "home_lineup", None) or [])] if home else [],
            "away_team_id":   away.team_id if away else 0,
            "away_team":      away.team_name if away else "BYE",
            "away_score":     num(getattr(b, "away_score", 0)),
            "away_projected": num(getattr(b, "away_projected", 0)),
            "away_lineup":    [player_row(p) for p in (getattr(b, "away_lineup", None) or [])] if away else [],
        })
    return out
