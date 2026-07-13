#!/usr/bin/env python3
"""
Analyze an extracted `akamas export study` bundle and emit a structured
analysis.json with everything a findings report needs: per-experiment table,
per-parameter effects (goal + every other metric), pairwise interactions,
failure/constraint analysis, and per-experiment timeseries + ready-to-embed
SVG chart markup for a curated set of metrics.

Pure Python 3 standard library — no third-party dependencies, so this runs
anywhere `python3` runs. See ../reference/export-schema.md for the bundle
format this script assumes (empirically reverse-engineered, not from
docs.akamas.io).

Every number in the output is traceable back to a field in the bundle; this
script never invents or estimates a value without flagging it as such (e.g.
the full-series-vs-windowed-score cross-check is reported as a delta, not
silently substituted for the authoritative score).
"""

import argparse
import glob
import json
import math
import os
import re
import statistics
import sys
from collections import defaultdict, Counter

# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def load_bundle(export_dir):
    def opt(name):
        p = os.path.join(export_dir, name)
        return load_json(p) if os.path.exists(p) else None

    study = opt("study.json")
    if study is None:
        raise SystemExit(f"study.json not found under {export_dir} — is this really an extracted export bundle?")
    study = study["study"]

    last_opt = opt("last-optimization.json")
    system = opt("system.json")
    workflow = opt("workflow.json")
    logs = opt("logs.json") or []

    metrics_files = sorted(glob.glob(os.path.join(export_dir, "metrics-*.json")))
    metrics = {}  # metric_key "Component.metric" -> list of raw sample dicts
    for path in metrics_files:
        try:
            entries = load_json(path)
        except Exception as e:
            print(f"warning: could not parse {path}: {e}", file=sys.stderr)
            continue
        for e in entries:
            comp = e.get("labels", {}).get("componentName", "?")
            metric = e.get("metric", os.path.basename(path))
            key = f"{comp}.{metric}"
            metrics.setdefault(key, []).append(e)

    return {
        "study": study,
        "last_optimization": last_opt,
        "system": system,
        "workflow": workflow,
        "logs": logs,
        "metrics": metrics,
    }


# --------------------------------------------------------------------------
# Tiny expression evaluator for goal formulas / parameterConstraints formulas
# Supports: + - * / ^, comparisons > < >= <= == !=, logical && || !, parens,
# numeric literals, quoted string literals, "Component.param" identifiers.
# --------------------------------------------------------------------------

TOKEN_RE = re.compile(r"""
    \s*(?:
        (?P<NUMBER>\d+\.\d+|\d+)
      | (?P<STRING>"[^"]*")
      | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)
      | (?P<OP>&&|\|\||<=|>=|==|!=|[()+\-*/^<>!])
    )
""", re.VERBOSE)


class FormulaError(Exception):
    pass


def tokenize(formula):
    tokens = []
    pos = 0
    while pos < len(formula):
        m = TOKEN_RE.match(formula, pos)
        if not m or m.end() == pos:
            if formula[pos:].strip() == "":
                break
            raise FormulaError(f"cannot tokenize {formula!r} at {pos}")
        pos = m.end()
        kind = m.lastgroup
        text = m.group(kind)
        tokens.append((kind, text))
    return tokens


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def expect_op(self, text):
        kind, tok = self.next()
        if tok != text:
            raise FormulaError(f"expected {text!r}, got {tok!r}")

    def parse(self):
        node = self.or_expr()
        if self.i != len(self.tokens):
            raise FormulaError(f"trailing tokens: {self.tokens[self.i:]}")
        return node

    def or_expr(self):
        node = self.and_expr()
        while self.peek()[1] == "||":
            self.next()
            node = ("or", node, self.and_expr())
        return node

    def and_expr(self):
        node = self.cmp_expr()
        while self.peek()[1] == "&&":
            self.next()
            node = ("and", node, self.cmp_expr())
        return node

    def cmp_expr(self):
        node = self.add_expr()
        if self.peek()[1] in (">", "<", ">=", "<=", "==", "!="):
            op = self.next()[1]
            node = ("cmp", op, node, self.add_expr())
        return node

    def add_expr(self):
        node = self.mul_expr()
        while self.peek()[1] in ("+", "-"):
            op = self.next()[1]
            node = ("arith", op, node, self.mul_expr())
        return node

    def mul_expr(self):
        node = self.pow_expr()
        while self.peek()[1] in ("*", "/"):
            op = self.next()[1]
            node = ("arith", op, node, self.pow_expr())
        return node

    def pow_expr(self):
        node = self.unary()
        if self.peek()[1] == "^":
            self.next()
            node = ("arith", "^", node, self.pow_expr())
        return node

    def unary(self):
        if self.peek()[1] == "!":
            self.next()
            return ("not", self.unary())
        if self.peek()[1] == "-":
            self.next()
            return ("neg", self.unary())
        return self.primary()

    def primary(self):
        kind, tok = self.next()
        if kind == "NUMBER":
            return ("num", float(tok))
        if kind == "STRING":
            return ("str", tok[1:-1])
        if kind == "IDENT":
            return ("ident", tok)
        if tok == "(":
            node = self.or_expr()
            self.expect_op(")")
            return node
        raise FormulaError(f"unexpected token {tok!r}")


