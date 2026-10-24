"""Построение графиков matplotlib и HTML-страницы с результатами."""

import html
import math
from pathlib import Path


def render_charts(data, output, label):
    """Создает шесть групп PNG, отдельный PNG каждого статуса и index.html."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    paths = []

    def save(fig, filename, title):
        if len(fig.axes) > 1 or not fig.axes[0].get_title():
            fig.suptitle(title, fontsize=13)
            fig.tight_layout(rect=(0, 0, 1, .94))
        else:
            fig.tight_layout(pad=1.5)

        fig.savefig(output / filename, dpi=180)
        plt.close(fig)
        paths.append((filename, title))

    def histogram(ax, values, title):
        maximum = max(values, default=0)

        if maximum < 1 / 60:
            factor, unit = 3600, "секунды"
        elif maximum < 1:
            factor, unit = 60, "минуты"
        else:
            factor, unit = 1, "часы"

        scaled = [value * factor for value in values]

        if scaled:
            bins = min(10, max(3, math.ceil(math.sqrt(len(scaled)))))
            upper = max(max(scaled) * 1.1, 1)
            ax.hist(
                scaled,
                bins=bins,
                range=(0, upper),
                color="#3674A8",
                edgecolor="white",
                linewidth=1.5,
                rwidth=.9,
            )
            ax.set_xlim(0, upper)
        else:
            ax.text(
                .5, .5, "Нет подходящих данных",
                ha="center", va="center",
                transform=ax.transAxes,
            )

        ax.set_title(f"{title} · задач: {len(values)}", fontsize=12, pad=14)
        ax.set_xlabel(f"Время, {unit}")
        ax.set_ylabel("Количество задач")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=.2)
        ax.spines[["top", "right"]].set_visible(False)

    fig, ax = plt.subplots(figsize=(10, 5))
    histogram(ax, data["lifetime_hours"], "От создания до финального закрытия")
    save(fig, "01_lifetime.png", "Длительность жизненного цикла закрытых задач")

    states = sorted(data["status_hours"].items())
    for index, (name, values) in enumerate(states, 1):
        fig, ax = plt.subplots(figsize=(10, 5))
        histogram(ax, values, name)
        save(fig, f"02_status_{index:02d}.png", "Время в состоянии " + name)
    count = max(1, len(states))
    fig, axes = plt.subplots(math.ceil(count / 2), 2, figsize=(12, 4 * math.ceil(count / 2)), squeeze=False)
    for ax, (name, values) in zip(axes.flat, states):
        histogram(ax, values, name)
    for ax in list(axes.flat)[len(states):]:
        ax.set_visible(False)
    if not states:
        axes.flat[0].set_visible(True)
        histogram(axes.flat[0], [], "Состояния")
    save(fig, "02_statuses.png", "Распределение времени по состояниям закрытых задач")

    fig, ax = plt.subplots(figsize=(11, 5))
    daily = data["daily"]
    x = list(range(len(daily)))
    if daily:
        ax.bar([v - .2 for v in x], [r["created"] for r in daily], width=.4, label="Созданы за день", color="#86b7df")
        ax.bar([v + .2 for v in x], [r["closed"] for r in daily], width=.4, label="Закрыты за день", color="#a8d5a2")
        ax.plot(x, [r["cumulative_created"] for r in daily], label="Созданы накопительно", color="#185991")
        ax.plot(x, [r["cumulative_closed"] for r in daily], label="Закрыты накопительно", color="#287b33")
        step = max(1, len(daily) // 10)
        ticks = sorted(set(list(range(0, len(daily), step)) + [len(daily) - 1]))
        ax.set_xticks(ticks, [daily[i]["day"] for i in ticks], rotation=35, ha="right")
        ax.legend()
    ax.set(xlabel=f"Календарный день, UTC{data['utc_offset_hours']:+g}", ylabel="Количество задач")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="y", alpha=.2)
    save(fig, "03_daily.png", "Созданные и закрытые задачи по дням")

    users = data["users"]
    fig, ax = plt.subplots(figsize=(11, max(5, .43 * len(users))))
    y = list(range(len(users)))
    ax.barh([v - .2 for v in y], [u["assignee"] for u in users], height=.4, label="Исполнитель", color="#2563a3")
    ax.barh([v + .2 for v in y], [u["reporter"] for u in users], height=.4, label="Репортер", color="#d69237")
    names = [u["name"] for u in users]
    labels = [u["name"] + (f" [{u['id'][-6:]}]" if names.count(u["name"]) > 1 else "") for u in users]
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set(xlabel="Количество задач", ylabel="Пользователь")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    if users:
        ax.legend()
    ax.grid(axis="x", alpha=.2)
    save(fig, "04_users.png", f"Топ пользователей по числу разных задач  показано {len(users)} из не более 30")

    fig, ax = plt.subplots(figsize=(10, 5))
    histogram(ax, data["logged_hours"], "Залогированные трудозатраты на задачу")
    save(fig, "05_logged.png", f"Трудозатраты закрытых задач  без данных {data['missing_worklogs']}")

    fig, ax = plt.subplots(figsize=(10, 5))
    severity = data["severity_counts"]
    ax.bar(list(severity), list(severity.values()), color="#2563a3")
    ax.set(xlabel="Значение поля " + data["severity_field"], ylabel="Количество задач")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.tick_params(axis="x", rotation=20)
    ax.grid(axis="y", alpha=.2)
    save(fig, "06_severity.png", "Распределение задач по выбранному полю серьезности")

    blocks = "".join(f'<h2>{html.escape(title)}</h2><img src="{filename}" alt="{html.escape(title)}">'
                     for filename, title in paths)
    page = ("<!doctype html><html lang='ru'><meta charset='utf-8'><title>Аналитика Jira</title>"
            "<style>body{max-width:1100px;margin:32px auto;font:17px Arial;padding:0 20px}"
            "img{width:100%;height:auto}h2{margin-top:40px}</style>"
            f"<h1>Аналитика Jira</h1><p>{html.escape(label)}</p>"
            f"<p>Задач: {data['total']}. Закрытых с датой: {data['closed_count']}. "
            f"Закрытых без трудозатрат: {data['missing_worklogs']}.</p>" + blocks + "</html>")
    (output / "index.html").write_text(page, encoding="utf-8")
