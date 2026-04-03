"""Conditional MLflow spans (e.g. omit tracing on periodic prewarm)."""

import contextlib

import mlflow


class _NoOpMlflowSpan:
    def set_inputs(self, *_args, **_kwargs) -> None:
        pass

    def set_outputs(self, *_args, **_kwargs) -> None:
        pass


@contextlib.contextmanager
def mlflow_span_if(record_trace: bool, **start_span_kwargs):
    """Use a real MLflow span when tracing is enabled; otherwise a no-op stand-in."""
    if not record_trace:
        yield _NoOpMlflowSpan()
        return
    with mlflow.start_span(**start_span_kwargs) as span:
        yield span
