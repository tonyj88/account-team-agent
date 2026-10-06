"""`atb-tools`: the deterministic steps the /account-plan skill runs through Bash."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from atb.catalog import Catalog, load_catalog
from atb.derive import growth_gap, next_review, parse_date, parse_usd
from atb.diff import diff_markdown, diff_plans
from atb.plan import Candidates, Evidence, Plan, PlanValue
from atb.reconcile import drift_markdown, reconcile
from atb.render import evidence_markdown, render_docx
from atb.transcript import clean_vtt, to_text
from atb.validate import validate


def _load_plan(path: str | None) -> Plan | None:
    if not path:
        return None
    return Plan.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _derived(value: str, rule: str, as_of: date) -> PlanValue:
    return PlanValue(
        value=value,
        status="auto",
        sources=[Evidence(kind="derived", as_of=as_of, ref=rule)],
    )


def apply_derived(plan: Plan, catalog: Catalog) -> Plan:
    """Fill the system and derived Snapshot fields from values already in the plan."""
    fields = plan.fields
    today = plan.plan_date
    fields["snapshot.account"] = _derived(plan.account, "account name", today)
    fields["snapshot.plan_date"] = _derived(today.isoformat(), "plan date", today)

    def value(key: str) -> str | None:
        pv = fields.get(key)
        return pv.value if pv else None

    arr = parse_usd(value("snapshot.current_arr") or "")
    last = parse_date(value("snapshot.last_reviewed") or "") or today
    due = next_review(last, arr, catalog.refresh_policy)
    fields["snapshot.next_review"] = _derived(
        due.isoformat(), "last reviewed + cadence from Current ARR", today
    )
    gap = growth_gap(parse_usd(value("snapshot.target_arr_fy") or ""), arr)
    if gap is not None:
        fields["snapshot.growth_gap_usd"] = _derived(
            f"${gap:,.0f}", "Target ARR (FY) - Current ARR", today
        )
    return plan


def cmd_reconcile(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    cands = Candidates.model_validate_json(Path(args.candidates).read_text(encoding="utf-8"))
    plan = apply_derived(reconcile(cands, _load_plan(args.baseline), catalog), catalog)
    Path(args.out).write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    if args.drift:
        Path(args.drift).write_text(drift_markdown(plan), encoding="utf-8")
    needs = sum(v.status == "needs_approval" for v in plan.fields.values())
    print(f"{len(plan.fields)} fields, {needs} need approval, {len(plan.drift)} drift items")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    issues = validate(_load_plan(args.plan), plan_path.parent)
    for issue in issues:
        print(f"{issue.level}: {issue.where}: {issue.message}")
    errors = sum(i.level == "error" for i in issues)
    print(f"{errors} errors, {len(issues) - errors} warnings")
    return 1 if errors else 0


def cmd_render(args: argparse.Namespace) -> int:
    plan = _load_plan(args.plan)
    report = render_docx(plan, Path(args.template), Path(args.out))
    if args.evidence:
        Path(args.evidence).write_text(evidence_markdown(plan), encoding="utf-8")
    print(f"filled {len(report.filled)} fields; rows {report.rows_written}")
    for label in report.missing_labels:
        print(f"not placed (label not found in template): {label}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    print(diff_markdown(diff_plans(_load_plan(args.plan), _load_plan(args.baseline))))
    return 0


def cmd_transcript_clean(args: argparse.Namespace) -> int:
    turns = clean_vtt(
        Path(args.vtt).read_text(encoding="utf-8-sig"),
        internal_domains=args.internal_domain,
        internal_org_labels=args.internal_org,
    )
    Path(args.out).write_text(to_text(turns), encoding="utf-8")
    print(f"{len(turns)} turns written to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atb-tools", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("reconcile", help="candidates.json -> plan.json (+ sf_drift.md)")
    p.add_argument("candidates")
    p.add_argument("--baseline", help="previous approved plan.json")
    p.add_argument("--out", required=True)
    p.add_argument("--drift", help="where to write the Salesforce drift report")
    p.set_defaults(func=cmd_reconcile)

    p = sub.add_parser("validate", help="check sources, quotes, approvals and secrets")
    p.add_argument("plan")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("render", help="fill the Account Plan template")
    p.add_argument("plan")
    p.add_argument("--template", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--evidence", help="where to write the evidence file")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("diff", help="changes against the baseline plan")
    p.add_argument("plan")
    p.add_argument("--baseline")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("transcript-clean", help="Teams WEBVTT -> cleaned, speaker-tagged text")
    p.add_argument("vtt")
    p.add_argument("--out", required=True)
    p.add_argument("--internal-domain", action="append", default=[])
    p.add_argument("--internal-org", action="append", default=[])
    p.set_defaults(func=cmd_transcript_clean)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
