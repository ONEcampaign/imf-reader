"""Generates ``src/imf_reader/weo/vocabulary.py`` from live IMF data.

Not shipped in the wheel. Run manually with::

    uv run python scripts/build_weo_vocabulary.py

It downloads every fetchable WEO SDMX bulk release plus the April 2025 API
frame (the one release available through both paths), derives the legacy
(numeric area code, single-letter unit) vocabulary's forward mapping onto the
api.imf.org vocabulary (ISO3 area codes, semantic units), and writes the
result as a Python module of literal dicts.

Re-run only if a WEO release is ever added. The bulk SDMX archive was
discontinued after April 2025, so the legacy side of the vocabulary is
closed: the eleven releases below are the complete set this script will ever
need to consider.
"""

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from imf_reader.cache import set_cache_dir  # noqa: E402
from imf_reader.weo import Version  # noqa: E402
from imf_reader.weo.api import get_weo_data  # noqa: E402
from imf_reader.weo.parser import SDMXParser  # noqa: E402
from imf_reader.weo.scraper import SDMXScraper  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "src" / "imf_reader" / "weo" / "vocabulary.py"
GENERATOR_NAME = "scripts/build_weo_vocabulary.py"

# The thirteen WEO SDMX bulk releases the IMF ever published, minus the two
# that are corrupt in the IMF's own archive (bad CRC-32 on the inner XML,
# stable across re-downloads: October 2023 and April 2021). April 2025 is the
# one release also servable through the API, and is used below as the join
# anchor between the two vocabularies.
FETCHABLE_RELEASES: tuple[Version, ...] = (
    ("April", 2019),
    ("October", 2019),
    ("April", 2020),
    ("October", 2020),
    ("October", 2021),
    ("April", 2022),
    ("October", 2022),
    ("April", 2023),
    ("April", 2024),
    ("October", 2024),
    ("April", 2025),
)

API_ANCHOR_VERSION: Version = ("April", 2025)

# Legacy area codes seen in the SDMX bulk data with no April 2025 API
# counterpart. All four are aggregates, so they get a synthetic code
# following the API's own convention for aggregates: "G" + the zero-padded
# 3-digit IMF numeric code.
LEGACY_ONLY_AREA_CODES = frozenset({406, 440, 511, 901})

# Hand-maintained resolutions for (CONCEPT_CODE, legacy UNIT_CODE) pairs that
# neither the April 2025 join nor the unit-label heuristic (see
# resolve_via_label) can settle on their own. A string value is the API unit
# to translate the pair to. A value of None is a considered decision that no
# API unit exists for the pair -- not a placeholder -- and the generator
# collects those into UNIT_PAIRS_WITH_NO_API_UNIT rather than guessing one.
UNIT_OVERRIDES: dict[tuple[str, str], str | None] = {
    # LE ("Employment"), legacy unit letter "N" ("Persons"). CL_UNIT has an
    # exact match: "PE" = "Persons". LE letter "C" ("Index, 2000=100")
    # resolves automatically via the label heuristic.
    ("LE", "N"): "PE",
    # LP ("Population"), legacy unit letter "N" ("Persons"). Same as LE/N.
    ("LP", "N"): "PE",
    # NGDPRPPPPC, PPPEX, PPPGDP, PPPPC: four PPP / "international dollar"
    # denominated concepts. April 2025's API rows for these carry a real
    # OBS_VALUE but a null UNIT on every single row (verified against the raw
    # CSV, not just the aligned frame), and CL_UNIT (IMF/CL_UNIT) has no code
    # at all for "purchasing power parity" or "international dollar" --
    # there is no correct API unit to translate to, so these are deliberately
    # null rather than invented.
    ("NGDPRPPPPC", "S"): None,
    ("PPPEX", "F"): None,
    ("PPPGDP", "T"): None,
    ("PPPPC", "T"): None,
    # PSUGAEEC ("Sugar, European Union, U.S. cents per pound"), legacy unit
    # letter "O" ("U.S. cents"). Ambiguous between USCPL and USCPP at the
    # label level, but moot: every observed row for this pair has a null
    # OBS_VALUE across every release that carries it, so it never actually
    # needs a translation once null observations are dropped. Deliberately
    # null rather than guessed.
    ("PSUGAEEC", "O"): None,
}