def parse_formula(formula):
    return Parser(tokenize(formula)).parse()


def eval_formula(node, context):
    """context: dict of "Component.param" -> value (str or number). Raises
    FormulaError (missing identifier) if the formula can't be evaluated for
    a given context — caller should treat that as 'skip, insufficient data'."""
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "str":
        return node[1]
    if kind == "ident":
        name = node[1]
        if name not in context:
            raise FormulaError(f"unknown identifier {name!r}")
        return context[name]
    if kind == "neg":
        return -eval_formula(node[1], context)
    if kind == "not":
        return not eval_formula(node[1], context)
    if kind == "arith":
        op, l, r = node[1], eval_formula(node[2], context), eval_formula(node[3], context)
        l, r = float(l), float(r)
        if op == "+":
            return l + r
        if op == "-":
            return l - r
        if op == "*":
            return l * r
        if op == "/":
            return l / r if r != 0 else math.nan
        if op == "^":
            return l ** r
    if kind == "cmp":
        op, l, r = node[1], eval_formula(node[2], context), eval_formula(node[3], context)
        if isinstance(l, str) or isinstance(r, str):
            l, r = str(l), str(r)
        else:
            l, r = float(l), float(r)
        if op == ">":
            return l > r
        if op == "<":
            return l < r
        if op == ">=":
            return l >= r
        if op == "<=":
            return l <= r
        if op == "==":
            return l == r
        if op == "!=":
            return l != r
    if kind == "and":
        return bool(eval_formula(node[1], context)) and bool(eval_formula(node[2], context))
    if kind == "or":
        return bool(eval_formula(node[1], context)) or bool(eval_formula(node[2], context))
    raise FormulaError(f"unhandled node {node!r}")


# --------------------------------------------------------------------------
# Experiment table
# --------------------------------------------------------------------------

def build_experiment_table(study, last_opt):
    """Returns list of dicts, one per experiment, 1-based experiment numbers.
    See reference/export-schema.md 'Experiment numbering' — last_opt's arrays
    are 0-based by position (index i == experiment i+1)."""
    experiments = []
    if last_opt is None:
        return experiments, set()

    scores = last_opt["scores"]
    assignments = last_opt["parametersAssignments"]
    violations = last_opt.get("metricConstraintsViolations") or [[]] * len(scores)
    failed_idx = set(last_opt.get("failedExperimentsIndex") or [])
    baseline_idx = last_opt.get("baselineExperimentIndex", 0)

    for i, score in enumerate(scores):
        exp_num = i + 1
        params = {a["name"]: a["value"] for a in (assignments[i] or [])}
        experiments.append({
            "experiment": exp_num,
            "failed": i in failed_idx,
            "is_baseline": i == baseline_idx,
            "goal_score": score,
            "parameters": params,
            "constraint_violations": violations[i] if i < len(violations) else [],
        })
    failed_experiments = {i + 1 for i in failed_idx}
    return experiments, failed_experiments


# --------------------------------------------------------------------------
# Per-experiment metric aggregation from raw timeseries
# --------------------------------------------------------------------------

