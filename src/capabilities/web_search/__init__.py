def register(api_key: str, model: str, tz, daily_limit: int) -> None:
    from src.capabilities.web_search import tools

    tools.configure(api_key, model, tz, daily_limit)