def fetch_sdmx_frames() -> dict[Version, pd.DataFrame]:
    """Download and parse every fetchable SDMX release, dropping null observations."""
    frames = {}
    for month, year in FETCHABLE_RELEASES:
        print(f"Fetching SDMX {month} {year}...")
        zf = SDMXScraper.scrape(month, year)
        df = SDMXParser.parse(zf)
        frames[(month, year)] = df.dropna(subset=["OBS_VALUE", "REF_AREA_CODE"])
    return frames


def _fingerprint(
    df: pd.DataFrame, area_col: str
) -> dict[str, frozenset[tuple[str, float]]]:
    """Per-area signature of (CONCEPT_CODE, TIME_PERIOD) -> OBS_VALUE, rounded to 4dp.

    Area codes come back as ``str`` regardless of the column's own dtype
    (``Int64`` on the SDMX side, ``string`` on the API side): pandas'
    ``groupby`` key type isn't precise enough for a type checker to narrow,
    so the boundary conversion happens once, here, rather than at every call
    site.
    """
    df = df.copy()
    df["_key"] = df["CONCEPT_CODE"] + "|" + df["TIME_PERIOD"].astype(str)
    df["_val"] = df["OBS_VALUE"].astype(float).round(4)
    return {
        str(area): frozenset(zip(group["_key"], group["_val"]))
        for area, group in df.groupby(area_col)
    }


def derive_area_map(
    sdmx_apr2025: pd.DataFrame, api_apr2025: pd.DataFrame
) -> dict[int, str]:
    """Join April 2025 SDMX and API frames on a per-area value fingerprint.

    Both frames cover the same release, so every legacy numeric area code
    should land on exactly one API code by matching the set of values each
    area reports. Areas the anchor release doesn't carry (the four
    legacy-only aggregates) are resolved separately in resolve_area_codes.
    """
    sdmx_fp = _fingerprint(sdmx_apr2025, "REF_AREA_CODE")
    api_fp = _fingerprint(api_apr2025, "REF_AREA_CODE")

    area_map: dict[int, str] = {}
    ambiguous = []
    for legacy_code, legacy_sig in sdmx_fp.items():
        scored = sorted(
            (
                (
                    len(legacy_sig & api_sig) / max(1, len(legacy_sig)),
                    len(legacy_sig & api_sig),
                    api_code,
                )
                for api_code, api_sig in api_fp.items()
                if legacy_sig & api_sig
            ),
            reverse=True,
        )
        if not scored:
            continue  # expected to resolve via the legacy-only aggregate list later
        best = scored[0]
        runner_up = scored[1] if len(scored) > 1 else (0.0, 0, None)
        if best[0] >= 0.90 and best[0] - runner_up[0] > 0.3:
            area_map[int(legacy_code)] = best[2]
        else:
            ambiguous.append((int(legacy_code), scored[:3]))

    if ambiguous:
        print("Ambiguous area matches (needs human review):")
        for legacy_code, candidates in ambiguous:
            print(f"  {legacy_code}: {candidates}")
        raise SystemExit("Aborting: ambiguous area match(es) found.")

    if len(set(area_map.values())) != len(area_map):
        raise SystemExit("Aborting: area map is not 1:1 (duplicate API targets).")

    return area_map


