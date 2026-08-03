<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DivDesk 목업 — 배당ETF 매수검토기</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{
  --ink:#0F1E3D;        /* 통장 잉크 */
  --ink-2:#4A5872;
  --paper:#E9EDF2;      /* 명세서 용지 */
  --card:#FFFFFF;
  --rule:#C8D1DD;       /* 괘선 */
  --in:#0E6F63;         /* 입금(배당) */
  --out:#A63A18;        /* 차감(세금·배당락) */
  --gold:#8A6D1F;       /* 관망 */
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--paper);color:var(--ink);
  font-family:Pretendard,-apple-system,sans-serif;
  font-size:15px;line-height:1.5;
  padding-bottom:80px;
}
.num{font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums}
.wrap{max-width:460px;margin:0 auto;padding:0 16px}

/* 헤더 */
header{padding:20px 0 14px}
.brand{display:flex;align-items:baseline;gap:8px}
.brand h1{font-size:19px;font-weight:800;letter-spacing:-.03em}
.brand span{font-size:11px;color:var(--ink-2);letter-spacing:.08em}
.asof{margin-top:4px;font-size:11px;color:var(--ink-2)}

/* 계좌모드 세그먼트 */
.seg{display:flex;border:1px solid var(--ink);border-radius:2px;overflow:hidden;margin-top:14px}
.seg button{flex:1;padding:9px 4px;font-size:12px;font-weight:600;background:transparent;
  border:0;border-right:1px solid var(--rule);color:var(--ink-2);cursor:pointer;font-family:inherit}
