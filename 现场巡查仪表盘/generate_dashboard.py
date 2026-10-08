# -*- coding: utf-8 -*-
"""
现场巡查记录 · 每日更新仪表盘生成器
用法:
    python3 generate_dashboard.py                 # 默认今天
    python3 generate_dashboard.py 2026-09-28      # 指定日期
只读连接草料二维码数据库 table_d93（现场巡查记录），按"记录时间=目标日期"取当天记录，
聚合后生成自包含 HTML 仪表盘。不写入、不修改数据库任何数据。
"""
import json
import sys
import os
import datetime
try:
    import pymysql
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pymysql"], check=True)
    import pymysql

DB = dict(
    host="rm-bp1m4fy8d66u3c6xmbo.mysql.rds.aliyuncs.com",
    port=3306, user="cli_9677100", password="dfeb45e53d940a3b7fad2b934273a18a",
    database="cli_9677100", charset="utf8mb4", connect_timeout=15, read_timeout=60,
)

FIELDS = {
    "record_time": "记录时间",
    "cat": "项目分类_3712283",
    "item": "巡查项目_3472176",
    "risk": "项目风险_3472174",
    "risk_lvl": "风险管理级别_3472224",
    "unit": "所属单位_3730135",
    "owner": "项目安健环责任归属_3472213",
    "leader": "项目现场负责人姓名_3472178",
    "guard": "项目现场监护人_3472179",
    "party": "相关方公司名称_3712303",
    "ship": "船名_3712296",
    "spec": "特殊作业_3472177",
    "inspector": "巡查人_3472187",
    "rec_no": "记录编号",
    "code_name": "码名称",
    "key_ship": "是否CAPE船或直航船或过境危险品船舶_3712318",
}

RISK_ORDER = ["重大风险（人机混合、大型检维修）", "较大风险（船舶靠离泊、清舱、皮带机）", "一般风险", "低风险"]


def conn():
    return pymysql.connect(**DB)


def fetch_day(cur, d):
    d0 = datetime.datetime.combine(d, datetime.time.min)
    d1 = datetime.datetime.combine(d + datetime.timedelta(days=1), datetime.time.min)
    cols = ", ".join("`%s`" % c for c in FIELDS.values())
    cur.execute("SELECT %s FROM table_d93 WHERE 记录时间 >= %%s AND 记录时间 < %%s ORDER BY 记录时间" % cols, (d0, d1))
    out = []
    for row in cur.fetchall():
        rec = dict(zip(FIELDS.keys(), row))
        rec["hour"] = rec["record_time"].hour if rec["record_time"] else 0
        rec["record_time"] = rec["record_time"].strftime("%m-%d %H:%M") if rec["record_time"] else ""
        for k in rec:
            if isinstance(rec[k], str):
                rec[k] = rec[k].strip()
        out.append(rec)
    return out


def fetch_trend(cur, d):
    # 从 08-31 到目标日期的每日新增记录数
    start = datetime.date(2026, 8, 31)
    cur.execute("""SELECT DATE(记录时间) dd, COUNT(*) FROM table_d93
                   WHERE 记录时间 >= '2026-08-31' AND 记录时间 < %s
                   GROUP BY DATE(记录时间) ORDER BY dd""",
                (datetime.datetime.combine(d + datetime.timedelta(days=1), datetime.time.min),))
    counts = {r[0]: r[1] for r in cur.fetchall()}
    dates, nums = [], []
    dd = start
    while dd <= d:
        dates.append(dd.strftime("%m-%d"))
        nums.append(counts.get(dd, 0))
        dd += datetime.timedelta(days=1)
    return dates, nums


def dist(records, key):
    from collections import Counter
    c = Counter()
    for r in records:
        v = r.get(key)
        if v:
            c[v] += 1
    return [{"name": k, "value": v} for k, v in c.items()]


def fetch_month(cur, d):
    """目标日期所在月的全部记录（仅取监管统计需要的字段）。"""
    if d.month == 12:
        m1 = datetime.date(d.year + 1, 1, 1)
    else:
        m1 = datetime.date(d.year, d.month + 1, 1)
    m0 = d.replace(day=1)
    cur.execute("""SELECT 记录时间, 项目风险_3472174, 特殊作业_3472177, 船名_3712296, 所属单位_3730135, 是否CAPE船或直航船或过境危险品船舶_3712318
                   FROM table_d93 WHERE 记录时间 >= %s AND 记录时间 < %s""",
                (datetime.datetime.combine(m0, datetime.time.min),
                 datetime.datetime.combine(m1, datetime.time.min)))
    out = []
    for r in cur.fetchall():
        out.append({"risk": (r[1] or "").strip(), "spec": (r[2] or "").strip(),
                    "ship": (r[3] or "").strip(), "unit": (r[4] or "").strip(),
                    "key_ship": (r[5] or "").strip()})
    return out