def resolve_area_codes(
    frames: dict[Version, pd.DataFrame], area_map: dict[int, str]
) -> tuple[dict[int, str], dict[str, str]]:
    """Extend area_map with the legacy-only aggregates, and collect their labels.

    Scans every release for the full set of legacy area codes in use. Any
    code that's neither in area_map nor one of the four known legacy-only
    aggregates is a hard failure: it would be a fifth code the design didn't
    account for.
    """
    all_codes: set[int] = set()
    labels: dict[int, str] = {}
    for df in frames.values():
        pairs = df[["REF_AREA_CODE", "REF_AREA_LABEL"]].drop_duplicates()
        for code, label in pairs.itertuples(index=False):
            code = int(code)
            all_codes.add(code)
            if label and code not in labels:
                labels[code] = label

    unresolved = all_codes - area_map.keys()
    unexpected = unresolved - LEGACY_ONLY_AREA_CODES
    if unexpected:
        print(
            f"Legacy area codes with no mapping and no known synthetic slot: {sorted(unexpected)}"
        )
        raise SystemExit("Aborting: unmapped legacy area code(s) found.")

    api_targets = set(area_map.values())
    legacy_only_labels: dict[str, str] = {}
    extended_map = dict(area_map)
    for code in sorted(LEGACY_ONLY_AREA_CODES):
        synthetic = f"G{code:03d}"
        if synthetic in api_targets:
            raise SystemExit(
                f"Aborting: synthetic code {synthetic} for legacy area {code} "
                "collides with a real API area code."
            )
        extended_map[code] = synthetic
        legacy_only_labels[synthetic] = labels[code]

    return extended_map, legacy_only_labels


def strict_inverse(mapping: dict[int, str]) -> dict[str, int]:
    """Invert a 1:1 dict, failing loudly on any collision."""
    inverse: dict[str, int] = {}
    for legacy, api in mapping.items():
        if api in inverse:
            raise SystemExit(
                f"Aborting: API area code {api!r} claimed by both "
                f"{inverse[api]} and {legacy}."
            )
        inverse[api] = legacy
    return inverse


def derive_unit_map(
    sdmx_apr2025: pd.DataFrame,
    api_apr2025: pd.DataFrame,
    area_map: dict[int, str],
) -> tuple[dict[tuple[str, str], str], list[tuple[tuple[str, str], set[str]]]]:
    """Join April 2025 SDMX rows to API rows on (concept, area, time, value).

    Keyed on (CONCEPT_CODE, legacy UNIT_CODE) rather than concept alone: LE
    and NGDP_D each carry two legacy units, and the row-level join resolves
    them correctly because the area each unit is attached to differs.
    """
    sdmx = sdmx_apr2025.copy()
    sdmx["_api_area"] = sdmx["REF_AREA_CODE"].map(lambda c: area_map.get(int(c)))
    sdmx = sdmx.dropna(subset=["_api_area"])
    sdmx["_key"] = (
        sdmx["CONCEPT_CODE"]
        + "|"
        + sdmx["_api_area"]
        + "|"
        + sdmx["TIME_PERIOD"].astype(str)
    )
    sdmx["_val"] = sdmx["OBS_VALUE"].astype(float).round(4)

    api = api_apr2025.copy()
    api["_key"] = (
        api["CONCEPT_CODE"]
        + "|"
        + api["REF_AREA_CODE"]
        + "|"
        + api["TIME_PERIOD"].astype(str)
    )
    api["_val"] = api["OBS_VALUE"].astype(float).round(4)

    merged = sdmx.merge(
        api[["_key", "_val", "UNIT_CODE"]], on="_key", suffixes=("_legacy", "_api")
    )
    matched = merged[merged["_val_legacy"] == merged["_val_api"]]
    # A handful of API indicators (LE, LP, LUR, ...) carry a value but no UNIT at
    # all -- a gap in the live API data, not a join failure. Treat "matched a row
    # with no unit" the same as "no match": fall through to the label heuristic
    # or an override rather than writing a null into the generated table.
    matched = matched.dropna(subset=["UNIT_CODE_api"])

    pair_targets: dict[tuple[str, str], set[str]] = {}
    grouped = matched.groupby(["CONCEPT_CODE", "UNIT_CODE_legacy"])[
        "UNIT_CODE_api"
    ].unique()
    for pair, targets in grouped.items():
        pair_targets[pair] = set(targets)

    ambiguous = [
        (pair, targets) for pair, targets in pair_targets.items() if len(targets) > 1
    ]
    unit_map = {
        pair: next(iter(targets))
        for pair, targets in pair_targets.items()
        if len(targets) == 1
    }
    return unit_map, ambiguous