.seg button:last-child{border-right:0}
.seg button[aria-selected=true]{background:var(--ink);color:#fff}

/* 카드 */
.card{background:var(--card);border:1px solid var(--rule);border-radius:3px;padding:16px;margin-top:14px}
.card h2{font-size:12px;font-weight:700;letter-spacing:.1em;color:var(--ink-2);
  text-transform:uppercase;display:flex;align-items:center;gap:6px;margin-bottom:12px}

/* ⓘ 버튼 */
.info{width:17px;height:17px;border-radius:50%;border:1px solid var(--rule);
  background:#fff;color:var(--ink-2);font-size:11px;font-weight:700;line-height:1;
  cursor:pointer;flex:0 0 auto;font-family:inherit}
.info:hover,.info:focus-visible{background:var(--ink);color:#fff;border-color:var(--ink);outline:none}

/* 입력 */
label{display:block;font-size:12px;color:var(--ink-2);margin-bottom:5px}
.field{display:flex;align-items:center;border-bottom:1.5px solid var(--ink);padding-bottom:6px}
.field input{flex:1;border:0;background:transparent;font-size:24px;font-weight:700;
  text-align:right;color:var(--ink);outline:none;font-family:'JetBrains Mono',monospace}
.field em{font-style:normal;font-size:13px;color:var(--ink-2);padding-left:6px}
.dir{display:flex;gap:0;margin-bottom:16px}
.dir button{flex:1;padding:8px;font-size:12.5px;font-weight:600;background:#fff;font-family:inherit;
  border:1px solid var(--rule);color:var(--ink-2);cursor:pointer}
.dir button[aria-selected=true]{background:#DDE6E4;border-color:var(--in);color:var(--in)}

/* 결과 큰 숫자 */
.result{margin-top:18px;padding-top:14px;border-top:1px dashed var(--rule)}
.result .big{font-family:'JetBrains Mono',monospace;font-size:34px;font-weight:700;
  letter-spacing:-.02em;color:var(--in);line-height:1.1}
.result .lbl{font-size:11.5px;color:var(--ink-2);letter-spacing:.04em}
.rows{margin-top:12px;font-size:13px}
.row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dotted var(--rule)}
.row:last-child{border-bottom:0}
.row span:first-child{color:var(--ink-2)}
.minus{color:var(--out)}

/* 시그니처: 12개월 입금 스트립 */
.strip{display:flex;gap:3px;align-items:flex-end;height:96px;margin-top:6px}
.mo{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px}
.bar{width:100%;background:var(--in);border-radius:1px 1px 0 0}
.bar.est{background:repeating-linear-gradient(-45deg,#0E6F63,#0E6F63 3px,#7FAEA8 3px,#7FAEA8 6px)}
.mo b{font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:400;color:var(--ink-2)}
.legend{display:flex;gap:12px;font-size:10.5px;color:var(--ink-2);margin-top:8px}
.legend i{display:inline-block;width:9px;height:9px;margin-right:4px;vertical-align:-1px}

/* 종목 카드 */
.etf{display:flex;gap:12px;padding:13px 0;border-bottom:1px solid var(--rule);align-items:center}
.etf:last-child{border-bottom:0}
.score{width:46px;height:46px;flex:0 0 auto;border-radius:2px;display:flex;flex-direction:column;
  align-items:center;justify-content:center;color:#fff}
.score b{font-family:'JetBrains Mono',monospace;font-size:19px;line-height:1}
.score s{text-decoration:none;font-size:8.5px;letter-spacing:.06em}
.s-buy{background:var(--in)}.s-hold{background:var(--gold)}.s-wait{background:#7A8598}
.etf-main{flex:1;min-width:0}
.tk{font-weight:800;font-size:15px;letter-spacing:-.01em}
.tk small{font-weight:500;font-size:11.5px;color:var(--ink-2);margin-left:6px}
.why{font-size:11.5px;color:var(--ink-2);margin-top:3px}
.badge{display:inline-block;font-size:9.5px;font-weight:700;padding:2px 5px;margin-top:5px;
  border:1px solid var(--out);color:var(--out);border-radius:2px}
.yld{text-align:right;flex:0 0 auto}
.yld b{font-family:'JetBrains Mono',monospace;font-size:15px}
.yld s{display:block;text-decoration:none;font-size:9.5px;color:var(--ink-2)}

/* 매수기록 */
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-size:10px;letter-spacing:.08em;color:var(--ink-2);font-weight:600;
  padding:0 0 7px;border-bottom:1px solid var(--ink)}
td{padding:9px 0;border-bottom:1px dotted var(--rule)}
td.n{text-align:right;font-family:'JetBrains Mono',monospace}
.warn{margin-top:14px;padding:11px 13px;background:#FBF0EA;border-left:3px solid var(--out);font-size:12px}

/* 하단 탭 */
nav{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid var(--rule);display:flex}
nav button{flex:1;padding:11px 0 13px;background:none;border:0;font-family:inherit;
  font-size:11px;font-weight:600;color:var(--ink-2);cursor:pointer}
nav button[aria-selected=true]{color:var(--in);box-shadow:inset 0 2px 0 var(--in)}
.page{display:none}.page.on{display:block}

/* 바텀시트 */
.sheet{position:fixed;inset:0;background:rgba(15,30,61,.45);display:none;align-items:flex-end;z-index:9}
.sheet.on{display:flex}
.sheet-in{background:#fff;width:100%;max-width:460px;margin:0 auto;padding:20px 18px 26px;
  border-radius:8px 8px 0 0}
.sheet h3{font-size:15px;font-weight:800;margin-bottom:9px}
.sheet p{font-size:13px;color:#28344B;margin-bottom:9px}
.sheet code{font-family:'JetBrains Mono',monospace;font-size:11.5px;background:var(--paper);
  padding:2px 5px;display:inline-block}
.sheet button{margin-top:6px;width:100%;padding:11px;background:var(--ink);color:#fff;
  border:0;border-radius:2px;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer}
@media(prefers-reduced-motion:no-preference){.sheet.on .sheet-in{animation:up .2s ease}}
@keyframes up{from{transform:translateY(14px)}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="brand"><h1>DivDesk</h1><span>배당ETF 매수검토</span></div>
  <div class="asof num">데이터 기준 2026-07-30 · USD/KRW 1,378.40 · 아래 숫자는 전부 더미</div>
  <div class="seg" role="tablist">
    <button role="tab" aria-selected="true">일반·미국상장</button>
    <button role="tab" aria-selected="false">일반·국내상장</button>
    <button role="tab" aria-selected="false">절세계좌</button>
  </div>
</header>

<!-- 계산기 -->
<section class="page on" id="p1">
  <div class="card">
    <h2>계산 방향 <button class="info" onclick="sheet('dir')">i</button></h2>
    <div class="dir">
      <button aria-selected="true">금액 → 월배당</button>
      <button aria-selected="false">월배당 → 필요금액</button>
    </div>
    <label>투자 원금</label>
    <div class="field"><input value="50,000,000" inputmode="numeric"><em>원</em></div>

    <div class="result">
      <div class="lbl">세후 월평균 배당 <button class="info" onclick="sheet('avg')">i</button></div>
      <div class="big">168,420원</div>
      <div class="rows">
        <div class="row"><span>연 세전 배당</span><b class="num">2,384,000원</b></div>
        <div class="row"><span>미국 원천징수 15%</span><b class="num minus">-357,600원</b></div>
        <div class="row"><span>국내 추가납부</span><b class="num">0원</b></div>
        <div class="row"><span>가중 배당률</span><b class="num">4.77%</b></div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>월별 실제 입금 <button class="info" onclick="sheet('strip')">i</button></h2>
    <div class="strip">
      <div class="mo"><div class="bar" style="height:22%"></div><b>1</b></div>
      <div class="mo"><div class="bar" style="height:24%"></div><b>2</b></div>
      <div class="mo"><div class="bar" style="height:88%"></div><b>3</b></div>
      <div class="mo"><div class="bar" style="height:23%"></div><b>4</b></div>
      <div class="mo"><div class="bar" style="height:25%"></div><b>5</b></div>
      <div class="mo"><div class="bar est" style="height:91%"></div><b>6</b></div>
      <div class="mo"><div class="bar est" style="height:24%"></div><b>7</b></div>
      <div class="mo"><div class="bar est" style="height:23%"></div><b>8</b></div>
      <div class="mo"><div class="bar est" style="height:95%"></div><b>9</b></div>
      <div class="mo"><div class="bar est" style="height:25%"></div><b>10</b></div>
      <div class="mo"><div class="bar est" style="height:24%"></div><b>11</b></div>
      <div class="mo"><div class="bar est" style="height:98%"></div><b>12</b></div>
    </div>
    <div class="legend">
      <span><i style="background:#0E6F63"></i>확정</span>
      <span><i class="bar est" style="height:9px"></i>추정</span>
      <span>분기배당 종목 때문에 3·6·9·12월에 몰립니다</span>
    </div>
  </div>
</section>

<!-- 타점 -->
<section class="page" id="p2">
  <div class="card">
    <h2>오늘의 매수타점 <button class="info" onclick="sheet('score')">i</button></h2>
    <div class="etf">
      <div class="score s-buy"><b>88</b><s>적극매수</s></div>
      <div class="etf-main">
        <div class="tk">SCHD<small>배당성장·분기</small></div>
        <div class="why">배당률 5년 상위 11% · 200일선 -6.3% · 배당락 D-42</div>
      </div>
      <div class="yld"><b>4.21%</b><s>배당률</s></div>
    </div>
    <div class="etf">
      <div class="score s-buy"><b>79</b><s>매수</s></div>
      <div class="etf-main">
        <div class="tk">TIGER 미국배당다우존스<small>월배당</small></div>
        <div class="why">환율 3년 상위 78%로 감점 · 분배금 12개월 +6.4%</div>
      </div>
      <div class="yld"><b>3.98%</b><s>배당률</s></div>
    </div>
    <div class="etf">
      <div class="score s-hold"><b>61</b><s>관망</s></div>
      <div class="etf-main">
        <div class="tk">JEPQ<small>커버드콜·월배당</small></div>
        <div class="why">분배율 10.8%인데 1년 총수익 +1.2% · 배당락 D-3</div>
        <div class="badge">분배금 ≠ 수익</div>
      </div>
      <div class="yld"><b>10.84%</b><s>배당률</s></div>
    </div>
    <div class="etf">
      <div class="score s-wait"><b>44</b><s>보류</s></div>
      <div class="etf-main">
        <div class="tk">QYLD<small>커버드콜·월배당</small></div>
        <div class="why">분배금 3년 -18% · 원금환급 성향 · 52주 상단 92%</div>
        <div class="badge">분배금 ≠ 수익</div>
      </div>
      <div class="yld"><b>11.92%</b><s>배당률</s></div>
    </div>
  </div>
</section>

<!-- 매수기록 -->
<section class="page" id="p3">
  <div class="card">
    <h2>매수기록</h2>
    <table>
      <tr><th>일자</th><th>종목</th><th style="text-align:right">수량</th><th style="text-align:right">단가</th><th style="text-align:right">평가</th></tr>
      <tr><td class="num">07-24</td><td>SCHD</td><td class="n">120</td><td class="n">$28.40</td><td class="n" style="color:#0E6F63">+3.1%</td></tr>
      <tr><td class="num">07-02</td><td>JEPI</td><td class="n">60</td><td class="n">$57.10</td><td class="n" style="color:#A63A18">-1.4%</td></tr>
      <tr><td class="num">06-18</td><td>TIGER 미국배당다우존스</td><td class="n">400</td><td class="n">11,905원</td><td class="n" style="color:#0E6F63">+2.2%</td></tr>
    </table>
    <div class="warn">
      <b>금융소득 워치독</b><br>
      올해 누적 세전 금융소득 <span class="num">7,412,000원</span> / 2,000만원 기준 37%.
      1,600만원 도달 시 절세계좌 이전을 제안합니다.
    </div>
  </div>
</section>
</div>

<nav role="tablist">
  <button role="tab" aria-selected="true" onclick="go(1,this)">계산</button>
  <button role="tab" aria-selected="false" onclick="go(2,this)">타점</button>
  <button role="tab" aria-selected="false" onclick="go(3,this)">기록</button>
</nav>

<div class="sheet" id="sh" onclick="if(event.target===this)close_()">
  <div class="sheet-in">
    <h3 id="sh-t"></h3>
    <div id="sh-b"></div>
    <button onclick="close_()">닫기</button>
  </div>
</div>

<script>
const DOC={
 dir:["계산 방향","<p>두 방향 모두 같은 세금 규칙을 씁니다.</p><p><b>금액 → 월배당</b>: 원금을 넣으면 세후 월평균과 월별 입금 편차를 보여줍니다.</p><p><b>월배당 → 필요금액</b>: 목표 월배당을 넣으면 필요 원금과 종목별 주수를 역산합니다. 주수는 정수로 내림한 뒤 부족분을 다시 채웁니다.</p>"],
 avg:["세후 월평균 배당은 어떻게 나오나요","<p><code>연 세전배당 ÷ 12 × (1 - 실효세율) × 환율</code></p><p>연 세전배당은 종목별 최근 4회 분배금 합계를 보유 주수에 곱해 더한 값입니다. 예상치가 아니라 이미 지급된 금액 기준입니다.</p><p>미국 상장 ETF는 현지에서 15%를 먼저 떼고, 한국 배당소득세율(14%)보다 높아 통상 추가 납부가 없습니다. 연 금융소득이 2,000만원을 넘으면 종합과세로 넘어가 계산이 달라집니다.</p>"],
 strip:["월별 입금이 왜 들쭉날쭉한가요","<p>분기배당 종목은 3·6·9·12월에만 입금됩니다. 그래서 '월평균'과 '이번 달 실제 입금'은 다릅니다.</p><p>빗금 막대는 아직 공시되지 않은 추정치입니다. 최근 4회 평균에 성장 추세를 반영해 계산하며, 운용사 배당 공시가 나오면 확정으로 바뀝니다.</p>"],
 score:["타점 점수 계산식","<p>두 축입니다. <b>품질은 이 상품이 꾸준한가, 타점은 지금 얼마나 싸게 사는가.</b></p><p><code>배당률 30 · 가격 위치 20 · 분배금 성장 15 · 위험조정 수익 15 · 환율 10 · 배당락 회복력 10</code></p><p>종합은 <b>품질 75% + 타점 25%</b>. 85 이상 적극매수, 70~84 매수, 55~69 분할·관망, 55 미만 보류. 품질이 50점 미만이면 아무리 싸도 제외합니다.</p><p><b>타점 비중이 낮은 이유</b> — 과거 10년으로 검증해 보니 가격으로 매수 시점을 맞히는 힘이 거의 없었습니다. 방향이 맞은 건 고점 대비 낙폭 하나뿐이라, 200일선 추세와 골든크로스는 점수에서 빼고 경고로만 남겼습니다.</p><p><b>가격 위치</b>는 고점 대비 낙폭을 그 종목 자기 이력과 함께 봅니다. 같은 -10%도 평소 -50%씩 빠지던 종목엔 평범하고, -14%가 최대였던 종목엔 역대급이기 때문입니다.</p><p>배당률이 높다고 점수가 오르는 게 아니라, <b>그 종목의 과거 자기 배당률 대비 지금이 싼지</b>를 봅니다. 커버드콜 종목은 분배금 일부가 옵션 프리미엄과 원금환급이라 총수익 항목에서 감점될 수 있습니다.</p>"]
};
function sheet(k){document.getElementById('sh-t').textContent=DOC[k][0];
 document.getElementById('sh-b').innerHTML=DOC[k][1];document.getElementById('sh').classList.add('on')}
function close_(){document.getElementById('sh').classList.remove('on')}
function go(n,b){document.querySelectorAll('.page').forEach(p=>p.classList.remove('on'));
 document.getElementById('p'+n).classList.add('on');
 document.querySelectorAll('nav button').forEach(x=>x.setAttribute('aria-selected','false'));
 b.setAttribute('aria-selected','true');window.scrollTo(0,0)}
document.querySelectorAll('.seg button,.dir button').forEach(b=>b.onclick=()=>{
 b.parentNode.querySelectorAll('button').forEach(x=>x.setAttribute('aria-selected','false'));
 b.setAttribute('aria-selected','true')});
addEventListener('keydown',e=>{if(e.key==='Escape')close_()});
</script>
</body>
</html>
