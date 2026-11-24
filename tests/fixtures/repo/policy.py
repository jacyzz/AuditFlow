"""Sample role policy for the offline documentation fixture."""
def visible(role: str) -> bool:
    return role in {"viewer", "member"}