def resolve_via_label(letter_label: str) -> str | None:
    """Map a legacy unit letter's description to an API unit.

    Only for pairs the April 2025 join can't reach -- the concept or that
    specific letter doesn't appear in April 2025 data (e.g. a commodity index
    concept that has since rolled to a new base-year letter, or a percent-change
    concept retired before April 2025). Handles only the unambiguous phrasings
    ("Percent", "...percent change", "Index, <base year>=100"); anything else
    needs UNIT_OVERRIDES.
    """
    lowered = letter_label.lower()
    if "percent" in lowered:
        return "PT"
    if "index" in lowered:
        return "IX"
    return None


def resolve_unit_pairs(
    frames: dict[Version, pd.DataFrame],
    unit_map: dict[tuple[str, str], str],
) -> tuple[dict[tuple[str, str], str], frozenset[tuple[str, str]]]:
    """Extend unit_map to cover every (concept, legacy unit letter) pair in any release.

    Returns the extended map and the pairs a UNIT_OVERRIDES entry has
    deliberately decided have no API unit (destined for
    UNIT_PAIRS_WITH_NO_API_UNIT, not the map).
    """
    resolved = dict(unit_map)
    unexplained: list[tuple[str, str]] = []

    all_pairs: set[tuple[str, str]] = set()
    labels: dict[tuple[str, str], str] = {}
    for df in frames.values():
        rows = df[["CONCEPT_CODE", "UNIT_CODE", "UNIT_LABEL"]].drop_duplicates()
        for concept, letter, label in rows.itertuples(index=False):
            pair = (concept, letter)
            all_pairs.add(pair)
            labels.setdefault(pair, label)

    for pair in sorted(all_pairs - resolved.keys()):
        via_label = resolve_via_label(labels[pair])
        if via_label is not None:
            resolved[pair] = via_label
            continue
        if pair in UNIT_OVERRIDES:
            override = UNIT_OVERRIDES[pair]
            if override is not None:
                resolved[pair] = override
            continue
        unexplained.append(pair)

    if unexplained:
        print("Unresolved (concept, unit) pairs (needs a UNIT_OVERRIDES entry):")
        for pair in unexplained:
            print(f"  {pair}: {labels[pair]!r}")
        raise SystemExit("Aborting: unresolved unit pair(s) found.")

    # A None override is a decision, not just an absence, so every one of them
    # belongs in the null set -- including PSUGAEEC/O, which is never observed
    # with a non-null OBS_VALUE and so never reaches the loop above at all.
    null_pairs = frozenset(
        pair for pair, target in UNIT_OVERRIDES.items() if target is None
    )
    return resolved, null_pairs


def _format_dict_literal(
    name: str, annotation: str, items: list[tuple[str, str]]
) -> str:
    """Render `name: annotation = {...}`, one key: value pair per line."""
    lines = [f"{name}: {annotation} = {{"]
    for key_repr, value_repr in items:
        lines.append(f"    {key_repr}: {value_repr},")
    lines.append("}")
    return "\n".join(lines)


def _format_frozenset_literal(name: str, annotation: str, items: list[str]) -> str:
    """Render `name: annotation = frozenset({...})`, one item per line."""
    lines = [f"{name}: {annotation} = frozenset({{"]
    for item_repr in items:
        lines.append(f"    {item_repr},")
    lines.append("})")
    return "\n".join(lines)