def aggregate_metrics_per_experiment(metrics):
    """metric_key -> experiment -> {mean, min, max, stdev, n, series:[(t_rel_s, value)]}"""
    agg = {}
    for key, samples in metrics.items():
        by_exp = defaultdict(list)
        for s in samples:
            ids = s.get("studyExperimentTrialIds") or [{}]
            exp = ids[0].get("experiment")
            if exp is None:
                continue
            by_exp[exp].append(s)
        per_exp = {}
        for exp, pts in by_exp.items():
            pts.sort(key=lambda p: p["timestamp"])
            values = [p["value"] for p in pts if isinstance(p.get("value"), (int, float))]
            if not values:
                continue
            t0 = pts[0]["timestamp"]
            series = [(_seconds_between(t0, p["timestamp"]), p["value"]) for p in pts
                      if isinstance(p.get("value"), (int, float))]
            per_exp[exp] = {
                "mean": statistics.fmean(values),
                "min": min(values),
                "max": max(values),
                "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
                "n": len(values),
                "series": series,
            }
        agg[key] = per_exp
    return agg


def _seconds_between(t0, t1):
    # timestamps like "2026-07-10T14:22:17.642" — lexicographic ISO, parse manually
    # to avoid a timezone/library dependency.
    from datetime import datetime
    fmt_candidates = ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]
    def parse(t):
        for fmt in fmt_candidates:
            try:
                return datetime.strptime(t, fmt)
            except ValueError:
                continue
        raise ValueError(f"unrecognized timestamp {t!r}")
    return (parse(t1) - parse(t0)).total_seconds()


# --------------------------------------------------------------------------
# Parameter effect analysis
# --------------------------------------------------------------------------

def pearson_r(xs, ys):
    if len(xs) < 3:
        return None
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def analyze_parameter_effects(param_specs, experiments, metric_means, goal_key, baseline_exp,
                               side_effect_threshold_pct=15.0, min_metric_coverage=0.5):
    """param_specs: list of {name, type, categories, domain} from study.parametersSelection.
    metric_means: metric_key -> experiment -> mean value (already extracted from
    aggregate_metrics_per_experiment, plus goal_key injected by caller).
    Returns list of per-parameter effect dicts."""
    successful = [e for e in experiments if not e["failed"] and e["goal_score"] is not None]
    n_success = len(successful)
    if n_success == 0:
        return []

    # only analyze metrics with reasonable coverage across successful experiments
    usable_metrics = [
        k for k, per_exp in metric_means.items()
        if sum(1 for e in successful if e["experiment"] in per_exp) >= max(3, int(n_success * min_metric_coverage))
    ]

    baseline_vals = {}
    if baseline_exp is not None:
        for k in usable_metrics:
            v = metric_means[k].get(baseline_exp)
            if v is not None:
                baseline_vals[k] = v

    results = []
    for spec in param_specs:
        name = spec["name"]
        ptype = spec.get("type")
        values_by_exp = {e["experiment"]: e["parameters"].get(name) for e in successful if name in e["parameters"]}
        if not values_by_exp:
            continue

        entry = {"name": name, "type": ptype, "n_experiments": len(values_by_exp)}

        if ptype == "categorical":
            groups = defaultdict(list)  # value -> [experiment,...]
            for exp, val in values_by_exp.items():
                groups[val].append(exp)
            per_metric = {}
            for k in usable_metrics:
                group_stats = {}
                for val, exps in groups.items():
                    vals = [metric_means[k][e] for e in exps if e in metric_means[k]]
                    if not vals:
                        continue
                    group_stats[val] = {
                        "mean": statistics.fmean(vals),
                        "stdev": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
                        "n": len(vals),
                    }
                if len(group_stats) < 2:
                    continue
                means = {v: s["mean"] for v, s in group_stats.items()}
                best_val = max(means, key=means.get)
                worst_val = min(means, key=means.get)
                spread = means[best_val] - means[worst_val]
                per_metric[k] = {
                    "groups": group_stats,
                    "best_value": best_val,
                    "worst_value": worst_val,
                    "spread": spread,
                }
            entry["categories"] = sorted(groups.keys())
            entry["per_metric"] = per_metric
            if goal_key in per_metric:
                goal_info = per_metric[goal_key]
                entry["goal_spread"] = goal_info["spread"]
                median_goal = statistics.median(e["goal_score"] for e in successful)
                entry["goal_spread_pct"] = (goal_info["spread"] / median_goal * 100.0) if median_goal else None
                entry["best_value_for_goal"] = goal_info["best_value"]
                entry["worst_value_for_goal"] = goal_info["worst_value"]
                # side effects: best-for-goal group's mean on every other metric vs baseline
                side_effects = []
                best_group_exps = groups[goal_info["best_value"]]
                for k in usable_metrics:
                    if k == goal_key or k not in baseline_vals:
                        continue
                    vals = [metric_means[k][e] for e in best_group_exps if e in metric_means[k]]
                    if not vals:
                        continue
                    group_mean = statistics.fmean(vals)
                    base = baseline_vals[k]
                    if base == 0:
                        continue
                    pct = (group_mean - base) / abs(base) * 100.0
                    if abs(pct) >= side_effect_threshold_pct:
                        side_effects.append({"metric": k, "pct_change_vs_baseline": pct,
                                              "group_mean": group_mean, "baseline": base})
                side_effects.sort(key=lambda s: -abs(s["pct_change_vs_baseline"]))
                entry["side_effects_of_best_value"] = side_effects[:8]

        elif ptype in ("real", "integer"):
            per_metric = {}
            xs_goal = [values_by_exp[e] for e in values_by_exp if e in metric_means.get(goal_key, {})]
            for k in usable_metrics:
                xs, ys = [], []
                for exp, val in values_by_exp.items():
                    if exp in metric_means[k]:
                        xs.append(val)
                        ys.append(metric_means[k][exp])
                r = pearson_r(xs, ys)
                if r is not None:
                    per_metric[k] = {"pearson_r": r, "n": len(xs)}
            entry["per_metric"] = per_metric
            if goal_key in per_metric:
                entry["goal_correlation"] = per_metric[goal_key]["pearson_r"]
                secondary = sorted(
                    ((k, v["pearson_r"]) for k, v in per_metric.items() if k != goal_key),
                    key=lambda kv: -abs(kv[1])
                )
                entry["notable_secondary_correlations"] = [
                    {"metric": k, "pearson_r": r} for k, r in secondary[:8] if abs(r) >= 0.5
                ]
        else:
            continue

        results.append(entry)

    return results


