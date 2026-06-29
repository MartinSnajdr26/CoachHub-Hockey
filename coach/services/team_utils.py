from sqlalchemy import func


def normalize_team_name(name: str) -> str:
    return ' '.join((name or '').split()).strip().casefold()


def team_name_exists(name: str) -> bool:
    from coach.models import Team

    normalized = normalize_team_name(name)
    if not normalized:
        return False
    return Team.query.filter(func.lower(func.trim(Team.name)) == normalized).first() is not None