def render_module(
    area_map: dict[int, str],
    unit_map: dict[tuple[str, str], str],
    unit_pairs_with_no_api_unit: frozenset[tuple[str, str]],
    legacy_only_labels: dict[str, str],
    api_to_legacy: dict[str, int],
) -> str:
    """Render the generated vocabulary module as literal Python source."""
    header = (
        '"""Static translation tables between the legacy SDMX WEO vocabulary and '
        "the api.imf.org vocabulary.\n\n"
        f"Generated by {GENERATOR_NAME} from live IMF data -- do not hand-edit. "
        "Re-run the\ngenerator if a WEO release is ever added; the bulk SDMX archive "
        "was\ndiscontinued after April 2025, so the legacy side is closed.\n\n"
        "LEGACY_UNIT_TO_API omits every pair in UNIT_PAIRS_WITH_NO_API_UNIT. That "
        "frozenset\nmeans the IMF's own api.imf.org publishes no unit for the "
        "concept -- not that this\ntable failed to work one out. Treat membership "
        'in it as a deliberate null, not an error.\n"""\n'
    )

    area_block = _format_dict_literal(
        "LEGACY_AREA_TO_API",
        "dict[int, str]",
        [(repr(k), repr(v)) for k, v in sorted(area_map.items())],
    )
    unit_block = _format_dict_literal(
        "LEGACY_UNIT_TO_API",
        "dict[tuple[str, str], str]",
        [(repr(k), repr(v)) for k, v in sorted(unit_map.items())],
    )
    no_unit_block = _format_frozenset_literal(
        "UNIT_PAIRS_WITH_NO_API_UNIT",
        "frozenset[tuple[str, str]]",
        [repr(pair) for pair in sorted(unit_pairs_with_no_api_unit)],
    )
    labels_block = _format_dict_literal(
        "LEGACY_ONLY_AREA_LABELS",
        "dict[str, str]",
        [(repr(k), repr(v)) for k, v in sorted(legacy_only_labels.items())],
    )
    inverse_block = _format_dict_literal(
        "API_AREA_TO_LEGACY",
        "dict[str, int]",
        [(repr(k), repr(v)) for k, v in sorted(api_to_legacy.items())],
    )

    return (
        "\n\n".join(
            [header, area_block, unit_block, no_unit_block, labels_block, inverse_block]
        )
        + "\n"
    )


def main() -> None:
    # Redirect to a scratch cache so this doesn't collide with the user's real
    # cache or with other work happening in the package concurrently.
    set_cache_dir(REPO_ROOT / ".cache" / "weo_vocabulary_build")

    frames = fetch_sdmx_frames()
    sdmx_apr2025 = frames[API_ANCHOR_VERSION]

    print(f"Fetching API {API_ANCHOR_VERSION[0]} {API_ANCHOR_VERSION[1]}...")
    api_apr2025 = get_weo_data(API_ANCHOR_VERSION).dropna(subset=["OBS_VALUE"])

    area_map = derive_area_map(sdmx_apr2025, api_apr2025)
    print(f"Area fingerprint join: {len(area_map)} matched 1:1.")

    area_map, legacy_only_labels = resolve_area_codes(frames, area_map)
    print(
        f"Legacy-only aggregates assigned synthetic codes: {sorted(legacy_only_labels)}"
    )

    api_to_legacy = strict_inverse(area_map)

    unit_map, unit_ambiguous = derive_unit_map(sdmx_apr2025, api_apr2025, area_map)
    if unit_ambiguous:
        print("Ambiguous unit pairs from the April 2025 join (needs human review):")
        for pair, targets in unit_ambiguous:
            print(f"  {pair}: {sorted(targets)}")
        raise SystemExit("Aborting: ambiguous unit pair(s) found.")
    print(f"Unit pairs resolved via April 2025 join: {len(unit_map)}.")

    unit_map, unit_pairs_with_no_api_unit = resolve_unit_pairs(frames, unit_map)
    print(f"Unit pairs total after cross-release resolution: {len(unit_map)}.")
    print(
        f"Unit pairs with a deliberately null API unit: {len(unit_pairs_with_no_api_unit)}."
    )
    for pair in sorted(unit_pairs_with_no_api_unit):
        print(f"  {pair}")

    module_source = render_module(
        area_map,
        unit_map,
        unit_pairs_with_no_api_unit,
        legacy_only_labels,
        api_to_legacy,
    )
    OUTPUT_PATH.write_text(module_source)

    print(f"\nWrote {OUTPUT_PATH}")
    print(f"  LEGACY_AREA_TO_API: {len(area_map)} entries")
    print(f"  LEGACY_UNIT_TO_API: {len(unit_map)} entries")
    print(f"  UNIT_PAIRS_WITH_NO_API_UNIT: {len(unit_pairs_with_no_api_unit)} entries")
    print(f"  LEGACY_ONLY_AREA_LABELS: {len(legacy_only_labels)} entries")
    print(f"  API_AREA_TO_LEGACY: {len(api_to_legacy)} entries")


if __name__ == "__main__":
    main()