# --------------------------------------------------------------------------
# Pairwise interaction scan (categorical parameters only, top-K by goal spread)
# --------------------------------------------------------------------------

def analyze_interactions(param_effects, experiments, goal_key, metric_means, top_k=4, max_categories=8, min_cell_n=2):
    cat_effects = [p for p in param_effects if p.get("type") == "categorical" and "goal_spread" in p]
    cat_effects = [p for p in cat_effects if len(p["categories"]) <= max_categories]
    cat_effects.sort(key=lambda p: -abs(p.get("goal_spread_pct") or 0))
    top = cat_effects[:top_k]

    successful = [e for e in experiments if not e["failed"] and e["goal_score"] is not None]

    interactions = []
    total_cells = 0
    filled_cells = 0
    supported_cells = 0

    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            a, b = top[i]["name"], top[j]["name"]
            cell = defaultdict(list)  # (a_val, b_val) -> [goal_score,...]
            for e in successful:
                av, bv = e["parameters"].get(a), e["parameters"].get(b)
                if av is None or bv is None:
                    continue
                cell[(av, bv)].append(e["goal_score"])

            b_values = sorted({bv for (_, bv) in cell.keys()})
            a_values = sorted({av for (av, _) in cell.keys()})
            total_cells += len(a_values) * len(b_values)

            best_a_by_b = {}
            cell_summary = {}
            for bv in b_values:
                means = {}
                for av in a_values:
                    scores = cell.get((av, bv), [])
                    if scores:
                        filled_cells += 1
                    if len(scores) >= min_cell_n:
                        supported_cells += 1
                        means[av] = statistics.fmean(scores)
                    cell_summary[f"{av}|{bv}"] = {"n": len(scores), "mean": statistics.fmean(scores) if scores else None}
                if means:
                    best_a_by_b[bv] = max(means, key=means.get)

            distinct_best = set(best_a_by_b.values())
            interaction_detected = len(best_a_by_b) >= 2 and len(distinct_best) > 1

            interactions.append({
                "param_a": a, "param_b": b,
                "b_values_with_support": list(best_a_by_b.keys()),
                "best_a_per_b": best_a_by_b,
                "interaction_detected": interaction_detected,
                "cells": cell_summary,
            })

    coverage = {
        "total_cells": total_cells,
        "filled_cells": filled_cells,
        "supported_cells_n_gte_%d" % min_cell_n: supported_cells,
        "coverage_pct": (filled_cells / total_cells * 100.0) if total_cells else None,
        "supported_pct": (supported_cells / total_cells * 100.0) if total_cells else None,
    }
    return interactions, coverage


