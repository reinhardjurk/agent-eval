"""Langfuse-Anbindung (v3-SDK, OTel-basiert).

Faellt bei fehlenden Keys oder Fehlern lautlos auf No-Op zurueck, damit der
Runner auch ohne Langfuse (z.B. im Fake-Modus oder in CI ohne Secrets) laeuft.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager


class _NoopGen:
    def record(self, result, output=None):
        pass


class Tracer:
    def __init__(self, enabled: bool = True):
        self.enabled = False
        if not enabled:
            return
        if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
            return
        try:
            from langfuse import get_client

            self._lf = get_client()
            self.enabled = True
        except Exception as exc:  # Langfuse nicht installiert / nicht erreichbar
            print(f"[tracing] Langfuse deaktiviert: {exc}", file=sys.stderr)

    @contextmanager
    def conversation(self, name: str, metadata: dict | None = None, tags: list[str] | None = None,
                     input=None):
        if not self.enabled:
            yield
            return
        cm = self._lf.start_as_current_span(name=name, input=input)
        span = cm.__enter__()
        try:
            try:
                span.update_trace(metadata=metadata or {}, tags=tags or [], input=input)
            except Exception:
                pass
            yield
        finally:
            cm.__exit__(*sys.exc_info())

    @contextmanager
    def span(self, name: str, input=None, output=None):
        if not self.enabled:
            yield
            return
        cm = self._lf.start_as_current_span(name=name, input=input)
        span = cm.__enter__()
        try:
            yield
            if output is not None:
                try:
                    span.update(output=output)
                except Exception:
                    pass
        finally:
            cm.__exit__(*sys.exc_info())

    @contextmanager
    def generation(self, name: str, model: str, input=None):
        """Um den eigentlichen LLM-Aufruf legen; danach handle.record(result, output)."""
        if not self.enabled:
            yield _NoopGen()
            return
        cm = self._lf.start_as_current_generation(name=name, model=model, input=input)
        gen = cm.__enter__()

        class _Handle:
            def record(self, result, output=None):
                try:
                    gen.update(
                        output=output,
                        usage_details={
                            "input": result.input_tokens,
                            "output": result.output_tokens,
                        },
                    )
                except Exception:
                    pass

        try:
            yield _Handle()
        finally:
            cm.__exit__(*sys.exc_info())

    def tool_call(self, agent: str, tool: str, args: dict, result: str):
        if not self.enabled:
            return
        try:
            with self._lf.start_as_current_span(name=f"tool:{tool}", input=args) as span:
                span.update(output=result, metadata={"agent": agent})
        except Exception:
            pass

    def score(self, name: str, value, comment: str | None = None):
        if not self.enabled:
            return
        try:
            self._lf.score_current_trace(name=name, value=value, comment=comment)
        except Exception:
            pass

    def update_trace_output(self, output):
        if not self.enabled:
            return
        try:
            self._lf.update_current_trace(output=output)
        except Exception:
            pass

    def flush(self):
        if not self.enabled:
            return
        try:
            self._lf.flush()
        except Exception:
            pass
