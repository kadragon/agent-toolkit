#!/usr/bin/env python3
"""Sample personas from nvidia/Nemotron-Personas-Korea over HTTP (no full download).

Reads HuggingFace parquet shards directly via DuckDB httpfs with column
pushdown, so only the requested columns are fetched. A 1M-row dataset is
sampled in ~2s without persisting 2GB to disk.

Entry point (handles the duckdb dependency itself):
    uv run --with duckdb python sample_personas.py <subcommand> ...

Subcommands:
    distinct --field <name>
        Print the exact categorical values for a low-cardinality field.
        Use this to validate WHERE literals before sampling — the Korean
        category strings are not guessable (e.g. province is '경상북', not '경북').

    sample --n <N> [--where "<sql>"] [--shard <0-8|all>] [--seed <int>]
        Return N random personas as a JSON array. Each shard holds ~111k
        personas; one shard is plenty for a diverse panel and is the default.
        Reports matched-row count to stderr and warns if fewer than N match,
        rather than silently returning a short panel.
"""
import argparse
import json
import sys

BASE = "https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea/resolve/main/data"
SHARD = "train-{:05d}-of-00009.parquet"
N_SHARDS = 9

# Fields fed to each debater. Narrative fields first (rich, idiosyncratic
# detail fights caricature); structured demographics last (for the panel
# composition summary, not for stereotyping).
DEBATER_FIELDS = [
    "persona",
    "professional_persona",
    "family_persona",
    "cultural_background",
    "hobbies_and_interests",
    "skills_and_expertise",
    "career_goals_and_ambitions",
    "sex", "age", "marital_status", "occupation",
    "education_level", "bachelors_field",
    "district", "province", "housing_type", "family_type",
]

# Low-cardinality fields whose exact literals the caller may need. occupation,
# district, family_type are higher-cardinality — query them with distinct too
# if needed, but expect long lists.
DISTINCTABLE = [
    "sex", "marital_status", "military_status", "education_level",
    "bachelors_field", "province", "housing_type", "family_type", "district",
]


def connect():
    try:
        import duckdb
    except ImportError:
        sys.exit("duckdb not importable — run via: uv run --with duckdb python sample_personas.py ...")
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    return con


def shard_urls(shard):
    if shard == "all":
        return [f"{BASE}/{SHARD.format(i)}" for i in range(N_SHARDS)]
    try:
        idx = int(shard)
    except (TypeError, ValueError):
        sys.exit("--shard must be an integer 0-8 or 'all'")
    if not 0 <= idx < N_SHARDS:
        sys.exit(f"--shard out of range: {idx} (valid 0-{N_SHARDS - 1} or 'all')")
    return [f"{BASE}/{SHARD.format(idx)}"]


def src(shard):
    urls = shard_urls(shard)
    lst = ", ".join(f"'{u}'" for u in urls)
    return f"read_parquet([{lst}])"


def cmd_distinct(args):
    if args.field not in DISTINCTABLE:
        print(f"warn: {args.field} may be high-cardinality", file=sys.stderr)
    con = connect()
    rows = con.execute(
        f"SELECT DISTINCT {args.field} FROM {src(args.shard)} WHERE {args.field} IS NOT NULL ORDER BY 1"
    ).fetchall()
    vals = [r[0] for r in rows]
    print(json.dumps({"field": args.field, "count": len(vals), "values": vals}, ensure_ascii=False, indent=2))


