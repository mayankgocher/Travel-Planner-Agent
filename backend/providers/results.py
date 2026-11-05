"""One typed boundary for provider results and safe partial-result warnings."""
from dataclasses import dataclass, field


@dataclass
class SearchResult:
    items: list
    warnings: list[str]
    response_shape: dict
    skipped_records: list[dict] = field(default_factory=list)


def unpack_search(result):
    """Legacy fixture callbacks may still return a list."""
    return (result.items, list(result.warnings)) if isinstance(result, SearchResult) else (result, [])
