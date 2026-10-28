"""Free structured Census context, kept separate from underwriting inputs."""
import copy
import re
import time
from datetime import date, datetime, timezone

import httpx

STATES = dict(pair.split(":") for pair in "AL:01 AK:02 AZ:04 AR:05 CA:06 CO:08 CT:09 DE:10 DC:11 FL:12 GA:13 HI:15 ID:16 IL:17 IN:18 IA:19 KS:20 KY:21 LA:22 ME:23 MD:24 MA:25 MI:26 MN:27 MS:28 MO:29 MT:30 NE:31 NV:32 NH:33 NJ:34 NM:35 NY:36 NC:37 ND:38 OH:39 OK:40 OR:41 PA:42 RI:44 SC:45 SD:46 TN:47 TX:48 UT:49 VT:50 VA:51 WA:53 WV:54 WI:55 WY:56 PR:72".split())
VARIABLES = {"population": ("B01003_001E", "Population", "people"),
             "median_household_income": ("B19013_001E", "Median household income", "USD, dataset-year inflation adjusted")}
_cache = {}


def normalized_place(value):
    return re.sub(r"\s+(city|town|village|cdp|municipality|borough)$", "", value.split(",")[0].strip(), flags=re.I).casefold()


def estimate(value):
    try:
        number = float(value)
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


async def census_context(city, state):
    retrieved = datetime.now(timezone.utc).isoformat()
    empty = {"status": "unavailable", "observations": [], "retrieved_at": retrieved,
             "message": "An exact Census place match is required; no county or property estimate is substituted."}
    if not city or not state:
        return empty | {"message": "Add city and state to load public context."}
    key = (city.strip().casefold(), state.strip().casefold())
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < cached[1]:
        return copy.deepcopy(cached[2])
    result = empty
    async with httpx.AsyncClient(timeout=8) as client:
        for year in range(date.today().year - 2, date.today().year - 5, -1):
            base = f"https://api.census.gov/data/{year}/acs/acs5"
            try:
                fips = STATES.get(state.strip().upper())
                if not fips:
                    response = await client.get(base, params={"get": "NAME", "for": "state:*"})
                    response.raise_for_status()
                    rows = response.json()
                    found = [row for row in rows[1:] if row[0].casefold() == state.strip().casefold()]
                    if len(found) != 1:
                        return empty | {"message": "State was not uniquely identified. Use its two-letter abbreviation."}
                    fips = found[0][1]
                fields = ["NAME"] + [entry[0] for entry in VARIABLES.values()] + [entry[0][:-1] + "M" for entry in VARIABLES.values()]
                response = await client.get(base, params={"get": ",".join(fields), "for": "place:*", "in": f"state:{fips}"})
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                rows = response.json()
                records = [dict(zip(rows[0], row)) for row in rows[1:]]
                matches = [row for row in records if normalized_place(row["NAME"]) == normalized_place(city)]
                if len(matches) != 1:
                    result = empty | {"message": "City was not uniquely matched to a Census place. Check city/state; unincorporated areas may need a different geography.", "candidate_count": len(matches)}
                    break
                row = matches[0]
                observations = []
                for metric, (variable, label, unit) in VARIABLES.items():
                    source_url = str(httpx.URL(base, params={"get": f"NAME,{variable},{variable[:-1]}M", "for": f"place:{row['place']}", "in": f"state:{fips}"}))
                    observations.append({"metric": metric, "label": label, "value": estimate(row.get(variable)),
                        "margin_of_error": estimate(row.get(variable[:-1] + "M")), "confidence_level": "90%",
                        "unit": unit, "currency_year": year if metric == "median_household_income" else None,
                        "observed_period": f"{year-4}–{year}", "dataset_vintage": year,
                        "publication_date": None, "publication_date_status": "Not supplied by this adapter",
                        "retrieved_at": retrieved, "source": "US Census Bureau ACS 5-year",
                        "source_url": source_url, "geography_id": f"1600000US{fips}{row['place']}",
                        "geography_level": "place", "geography_name": row["NAME"],
                        "applicability": "Area demographics; not a property, neighborhood, rent comparable or sponsor assumption.",
                        "status": "source_reported" if estimate(row.get(variable)) is not None else "suppressed_or_unavailable"})
                result = {"status": "available", "observations": observations, "retrieved_at": retrieved,
                          "message": "Survey estimates over the stated five-year period; not current-year counts or property forecasts."}
                break
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                result = empty | {"message": "Census context could not be retrieved. Retry later; accepted deal facts are unaffected."}
                break
    if len(_cache) >= 256:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (time.monotonic(), 86400 if result["status"] == "available" else 900, copy.deepcopy(result))
    return result
