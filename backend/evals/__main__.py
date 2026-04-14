"""CLI entry point for running evals.

Usage:
    # Run custom cases (reads provider/model/key from .env)
    python -m evals

    # Run specific custom cases
    python -m evals --cases dev_snake_game dev_todo_api

    # Run only cases for a single capability
    python -m evals --capability developer_agent

    # Run every case 3 times to expose variance
    python -m evals --runs 3

    # Snapshot current behaviour as a baseline for A/B comparison
    python -m evals --runs 3 --save-baseline pre_refactor

    # After changes, compare to the baseline (McNemar significance test)
    python -m evals --runs 3 --compare-to pre_refactor

    # Run GAIA benchmark (10 Level-1 questions by default)
    python -m evals --gaia

    # Run GAIA Level 2, limit 5 questions
    python -m evals --gaia --gaia-level 2 --gaia-limit 5

    # Run both custom + GAIA
    python -m evals --all

    # Override provider/model via CLI
    python -m evals --gaia --provider anthropic --model claude-sonnet-4-20250514

    # List available custom cases
    python -m evals --list
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add backend root to path so `app` and `evals` are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env before any app imports so env vars are available
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from evals.runner import run_all_evals, save_report, CASES_PATH

# Map EVAL_PROVIDER to the env var name for the API key
_PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def _resolve_api_key(provider: str, cli_key: str | None) -> str | None:
    """CLI flag > provider-specific env var > None."""
    if cli_key:
        return cli_key
    env_name = _PROVIDER_KEY_MAP.get(provider)
    if env_name:
        return os.environ.get(env_name)
    return None


def _list_cases():
    import yaml
    cases = yaml.safe_load(CASES_PATH.read_text())
    print(f"\nAvailable custom eval cases ({len(cases)}):\n")
    for c in cases:
        kind = c.get("expected", {}).get("classification", "?")
        print(f"  {c['id']:<35} [{kind:<7}]  {c.get('description', '')}")
    print(f"\nGAIA benchmark:")
    print(f"  Use --gaia to run (requires HuggingFace access)")
    print(f"  Use --gaia-level 1|2|3 to filter by difficulty")
    print(f"  Use --gaia-limit N to limit number of questions")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Cape Agent Evaluation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables (set in .env):\n"
            "  EVAL_PROVIDER    LLM provider        (default: openai)\n"
            "  EVAL_MODEL       Model name           (default: gpt-4o)\n"
            "  EVAL_API_BASE    Custom API base URL  (optional)\n"
            "  OPENAI_API_KEY   OpenAI API key\n"
            "  ANTHROPIC_API_KEY  Anthropic API key\n"
            "  HF_TOKEN         HuggingFace token (for GAIA dataset)\n"
        ),
    )
    parser.add_argument("--provider", default=None, help="LLM provider (overrides EVAL_PROVIDER)")
    parser.add_argument("--model", default=None, help="Model name (overrides EVAL_MODEL)")
    parser.add_argument("--api-key", default=None, help="API key (overrides env var)")
    parser.add_argument("--api-base", default=None, help="Custom API base URL")
    parser.add_argument("--cases", nargs="*", default=None, help="Specific custom case IDs to run")
    parser.add_argument("--capability", default=None, help="Filter cases by capability tag")
    parser.add_argument("--runs", type=int, default=1, help="Runs per case (default: 1, recommend 3+ for variance)")
    parser.add_argument("--save-baseline", default=None, metavar="TAG", help="Save results as a named baseline")
    parser.add_argument("--compare-to", default=None, metavar="TAG", help="Compare current results to a saved baseline")
    parser.add_argument("--gaia", action="store_true", help="Run GAIA benchmark")
    parser.add_argument("--gaia-level", type=int, choices=[1, 2, 3], default=None, help="GAIA difficulty level")
    parser.add_argument("--gaia-limit", type=int, default=10, help="Max GAIA questions to run (default: 10)")
    parser.add_argument("--all", action="store_true", help="Run both custom cases and GAIA")
    parser.add_argument("--list", action="store_true", help="List available cases and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.runs < 1:
        print("Error: --runs must be >= 1", file=sys.stderr)
        sys.exit(1)

    if args.list:
        _list_cases()
        return

    # Decide what to run
    run_custom = not args.gaia or args.all  # default: run custom
    run_gaia = args.gaia or args.all

    # If --cases is explicitly given, only run custom
    if args.cases:
        run_custom = True
        run_gaia = False

    # Resolve config: CLI flag > env var > default
    provider = args.provider or os.environ.get("EVAL_PROVIDER", "openai")
    model = args.model or os.environ.get("EVAL_MODEL", "gpt-4o")
    api_base = args.api_base or os.environ.get("EVAL_API_BASE")
    api_key = _resolve_api_key(provider, args.api_key)

    if not api_key:
        env_name = _PROVIDER_KEY_MAP.get(provider, f"{provider.upper()}_API_KEY")
        print(
            f"Error: No API key found for provider '{provider}'.\n"
            f"Set {env_name} in .env or pass --api-key.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Provider: {provider} | Model: {model}")
    if api_base:
        print(f"API Base: {api_base}")
    modes = []
    if run_custom:
        modes.append("custom")
    if run_gaia:
        modes.append("GAIA")
    print(f"Mode: {' + '.join(modes)}")

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("camel").setLevel(logging.WARNING)

    async def _run():
        custom_results = None
        gaia_results = None

        if run_custom:
            custom_results = await run_all_evals(
                provider=provider,
                model_name=model,
                api_key=api_key,
                api_base=api_base,
                case_ids=args.cases,
                capability=args.capability,
                n_runs=args.runs,
            )

            if args.save_baseline:
                from evals.comparison import save_baseline
                bpath = save_baseline(
                    custom_results, args.save_baseline,
                    provider=provider, model_name=model, n_runs=args.runs,
                )
                print(f"\nBaseline '{args.save_baseline}' saved: {bpath}")

            if args.compare_to:
                from evals.comparison import (
                    compare_reports, format_comparison, load_baseline,
                    save_comparison,
                )
                from evals.runner import REPORTS_DIR
                baseline = load_baseline(args.compare_to)
                comparison = compare_reports(baseline, custom_results)
                print()
                print(format_comparison(comparison))
                cpath = save_comparison(comparison, REPORTS_DIR)
                print(f"\nComparison saved: {cpath}")

        if run_gaia:
            from evals.gaia import run_gaia_eval
            gaia_results = await run_gaia_eval(
                provider=provider,
                model_name=model,
                api_key=api_key,
                api_base=api_base,
                level=args.gaia_level,
                limit=args.gaia_limit,
            )

        # Save combined report if both were run
        if run_custom and run_gaia:
            tag = "combined"
            report_path = save_report(
                provider=provider,
                model_name=model,
                custom_results=custom_results,
                gaia_results=gaia_results,
                n_runs=args.runs,
                tag=tag,
            )
            print(f"\nCombined report saved: {report_path}")

        elif run_gaia and gaia_results:
            report_path = save_report(
                provider=provider,
                model_name=model,
                gaia_results=gaia_results,
                tag="gaia",
            )
            print(f"\nGAIA report saved: {report_path}")

        return custom_results, gaia_results

    custom_results, gaia_results = asyncio.run(_run())

    # Exit code
    custom_ok = all(r.passed for r in custom_results) if custom_results else True
    gaia_ok = True  # GAIA is informational, don't fail CI on it
    sys.exit(0 if custom_ok else 1)


if __name__ == "__main__":
    main()
