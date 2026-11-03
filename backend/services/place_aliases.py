"""Flag likely aliases conservatively; nearby distinct attractions stay distinct."""
import math
import re


def distance_meters(a, b):
    if any(x is None for x in (a.latitude, a.longitude, b.latitude, b.longitude)):
        return None
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat, dlon = lat2 - lat1, math.radians(b.longitude - a.longitude)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(min(1, value)))


def possible_alias_pairs(places):
    pairs = []
    for index, a in enumerate(places):
        a_words = re.findall(r"\w+", a.name.casefold())
        for b in places[index + 1:]:
            distance = distance_meters(a, b)
            if distance is None or distance > 40:
                continue
            b_words = re.findall(r"\w+", b.name.casefold())
            stepwell_words = {"stepwell", "kund", "baori", "baoli", "bawdi"}
            same_name = a_words == b_words
            stepwell_alias = bool(set(a_words) & stepwell_words) and bool(set(b_words) & stepwell_words)
            if same_name or stepwell_alias:
                pairs.append((a, b))
    return pairs
