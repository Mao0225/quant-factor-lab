"""Small versioned, causal expression space with prefix generation masks."""
import ast
from dataclasses import dataclass

import numpy as np
import pandas as pd


class ExpressionError(ValueError):
    pass


@dataclass(frozen=True)
class Node:
    token: str
    children: tuple = ()

    @property
    def tokens(self):
        return (self.token,) + tuple(t for child in self.children for t in child.tokens)

    @property
    def text(self):
        if self.token.startswith("const:"):
            return self.token[6:]
        return self.token if not self.children else self.token + "(" + ",".join(c.text for c in self.children) + ")"


class ExpressionSpace:
    def __init__(self, protocol):
        self.p = protocol
        self.arity = {f: 0 for f in protocol.fields}
        self.arity.update({f"const:{float(c):g}": 0 for c in protocol.constants})
        self.arity.update({"add": 2, "sub": 2, "mul": 2, "div": 2, "neg": 1, "rank": 1})
        self.arity.update({f"{op}_{w}": 1 for op in ["delay", "mean"] for w in protocol.windows})
        if protocol.operator_profile == "extended":
            self.arity["abs"] = 1
            self.arity.update({f"{op}_{w}": 1 for op in ["std", "min", "max", "delta"] for w in protocol.windows})
        if any(f in {"add", "sub", "mul", "div", "neg", "rank", "abs"} or f.startswith(("delay_", "mean_", "std_", "min_", "max_", "delta_")) for f in protocol.fields):
            raise ValueError("field collides with operator")
        self.vocabulary = ["END"] + list(self.arity)
        self.ids = {v: i for i, v in enumerate(self.vocabulary)}

    def parse(self, expression):
        try:
            tree = ast.parse(expression.strip(), mode="eval").body
            def walk(n):
                if isinstance(n, ast.Name) and n.id in self.p.fields:
                    return Node(n.id)
                if isinstance(n, ast.Constant) and type(n.value) in (int, float):
                    token = f"const:{float(n.value):g}"
                    if token in self.arity:
                        return Node(token)
                if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub) and isinstance(n.operand, ast.Constant):
                    token = f"const:{-float(n.operand.value):g}"
                    if token in self.arity:
                        return Node(token)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.keywords:
                    op = n.func.id
                    if op in self.arity and self.arity[op] > 0 and len(n.args) == self.arity[op]:
                        children = tuple(walk(a) for a in n.args)
                        if op in {"add", "mul"}:
                            children = tuple(sorted(children, key=lambda c: c.text))
                        return Node(op, children)
                raise ExpressionError("unknown field, operator, constant or invalid syntax")
            node = walk(tree)
            if len(node.tokens) > self.p.max_tokens:
                raise ExpressionError("expression length exceeds protocol")
            if self.p.max_lookback is not None and self.lookback(node) > self.p.max_lookback:
                raise ExpressionError("expression history exceeds protocol")
            if self.p.require_feature and not any(t in self.p.fields for t in node.tokens):
                raise ExpressionError("expression must contain a field")
            return node
        except (SyntaxError, RecursionError, TypeError) as exc:
            raise ExpressionError(str(exc)) from exc

    def from_prefix(self, tokens):
        tokens = list(tokens)
        def take():
            if not tokens:
                raise ExpressionError("unfinished prefix")
            token = tokens.pop(0)
            if token not in self.arity:
                raise ExpressionError("unknown prefix token")
            return Node(token, tuple(take() for _ in range(self.arity[token])))
        node = take()
        if tokens:
            raise ExpressionError("extra prefix tokens")
        return self.parse(node.text)

    def mask(self, prefix):
        pending = 1
        costs = [0]
        featured = False
        for token in prefix:
            if pending <= 0 or token not in self.arity:
                raise ExpressionError("invalid prefix")
            pending += self.arity[token] - 1
            cost = costs.pop()
            if token in self.p.fields:
                featured = True
            if self.arity[token]:
                costs.extend([cost+self._history_cost(token)]*self.arity[token])
        mask = np.zeros(len(self.vocabulary), dtype=bool)
        if pending == 0:
            mask[0] = True
        else:
            remaining = self.p.max_tokens - len(prefix)
            for token, arity in self.arity.items():
                allowed = pending + arity <= remaining
                if self.p.max_lookback is not None:
                    own = dict(self.p.field_lookbacks).get(token, 0) if arity == 0 else self._history_cost(token)
                    allowed = allowed and costs[-1]+own <= self.p.max_lookback
                    after = costs[:-1]+[costs[-1]+own]*arity
                    minimum_field = min(dict(self.p.field_lookbacks).get(f, 0) for f in self.p.fields)
                    minimum_leaf = 0 if self.p.constants else minimum_field
                    allowed = allowed and all(c+minimum_leaf <= self.p.max_lookback for c in after)
                    if self.p.require_feature and not featured and token not in self.p.fields:
                        allowed = allowed and any(c+minimum_field <= self.p.max_lookback for c in after)
                if self.p.require_feature and not featured and pending == 1 and arity == 0 and token not in self.p.fields:
                    allowed = False
                mask[self.ids[token]] = allowed
        if not mask.any():
            raise ExpressionError("no legal completion within token budget")
        return mask

    def _history_cost(self, token):
        if token in self.p.fields or "_" not in token:
            return 0
        op, window = token.split("_")
        return int(window) if op in {"delay", "delta"} else int(window)-1

    def lookback(self, node):
        if node.token in self.p.fields:
            return dict(self.p.field_lookbacks).get(node.token, 0)
        return self._history_cost(node.token)+max([self.lookback(c) for c in node.children] or [0])

    def evaluate(self, expression, frame):
        node = self.parse(expression) if isinstance(expression, str) else expression
        # Evaluation assumes sorted snapshot rows; grouped shift never reaches future rows.
        def ev(n):
            if n.token in self.p.fields:
                return frame[n.token].to_numpy(dtype=float)
            if n.token.startswith("const:"):
                return np.full(len(frame), float(n.token[6:]))
            args = [ev(c) for c in n.children]
            with np.errstate(all="ignore"):
                if n.token == "add": out = args[0] + args[1]
                elif n.token == "sub": out = args[0] - args[1]
                elif n.token == "mul": out = args[0] * args[1]
                elif n.token == "div": out = np.divide(args[0], args[1], out=np.full(len(frame), np.nan), where=np.abs(args[1]) > self.p.epsilon)
                elif n.token == "neg": out = -args[0]
                elif n.token == "abs": out = np.abs(args[0])
                elif n.token == "rank":
                    s = pd.Series(args[0], index=frame.index).where(frame.eligible)
                    out = s.groupby(frame.date).rank(method="average", pct=True).to_numpy()
                else:
                    op, window = n.token.split("_")
                    g = pd.Series(args[0], index=frame.index).groupby(frame.code, sort=False)
                    if op == "delay": out = g.shift(int(window)).to_numpy()
                    elif op == "delta": out = args[0]-g.shift(int(window)).to_numpy()
                    elif op == "std": out = g.transform(lambda x: x.rolling(int(window), min_periods=int(window)).std(ddof=0)).to_numpy()
                    else: out = g.transform(lambda x: getattr(x.rolling(int(window), min_periods=int(window)), op)()).to_numpy()
            return np.where(np.isfinite(out), out, np.nan)
        return ev(node)