def cmd_sample(args):
    con = connect()
    where = args.where.strip() if args.where else "TRUE"
    source = src(args.shard)

    if args.fields:
        fields = [f.strip() for f in args.fields.split(",") if f.strip()]
        bad = [f for f in fields if f not in DEBATER_FIELDS]
        if bad:
            sys.exit(f"unknown --fields: {bad}; valid: {DEBATER_FIELDS}")
    else:
        fields = DEBATER_FIELDS

    matched = con.execute(f"SELECT count(*) FROM {source} WHERE {where}").fetchone()[0]
    print(f"matched rows: {matched}", file=sys.stderr)
    if matched == 0:
        sys.exit("no rows match the filter — check categorical literals with the `distinct` subcommand")
    if matched < args.n:
        print(f"WARN: only {matched} match (< requested {args.n}); returning all matches", file=sys.stderr)

    # setseed must run as its own statement (`SELECT setseed(...)`); DuckDB rejects
    # a bare `setseed(...);` prefix. Seeds random() for the ORDER BY that follows on
    # the same connection.
    if args.seed is not None:
        con.execute(f"SELECT setseed({(args.seed % 1000) / 1000.0})")
    cols = ", ".join(fields)
    rows = con.execute(
        f"SELECT {cols} FROM {source} WHERE {where} ORDER BY random() LIMIT {args.n}"
    ).fetchall()
    out = [dict(zip(fields, r)) for r in rows]
    print(json.dumps(out, ensure_ascii=False, indent=2))


# Deterministic depth -> panel plan. Single source of truth for "never opus"
# and the round/model routing, so the running model can't drift into opus or
# misremember the table.
DEPTH_PLAN = {
    "simple": {"n": 4, "run_round1": False, "opening_model": "haiku", "rebuttal_model": "haiku"},
    "normal": {"n": 6, "run_round1": True,  "opening_model": "haiku", "rebuttal_model": "sonnet"},
    "deep":   {"n": 8, "run_round1": True,  "opening_model": "sonnet", "rebuttal_model": "sonnet"},
}


def cmd_plan(args):
    if args.depth not in DEPTH_PLAN:
        sys.exit(f"depth must be one of {list(DEPTH_PLAN)}")
    plan = dict(DEPTH_PLAN[args.depth])
    if args.n is not None:
        plan["n"] = args.n
    # devil's-advocate seat always gets the stronger model; opus never appears.
    plan["devil_advocate_model"] = "sonnet"
    plan["depth"] = args.depth
    print(json.dumps(plan, ensure_ascii=False, indent=2))


def cmd_roster(_args):
    """Format a sampled-panel JSON (stdin) into the synthesis roster + attribution.
    Deterministic — keeps the moderator from miscounting or mis-formatting."""
    import re
    data = json.load(sys.stdin)
    lines = []
    for p in data:
        # Names aren't a structured field; they lead the persona prose
        # ("양기우 씨는 …"). Pull it so the roster matches the named debate body.
        m = re.match(r"\s*([가-힣]{2,4})\s*씨", p.get("persona", ""))
        name = (m.group(1) + " · ") if m else ""
        bits = [f"{p.get('age','?')}세", p.get("sex", ""), p.get("province", ""), p.get("occupation", "")]
        lines.append(f"- {name}" + " · ".join(b for b in bits if b))
    print("\n".join(lines))
    print("personas: nvidia/Nemotron-Personas-Korea (CC-BY-4.0)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("distinct", help="list exact categorical values for a field")
    d.add_argument("--field", required=True)
    d.add_argument("--shard", default="0", help="shard index 0-8 (default 0); 'all' for full scan")
    d.set_defaults(func=cmd_distinct)

    s = sub.add_parser("sample", help="sample N random personas as JSON")
    s.add_argument("--n", type=int, default=6)
    s.add_argument("--where", default=None, help="SQL WHERE clause body, e.g. \"age BETWEEN 20 AND 39 AND province IN ('서울','경기')\"")
    s.add_argument("--fields", default=None, help="CSV subset of debater fields to return (default: curated full set); trim to the topic to cut spawn tokens")
    s.add_argument("--shard", default="0", help="shard index 0-8 (default 0); 'all' for full 1M scan (~18s)")
    s.add_argument("--seed", type=int, default=None, help="seed random() for sampling; not fully reproducible over HTTP (parquet fetch order varies)")
    s.set_defaults(func=cmd_sample)

    pl = sub.add_parser("plan", help="deterministic N + round + model routing for a depth (never opus)")
    pl.add_argument("--depth", required=True, help="simple | normal | deep")
    pl.add_argument("--n", type=int, default=None, help="override N (e.g. user gave a number)")
    pl.set_defaults(func=cmd_plan)

    r = sub.add_parser("roster", help="format sampled-panel JSON (stdin) into synthesis roster + attribution")
    r.set_defaults(func=cmd_roster)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