# --------------------------------------------------------------------------
# Constraint cross-check
# --------------------------------------------------------------------------

def check_parameter_constraints(constraints, experiments):
    parsed = []
    for c in constraints or []:
        try:
            parsed.append((c["name"], c["formula"], parse_formula(c["formula"])))
        except FormulaError as e:
            parsed.append((c["name"], c["formula"], None))
            print(f"warning: could not parse parameterConstraint {c['name']!r}: {e}", file=sys.stderr)

    violations = []
    unevaluated = 0
    for e in experiments:
        ctx = dict(e["parameters"])
        for name, formula, node in parsed:
            if node is None:
                continue
            try:
                ok = eval_formula(node, ctx)
            except FormulaError:
                unevaluated += 1
                continue
            if not ok:
                violations.append({"experiment": e["experiment"], "constraint": name, "formula": formula})
    return violations, unevaluated


def cross_check_goal_formula(goal_formula, experiments, metric_means):
    try:
        node = parse_formula(goal_formula)
    except FormulaError as e:
        return {"error": str(e)}
    diffs = []
    for e in experiments:
        if e["failed"] or e["goal_score"] is None:
            continue
        ctx = {}
        ok = True
        for k, per_exp in metric_means.items():
            if e["experiment"] in per_exp:
                ctx[k] = per_exp[e["experiment"]]["mean"]
        try:
            recomputed = eval_formula(node, ctx)
        except FormulaError:
            ok = False
        if ok and e["goal_score"]:
            rel_diff = (recomputed - e["goal_score"]) / e["goal_score"] * 100.0
            diffs.append(rel_diff)
    if not diffs:
        return {"n": 0}
    return {
        "n": len(diffs),
        "median_pct_diff": statistics.median(diffs),
        "mean_pct_diff": statistics.fmean(diffs),
        "max_abs_pct_diff": max(diffs, key=abs),
    }


# --------------------------------------------------------------------------
# SVG chart generation (theme-aware via CSS custom properties defined by the
# HTML page this gets embedded into — see plugin README / dataviz skill)
# --------------------------------------------------------------------------

def svg_line_chart(chart_id, title, y_label, series, width=680, height=300):
    """series: list of {"label": str, "slot": int (0-7), "points": [(x,y), ...]}"""
    margin_l, margin_r, margin_t, margin_b = 56, 16, 28, 32
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    all_x = [p[0] for s in series for p in s["points"]]
    all_y = [p[1] for s in series for p in s["points"]]
    if not all_x or not all_y:
        return f'<svg class="chart" viewBox="0 0 {width} {height}"><text x="16" y="24" class="chart-title">{esc(title)} — no data</text></svg>'

    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    if x_max == x_min:
        x_max += 1
    if y_max == y_min:
        y_max += 1 if y_max == 0 else abs(y_max) * 0.1

    def X(x):
        return margin_l + (x - x_min) / (x_max - x_min) * plot_w

    def Y(y):
        return margin_t + plot_h - (y - y_min) / (y_max - y_min) * plot_h

    parts = [f'<svg class="chart" id="{chart_id}" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">']
    parts.append(f'<text x="{margin_l}" y="16" class="chart-title">{esc(title)}</text>')

    # gridlines + y ticks
    n_ticks = 4
    for i in range(n_ticks + 1):
        y_val = y_min + (y_max - y_min) * i / n_ticks
        y_px = Y(y_val)
        parts.append(f'<line x1="{margin_l}" y1="{y_px:.1f}" x2="{width - margin_r}" y2="{y_px:.1f}" class="chart-grid" />')
        parts.append(f'<text x="{margin_l - 8}" y="{y_px + 4:.1f}" class="chart-tick" text-anchor="end">{fmt_num(y_val)}</text>')
    parts.append(f'<text x="{margin_l - 44}" y="{margin_t - 12}" class="chart-axis-label">{esc(y_label)}</text>')

    # x ticks (start/mid/end, in minutes)
    for frac in (0.0, 0.5, 1.0):
        x_val = x_min + (x_max - x_min) * frac
        x_px = X(x_val)
        parts.append(f'<text x="{x_px:.1f}" y="{height - margin_b + 16}" class="chart-tick" text-anchor="middle">{x_val/60:.0f}m</text>')

    # series lines
    for s in series:
        pts = sorted(s["points"])
        if not pts:
            continue
        path = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in pts)
        slot = s.get("slot", 0) % 8
        parts.append(f'<polyline points="{path}" class="chart-series s{slot}" fill="none">'
                      f'<title>{esc(s["label"])}</title></polyline>')

    parts.append("</svg>")

    legend = "".join(
        f'<span class="legend-item"><span class="legend-swatch s{s.get("slot", 0) % 8}"></span>{esc(s["label"])}</span>'
        for s in series
    )
    return "".join(parts) + f'<div class="chart-legend">{legend}</div>'