UNIT_ORDER = ["安全环保部", "生产业务部（原现场指挥中心）", "生产作业分公司",
              "设备技术分公司", "散杂货分公司", "集装箱分公司", "综合支援分公司"]
SPEC_ORDER = ["动火作业", "高空作业", "有限空间", "吊装作业", "临时用电"]
RISK_ORDER2 = ["重大风险（人机混合、大型检维修）", "较大风险（船舶靠离泊、清舱、皮带机）"]

# 差异化色板：足够覆盖所有出现单位，色相彼此拉开
PALETTE = ["#2563eb", "#7c3aed", "#16a34a", "#f59e0b", "#db2777", "#0d9488",
           "#64748b", "#0891b2", "#9333ea", "#22c55e", "#f43f5e", "#6366f1",
           "#059669", "#f97316", "#84cc16", "#a16207"]


def build_unit_colors(unit_names):
    """给所有出现单位分配稳定且互不相同的颜色（同一单位在所有图中颜色一致）。"""
    ordered = [u for u in UNIT_ORDER if u in unit_names] + sorted(unit_names - set(UNIT_ORDER))
    return {u: PALETTE[i % len(PALETTE)] for i, u in enumerate(ordered)}, ordered


def build_monitor(recs, keyfield, rowset):
    """按 [类别行 x 所属单位] 统计人次，返回 {rows, units, series}。
    rows: 类别（如风险等级/特殊作业/船名）；series: {unit: [row对应的计数]}。"""
    from collections import defaultdict
    mat = defaultdict(lambda: defaultdict(int))
    unit_set = set()
    for r in recs:
        v = r.get(keyfield)
        if not v:
            continue
        if rowset is not None and v not in rowset:
            continue
        if keyfield == "ship" and r.get("key_ship") != "是":
            continue  # 重点船舶：仅统计CAPE/直航/过境危险品船
        u = r.get("unit") or "未填写"
        mat[v][u] += 1
        unit_set.add(u)
    # 类别行排序：优先固定顺序，其余按出现次数降序
    def row_key(r):
        if keyfield == "risk":
            return RISK_ORDER2.index(r) if r in RISK_ORDER2 else 99
        if keyfield == "spec":
            return SPEC_ORDER.index(r) if r in SPEC_ORDER else 99
        return -sum(mat[r].values())
    rows = sorted(mat.keys(), key=row_key)
    units = [u for u in UNIT_ORDER if u in unit_set] + sorted(unit_set - set(UNIT_ORDER))
    series = {u: [mat[r].get(u, 0) for r in rows] for u in units}
    return {"rows": rows, "units": units, "series": series}


def build_hourly(records):
    """按 [时段 x 所属单位] 统计当日巡查覆盖量，仅保留有记录的时段。返回 {hours, units, series}。"""
    from collections import defaultdict
    mat = defaultdict(lambda: defaultdict(int))
    unit_set = set()
    for r in records:
        h = r.get("hour")
        if h is None:
            continue
        u = r.get("unit") or "未填写"
        mat[h][u] += 1
        unit_set.add(u)
    units = [u for u in UNIT_ORDER if u in unit_set] + sorted(unit_set - set(UNIT_ORDER))
    # 只保留有巡查记录的时段（任一单位计数>0），按时间升序
    hours = sorted(h for h in mat if sum(mat[h].values()) > 0)
    hours_s = [f"{h:02d}" for h in hours]
    return {"hours": hours_s, "units": units,
            "series": {u: [mat[h].get(u, 0) for h in hours] for u in units}}


