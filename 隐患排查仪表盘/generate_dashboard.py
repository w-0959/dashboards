# -*- coding: utf-8 -*-
"""
D91 隐患排查和整改（安管）· 隐患排查整改情况仪表盘生成器
用法:
    python3 generate_dashboard.py                 # 默认前一天
    python3 generate_dashboard.py 2026-09-27      # 指定日期
只读连接草料二维码数据库 table_d91，按参考图六宫格布局生成自包含 HTML 仪表盘。
"""
import json
import sys
import os
import datetime
from collections import Counter
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

UNIT_ORDER = ["安全环保部", "生产作业分公司", "设备技术分公司", "综合支援分公司",
              "散杂货分公司", "集装箱分公司", "科技工程部", "资产财务部",
              "生产业务部", "现场指挥中心（业务部）", "管理公司（港荣）", "管理公司（长合）", "相关方"]
REASON_ORDER = ["人的不安全行为", "安全管理存在的缺陷或漏洞", "环境的不安全因素", "设备设施的不安全状态"]

PALETTE = ["#2563eb", "#7c3aed", "#16a34a", "#f59e0b", "#db2777", "#0d9488",
           "#64748b", "#0891b2", "#9333ea", "#22c55e", "#f43f5e", "#6366f1",
           "#059669", "#f97316", "#84cc16", "#a16207"]


def conn():
    return pymysql.connect(**DB)


def fetch_day(cur, d):
    d0 = datetime.datetime.combine(d, datetime.time.min)
    d1 = datetime.datetime.combine(d + datetime.timedelta(days=1), datetime.time.min)
    cur.execute("""SELECT 记录时间, 隐患原因_3468060, 隐患分类_3468054, 隐患级别_3472164,
                    隐患部门_3468055, 所在部门_3468070, 姓名_3468069, 隐患描述_3468053,
                    隐患排查形式_3472220, 记录编号, 整改负责人_3468068, 隐患立行立改情况_3468065
                   FROM table_d91 WHERE 记录时间 >= %s AND 记录时间 < %s ORDER BY 记录时间""", (d0, d1))
    out = []
    for r in cur.fetchall():
        rec = {
            "time": r[0].strftime("%H:%M") if r[0] else "",
            "reason": (r[1] or "").strip(),
            "category": (r[2] or "").strip(),
            "level": (r[3] or "").strip(),
            "danger_dept": (r[4] or "").strip(),
            "unit": (r[5] or "").strip(),
            "name": (r[6] or "").strip(),
            "desc": (r[7] or "").strip(),
            "form": (r[8] or "").strip(),
            "rec_no": (r[9] or "").strip(),
            "fix_owner": (r[10] or "").strip(),
            "fix_status": (r[11] or "").strip(),
        }
        out.append(rec)
    return out


def fetch_month_trend(cur, d):
    """目标日期所在月从1号到目标日期的每日记录数。"""
    if d.month == 12:
        m1 = datetime.date(d.year + 1, 1, 1)
    else:
        m1 = datetime.date(d.year, d.month + 1, 1)
    m0 = d.replace(day=1)
    cur.execute("""SELECT DATE(记录时间), COUNT(*) FROM table_d91
                   WHERE 记录时间 >= %s AND 记录时间 < %s GROUP BY DATE(记录时间) ORDER BY 1""",
                (datetime.datetime.combine(m0, datetime.time.min),
                 datetime.datetime.combine(m1, datetime.time.min)))
    counts = {r[0]: r[1] for r in cur.fetchall()}
    dates, nums = [], []
    dd = m0
    while dd <= d:
        dates.append(dd.strftime("%m-%d"))
        nums.append(counts.get(dd, 0))
        dd += datetime.timedelta(days=1)
    return dates, nums


def fetch_year_categories(cur, d):
    """今年所有记录的隐患分类（逗号分隔多选）。"""
    cur.execute("""SELECT 隐患分类_3468054 FROM table_d91
                   WHERE 记录时间 >= %s AND 记录时间 < %s""",
                (datetime.datetime(d.year, 1, 1, 0, 0),
                 datetime.datetime(d.year + 1, 1, 1, 0, 0)))
    out = []
    for (c,) in cur.fetchall():
        if c:
            for x in c.split(","):
                x = x.strip()
                if x:
                    out.append(x)
    return out


def dist(records, key):
    from collections import Counter
    c = Counter()
    for r in records:
        v = r.get(key)
        if v:
            c[v] += 1
    return [{"name": k, "value": v} for k, v in c.items()]


