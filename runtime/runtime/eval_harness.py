"""Cross-backend eval harness for measuring local-vs-remote quality parity.

For each sample in an eval set, runs the agent twice — once forced to
Anthropic, once forced to Ollama — and emits a JSONL report we can diff.

Output contract: see `MODEL_ROUTING_CONTRACT.md` §6.

Usage (CLI registered in pyproject):

    quill-runtime eval-parity rfi-triage --inputs path/to/inputs.jsonl

Or in-process::

    from runtime.eval_harness import run_parity
    asyncio.run(run_parity("design-classifier", inputs=[...], out_dir=Path("./_eval_runs")))
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any

import structlog

from runtime.agent import Agent, AgentRun
from runtime.agent_loader import load_agent
from runtime.llm_client import LLMClient
from runtime.local_llm_client import LocalLLMClient
from runtime.model_router import ModelRouter

log = structlog.get_logger(__name__)


@dataclass
class EvalRecord:
    """One row of the eval JSONL output."""

    agent_id: str
    sample_id: str
    backend: str
    model: str
    validation_ok: bool
    validation_errors: list[str]
    lane_decision: str | None
    latency_ms: int
    input_tokens: int
    output_tokens: int
    fell_back: bool
    raw_text_preview: str
    output: dict[str, Any] | None


def _summarize(records: list[EvalRecord]) -> dict[str, Any]:
    by_backend: dict[str, list[EvalRecord]] = {}
    for r in records:
        by_backend.setdefault(r.backend, []).append(r)

    summary: dict[str, Any] = {"by_backend": {}, "agreement": {}}
    for backend, rows in by_backend.items():
        latencies = sorted(r.latency_ms for r in rows)
        n = max(1, len(rows))
        valid = sum(1 for r in rows if r.validation_ok)
        summary["by_backend"][backend] = {
            "count": len(rows),
            "valid_count": valid,
            "valid_pct": round(100.0 * valid / n, 2),
            "p50_latency_ms": int(median(latencies)) if latencies else 0,
            "p95_latency_ms": int(latencies[int(0.95 * (len(latencies) - 1))])
            if latencies
            else 0,
            "total_input_tokens": sum(r.input_tokens for r in rows),
            "total_output_tokens": sum(r.output_tokens for r in rows),
            "fell_back_count": sum(1 for r in rows if r.fell_back),
        }

    # Pairwise agreement on lane_decision when both backends ran the same sample.
    by_sample: dict[str, dict[str, EvalRecord]] = {}
    for r in records:
        by_sample.setdefault(r.sample_id, {})[r.backend] = r
    paired = [s for s, m in by_sample.items() if len(m) >= 2]
    if paired:
        lane_match = sum(
            1
            for s in paired
            if by_sample[s].get("anthropic")
            and by_sample[s].get("ollama")
            and by_sample[s]["anthropic"].lane_decision == by_sample[s]["ollama"].lane_decision
        )
        validity_match = sum(
            1
            for s in paired
            if by_sample[s].get("anthropic")
            and by_sample[s].get("ollama")
            and by_sample[s]["anthropic"].validation_ok == by_sample[s]["ollama"].validation_ok
        )
        summary["agreement"] = {
            "paired_samples": len(paired),
            "lane_match_count": lane_match,
            "lane_match_pct": round(100.0 * lane_match / len(paired), 2),
            "validity_match_count": validity_match,
            "validity_match_pct": round(100.0 * validity_match / len(paired), 2),
        }
    return summary


def _record_from_run(
    run: AgentRun, sample_id: str, *, forced_backend: str, forced_model: str
) -> EvalRecord:
    lane = None
    if run.lane_decision is not None:
        lane = run.lane_decision.tier
    return EvalRecord(
        agent_id=run.agent_id,
        sample_id=sample_id,
        backend=getattr(run, "backend", forced_backend),
        model=run.model_used or forced_model,
        validation_ok=run.validation_ok,
        validation_errors=list(run.validation_errors or []),
        lane_decision=lane,
        latency_ms=run.latency_ms,
        input_tokens=int(run.tokens_used.get("input", 0)),
        output_tokens=int(run.tokens_used.get("output", 0)),
        fell_back=run.fell_back,
        raw_text_preview=(run.raw_text or "")[:300],
        output=run.output,
    )


async def run_parity(
    agent_id: str,
    *,
    inputs: Iterable[dict[str, Any]],
    out_dir: Path,
    sample_id_key: str = "id",
    backends: tuple[str, ...] = ("anthropic", "ollama"),
) -> dict[str, Any]:
    """Run each input through each backend once. Emit per-row JSONL + summary.json.

    The agent is loaded once; we override the model per call to force the backend.
    Anthropic-forced runs use ``spec.default_model``; Ollama-forced runs use
    ``LOCAL_MODEL_NAME`` env (default ``gemma4:12b-mlx``).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    jsonl_path = out_dir / f"{agent_id}_{run_id}.jsonl"
    summary_path = out_dir / f"{agent_id}_{run_id}.summary.json"

    spec = load_agent(agent_id)
    # Shared clients so we don't churn Anthropic auth or Ollama keep-alive.
    remote = LLMClient()
    local = LocalLLMClient()

    records: list[EvalRecord] = []
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for payload in inputs:
            sample_id = str(payload.get(sample_id_key) or payload.get("sample_id") or "unknown")
            for backend in backends:
                if backend == "anthropic":
                    forced_model = spec.default_model
                else:
                    import os as _os

                    forced_model = _os.environ.get("LOCAL_MODEL_NAME", "gemma4:12b-mlx")

                # Build a fresh Agent each call so the router uses the same
                # injected clients but the forced-model path triggers the
                # right backend (router picks backend by model name prefix).
                agent = Agent(agent_id, spec=spec)
                agent._llm = remote  # type: ignore[attr-defined]
                agent._router = ModelRouter(remote_client=remote, local_client=local)  # type: ignore[attr-defined]

                try:
                    run = await agent.run(
                        payload,
                        submit_to_queue=False,
                        model_override=forced_model,
                    )
                except Exception as e:  # noqa: BLE001
                    log.error(
                        "eval_harness.run_failed",
                        agent_id=agent_id,
                        sample_id=sample_id,
                        backend=backend,
                        err=str(e),
                    )
                    continue

                rec = _record_from_run(run, sample_id, forced_backend=backend, forced_model=forced_model)
                records.append(rec)
                fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
                fh.flush()
                log.info(
                    "eval_harness.sample_done",
                    agent_id=agent_id,
                    sample_id=sample_id,
                    backend=backend,
                    validation_ok=rec.validation_ok,
                    latency_ms=rec.latency_ms,
                )

    summary = _summarize(records)
    summary["agent_id"] = agent_id
    summary["run_id"] = run_id
    summary["jsonl_path"] = str(jsonl_path)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


__all__ = ["run_parity", "EvalRecord"]