def svg_bar_chart(chart_id, title, y_label, bars, width=560, height=280):
    """bars: list of {"label": str, "value": float, "stdev": float, "n": int, "slot": int}"""
    margin_l, margin_r, margin_t, margin_b = 56, 16, 28, 64
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b
    if not bars:
        return f'<svg class="chart" viewBox="0 0 {width} {height}"><text x="16" y="24">{esc(title)} — no data</text></svg>'

    values = [b["value"] for b in bars]
    y_min = min(0, min(values))
    y_max = max(values) * 1.15 if max(values) > 0 else max(values) * 0.85

    def Y(y):
        return margin_t + plot_h - (y - y_min) / (y_max - y_min) * plot_h

    bar_w = plot_w / len(bars) * 0.6
    gap = plot_w / len(bars)

    parts = [f'<svg class="chart" id="{chart_id}" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">']
    parts.append(f'<text x="{margin_l}" y="16" class="chart-title">{esc(title)}</text>')
    parts.append(f'<text x="{margin_l - 44}" y="{margin_t - 12}" class="chart-axis-label">{esc(y_label)}</text>')

    zero_y = Y(0)
    parts.append(f'<line x1="{margin_l}" y1="{zero_y:.1f}" x2="{width - margin_r}" y2="{zero_y:.1f}" class="chart-axis" />')

    for i, b in enumerate(bars):
        x0 = margin_l + i * gap + (gap - bar_w) / 2
        y_top = Y(b["value"])
        h = abs(zero_y - y_top)
        slot = b.get("slot", i) % 8
        parts.append(f'<rect x="{x0:.1f}" y="{min(y_top, zero_y):.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
                      f'class="chart-bar s{slot}"><title>{esc(b["label"])}: {fmt_num(b["value"])} (n={b.get("n", "?")})</title></rect>')
        parts.append(f'<text x="{x0 + bar_w/2:.1f}" y="{height - margin_b + 16}" class="chart-tick" '
                      f'text-anchor="middle" transform="rotate(20 {x0 + bar_w/2:.1f} {height - margin_b + 16})">{esc(str(b["label"]))}</text>')

    parts.append("</svg>")
    return "".join(parts)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def fmt_num(x):
    if x is None:
        return "n/a"
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    if abs(x) >= 10:
        return f"{x:.1f}"
    return f"{x:.3f}"


# --------------------------------------------------------------------------
# Curated timeseries selection
# --------------------------------------------------------------------------

CURATED_METRIC_SUFFIXES = [
    "prefill_token_throughput", "decode_token_throughput",
    "e2e_request_latency_p95", "e2e_request_latency_avg",
    "inter_token_latency_p95", "inter_token_latency_avg",
    "time_to_first_token_p95", "time_to_first_token_avg",
    "num_requests_waiting", "num_requests_running", "preemption_rate",
    "kv_cache_usage_avg", "kv_cache_usage_max", "fleet_kv_cache_usage_avg",
    "gpu_util", "gpu_fb_used", "gpu_temp", "gpu_power_usage", "gpu_sm_active",
    "container_memory_util", "container_cpu_util", "container_oom_kills_count",
]