def main():
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    d = datetime.date.fromisoformat(date_str)

    c = conn()
    cur = c.cursor()
    records = fetch_day(cur, d)
    trend_dates, trend_nums = fetch_month_trend(cur, d)
    year_cats = fetch_year_categories(cur, d)
    cur.close(); c.close()

    # 各单位排查隐患数量（昨日）
    units = dist(records, "unit")
    units.sort(key=lambda x: -x["value"])
    # 隐患原因（昨日）按固定顺序
    reasons = dist(records, "reason")
    reasons.sort(key=lambda x: REASON_ORDER.index(x["name"]) if x["name"] in REASON_ORDER else 99)
    # 隐患分类（今年），拆分多选并聚合，取前8+其他
    catc = Counter(year_cats)
    cat_all = [{"name": k, "value": v} for k, v in catc.items()]
    cat_all.sort(key=lambda x: -x["value"])
    top8 = cat_all[:8]
    rest = sum(x["value"] for x in cat_all[8:])
    if rest > 0:
        top8.append({"name": "其他", "value": rest})
    year_total = sum(x["value"] for x in cat_all)

    # 动态单位配色
    unit_names = set(x["name"] for x in units)
    ordered_units = [u for u in UNIT_ORDER if u in unit_names] + sorted(unit_names - set(UNIT_ORDER))
    unit_color = {u: PALETTE[i % len(PALETTE)] for i, u in enumerate(ordered_units)}

    data = {
        "date": date_str,
        "gen_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "day_total": len(records),
        "month_total": sum(trend_nums),
        "year_total": year_total,
        "units": units,
        "reasons": reasons,
        "trend_dates": trend_dates,
        "trend_nums": trend_nums,
        "year_cats": top8,
        "records": records,
        "unit_color": unit_color,
    }

    html = TEMPLATE.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "隐患排查整改仪表盘.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("OK 生成:", out)
    print("日期=%s 昨日=%d 本月=%d 今年=%d 单位=%d 原因=%d 分类=%d" % (
        date_str, len(records), sum(trend_nums), year_total, len(units), len(reasons), len(top8)))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>全公司隐患排查整改情况</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%232563eb'/%3E%3Cpath d='M18 33l10 10 18-20' stroke='white' stroke-width='6' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<script>window.echarts || document.write('<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js"><\/script>');</script>
