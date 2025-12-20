#!/usr/bin/env python3
"""
Generate SVG figures used by `reports/pendle-market-pricing-mechanism-explained.md`.

No third-party deps: uses only Python stdlib.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True)
class Series:
    name: str
    points: Sequence[tuple[float, float]]
    color: str
    stroke_width: float = 2.0
    dasharray: str | None = None


@dataclass(frozen=True)
class Marker:
    x: float
    y: float
    label: str
    color: str = "#111827"  # gray-900


def _linspace(a: float, b: float, n: int) -> list[float]:
    if n < 2:
        return [a]
    step = (b - a) / (n - 1)
    return [a + i * step for i in range(n)]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _svg_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _fmt_num(v: float) -> str:
    if abs(v) >= 100:
        return f"{v:.0f}"
    if abs(v) >= 10:
        return f"{v:.1f}"
    if abs(v) >= 1:
        return f"{v:.2f}"
    return f"{v:.3f}"


def _ticks(vmin: float, vmax: float, count: int) -> list[float]:
    if count <= 1:
        return [vmin]
    if vmax == vmin:
        return [vmin for _ in range(count)]
    return _linspace(vmin, vmax, count)


def _polyline_points(
    points: Sequence[tuple[float, float]],
    x_to_px: Callable[[float], float],
    y_to_px: Callable[[float], float],
) -> str:
    return " ".join(f"{x_to_px(x):.2f},{y_to_px(y):.2f}" for x, y in points)


def _render_panel(
    *,
    width: int,
    height: int,
    margin_left: int,
    margin_right: int,
    margin_top: int,
    margin_bottom: int,
    title: str,
    x_label: str,
    y_label: str,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    series_list: Sequence[Series],
    markers: Sequence[Marker] = (),
    vlines: Sequence[tuple[float, str]] = (),  # (x, label)
    x_tick_count: int = 6,
    y_tick_count: int = 5,
    y_formatter: Callable[[float], str] = _fmt_num,
) -> str:
    x_min, x_max = x_range
    y_min, y_max = y_range

    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    def x_to_px(x: float) -> float:
        return margin_left + (x - x_min) / (x_max - x_min) * plot_w

    def y_to_px(y: float) -> float:
        return margin_top + (y_max - y) / (y_max - y_min) * plot_h

    # Axis + grid
    x_ticks = _ticks(x_min, x_max, x_tick_count)
    y_ticks = _ticks(y_min, y_max, y_tick_count)

    parts: list[str] = []

    parts.append(
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white" />'
    )

    # Title
    parts.append(
        f'<text x="{width/2:.1f}" y="{margin_top/2:.1f}" text-anchor="middle" '
        f'font-family="ui-sans-serif, system-ui, -apple-system" font-size="16" fill="#111827">'
        f"{_svg_escape(title)}</text>"
    )

    # Grid lines
    for yt in y_ticks:
        y = y_to_px(yt)
        parts.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" '
            f'stroke="#E5E7EB" stroke-width="1" />'
        )

    # Vertical helper lines
    for xv, label in vlines:
        if xv < x_min or xv > x_max:
            continue
        x = x_to_px(xv)
        parts.append(
            f'<line x1="{x:.2f}" y1="{margin_top}" x2="{x:.2f}" y2="{height - margin_bottom}" '
            f'stroke="#9CA3AF" stroke-width="1.5" stroke-dasharray="4 4" />'
        )
        parts.append(
            f'<text x="{x + 6:.2f}" y="{margin_top + 16}" text-anchor="start" '
            f'font-family="ui-sans-serif, system-ui, -apple-system" font-size="12" fill="#6B7280">'
            f"{_svg_escape(label)}</text>"
        )

    # Axes
    parts.append(
        f'<line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" '
        f'y2="{height - margin_bottom}" stroke="#111827" stroke-width="1.5" />'
    )
    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" '
        f'stroke="#111827" stroke-width="1.5" />'
    )

    # Tick labels
    for xt in x_ticks:
        x = x_to_px(xt)
        parts.append(
            f'<line x1="{x:.2f}" y1="{height - margin_bottom}" x2="{x:.2f}" y2="{height - margin_bottom + 6}" '
            f'stroke="#111827" stroke-width="1" />'
        )
        parts.append(
            f'<text x="{x:.2f}" y="{height - margin_bottom + 22}" text-anchor="middle" '
            f'font-family="ui-sans-serif, system-ui, -apple-system" font-size="12" fill="#374151">'
            f"{_svg_escape(_fmt_num(xt))}</text>"
        )

    for yt in y_ticks:
        y = y_to_px(yt)
        parts.append(
            f'<line x1="{margin_left - 6}" y1="{y:.2f}" x2="{margin_left}" y2="{y:.2f}" '
            f'stroke="#111827" stroke-width="1" />'
        )
        parts.append(
            f'<text x="{margin_left - 10}" y="{y + 4:.2f}" text-anchor="end" '
            f'font-family="ui-sans-serif, system-ui, -apple-system" font-size="12" fill="#374151">'
            f"{_svg_escape(y_formatter(yt))}</text>"
        )

    # Axis labels
    parts.append(
        f'<text x="{width/2:.1f}" y="{height - 10}" text-anchor="middle" '
        f'font-family="ui-sans-serif, system-ui, -apple-system" font-size="13" fill="#111827">'
        f"{_svg_escape(x_label)}</text>"
    )
    parts.append(
        f'<text x="14" y="{height/2:.1f}" text-anchor="middle" '
        f'font-family="ui-sans-serif, system-ui, -apple-system" font-size="13" fill="#111827" '
        f'transform="rotate(-90, 14, {height/2:.1f})">'
        f"{_svg_escape(y_label)}</text>"
    )

    # Series polylines
    for s in series_list:
        poly = _polyline_points(s.points, x_to_px, y_to_px)
        dash = f' stroke-dasharray="{s.dasharray}"' if s.dasharray else ""
        parts.append(
            f'<polyline fill="none" stroke="{s.color}" stroke-width="{s.stroke_width}"{dash} '
            f'stroke-linejoin="round" stroke-linecap="round" points="{poly}" />'
        )

    # Markers
    for m in markers:
        if not (x_min <= m.x <= x_max and y_min <= m.y <= y_max):
            continue
        cx = x_to_px(m.x)
        cy = y_to_px(m.y)
        parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="4" fill="{m.color}" />')
        parts.append(
            f'<text x="{cx + 8:.2f}" y="{cy - 8:.2f}" text-anchor="start" '
            f'font-family="ui-sans-serif, system-ui, -apple-system" font-size="12" fill="#111827">'
            f"{_svg_escape(m.label)}</text>"
        )

    # Legend (top-right)
    if len(series_list) > 1:
        legend_x = width - margin_right - 10
        legend_y = margin_top + 8
        line_h = 18
        for idx, s in enumerate(series_list):
            y = legend_y + idx * line_h
            parts.append(
                f'<line x1="{legend_x - 130}" y1="{y:.2f}" x2="{legend_x - 110}" y2="{y:.2f}" '
                f'stroke="{s.color}" stroke-width="{s.stroke_width}" '
                f'{f"stroke-dasharray={chr(34)}{s.dasharray}{chr(34)}" if s.dasharray else ""} />'
            )
            parts.append(
                f'<text x="{legend_x - 104}" y="{y + 4:.2f}" text-anchor="start" '
                f'font-family="ui-sans-serif, system-ui, -apple-system" font-size="12" fill="#111827">'
                f"{_svg_escape(s.name)}</text>"
            )

    return "\n".join(parts)


def _render_svg_document(*, width: int, height: int, body: str) -> str:
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">',
            body,
            "</svg>",
        ]
    )


def _write_svg(path: Path, svg: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg + "\n", encoding="utf-8")


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def _exchange_rate_curve(
    *,
    scalar_root: float,
    last_ln_implied_rate: float,
    time_to_expiry_seconds: float,
    p0: float,
) -> Callable[[float], float]:
    one_year = 365 * 86400
    rate_scalar = scalar_root * one_year / time_to_expiry_seconds
    e0 = math.exp(last_ln_implied_rate * time_to_expiry_seconds / one_year)
    rate_anchor = e0 - _logit(p0) / rate_scalar

    def E(p: float) -> float:
        return _logit(p) / rate_scalar + rate_anchor

    return E


def _generate_fig1(out_dir: Path) -> None:
    """
    Figure 1: PT price and implied APY as a function of p (inventory proportion),
    using the example market snapshot from the previous research note.
    """
    # Snapshot-like parameters (floats, human-readable scale).
    py_index = 1.1590929262
    total_pt = 168_324.7732
    total_sy = 282_260.1990
    total_asset = total_sy * py_index
    p0 = total_pt / (total_pt + total_asset)

    scalar_root = 10.7165715974
    last_ln_implied_rate = 0.2103754602
    time_to_expiry_days = 95.3786
    time_to_expiry = time_to_expiry_days * 86400

    E = _exchange_rate_curve(
        scalar_root=scalar_root,
        last_ln_implied_rate=last_ln_implied_rate,
        time_to_expiry_seconds=time_to_expiry,
        p0=p0,
    )

    p_min, p_max = 0.052, 0.96
    xs = _linspace(p_min, p_max, 400)

    pt_price = [(p, 1.0 / E(p)) for p in xs]
    ln_implied = [(p, math.log(E(p)) * (365 * 86400) / time_to_expiry) for p in xs]
    apy = [(p, math.exp(r) - 1.0) for p, r in ln_implied]  # effective APY

    pt_min = min(y for _, y in pt_price)
    pt_max = max(y for _, y in pt_price)
    pt_pad = (pt_max - pt_min) * 0.08 or 0.01

    apy_min = min(y for _, y in apy)
    apy_max = max(y for _, y in apy)
    apy_pad = (apy_max - apy_min) * 0.10 or 0.01

    # Panel 1: PT price
    panel1 = _render_panel(
        width=920,
        height=320,
        margin_left=70,
        margin_right=30,
        margin_top=50,
        margin_bottom=60,
        title="Figure 1A — PT price (asset) vs inventory proportion p",
        x_label="p = PT / (PT + asset)  (after applying trade size: totalPt - netPtToAccount)",
        y_label="PT_price_asset",
        x_range=(p_min, p_max),
        y_range=(pt_min - pt_pad, pt_max + pt_pad),
        series_list=[Series(name="PT_price_asset = 1/E(p)", points=pt_price, color="#2563EB")],
        markers=[Marker(x=p0, y=1.0 / E(p0), label=f"current p0={p0:.3f}", color="#DC2626")],
        vlines=[(p0, "current p0")],
        y_tick_count=5,
        x_tick_count=6,
        y_formatter=lambda v: f"{v:.4f}",
    )

    # Panel 2: implied APY
    panel2 = _render_panel(
        width=920,
        height=320,
        margin_left=70,
        margin_right=30,
        margin_top=50,
        margin_bottom=60,
        title="Figure 1B — Implied APY (effective, from lnImpliedRate) vs p",
        x_label="p (same as above)",
        y_label="Implied APY",
        x_range=(p_min, p_max),
        y_range=(max(0.0, apy_min - apy_pad), apy_max + apy_pad),
        series_list=[Series(name="APY = exp( ln(E(p))*1y/T ) - 1", points=apy, color="#059669")],
        markers=[
            Marker(
                x=p0,
                y=math.exp(math.log(E(p0)) * (365 * 86400) / time_to_expiry) - 1.0,
                label="at p0",
                color="#DC2626",
            )
        ],
        vlines=[(p0, "current p0")],
        y_tick_count=5,
        x_tick_count=6,
        y_formatter=lambda v: f"{v*100:.1f}%",
    )

    # Compose a 2-panel SVG document.
    width = 920
    height = 680
    body = "\n".join(
        [
            f'<g transform="translate(0,0)">\n{panel1}\n</g>',
            f'<g transform="translate(0,340)">\n{panel2}\n</g>',
        ]
    )
    svg = _render_svg_document(width=width, height=height, body=body)
    _write_svg(out_dir / "pendle-fig1-ptprice-and-apy-vs-p.svg", svg)


def _generate_fig2(out_dir: Path) -> None:
    """
    Figure 2: show how time-to-expiry changes the PT price curve (holding scalarRoot and lnImpliedRate fixed).
    """
    py_index = 1.1590929262
    total_pt = 168_324.7732
    total_sy = 282_260.1990
    total_asset = total_sy * py_index
    p0 = total_pt / (total_pt + total_asset)

    scalar_root = 10.7165715974
    last_ln_implied_rate = 0.2103754602

    p_min, p_max = 0.052, 0.96
    xs = _linspace(p_min, p_max, 400)

    curves: list[Series] = []
    for days, color in [
        (180, "#7C3AED"),  # purple
        (90, "#2563EB"),  # blue
        (30, "#059669"),  # green
    ]:
        E = _exchange_rate_curve(
            scalar_root=scalar_root,
            last_ln_implied_rate=last_ln_implied_rate,
            time_to_expiry_seconds=days * 86400,
            p0=p0,
        )
        pts = [(p, 1.0 / E(p)) for p in xs]
        curves.append(Series(name=f"T={days}d", points=pts, color=color))

    all_y = [y for s in curves for _, y in s.points]
    y_min, y_max = min(all_y), max(all_y)
    y_pad = (y_max - y_min) * 0.10 or 0.01

    panel = _render_panel(
        width=920,
        height=420,
        margin_left=70,
        margin_right=30,
        margin_top=55,
        margin_bottom=65,
        title="Figure 2 — PT price curve flattens as expiry approaches (smaller T)",
        x_label="p = PT / (PT + asset)",
        y_label="PT_price_asset",
        x_range=(p_min, p_max),
        y_range=(y_min - y_pad, y_max + y_pad),
        series_list=curves,
        vlines=[(p0, "current p0")],
        y_formatter=lambda v: f"{v:.4f}",
    )
    svg = _render_svg_document(width=920, height=420, body=panel)
    _write_svg(out_dir / "pendle-fig2-ptprice-vs-p-different-T.svg", svg)


def _generate_fig3(out_dir: Path) -> None:
    """
    Figure 3: show the geometric-series effect for Buy YT:
        YT_per_SY ≈ pyIndex / (1 - PT_price_asset / F)
    """
    py_index = 1.1590929262

    # Use the same example snapshot parameters for a point marker.
    # (Values are computed from the same "research-note snapshot" constants used in Figure 1.)
    last_ln_implied_rate = 0.2103754602
    ln_fee_rate_root = 0.0028089610
    time_to_expiry_days = 95.3786
    time_to_expiry = time_to_expiry_days * 86400
    one_year = 365 * 86400
    fee_factor = math.exp(ln_fee_rate_root * time_to_expiry / one_year)
    spot_exchange_rate = math.exp(last_ln_implied_rate * time_to_expiry / one_year)
    pt_price_at_p0 = 1.0 / spot_exchange_rate

    d_min, d_max = 0.80, 0.999
    ds = _linspace(d_min, d_max, 400)

    def yt_per_sy(d: float, F: float) -> float:
        # Guard the vertical asymptote (unreachable in normal PT markets, but keep plot stable)
        denom = 1.0 - d / F
        denom = max(1e-6, denom)
        return py_index / denom

    curve_no_fee = [(d, yt_per_sy(d, 1.0)) for d in ds]
    curve_with_fee = [(d, yt_per_sy(d, fee_factor)) for d in ds]

    y_all = [y for _, y in curve_no_fee] + [y for _, y in curve_with_fee]
    y_min, y_max = min(y_all), min(max(y_all), 120.0)  # clamp y for readability

    # Also clamp plotted y to y_max so the chart stays readable near d -> 1
    curve_no_fee_clamped = [(d, _clamp(y, y_min, y_max)) for d, y in curve_no_fee]
    curve_with_fee_clamped = [(d, _clamp(y, y_min, y_max)) for d, y in curve_with_fee]

    panel = _render_panel(
        width=920,
        height=420,
        margin_left=70,
        margin_right=30,
        margin_top=55,
        margin_bottom=65,
        title="Figure 3 — Why “1 SY buys many YT”: geometric series amplification",
        x_label="PT_price_asset (d = 1 / exchangeRate at the spot point)",
        y_label="YT per SY (approx)",
        x_range=(d_min, d_max),
        y_range=(0.0, y_max * 1.05),
        series_list=[
            Series(name="No fee (F=1)", points=curve_no_fee_clamped, color="#2563EB"),
            Series(name=f"With fee (F≈{fee_factor:.6f})", points=curve_with_fee_clamped, color="#DC2626"),
        ],
        markers=[
            Marker(
                x=pt_price_at_p0,
                y=_clamp(yt_per_sy(pt_price_at_p0, fee_factor), 0.0, y_max * 1.05),
                label=f"example: d≈{pt_price_at_p0:.3f} → ~{yt_per_sy(pt_price_at_p0, fee_factor):.1f} YT/SY",
                color="#111827",
            )
        ],
        y_tick_count=6,
        y_formatter=lambda v: f"{v:.0f}",
    )
    svg = _render_svg_document(width=920, height=420, body=panel)
    _write_svg(out_dir / "pendle-fig3-yt-per-sy-vs-ptprice.svg", svg)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / "reports" / "assets"

    _generate_fig1(out_dir)
    _generate_fig2(out_dir)
    _generate_fig3(out_dir)

    print("Generated:")
    for name in [
        "pendle-fig1-ptprice-and-apy-vs-p.svg",
        "pendle-fig2-ptprice-vs-p-different-T.svg",
        "pendle-fig3-yt-per-sy-vs-ptprice.svg",
    ]:
        print(" -", out_dir / name)


if __name__ == "__main__":
    main()