def build_timeseries_charts(metric_means, curated_keys, selected_experiments):
    charts = {}
    for key in curated_keys:
        per_exp = metric_means.get(key)
        if not per_exp:
            continue
        series = []
        for slot, exp in enumerate(selected_experiments):
            data = per_exp.get(exp["experiment"])
            if not data or not data["series"]:
                continue
            series.append({
                "label": exp["display_label"],
                "slot": slot,
                "points": data["series"],
            })
        if series:
            chart_id = "ts_" + re.sub(r"[^A-Za-z0-9_]", "_", key)
            charts[key] = svg_line_chart(chart_id, key, "value", series)
    return charts


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("export_dir", help="directory the export bundle was extracted into")
    ap.add_argument("--out", required=True, help="path to write analysis.json to")
    ap.add_argument("--side-effect-threshold-pct", type=float, default=15.0)
    args = ap.parse_args()

    bundle = load_bundle(args.export_dir)
    study = bundle["study"]

    experiments, failed_experiments = build_experiment_table(study, bundle["last_optimization"])
    if not experiments:
        raise SystemExit("no experiments found — last-optimization.json missing or empty")

    metric_means_raw = aggregate_metrics_per_experiment(bundle["metrics"])

    # figure out the goal formula's own metric key(s) so we can inject the
    # authoritative per-experiment goal score as a first-class "metric" too
    goal_formula = study["goal"]["function"]["formula"]
    goal_key = "__goal__"
    metric_means = dict(metric_means_raw)
    metric_means[goal_key] = {
        e["experiment"]: {"mean": e["goal_score"], "min": e["goal_score"], "max": e["goal_score"],
                           "stdev": 0.0, "n": 1, "series": []}
        for e in experiments if e["goal_score"] is not None
    }
    # flatten to plain mean dict for the parameter-effects module's convenience
    metric_means_flat = {k: {exp: v["mean"] for exp, v in per_exp.items()} for k, per_exp in metric_means.items()}

    baseline_exp_list = [e["experiment"] for e in experiments if e["is_baseline"]]
    baseline_exp = baseline_exp_list[0] if baseline_exp_list else None

    param_effects = analyze_parameter_effects(
        study.get("parametersSelection") or [], experiments, metric_means_flat, goal_key, baseline_exp,
        side_effect_threshold_pct=args.side_effect_threshold_pct,
    )

    interactions, interaction_coverage = analyze_interactions(param_effects, experiments, goal_key, metric_means_flat)

    constraint_violations, unevaluated_constraint_checks = check_parameter_constraints(
        study.get("parameterConstraints") or [], experiments
    )

    goal_cross_check = cross_check_goal_formula(goal_formula, experiments, metric_means_raw)

    # metrics selected but never producing a sample
    selected_metric_names = set(study.get("metricsSelection") or [])
    produced_metric_names = {k.split(".", 1)[1] if "." in k else k for k in bundle["metrics"].keys()}
    missing_metrics = sorted(m for m in selected_metric_names
                              if (m.split(".", 1)[1] if "." in m else m) not in produced_metric_names)

    # NaN-skip warning counts per metric, from logs.json
    nan_skips = Counter()
    for entry in bundle["logs"]:
        msg = entry.get("message", "")
        m = re.match(r"Skipping sample for metric ([\w\.]+): value is NaN", msg)
        if m:
            nan_skips[m.group(1)] += 1

    # failed-experiment detail incl. any ERROR/WARN log lines tagged with that exp
    failed_detail = []
    for exp_num in sorted(failed_experiments):
        exp_row = next((e for e in experiments if e["experiment"] == exp_num), None)
        related_logs = [
            {"loglevel": l.get("loglevel"), "message": l.get("message")}
            for l in bundle["logs"]
            if l.get("exp") == exp_num and l.get("loglevel") in ("ERROR", "WARN")
        ][:5]
        failed_detail.append({
            "experiment": exp_num,
            "parameters": exp_row["parameters"] if exp_row else {},
            "related_log_entries": related_logs,
        })

    # curated timeseries: baseline, study-best, each kpi's best (deduped), worst successful
    successful = [e for e in experiments if not e["failed"] and e["goal_score"] is not None]
    worst = min(successful, key=lambda e: e["goal_score"]) if successful else None
    selected_experiments = []
    seen = set()

    def add_selected(exp_num, label):
        if exp_num is None or exp_num in seen or len(seen) >= 8:
            return
        seen.add(exp_num)
        selected_experiments.append({"experiment": exp_num, "display_label": label})

    add_selected(baseline_exp, f"baseline (exp {baseline_exp})")
    add_selected(study.get("bestExperiment"), f"goal-best (exp {study.get('bestExperiment')})")
    for kpi in study.get("kpis") or []:
        add_selected(kpi.get("bestExperiment"), f"{kpi['name']}-best (exp {kpi.get('bestExperiment')})")
    if worst:
        add_selected(worst["experiment"], f"worst-successful (exp {worst['experiment']})")

    available_curated = [k for k in metric_means_raw.keys()
                          if any(k.endswith(suf) for suf in CURATED_METRIC_SUFFIXES)]
    timeseries_charts = build_timeseries_charts(metric_means_raw, available_curated, selected_experiments)

    # full per-metric mean snapshot for every "highlighted" experiment (baseline,
    # goal-best, each kpi-best, worst-successful) — a report needs these grouped
    # together without re-reading the raw export a second time.
    highlight_experiments = {}
    for sel in selected_experiments:
        exp_num = sel["experiment"]
        row = next((e for e in experiments if e["experiment"] == exp_num), None)
        highlight_experiments[exp_num] = {
            "label": sel["display_label"],
            "goal_score": row["goal_score"] if row else None,
            "parameters": row["parameters"] if row else {},
            "metrics": {k: per_exp[exp_num]["mean"] for k, per_exp in metric_means_raw.items() if exp_num in per_exp},
        }

    # bar charts for top categorical parameter effects on the goal
    bar_charts = {}
    for p in sorted(param_effects, key=lambda p: -abs(p.get("goal_spread_pct") or 0)):
        if p.get("type") != "categorical" or "per_metric" not in p or goal_key not in p["per_metric"]:
            continue
        groups = p["per_metric"][goal_key]["groups"]
        bars = [{"label": val, "value": g["mean"], "stdev": g["stdev"], "n": g["n"], "slot": i}
                for i, (val, g) in enumerate(sorted(groups.items()))]
        bar_charts[p["name"]] = svg_bar_chart("bar_" + re.sub(r"[^A-Za-z0-9_]", "_", p["name"]),
                                              f"{p['name']} vs. goal", "goal score", bars)

    output = {
        "study": {
            "name": study.get("name"),
            "state": study.get("state"),
            "startTimestamp": study.get("startTimestamp"),
            "endTimestamp": study.get("endTimestamp"),
            "goal": study.get("goal"),
            "bestScore": study.get("bestScore"),
            "bestValue": study.get("bestValue"),
            "bestExperiment": study.get("bestExperiment"),
            "bestConfiguration": study.get("bestConfiguration"),
            "kpis": study.get("kpis"),
            "finishedExperiments": study.get("finishedExperiments"),
            "experimentsWithErrors": study.get("experimentsWithErrors"),
            "parametersSelection": study.get("parametersSelection"),
            "parameterConstraints": study.get("parameterConstraints"),
        },
        "experiments": experiments,
        "baseline_experiment": baseline_exp,
        "n_experiments": len(experiments),
        "n_failed": len(failed_experiments),
        "failed_experiments": failed_detail,
        "parameter_effects": param_effects,
        "interactions": interactions,
        "interaction_data_coverage": interaction_coverage,
        "parameter_constraint_violations_found": constraint_violations,
        "parameter_constraint_checks_unevaluated": unevaluated_constraint_checks,
        "goal_formula_cross_check": goal_cross_check,
        "metrics_selected_but_never_produced_a_sample": missing_metrics,
        "nan_skip_warning_counts_by_metric": dict(nan_skips),
        "curated_timeseries_experiments": selected_experiments,
        "highlight_experiments": highlight_experiments,
        "charts": {
            "timeseries": timeseries_charts,
            "parameter_bars": bar_charts,
        },
    }

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"wrote {args.out}")
    print(f"experiments: {len(experiments)} ({len(failed_experiments)} failed)")
    print(f"parameters analyzed: {len(param_effects)}")
    print(f"interactions scanned: {len(interactions)} (coverage: {interaction_coverage.get('coverage_pct')})")
    print(f"parameterConstraints violations found (should be 0): {len(constraint_violations)}")
    print(f"goal formula cross-check (full-series vs windowed score): {goal_cross_check}")


if __name__ == "__main__":
    main()