def main():
    # 默认生成"前一天"（每天6点自动刷新前一整天的数据）；可传日期参数手动生成指定日
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    d = datetime.date.fromisoformat(date_str)

    c = conn()
    cur = c.cursor()
    records = fetch_day(cur, d)
    trend_dates, trend_nums = fetch_trend(cur, d)
    month_recs = fetch_month(cur, d)
    cur.close(); c.close()

    total = len(records)
    units = dist(records, "unit")
    cats = dist(records, "cat")
    risks = dist(records, "risk")
    risk_lvls = dist(records, "risk_lvl")
    items = dist(records, "item")
    items.sort(key=lambda x: -x["value"])
    items = items[:10]

    # 高风险记录（重大/较大风险）
    high_risk = [r for r in records if r.get("risk") in ("重大风险（人机混合、大型检维修）", "较大风险（船舶靠离泊、清舱、皮带机）")]
    # 特殊作业（动火等）
    spec = [r for r in records if r.get("spec")]
    # 责任归属概览
    owners = dist(records, "owner")

    risk_sorted = sorted(risks, key=lambda x: RISK_ORDER.index(x["name"]) if x["name"] in RISK_ORDER else 99)

    # 监管人次统计（按所属单位分组）
    monitor = {
        "day": {
            "risk": build_monitor(records, "risk", {"重大风险（人机混合、大型检维修）", "较大风险（船舶靠离泊、清舱、皮带机）"}),
            "spec": build_monitor(records, "spec", None),
            "ship": build_monitor(records, "ship", None),
        },
        "month": {
            "risk": build_monitor(month_recs, "risk", {"重大风险（人机混合、大型检维修）", "较大风险（船舶靠离泊、清舱、皮带机）"}),
            "spec": build_monitor(month_recs, "spec", None),
            "ship": build_monitor(month_recs, "ship", None),
        },
    }

    # 所有涉及单位（当日+本月），为每张图的单位图例统一分配差异化颜色
    all_units = {r.get("unit") or "" for r in records} | {r.get("unit") or "" for r in month_recs}
    all_units.discard("")
    unit_color, unit_order = build_unit_colors(all_units)

    data = {
        "date": date_str,
        "gen_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": total,
        "unit_count": len(units),
        "cat_count": len(cats),
        "high_count": len(high_risk),
        "spec_count": len(spec),
        "trend_dates": trend_dates,
        "trend_nums": trend_nums,
        "cats": cats,
        "units": units,
        "risks": risk_sorted,
        "risk_lvls": risk_lvls,
        "items": items,
        "high_risk": high_risk,
        "records": records,
        "monitor": monitor,
        "hourly": build_hourly(records),
        "unit_color": unit_color,
    }

    html = TEMPLATE.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "现场巡查记录仪表盘.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("OK 生成:", out)
    print("日期=%s 记录数=%d 单位数=%d 分类数=%d 重大+较大风险=%d 特殊作业=%d" % (
        date_str, total, len(units), len(cats), len(high_risk), len(spec)))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>现场巡查记录 · 每日更新看板</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%230f766e'/%3E%3Cpath d='M18 33l10 10 18-20' stroke='white' stroke-width='6' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<script>window.echarts || document.write('<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js"><\/script>');</script>