<style>
:root{
  --bg:#f4f6fb; --panel:#ffffff; --line:#e4e9f1;
  --tx:#22304a; --tx2:#5d6f8a; --tx3:#8b98ad;
  --ac:#2563eb;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;line-height:1.5;padding:18px;min-height:100vh}
.num{font-variant-numeric:tabular-nums}
.wrap{max-width:1120px;margin:0 auto}
.head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:6px 2px 16px}
.head h1{font-size:22px;font-weight:800;color:var(--tx);letter-spacing:.5px}
.head .sub{color:var(--tx2);font-size:13px;margin-top:4px}
.head .meta{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.pill{background:var(--panel);border:1px solid var(--line);color:var(--tx2);border-radius:999px;padding:5px 13px;font-size:12.5px}
.pill b{color:var(--ac);font-weight:700}
.grid{display:grid;grid-template-columns:260px 1fr 1fr;gap:12px}
@media(max-width:960px){.grid{grid-template-columns:1fr 1fr}}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 1px 2px rgba(34,48,74,.04);display:flex;flex-direction:column}
.panel h3{font-size:14px;font-weight:700;color:var(--tx);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.panel h3 .dot{width:8px;height:8px;border-radius:2px;background:var(--ac);display:inline-block}
.chart{width:100%;flex:1;min-height:250px}
/* KPI 卡 */
.kpi-card{justify-content:center;align-items:center;text-align:center;gap:6px;cursor:default}
.kpi-card .label{font-size:13px;color:var(--tx2);line-height:1.4}
.kpi-card .value{font-size:64px;font-weight:800;color:var(--ac);line-height:1}
.kpi-card .hint{font-size:11px;color:var(--tx3)}
.kpi-card.month .value{color:var(--tx)}
/* pie 图例说明 */
.pie-legend{margin-top:10px;display:flex;flex-direction:column;gap:6px}
.pie-legend .row{display:flex;justify-content:space-between;font-size:12px;color:var(--tx2);align-items:center}
.pie-legend .row b{color:var(--tx);font-weight:600}
.pie-legend .dot{width:10px;height:10px;border-radius:2px;margin-right:6px;display:inline-block}
/* 明细 */
.tbl{overflow-x:auto;margin-top:16px}
table{width:100%;min-width:820px;border-collapse:collapse;table-layout:fixed;font-size:12.5px}
thead th{text-align:left;color:var(--tx2);font-weight:600;border-bottom:1px solid var(--line);padding:8px;white-space:nowrap;background:var(--bg)}
tbody td{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;color:var(--tx)}
tbody tr:hover{background:rgba(37,99,235,.04)}
.lv{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;font-weight:600}
.lv.major{background:rgba(220,38,38,.12);color:#b91c1c}
.lv.big{background:rgba(249,115,22,.14);color:#c2410c}
.lv.mid{background:rgba(202,138,4,.16);color:#92400e}
.lv.low{background:rgba(22,163,74,.13);color:#15803d}
.foot{color:var(--tx3);font-size:11.5px;text-align:center;margin-top:18px;line-height:1.8}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <h1>上昼夜全公司隐患排查整改情况</h1>
      <div class="sub">草料二维码「隐患排查和整改（安管）」· 每天自动更新前一天</div>
    </div>
    <div class="meta">
      <div class="pill">数据日期：<b id="datelbl"></b></div>
      <div class="pill">生成时间：<b id="gen"></b></div>
    </div>
  </div>

  <div class="grid">
    <div class="panel kpi-card">
      <div class="label">昨日排查隐患总数<br>（不含零点之后）</div>
      <div class="value num" id="dayTotal">0</div>
      <div class="hint">记录时间处于目标日期当天</div>
    </div>
    <div class="panel">
      <h3><span class="dot"></span>各单位排查隐患数量（昨日）</h3>
      <div id="chUnit" class="chart"></div>
    </div>
    <div class="panel">
      <h3><span class="dot"></span>隐患原因（昨日）</h3>
      <div id="chReason" class="chart"></div>
    </div>

    <div class="panel kpi-card month">
      <div class="label">本月排查隐患总数</div>
      <div class="value num" id="monthTotal">0</div>
      <div class="hint">本月 1 日至目标日期累计</div>
    </div>
    <div class="panel">
      <h3><span class="dot"></span>排查隐患趋势（本月）</h3>
      <div id="chTrend" class="chart"></div>
    </div>
    <div class="panel">
      <h3><span class="dot"></span>隐患分类（今年）</h3>
      <div id="chCat" class="chart"></div>
      <div class="pie-legend" id="catLegend"></div>
    </div>
  </div>

  <div class="panel tbl">
    <h3 style="margin-bottom:6px"><span class="dot"></span>昨日隐患明细（<span id="recCnt" class="num"></span> 条）</h3>
    <table>
      <colgroup>
        <col style="width:10%"><col style="width:13%"><col style="width:13%"><col style="width:26%"><col style="width:10%"><col style="width:14%"><col style="width:14%">
      </colgroup>
      <thead>
        <tr><th>时间</th><th>隐患级别</th><th>所在部门</th><th>隐患描述</th><th>隐患原因</th><th>责任人</th><th>整改情况</th></tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>

  <div class="foot">
    数据来源：草料二维码「隐患排查和整改（安管）」数据库（只读）· 昨日=数据日期当天，本月=当月累计，今年=2026年累计
  </div>
</div>

<script>
const DATA = __DATA_JSON__;
document.getElementById("datelbl").textContent = DATA.date;
document.getElementById("gen").textContent = DATA.gen_time;
document.getElementById("dayTotal").textContent = DATA.day_total;
document.getElementById("monthTotal").textContent = DATA.month_total;
document.getElementById("recCnt").textContent = DATA.records.length;

const CAT_COLORS = ["#2563eb","#16a34a","#f59e0b","#7c3aed","#dc2626","#0d9488","#db2777","#64748b","#0891b2","#9333ea"];
const REASON_COLORS = ["#ef4444","#f59e0b","#3b82f6","#8b5cf6"];
const lvClass = l => (l||"").indexOf("重大")===0?"major":(l||"").indexOf("较大")===0?"big":(l||"").indexOf("一般")===0?"mid":"low";
function shortLv(l){return (l||"").replace(/[（(].*[)）]/g,"")||"—";}

/* 各单位排查隐患数量（昨日）bar */
(function(){
  const el=document.getElementById("chUnit"); if(!el) return;
  const ch=echarts.init(el);
  const rows=DATA.units.slice().reverse();
  ch.setOption({
    grid:{left:4,right:24,top:8,bottom:4,containLabel:true},
    tooltip:{trigger:"axis",axisPointer:{type:"shadow"}},
    xAxis:{type:"value",minInterval:1,splitLine:{lineStyle:{color:"rgba(34,48,74,.08)"}},axisLabel:{color:"#5d6f8a",fontSize:11}},
    yAxis:{type:"category",data:rows.map(r=>r.name),axisLabel:{color:"#334155",fontSize:11.5,width:90,overflow:"truncate"},axisLine:{show:false},axisTick:{show:false}},
    series:[{type:"bar",data:rows.map(r=>r.value),barMaxWidth:16,itemStyle:{color:p=>DATA.unit_color[rows[p.dataIndex].name]||"#2563eb",borderRadius:[0,3,3,0]},label:{show:true,position:"right",color:"#5d6f8a",fontSize:11}}]
  });
})();

/* 隐患原因（昨日）pie */
(function(){
  const el=document.getElementById("chReason"); if(!el) return;
  const ch=echarts.init(el);
  ch.setOption({
    color:REASON_COLORS,
    tooltip:{trigger:"item",formatter:"{b}<br/>{c} 项 ({d}%)"},
    series:[{type:"pie",radius:["40%","68%"],center:["50%","52%"],avoidLabelOverlap:true,
      label:{color:"#334155",fontSize:11,formatter:"{b}"},
      itemStyle:{borderRadius:4,borderColor:"#fff",borderWidth:1},
      data:DATA.reasons.map(r=>({name:r.name,value:r.value}))}]
  });
})();

/* 排查隐患趋势（本月）line */
(function(){
  const el=document.getElementById("chTrend"); if(!el) return;
  const ch=echarts.init(el);
  const last=DATA.trend_nums.length-1;
  ch.setOption({
    grid:{left:4,right:14,top:18,bottom:4,containLabel:true},
    tooltip:{trigger:"axis"},
    xAxis:{type:"category",boundaryGap:false,data:DATA.trend_dates,axisLabel:{color:"#5d6f8a",fontSize:10.5},axisLine:{lineStyle:{color:"#d0d7e2"}}},
    yAxis:{type:"value",minInterval:1,splitLine:{lineStyle:{color:"rgba(34,48,74,.08)"}},axisLabel:{color:"#5d6f8a",fontSize:11}},
    series:[{type:"line",smooth:true,symbol:"circle",symbolSize:5,
      data:DATA.trend_nums,
      lineStyle:{color:"#2563eb",width:2},
      itemStyle:{color:p=>p.dataIndex===last?"#f97316":"#2563eb"},
      areaStyle:{color:"rgba(37,99,235,.08)"},
      label:{show:true,position:"top",color:"#5d6f8a",fontSize:10}}]
  });
})();

/* 隐患分类（今年）pie + legend */
(function(){
  const el=document.getElementById("chCat"); if(!el) return;
  const ch=echarts.init(el);
  const cats=DATA.year_cats;
  ch.setOption({
    color:CAT_COLORS,
    tooltip:{trigger:"item",formatter:"{b}<br/>{c} ({d}%)"},
    series:[{type:"pie",radius:"62%",center:["50%","52%"],avoidLabelOverlap:true,
      label:{show:false},emphasis:{label:{show:true,color:"#334155",fontSize:12}},
      itemStyle:{borderRadius:4,borderColor:"#fff",borderWidth:1},
      data:cats.map(r=>({name:r.name,value:r.value}))}]
  });
  const total=DATA.year_total;
  document.getElementById("catLegend").innerHTML=cats.map((c,i)=>
    `<div class="row"><span><span class="dot" style="background:${CAT_COLORS[i%CAT_COLORS.length]}"></span>${c.name}</span><b class="num">${c.value} (${(c.value/total*100).toFixed(1)}%)</b></div>`
  ).join("");
})();

/* 昨日隐患明细 */
const tb=document.getElementById("tbody");
tb.innerHTML=DATA.records.map(r=>`<tr>
  <td class="num">${r.time}</td>
  <td><span class="lv ${lvClass(r.level)}">${shortLv(r.level)}</span></td>
  <td>${r.unit||"—"}</td>
  <td>${r.desc||"—"}</td>
  <td>${r.reason||"—"}</td>
  <td>${r.fix_owner||"—"}</td>
  <td>${r.fix_status||"—"}</td>
</tr>`).join("");

window.addEventListener("resize",()=>{
  ["chUnit","chReason","chTrend","chCat"].forEach(id=>{const e=document.getElementById(id);if(e&&e.__ec)e.__ec.resize();});
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
