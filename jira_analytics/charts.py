"""Читаемые гистограммы, диаграммы и автономный HTML-отчет."""

import html
import json
import math
from pathlib import Path
import textwrap

BLUE = "#2563EB"
RED = "#DC4446"
GREEN = "#398653"
INK = "#172B4D"
MUTED = "#52647A"
STATE_COLORS = ["#2563EB", "#D18A20", "#7C58BB", "#398653"]


def _number(value):
    """Короткое число без незначащих нулей, с русским десятичным разделителем."""
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _time_unit(values, seconds_below=1 / 60):
    maximum = max(values, default=0)
    if maximum < seconds_below:
        return 3600, "секунды", "с"
    if maximum < 3:
        return 60, "минуты", "мин"
    return 1, "часы", "ч"


def _bin_edges(maximum, size):
    """Равные интервалы с удобными границами 1, 2, 2.5 или 5 × 10^k."""
    target = maximum / min(12, max(4, math.ceil(math.sqrt(size))))
    base = 10 ** math.floor(math.log10(target))
    fraction = target / base
    width = max(v for v in (1, 2, 2.5, 5, 10) if v <= fraction + 1e-10) * base
    count = max(1, math.ceil(maximum / width - 1e-10))
    return [i * width for i in range(count + 1)], width


def _priority_order(name):
    order = {"highest": 0, "blocker": 0, "high": 1, "critical": 1,
             "medium": 2, "major": 2, "low": 3, "minor": 3,
             "lowest": 4, "trivial": 4}
    return order.get(name.casefold(), 5), name.casefold()


