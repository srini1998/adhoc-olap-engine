"""Ad-hoc OLAP engine for Multi-Feature (MF) and Extended Multi-Feature (EMF) queries.

A query is written as a Phi operator: select list S, grouping-variable count n,
grouping attributes V, aggregate vector F, one predicate per grouping variable
and an optional HAVING condition G. The engine evaluates it by scanning the base
table once per dependency level, building an in-memory mf-structure keyed by V,
instead of delegating the grouping to the database's own GROUP BY.
"""

from .spec import PhiQuery, parse_phi
from .engine import evaluate

__all__ = ["PhiQuery", "parse_phi", "evaluate"]