<style>
:root{
  --bg:#f4f6fb; --panel:#ffffff; --panel2:#eef2f8; --line:#e4e9f1;
  --tx:#22304a; --tx2:#5d6f8a; --tx3:#8b98ad;
  --ac:#2563eb; --ac2:#0ea5e9;
  --r-major:#dc2626; --r-big:#f97316; --r-mid:#ca8a04; --r-low:#16a34a;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;line-height:1.5;padding:18px;min-height:100vh}
.num{font-variant-numeric:tabular-nums}
.wrap{max-width:1240px;margin:0 auto}
/* header */
.head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:6px 2px 16px}
.head h1{font-size:22px;font-weight:800;letter-spacing:.5px;color:var(--tx)}
.head .sub{color:var(--tx2);font-size:13px;margin-top:4px}
.head .meta{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.pill{background:var(--panel);border:1px solid var(--line);color:var(--tx2);border-radius:999px;padding:5px 13px;font-size:12.5px}
.pill b{color:var(--ac);font-weight:700}
.datebox{display:flex;align-items:center;gap:6px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:6px 10px}
.datebox input{background:transparent;border:none;color:var(--tx);font:inherit;font-size:13px;outline:none}
/* kpi */
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
@media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}}
@media(max-width:480px){.kpis{grid-template-columns:1fr 1fr}}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:0 1px 2px rgba(34,48,74,.04)}
.kpi .k{font-size:12px;color:var(--tx2)}
.kpi .v{font-size:30px;font-weight:800;margin-top:6px;line-height:1;color:var(--tx)}
.kpi .d{font-size:11.5px;color:var(--tx3);margin-top:6px}
.kpi.hot .v{color:var(--r-major)}
.kpi.ac .v{color:var(--ac)}
/* panel */
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:0 1px 2px rgba(34,48,74,.04)}
.panel h3{font-size:14px;font-weight:700;color:var(--tx);margin-bottom:10px;display:flex;align-items:center;gap:8px}
.panel h3 .dot{width:8px;height:8px;border-radius:2px;background:var(--ac);display:inline-block}
.chart{width:100%;height:280px}
.grid{display:grid;gap:12px;margin-top:12px}
.g-trend{grid-template-columns:1.6fr 1fr}
.g-dim{grid-template-columns:1fr 1fr 1fr}
.g-item{grid-template-columns:1fr}
.g-mon{grid-template-columns:repeat(3,1fr);margin-top:0}
.g-mon .chart{height:320px}
.sec-title{margin-top:16px;margin-bottom:2px;font-size:15px;font-weight:800;color:var(--tx);display:flex;align-items:center;gap:8px}
.sec-title::before{content:"";width:10px;height:10px;background:var(--ac);border-radius:2px}
@media(max-width:1100px){.g-mon{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){.g-mon{grid-template-columns:1fr}}
@media(max-width:900px){.g-trend,.g-dim{grid-template-columns:1fr}}
/* high risk strip */
.high{border:1px solid rgba(220,38,38,.35);background:linear-gradient(180deg,rgba(220,38,38,.05),rgba(220,38,38,.015));margin-top:12px}
.high h3 .dot{background:var(--r-major)}
.hr-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.hr-item{background:#fff7f7;border:1px solid rgba(249,115,22,.35);border-radius:10px;padding:10px 12px;font-size:12.5px}
.hr-item .t{color:var(--tx2);font-size:11.5px;display:flex;justify-content:space-between}
.hr-item .t b{color:var(--r-big);font-weight:800}
.hr-item .m{margin-top:6px;font-weight:700;font-size:13px;color:var(--tx)}
.hr-item .u{color:var(--tx2);margin-top:4px;font-size:12px}
.empty{color:var(--tx3);font-size:13px;padding:6px 2px}
/* table */
.tbl{overflow-x:auto;margin-top:12px}
table{width:100%;min-width:760px;border-collapse:collapse;table-layout:fixed;font-size:12.5px}
thead th{text-align:left;color:var(--tx2);font-weight:600;border-bottom:1px solid var(--line);padding:8px 8px;white-space:nowrap;background:var(--panel2)}
tbody td{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;color:var(--tx)}
tbody tr:hover{background:rgba(37,99,235,.04)}
.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;font-weight:600;white-space:nowrap}
.tag.major{background:rgba(220,38,38,.12);color:#b91c1c}
.tag.big{background:rgba(249,115,22,.14);color:#c2410c}
.tag.mid{background:rgba(202,138,4,.16);color:#92400e}
.tag.low{background:rgba(22,163,74,.13);color:#15803d}
.risk-tag{color:#b91c1c;font-weight:700}
/* footer */
.foot{color:var(--tx3);font-size:11.5px;text-align:center;margin-top:20px;line-height:1.8}
.toast{position:fixed;left:50%;bottom:30px;transform:translateX(-50%) translateY(20px);background:#22304a;border:none;color:#fff;padding:10px 16px;border-radius:10px;font-size:13px;opacity:0;pointer-events:none;transition:all .25s;z-index:99;max-width:86vw}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
@media(max-width:520px){.head h1{font-size:18px}.kpi .v{font-size:24px}.datebox input{font-size:16px}.panel h3{font-size:14px}table{font-size:13px}.pill{font-size:12.5px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <h1>现场巡查记录 · 每日更新看板</h1>
      <div class="sub">草料二维码「现场巡查记录」· 每天凌晨 1 点更新前一整天的数据</div>
    </div>
    <div class="meta">
      <div class="pill">数据范围：<b>2026-08-31 起</b></div>
      <div class="pill">生成时间：<b id="gen"></b></div>
      <div class="datebox">
        <label style="color:var(--tx2);font-size:12.5px">查看日期</label>
        <input type="date" id="datepicker">
      </div>
    </div>
  </div>

  <div class="kpis" id="kpis"></div>

  <div class="panel high">
    <h3><span class="dot"></span>当日重大 / 较大风险巡查（重点关注）</h3>
    <div class="hr-list" id="hrlist"></div>
  </div>

  <div class="grid g-trend">
    <div class="panel"><h3><span class="dot"></span>近 30 天每日新增记录数</h3><div id="chTrend" class="chart"></div></div>
    <div class="panel"><h3><span class="dot"></span>当日项目分类分布</h3><div id="chCat" class="chart"></div></div>
  </div>

  <div class="grid g-dim">
    <div class="panel"><h3><span class="dot"></span>当日所属单位分布</h3><div id="chUnit" class="chart"></div></div>
    <div class="panel"><h3><span class="dot"></span>当日项目风险等级</h3><div id="chRisk" class="chart"></div></div>
    <div class="panel"><h3><span class="dot"></span>当日风险管理级别分布</h3><div id="chLvl" class="chart"></div></div>
  </div>

  <div class="grid g-item">
    <div class="panel"><h3><span class="dot"></span>当日巡查项目 TOP10</h3><div id="chItem" class="chart" style="height:230px"></div></div>
  </div>

  <div class="panel" style="margin-top:12px">
    <h3><span class="dot"></span>全天动态巡查覆盖情况（昨日 · 仅显示有记录的时段）</h3>
    <div id="chHourly" class="chart" style="height:300px"></div>
  </div>

  <div class="sec-title">监管人次统计（按所属单位）</div>
  <div class="grid g-mon">
    <div class="panel"><h3><span class="dot"></span>较大及以上风险监管人次（昨日）</h3><div id="chMRiskD" class="chart"></div></div>
    <div class="panel"><h3><span class="dot"></span>特殊作业风险监管人次（昨日）</h3><div id="chMSpecD" class="chart"></div></div>
    <div class="panel"><h3><span class="dot"></span>重点船舶靠离泊风险监管人次（昨日）</h3><div id="chMShipD" class="chart"></div></div>
    <div class="panel"><h3><span class="dot"></span>较大及以上风险监管人次（本月）</h3><div id="chMRiskM" class="chart"></div></div>
    <div class="panel"><h3><span class="dot"></span>特殊作业风险监管人次（本月）</h3><div id="chMSpecM" class="chart"></div></div>
    <div class="panel"><h3><span class="dot"></span>重点船舶靠离泊风险监管人次（本月）</h3><div id="chMShipM" class="chart"></div></div>
  </div>

  <div class="panel tbl">
    <h3 style="margin-bottom:6px"><span class="dot"></span>当日记录明细（<span id="recCnt" class="num"></span> 条）</h3>
    <table>
      <colgroup>
        <col style="width:12%"><col style="width:12%"><col style="width:16%"><col style="width:11%"><col style="width:13%"><col style="width:12%"><col style="width:12%"><col style="width:12%">
      </colgroup>
      <thead>
        <tr><th>时间</th><th>项目分类</th><th>巡查项目</th><th>项目风险</th><th>风险管理级别</th><th>所属单位</th><th>责任人</th><th>巡查人</th></tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>

  <div class="foot">
    数据来源：草料二维码「现场巡查记录」数据库（只读） · 本页展示「生成日期」当天提交的记录（每天凌晨 1 点自动更新前一整天）<br>
    每日自动刷新：定时任务在每天 01:00 重新生成本页；「监管人次」按所属单位统计昨日与本月。
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
let toastTimer=null;
function toast(msg){
  const t=document.getElementById("toast");
  t.textContent=msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>t.classList.remove("show"),3200);
}
const DATA = __DATA_JSON__;
const RISK_COLOR = {"重大风险（人机混合、大型检维修）":"#dc2626","较大风险（船舶靠离泊、清舱、皮带机）":"#f97316","一般风险":"#ca8a04","低风险":"#16a34a"};
const CAT_COLORS = ["#2563eb","#16a34a","#f59e0b","#7c3aed","#dc2626","#0d9488","#db2777","#64748b"];

function shortRisk(r){return (r||"").replace(/（.+）$/,"");}
function riskTagClass(r){if(r.indexOf("重大")===0)return "major";if(r.indexOf("较大")===0)return "big";if(r.indexOf("一般")===0)return "mid";return "low";}

document.getElementById("gen").textContent = DATA.gen_time;
document.getElementById("recCnt").textContent = DATA.total;
document.getElementById("datepicker").value = DATA.date;
document.getElementById("datepicker").max = DATA.trend_dates[DATA.trend_dates.length-1];
document.getElementById("datepicker").min = DATA.trend_dates[0];
document.getElementById("datepicker").addEventListener("change", function(e){
  const d = this.value;
  if(d && d !== DATA.date){
    toast("本页仅展示「" + DATA.date + "」当天记录。查看其他日期请运行 generate_dashboard.py 指定日期生成，或等待每日自动刷新。");
    this.value = DATA.date;
  }
});

/* KPI */
const kpis = [
  {k:"当日巡查记录", v:DATA.total, d:"当日提交的记录总数", c:"ac"},
  {k:"涉及单位数", v:DATA.unit_count, d:"当日巡查所属单位", c:""},
  {k:"项目分类数", v:DATA.cat_count, d:"当日覆盖的作业分类", c:""},
  {k:"重大+较大风险", v:DATA.high_count, d:"需重点关注的高风险项", c:"hot"},
  {k:"特殊作业记录", v:DATA.spec_count, d:"当日特殊作业(动火等)", c:""},
];
document.getElementById("kpis").innerHTML = kpis.map(k=>`<div class="kpi ${k.c}"><div class="k">${k.k}</div><div class="v num">${k.v}</div><div class="d">${k.d}</div></div>`).join("");

/* 高风险列表 */
const hr = DATA.high_risk;
const hrBox = document.getElementById("hrlist");
if(hr.length===0){hrBox.innerHTML='<div class="empty">当日暂无重大 / 较大风险巡查记录</div>';}
else{
  hrBox.innerHTML = hr.map(r=>`<div class="hr-item">
    <div class="t"><span>${r.record_time} · ${r.inspector||r.record_time}</span><b>${shortRisk(r.risk)}</b></div>
    <div class="m">${r.cat} · ${r.item||"—"}</div>
    <div class="u">${r.unit} ｜ 责任人：${r.leader||"—"}</div>
  </div>`).join("");
}

/* 通用横向条形 */
function bar(id, data, {colors, name}={}){
  const el = document.getElementById(id); if(!el) return;
  const ch = echarts.init(el);
  const rows = data.slice().reverse();
  ch.setOption({
    grid:{left:8,right:28,top:8,bottom:8,containLabel:true},
    tooltip:{trigger:"axis",axisPointer:{type:"shadow"}},
    xAxis:{type:"value",splitLine:{lineStyle:{color:"rgba(34,48,74,.08)"}},axisLabel:{color:"#5d6f8a",fontSize:11}},
    yAxis:{type:"category",data:rows.map(r=>r.name),axisLabel:{color:"#334155",fontSize:11.5,width:96,overflow:"truncate"},axisLine:{show:false},axisTick:{show:false}},
    series:[{type:"bar",data:rows.map(r=>r.value),barMaxWidth:16,itemStyle:{color:p=> (colors?colors(p.name):CAT_COLORS[p.dataIndex%CAT_COLORS.length]),borderRadius:[0,3,3,0]},label:{show:true,position:"right",color:"#5d6f8a",fontSize:11}}]
  });
  return ch;
}

/* 趋势 */
(function(){
  const el = document.getElementById("chTrend"); if(!el) return;
  const ch = echarts.init(el);
  const last = DATA.trend_nums.length-1;
  ch.setOption({
    grid:{left:4,right:10,top:22,bottom:4,containLabel:true},
    tooltip:{trigger:"axis"},
    xAxis:{type:"category",data:DATA.trend_dates,axisLabel:{color:"#5d6f8a",fontSize:10.5,interval:3},axisLine:{lineStyle:{color:"#d0d7e2"}}},
    yAxis:{type:"value",splitLine:{lineStyle:{color:"rgba(34,48,74,.08)"}},axisLabel:{color:"#5d6f8a",fontSize:11}},
    series:[{type:"bar",data:DATA.trend_nums,barMaxWidth:14,
      itemStyle:{color:p=> p.dataIndex===last?"#f97316":"#2563eb",borderRadius:[2,2,0,0]},
      label:{show:true,position:"top",color:"#5d6f8a",fontSize:10,formatter:p=> p.dataIndex===last?p.value:""}}]
  });
  ch.on("click",()=>{});
})();

bar("chCat", DATA.cats);
bar("chUnit", DATA.units);
bar("chRisk", DATA.risks, {colors:n=>RISK_COLOR[n]||"#2563eb"});
bar("chLvl", DATA.risk_lvls);
bar("chItem", DATA.items);

/* 监管人次：横向分组条形图，按所属单位配色 */
/* 监管人次：横向分组条形图，按所属单位配色（覆盖所有出现单位，动态分配） */
const UNIT_COLOR = DATA.unit_color;
function monitorChart(id, m){
  const el = document.getElementById(id); if(!el||!m||!m.rows||!m.rows.length){ if(el){el.style.paddingTop="40px";el.textContent="当日无此类记录";el.style.color="var(--tx3)";el.style.fontSize="13px";} return; }
  const ch = echarts.init(el);
  const rows = m.rows.slice().reverse();
  const series = m.units.map(u=>({
    name:u, type:"bar", stack:"total", barMaxWidth:16,
    itemStyle:{color:UNIT_COLOR[u]||"#2563eb",borderRadius:0},
    label:{show:true,position:"inside",color:"#fff",fontSize:10.5},
    data:m.series[u].slice().reverse()
  }));
  ch.setOption({
    grid:{left:4,right:18,top:8,bottom:4,containLabel:true},
    tooltip:{trigger:"axis",axisPointer:{type:"shadow"}},
    legend:{top:0,textStyle:{color:"#5d6f8a",fontSize:10.5},itemWidth:12,itemHeight:8,type:"scroll"},
    xAxis:{type:"value",minInterval:1,splitLine:{lineStyle:{color:"rgba(34,48,74,.08)"}},axisLabel:{color:"#5d6f8a",fontSize:11}},
    yAxis:{type:"category",data:rows,axisLabel:{color:"#334155",fontSize:11.5,width:110,overflow:"truncate"},axisLine:{show:false},axisTick:{show:false}},
    series:series
  });
  return ch;
}
monitorChart("chMRiskD", DATA.monitor.day.risk);
monitorChart("chMSpecD", DATA.monitor.day.spec);
monitorChart("chMShipD", DATA.monitor.day.ship);
monitorChart("chMRiskM", DATA.monitor.month.risk);
monitorChart("chMSpecM", DATA.monitor.month.spec);
monitorChart("chMShipM", DATA.monitor.month.ship);

/* 全天24时段动态巡查覆盖情况（昨日） */
(function(){
  const el = document.getElementById("chHourly"); if(!el) return;
  const h = DATA.hourly;
  const ch = echarts.init(el);
  const series = h.units.map(u=>({
    name:u, type:"bar", stack:"total", barMaxWidth:20,
    itemStyle:{color:UNIT_COLOR[u]||"#2563eb"},
    data:h.series[u]
  }));
  ch.setOption({
    grid:{left:4,right:14,top:28,bottom:4,containLabel:true},
    tooltip:{trigger:"axis",axisPointer:{type:"shadow"}},
    legend:{top:0,textStyle:{color:"#5d6f8a",fontSize:10.5},itemWidth:12,itemHeight:8,type:"scroll"},
    xAxis:{type:"category",data:h.hours,axisLabel:{color:"#5d6f8a",fontSize:10.5},axisLine:{lineStyle:{color:"#d0d7e2"}},axisTick:{show:false}},
    yAxis:{type:"value",minInterval:1,splitLine:{lineStyle:{color:"rgba(34,48,74,.08)"}},axisLabel:{color:"#5d6f8a",fontSize:11}},
    series:series
  });
})();

/* 明细表 */
const tb = document.getElementById("tbody");
tb.innerHTML = DATA.records.map(r=>`<tr>
  <td class="num">${r.record_time}</td>
  <td>${r.cat||"—"}</td>
  <td>${r.item||"—"}</td>
  <td><span class="tag ${riskTagClass(r.risk||"低风险")}">${shortRisk(r.risk||"低风险")}</span></td>
  <td>${r.risk_lvl||"—"}</td>
  <td>${r.unit||"—"}</td>
  <td>${r.leader||"—"}</td>
  <td>${r.inspector||"—"}</td>
</tr>`).join("");

/* 响应式重绘 */
window.addEventListener("resize", ()=>{
  const els=["chTrend","chCat","chUnit","chRisk","chLvl","chItem","chHourly","chMRiskD","chMSpecD","chMShipD","chMRiskM","chMSpecM","chMShipM"];
  els.forEach(id=>{const e=document.getElementById(id); if(e&&e.__ec){e.__ec.resize();}});
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
