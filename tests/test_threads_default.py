"""Llama thread defaults stay on the single named constant."""
from __future__ import annotations

import inspect

from sentinel.advisor import DEFAULT_LLAMA_THREADS, LlamaAdvisor
from sentinel.cli import build_parser as build_cli_parser
from sentinel.llama_server import LlamaServerClient


def _threads_default(function) -> int:
    """Return the declared threads default of an initializer."""
    param = inspect.signature(function).parameters["threads"]
    return param.default


def _parser_threads_default(build_parser) -> int:
    """Return the --threads default of a built CLI parser."""
    parser = build_parser()
    for action in parser._actions:
        if isinstance(getattr(action, "choices", None), dict):
            for sub in action.choices.values():
                for sub_action in sub._actions:
                    if "--threads" in sub_action.option_strings:
                        return sub_action.default
        if "--threads" in action.option_strings:
            return action.default
    raise AssertionError("no --threads option found")


def test_advisor_threads_default_matches_constant():
    """LlamaAdvisor defaults to DEFAULT_LLAMA_THREADS."""
    assert _threads_default(LlamaAdvisor.__init__) == DEFAULT_LLAMA_THREADS


def test_llama_server_threads_default_matches_constant():
    """LlamaServerClient defaults to DEFAULT_LLAMA_THREADS."""
    assert _threads_default(LlamaServerClient.__init__) == DEFAULT_LLAMA_THREADS


def test_cli_threads_default_matches_constant():
    """The sentinel CLI --threads default matches DEFAULT_LLAMA_THREADS."""
    assert _parser_threads_default(build_cli_parser) == DEFAULT_LLAMA_THREADS


def test_run_bench_threads_default_matches_constant():
    """The benchmark --threads default matches DEFAULT_LLAMA_THREADS."""
    from bench.run_bench import build_parser as build_bench_parser

    assert _parser_threads_default(build_bench_parser) == DEFAULT_LLAMA_THREADS
