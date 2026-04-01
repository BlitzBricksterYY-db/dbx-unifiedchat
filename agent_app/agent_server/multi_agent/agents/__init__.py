"""
Agent implementations for the multi-agent system.

This package contains both agent node functions and agent classes.
"""

from importlib import import_module

__all__ = [
    # ClarificationAgent (subgraph-based class, replaces old node function)
    "ClarificationAgent",

    # Node functions (used by graph)
    "planning_node",
    "sql_synthesis_table_node",
    "sql_synthesis_genie_node",
    "sql_execution_node",
    "summarize_node",

    # Agent classes
    "PlanningAgent",
    "SQLSynthesisTableAgent",
    "SQLSynthesisGenieAgent",
    "SQLExecutionAgent",
    "ResultSummarizeAgent",
]

_LAZY_IMPORTS = {
    "ClarificationAgent": (".clarification", "ClarificationAgent"),
    "planning_node": (".planning", "planning_node"),
    "sql_synthesis_table_node": (".sql_synthesis", "sql_synthesis_table_node"),
    "sql_synthesis_genie_node": (".sql_synthesis", "sql_synthesis_genie_node"),
    "sql_execution_node": (".sql_execution", "sql_execution_node"),
    "summarize_node": (".summarize", "summarize_node"),
    "PlanningAgent": (".planning_agent", "PlanningAgent"),
    "SQLSynthesisTableAgent": (".sql_synthesis_agents", "SQLSynthesisTableAgent"),
    "SQLSynthesisGenieAgent": (".sql_synthesis_agents", "SQLSynthesisGenieAgent"),
    "SQLExecutionAgent": (".sql_execution_agent", "SQLExecutionAgent"),
    "ResultSummarizeAgent": (".summarize_agent", "ResultSummarizeAgent"),
}


def __getattr__(name: str):
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _LAZY_IMPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