def render_charts(data, output, label):
    """Строит шесть видов отчетов и отдельную диаграмму каждого статуса.

    Длительности поступают в часах. На всех диаграммах состояний используется
    одна единица времени; нули показаны в точке 0 без выдуманного интервала.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"states": [], "groups": []}
    dated = [r for r in data["issues"] if r["lifetime_hours"] is not None]
    dated_keys = [r["key"] for r in dated]

    def style(ax, horizontal=False):
        ax.spines[["top", "right"]].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color("#B5C2D1")
        ax.tick_params(colors=MUTED, length=0, pad=8)
        ax.set_axisbelow(True)
        ax.grid(axis="x" if horizontal else "y", color="#E5EAF1", linewidth=.8)
        (ax.xaxis if horizontal else ax.yaxis).set_major_locator(MaxNLocator(integer=True))
        ax.xaxis.label.set_color(INK)
        ax.yaxis.label.set_color(INK)

    def canvas(title, subtitle, height=6.3):
        fig, ax = plt.subplots(figsize=(11.6, height))
        fig.patch.set_facecolor("white")
        fig.suptitle(title, x=.10, y=.97, ha="left", fontsize=19, color=INK, fontweight="bold")
        fig.text(.10, .885, subtitle, fontsize=11, color=MUTED)
        fig.subplots_adjust(left=.10, right=.965, top=.81, bottom=.23)
        style(ax)
        return fig, ax

    def save(fig, filename):
        fig.savefig(output / filename, dpi=200, facecolor="white")
        plt.close(fig)

    def histogram(ax, values, unit, color=BLUE, compact=False):
        factor, long_unit, short_unit = unit
        scaled = [v * factor for v in values]
        ax.set_xlabel(f"Время, {long_unit}", labelpad=10)
        ax.set_ylabel("Количество задач", labelpad=10)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: _number(x)))
        if not scaled:
            ax.set(xlim=(0, 1), ylim=(0, 1))
            ax.text(.5, .5, "Нет подходящих данных", transform=ax.transAxes,
                    ha="center", va="center", fontsize=14, color=MUTED)
            return "Нет наблюдений"
        if max(scaled) == 0:
            ax.vlines(0, 0, len(scaled), color=color, linewidth=3)
            ax.scatter([0], [len(scaled)], s=110, color=color, zorder=4)
            ax.set(xlim=(-.08, .92), ylim=(0, len(scaled) * 1.4))
            ax.set_xticks([0], ["0"])
            ax.text(.42, .68, f"Все {len(scaled)} значения\nравны 0 {short_unit}",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=14 if compact else 18, color=INK, linespacing=1.5)
            return f"Все значения равны 0 {short_unit}; расчет до финального закрытия"
        edges, width = _bin_edges(max(scaled), len(scaled))
        counts, _, bars = ax.hist(scaled, bins=edges, color=color,
                                 edgecolor="white", linewidth=1.5, rwidth=.82)
        for bar, count in zip(bars, counts):
            if count:
                ax.annotate(str(int(count)), (bar.get_x() + bar.get_width() / 2, count),
                            xytext=(0, 7), textcoords="offset points", ha="center",
                            fontsize=13, fontweight="bold", color=INK)
        ax.set_xlim(0, edges[-1])
        ax.set_ylim(0, max(counts) * 1.38)
        if len(edges) <= 9:
            ax.set_xticks(edges)
        else:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=8))
        return f"Интервал: {_number(width)} {short_unit}"

    def values_note(values, keys, unit):
        factor, _, short_unit = unit
        if len(values) <= 6:
            text = "   ·   ".join(f"{key}: {_number(v * factor)} {short_unit}"
                                  for key, v in zip(keys, values))
            return "\n".join(textwrap.wrap("Фактические значения: " + text, 105))
        return f"Наблюдений: {len(values)}. Высота столбца — число задач в интервале времени."

    def single_hist(filename, title, values, keys, unit, color=BLUE):
        fig, ax = canvas(title, f"Закрытые задачи · наблюдений: {len(values)}")
        detail = histogram(ax, values, unit, color)
        fig.text(.965, .885, detail, ha="right", color=MUTED, fontsize=11)
        fig.text(.10, .055, values_note(values, keys, unit), fontsize=10, color=MUTED, linespacing=1.5)
        save(fig, filename)

    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 12,
                         "axes.labelsize": 12, "xtick.labelsize": 11, "ytick.labelsize": 11}):
        lifetime_unit = _time_unit(data["lifetime_hours"])
        single_hist("01_lifetime.png", "От создания до финального закрытия",
                    data["lifetime_hours"], dated_keys, lifetime_unit)

        states = list(data["status_hours"].items())
        state_unit = _time_unit([v for _, values in states for v in values], seconds_below=1)
        for i, (name, values) in enumerate(states, 1):
            filename = f"02_status_{i:02d}.png"
            single_hist(filename, f"Время в состоянии «{name}»", values,
                        dated_keys, state_unit, STATE_COLORS[(i - 1) % len(STATE_COLORS)])
            manifest["states"].append({"name": name, "filename": filename,
                                       "unit": state_unit[1], "sample_count": len(values)})
        rows = max(1, math.ceil(len(states) / 2))
        fig, axes = plt.subplots(rows, 2, figsize=(14, 4.5 * rows + 1), squeeze=False)
        fig.suptitle("Время по состояниям закрытых задач", x=.07, y=.97,
                     ha="left", fontsize=20, color=INK, fontweight="bold")
        fig.text(.07, .925, f"Единица времени на всех панелях — {state_unit[1]}", color=MUTED)
        fig.subplots_adjust(left=.07, right=.97, bottom=.09, top=.83, wspace=.26, hspace=.62)
        for i, (ax, (name, values)) in enumerate(zip(axes.flat, states)):
            style(ax)
            histogram(ax, values, state_unit, STATE_COLORS[i % len(STATE_COLORS)], compact=True)
            ax.set_title(f"{name} · задач: {len(values)}", loc="left", fontsize=14,
                         color=INK, fontweight="bold", pad=17)
        for ax in list(axes.flat)[len(states):]:
            ax.set_visible(False)
        save(fig, "02_statuses.png")

        daily = data["daily"]
        fig, axes = plt.subplots(2, 1, figsize=(11.6, 8.2), sharex=True,
                                 gridspec_kw={"height_ratios": [1.15, 1]})
        fig.suptitle("Созданные и закрытые задачи по дням", x=.10, y=.97,
                     ha="left", color=INK, fontsize=19, fontweight="bold")
        fig.text(.10, .915, "Дневные значения и накопительный итог показаны отдельно", color=MUTED, fontsize=11)
        fig.subplots_adjust(left=.10, right=.965, top=.82, bottom=.16, hspace=.43)
        x = list(range(len(daily)))
        for ax in axes:
            style(ax)
            ax.set_ylabel("Количество задач")
        axes[0].set_title("За каждый день", loc="left", color=INK, fontsize=13, pad=12)
        axes[1].set_title("Накопительным итогом", loc="left", color=INK, fontsize=13, pad=12)
        if daily:
            for field, color, offset, label_text in (("created", RED, -.20, "Создано"),
                                                       ("closed", GREEN, .20, "Закрыто")):
                bars = axes[0].bar([v + offset for v in x], [r[field] for r in daily],
                                   width=.32, color=color, label=label_text, zorder=3)
                if len(daily) <= 15:
                    axes[0].bar_label(bars, labels=[str(int(r[field])) if r[field] else "" for r in daily],
                                      padding=5, fontsize=12, color=color, fontweight="bold")
            for field, color, marker, label_text in (("cumulative_created", RED, "o", "Создано"),
                                                     ("cumulative_closed", GREEN, "s", "Закрыто")):
                axes[1].plot(x, [r[field] for r in daily], color=color, marker=marker,
                             markersize=7, linewidth=2.2, label=label_text, zorder=3)
                axes[1].annotate(str(daily[-1][field]), (x[-1], daily[-1][field]),
                                 xytext=(10, 3), textcoords="offset points", color=color,
                                 fontsize=12, fontweight="bold")
            peak = max(max(r["created"], r["closed"]) for r in daily)
            axes[0].set_ylim(0, max(peak * 1.3, 1))
            axes[1].set_ylim(0, max(daily[-1]["cumulative_created"], daily[-1]["cumulative_closed"], 1) * 1.3)
            step = max(1, math.ceil(len(daily) / 8))
            ticks = sorted(set(range(0, len(daily), step)) | {len(daily) - 1})
            axes[1].set_xticks(ticks, [daily[i]["day"] for i in ticks], rotation=25, ha="right")
            if len(daily) == 1:
                axes[1].set_xlim(-.8, .8)
            else:
                axes[1].set_xlim(-.6, len(daily) - .2)
            axes[0].legend(loc="upper right", ncol=2, frameon=False, bbox_to_anchor=(1, 1.28))
        axes[1].set_xlabel(f"Календарный день · UTC{data['utc_offset_hours']:+g}", labelpad=10)
        save(fig, "03_daily.png")

        users = data["users"]
        height = max(4.5, .6 * len(users) + 2.5)
        fig, ax = canvas("Топ пользователей по количеству задач",
                         f"Показано пользователей: {len(users)} · ограничение: 30 · рейтинг по различным задачам", height)
        ax.grid(False)
        style(ax, horizontal=True)
        y = list(range(len(users)))
        for role, color, offset, label_text in (("assignee", RED, -.18, "Исполнитель"),
                                                  ("reporter", GREEN, .18, "Репортер")):
            bars = ax.barh([v + offset for v in y], [u[role] for u in users],
                           height=.26, color=color, label=label_text, zorder=3)
            ax.bar_label(bars, padding=7, fontsize=12, color=color, fontweight="bold")
        names = [u["name"] for u in users]
        labels = [u["name"] + (f" [{u['id'][-6:]}]" if names.count(u["name"]) > 1 else "") for u in users]
        ax.set_yticks(y, labels)
        ax.set_ylim(len(users) - .38, -.62)
        peak = max((max(u["assignee"], u["reporter"]) for u in users), default=1)
        ax.set_xlim(0, max(peak * 1.18, 1))
        ax.set_xlabel("Количество задач", labelpad=10)
        ax.set_ylabel("Пользователь", labelpad=10)
        if users:
            ax.legend(loc="lower right", bbox_to_anchor=(1, 1.02), ncol=2, frameon=False, fontsize=10)
        fig.text(.10, .045, "Для каждой роли подсчет отдельный. Одна задача учитывается один раз при выборе топ-30.",
                 color=MUTED, fontsize=10)
        save(fig, "04_users.png")

        logged_keys = [r["key"] for r in data["issues"] if r["logged_hours"] is not None]
        logged_unit = _time_unit(data["logged_hours"])
        single_hist("05_logged.png", "Залогированные трудозатраты закрытых задач",
                    data["logged_hours"], logged_keys, logged_unit, GREEN)

        severity = data["severity_counts"]
        names = sorted(severity, key=_priority_order)
        title = "Количество задач по приоритетам" if data["severity_field"] == "priority" else "Количество задач по степени серьезности"
        fig, ax = canvas(title, f"Вся выборка · задач: {data['total']} · поле: {data['severity_field']}")
        palette = ["#A9252D", "#DC4446", "#CE8B23", "#377BC4", "#94A3B8"]
        bars = ax.bar(names, [severity[n] for n in names],
                      color=[palette[min(_priority_order(n)[0], 4)] for n in names], width=.58, zorder=3)
        ax.bar_label(bars, padding=7, fontsize=13, fontweight="bold", color=INK)
        ax.set_ylim(0, max(severity.values(), default=1) * 1.4)
        ax.set_ylabel("Количество задач", labelpad=10)
        ax.set_xlabel("Приоритет" if data["severity_field"] == "priority" else "Степень серьезности", labelpad=12)
        if len(names) > 7:
            ax.tick_params(axis="x", labelrotation=25)
        fig.text(.10, .055, "   ·   ".join(f"{n}: {severity[n]}" for n in names), fontsize=10, color=MUTED)
        save(fig, "06_severity.png")

    manifest["groups"] = ["01_lifetime.png", "02_statuses.png", "03_daily.png",
                          "04_users.png", "05_logged.png", "06_severity.png"]
    (output / "charts.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_html(data, output, label, manifest)
    return manifest


def _write_html(data, output, label, manifest):
    escape = html.escape

    def picture(filename, description):
        return f'<figure><a href="{filename}" target="_blank"><img src="{filename}" alt="{escape(description)}" loading="lazy"></a></figure>'

    state_buttons = "".join(f'<button type="button" class="state-button{" active" if i == 0 else ""}" data-panel="state-{i}" aria-pressed="{"true" if i == 0 else "false"}">{escape(s["name"])}</button>'
                            for i, s in enumerate(manifest["states"]))
    state_panels = "".join(f'<div id="state-{i}" class="state-panel" {"" if i == 0 else "hidden"}>{picture(s["filename"], s["name"])}</div>'
                           for i, s in enumerate(manifest["states"]))
    warning = "".join(f'<li>{escape(w)}</li>' for w in data.get("warnings", []))
    warning = f'<aside><strong>Особенности данных</strong><ul>{warning}</ul></aside>' if warning else ""
    mode = "Учебный пример" if data.get("source", {}).get("mode") == "demo" else "Данные Jira"
    field_title = "Приоритеты" if data["severity_field"] == "priority" else "Степень серьезности"
    titles = ["Жизненный цикл", "Время по состояниям", "Динамика задач", "Пользователи", "Трудозатраты", field_title]
    nav = "".join(f'<a href="#section-{i}">{i}. {t}</a>' for i, t in enumerate(titles, 1))
    body = f'''<header><p class="eyebrow">{mode} · аналитика проекта</p><h1>Задачи Jira</h1><p class="query">{escape(label)}</p>
<dl class="metrics"><div><dt>Всего задач</dt><dd>{data['total']}</dd></div><div><dt>Закрыто</dt><dd>{data['closed_count']}</dd></div><div><dt>С известной датой закрытия</dt><dd>{data.get('closed_with_date_count', len(data['lifetime_hours']))}</dd></div><div><dt>Без записей трудозатрат</dt><dd>{data['missing_worklogs']}</dd></div></dl></header>
<nav aria-label="Разделы отчета">{nav}</nav>{warning}
<section id="section-1"><h2>1. Жизненный цикл закрытых задач</h2><p>По X — время от создания до финального закрытия. По Y — количество задач в каждом интервале.</p>{picture('01_lifetime.png', titles[0])}</section>
<section id="section-2"><h2>2. Время по состояниям</h2><p>Каждое состояние показано отдельно. Единица времени одинакова на всех диаграммах. Повторные посещения состояния суммируются; непосещенные состояния имеют нулевую длительность.</p><div class="state-controls">{state_buttons}</div>{state_panels}<p><a href="02_statuses.png" target="_blank">Открыть общий обзор состояний</a></p></section>
<section id="section-3"><h2>3. Созданные и закрытые задачи</h2><p>Верхняя панель показывает события за день, нижняя — накопительный итог. Красный цвет — созданные задачи, зеленый — закрытые.</p>{picture('03_daily.png', titles[2])}</section>
<section id="section-4"><h2>4. Исполнители и репортеры</h2><p>По X — количество задач, по Y — пользователи. Отбор топ-30 выполняется по числу различных задач в объединении двух ролей.</p>{picture('04_users.png', titles[3])}</section>
<section id="section-5"><h2>5. Трудозатраты закрытых задач</h2><p>Используются записи учета времени. Отсутствующее значение не заменяется нулем.</p>{picture('05_logged.png', titles[4])}</section>
<section id="section-6"><h2>6. {field_title}</h2><p>Количество задач во всей выборке сгруппировано по выбранному полю серьезности.</p>{picture('06_severity.png', titles[5])}</section>
<footer><a href="daily.csv" download>Скачать таблицу по дням</a><a href="summary.json" download>Скачать сводные данные</a></footer>'''
    css = '''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f5f7fb;color:#172b4d;font:16px/1.65 system-ui,"Segoe UI",sans-serif}main{max-width:1180px;margin:auto;padding:38px 24px 52px}header{padding:8px 0 24px}.eyebrow{color:#52647a;font-size:14px;margin:0}h1{font-size:38px;line-height:1.2;margin:8px 0 12px}h2{font-size:24px;line-height:1.35;margin:0 0 10px}.query{color:#52647a;overflow-wrap:anywhere;margin:0}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:24px;margin:26px 0 0}.metrics div{border-left:3px solid #d4deec;padding-left:16px}dt{font-size:13px;color:#52647a}dd{font-size:32px;line-height:1.25;font-weight:700;margin:5px 0 0}nav{display:flex;flex-wrap:wrap;gap:8px 20px;border-top:1px solid #dce3ed;border-bottom:1px solid #dce3ed;padding:16px 0;margin-bottom:26px}a{color:#2459bd;text-decoration:none}a:hover{text-decoration:underline}section{background:white;padding:26px 24px;margin:22px 0;border-radius:10px;scroll-margin-top:16px}section>p{color:#52647a;margin:0 0 12px;max-width:980px}figure{margin:12px 0 0}figure img{display:block;width:100%;height:auto}.state-controls{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 8px}.state-button{border:1px solid #c9d5e5;background:white;border-radius:6px;padding:9px 18px;font:inherit;font-size:14px;color:#2459bd;cursor:pointer}.state-button.active{background:#2459bd;color:white;border-color:#2459bd}.state-button:focus-visible{outline:3px solid #97bbfa;outline-offset:2px}footer{display:flex;gap:26px;padding-top:12px;font-size:14px}aside{padding:12px 0;color:#805b10}aside ul{margin-top:8px}@media(max-width:700px){main{padding:22px 12px}.metrics{grid-template-columns:repeat(2,1fr);gap:18px}h1{font-size:30px}h2{font-size:21px}section{padding:20px 10px}nav{font-size:14px;gap:8px 14px}footer{flex-wrap:wrap;gap:12px}}'''
    script = '''document.querySelectorAll('.state-button').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('.state-button').forEach(b=>{const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))});document.querySelectorAll('.state-panel').forEach(p=>{p.hidden=p.id!==button.dataset.panel})}));'''
    page = f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Аналитика задач Jira</title><style>{css}</style></head><body><main>{body}</main><script>{script}</script></body></html>'
    (output / "index.html").write_text(page, encoding="utf-8")
