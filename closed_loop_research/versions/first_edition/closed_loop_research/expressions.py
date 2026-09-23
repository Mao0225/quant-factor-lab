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
        if any(f in {"add", "sub", "mul", "div", "neg", "rank"} or f.startswith(("delay_", "mean_")) for f in protocol.fields):
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
        for token in prefix:
            if pending <= 0 or token not in self.arity:
                raise ExpressionError("invalid prefix")
            pending += self.arity[token] - 1
        mask = np.zeros(len(self.vocabulary), dtype=bool)
        if pending == 0:
            mask[0] = True
        else:
            remaining = self.p.max_tokens - len(prefix)
            for token, arity in self.arity.items():
                mask[self.ids[token]] = pending + arity <= remaining
        if not mask.any():
            raise ExpressionError("no legal completion within token budget")
        return mask

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
                elif n.token == "rank":
                    s = pd.Series(args[0], index=frame.index).where(frame.eligible)
                    out = s.groupby(frame.date).rank(method="average", pct=True).to_numpy()
                else:
                    op, window = n.token.split("_")
                    g = pd.Series(args[0], index=frame.index).groupby(frame.code, sort=False)
                    if op == "delay": out = g.shift(int(window)).to_numpy()
                    else: out = g.transform(lambda x: x.rolling(int(window), min_periods=int(window)).mean()).to_numpy()
            return np.where(np.isfinite(out), out, np.nan)
        return ev(node)
