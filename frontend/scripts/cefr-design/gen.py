import json
D=json.load(open('table.json'))
THEMES=[('serika-dark','Serika Dark','dark',dict(bg='#323437',fg='#d1d0c5',card='#2c2e31',primary='#e2b714',ok='#5fb87a',bad='#ca4754',muted='#646669',border='#46484b')),
        ('serika-light','Serika Light','light',dict(bg='#e1e1e3',fg='#2c2e31',card='#d4d4d6',primary='#e2b714',ok='#4caf72',bad='#ca4754',muted='#6b6e74',border='#c4c4c6')),
        ('dracula','Dracula','dark',dict(bg='#282a36',fg='#f8f8f2',card='#21222c',primary='#bd93f9',ok='#50fa7b',bad='#ff5555',muted='#6272a4',border='#44475a'))]
LV=['A1','A2','B1','B2','C1','C2']
WORDS={'A1':'city','A2':'common','B1':'compete','B2':'decline','C1':'scarce','C2':'proliferation'}
COUNTS={'A1':3,'A2':8,'B1':34,'B2':27,'C1':15,'C2':4}
def fmt(x,need=None):
    s='%.2f'%x
    if need and x<need: return '<span class="fail">%s<em>below AA</em></span>'%s
    return s
def chips_new(): return ''.join('<span class="chip n-%s">%s</span>'%(l.lower(),l) for l in LV)
def chips_old():
    out=[]
    for l in LV:
        if l in ('B1','B2','C1'): out.append('<span class="chip o-%s">%s</span>'%(l.lower(),l))
        else: out.append('<span class="nochip" title="CefrTag draws nothing for this level today">%s</span>'%l)
    return ''.join(out)
def bar(kind):
    segs=[]
    for l in LV:
        cls=('n-'+l.lower()) if kind=='new' else ('o-'+l.lower() if l in ('B1','B2','C1') else 'o-none')
        segs.append('<li class="seg %s" style="flex-grow:%d"><span class="seg-l">%s</span><span class="seg-n">%d</span></li>'%(cls,COUNTS[l],l,COUNTS[l]))
    return '<div class="scroll"><ul class="bar" aria-label="Words by CEFR level, %s">%s</ul></div>'%('proposed' if kind=='new' else 'today',''.join(segs))
def ladder(kind):
    items=[]
    for l in LV:
        if kind=='new': cls='w-'+l.lower()
        else: cls=('w-'+l.lower()) if l in ('B1','B2','C1') else 'w-none'
        items.append('<li><mark class="m %s">%s</mark><span class="tag">%s</span></li>'%(cls,WORDS[l],l))
    return '<ul class="words">%s</ul>'%''.join(items)
def passage():
    return ('<p class="passage">Twenty years ago, few people kept bees in the <mark class="m w-a1">city</mark>. Today '
     '<mark class="m pen-fill">rooftop hives</mark> are <mark class="m w-a2">common</mark> in London and Paris, and their honey is sold at weekend markets. '
     'Supporters say urban beekeeping helps to reverse the <mark class="m w-b2 looked">decline</mark> of wild pollinators. Some ecologists argue '
     '<mark class="m pen-line">the opposite</mark>: managed hives may <mark class="m w-b1">compete</mark> with native species for the same '
     '<mark class="m w-c1">scarce</mark> flowers, and the sheer <mark class="m w-c2">proliferation</mark> of hobby colonies could make the problem worse.</p>')
def verdicts():
    return ('<p class="passage">Supporters say urban beekeeping <mark class="m v-chose"><b class="q q-bad">Q13</b>helps to reverse the decline</mark> of wild pollinators. '
     'Some ecologists argue that <mark class="m v-missed"><b class="q q-ok">Q12</b>managed hives may compete with native species</mark> for food. '
     'Their honey is <mark class="m v-got"><b class="q q-got">Q14</b>sold at weekend markets</mark>.</p>')
def figs(tid):
    d=D[tid]; rows=[]
    adj={a['pair'].split('→')[0]:a for a in d['adj']}
    for r in d['rows']:
        l=r['lv']; a=adj.get(l)
        step='%.1f <small>(%.1f)</small>'%(a['washN'],a['washCVD']) if a else '<small>top</small>'
        if l in ('A1','C1'): step='0.0 <small>shared mark</small>'
        cs='%.1f <small>(%.1f)</small>'%(a['chipN'],a['chipCVD']) if a else '<small>top</small>'
        rows.append('<tr><th scope="row"><span class="chip n-%s">%s</span></th><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(
            l.lower(),l,fmt(r['chipCR'],4.5),fmt(r['washCR']),fmt(r['textOnWash'],4.5),step,cs))
    cur=' · '.join('%s %s'%(c['lv'],fmt(c['chipCR'],4.5)) for c in d['cur'])
    co=d['coll']
    near='A wash vs correct/18: %.1f (%.1f CVD) · B2 wash vs pen fill: %.1f (%.1f CVD) · C1 wash vs pen fill: %.1f (%.1f CVD)'%(
        co['A2']['correct/18'][0],co['A2']['correct/18'][1],co['B2']['pen/40'][0],co['B2']['pen/40'][1],co['C1']['pen/40'][0],co['C1']['pen/40'][1])
    return ('<div class="scroll"><table class="figs"><thead><tr><th scope="col">Level</th><th scope="col">Chip text<br>vs chip ground</th>'
      '<th scope="col">Wash<br>vs page ground</th><th scope="col">Passage text<br>on the wash</th><th scope="col">Wash step to next<br>&Delta;E (colour-blind)</th>'
      '<th scope="col">Chip step to next<br>&Delta;E (colour-blind)</th></tr></thead><tbody>%s</tbody></table></div>'
      '<p class="note">Today&rsquo;s chips, same grounds with coloured letters: %s. A1 outline edge vs ground: %.2f. Reader&rsquo;s pen fill vs ground: %.2f.</p>'
      '<p class="note">Nearest other marks: %s.</p>')%(''.join(rows),cur,d['a1edgeCR'],d['penCR'],near)
NOTES={
 'serika-dark':'Passage text over the C1 and C2 wash is 3.99, and over the pen&rsquo;s fill 3.53. Both were already below AA before this proposal. Decision 4 below fixes both.',
 'serika-light':'The quietest theme. The A wash sits only 1.09:1 off the ground (&Delta;E 3.2), which is faint but present. The pen is fainter still here (1.18).',
 'dracula':'The pen here is the theme&rsquo;s violet accent (#bd93f9), only 6&deg; from B2. Pen fill vs B2 wash is 4.5 &Delta;E (3.7 colour-blind). That predates this proposal; see decision 5.'}
def plate(tid,name,app,v):
    vars_=';'.join('--%s:%s'%(k,x) for k,x in v.items())
    return ('<article class="plate is-%s" style="%s" aria-labelledby="h-%s">'
     '<header class="plate-head"><h2 id="h-%s">%s</h2><p class="hexes">ground %s · text %s · pen %s · correct %s · wrong %s</p></header>'
     '<div class="plate-body"><div class="col">'
       '<section class="blk"><h3 class="lbl">Chips · proposed</h3><div class="chips">%s</div>'
       '<h3 class="lbl">Chips · today</h3><div class="chips">%s</div></section>'
       '<section class="blk"><h3 class="lbl">Level bar · proposed</h3>%s<h3 class="lbl">Level bar · today</h3>%s</section>'
       '<section class="blk"><h3 class="lbl">Word marks · proposed</h3>%s<h3 class="lbl">Word marks · today (A1, A2, C2 fall back to unrated grey)</h3>%s</section>'
     '</div><div class="col">'
       '<section class="blk"><h3 class="lbl">Vocabulary layer, with the reader&rsquo;s own pen marks</h3>%s'
       '<ul class="key"><li><mark class="m pen-fill">fill</mark> pen: something that matters</li><li><mark class="m pen-line">line</mark> pen: not sure</li><li><mark class="m w-b2 looked">word</mark> one of the three look-ups</li></ul></section>'
       '<section class="blk"><h3 class="lbl">Answers layer, for comparison (the app shows one layer at a time)</h3>%s</section>'
       '<p class="caveat">%s</p>'
     '</div></div>'
     '<section class="blk"><h3 class="lbl">Measured on this ground</h3>%s</section>'
     '</article>')%(app,vars_,tid,tid,name,v['bg'],v['fg'],v['primary'],v['ok'],v['bad'],chips_new(),chips_old(),bar('new'),bar('old'),ladder('new'),ladder('old'),passage(),verdicts(),NOTES[tid],figs(tid))

CSS=r'''
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap");
/* Layout: a spec sheet. One thesis, one ladder, then three plates, each painted on a real app theme's ground.
   The page chrome carries no hue of its own, so the only colours on screen are the ones under review. */
:root{
  color-scheme:dark;
  --page:#131416; --raise:#1a1b1e; --rule:#2a2b30; --text:#e7e6df; --dim:#a7a69f; --faint:#7b7a74;
  --sans:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --s-xs:.75rem; --s-sm:.8125rem; --s-md:.9375rem; --s-lg:1.125rem; --s-xl:1.5rem; --s-2xl:clamp(2rem,6vw,3.25rem);
}
*{box-sizing:border-box}
body{background:var(--page);color:var(--text);font-family:var(--sans);font-size:var(--s-md);line-height:1.6;-webkit-font-smoothing:antialiased}
.page{max-width:76rem;margin:0 auto;padding-inline:clamp(16px,4vw,40px);padding-block:clamp(28px,5vw,64px) 72px;display:grid;gap:clamp(40px,6vw,72px)}
h1,h2,h3{margin:0;text-wrap:balance}
p{margin:0}
.eyebrow,.lbl{font-family:var(--mono);font-size:.6875rem;font-weight:500;letter-spacing:.08em;text-transform:uppercase}
.eyebrow{color:var(--dim)}
.intro{display:grid;gap:20px}
.intro h1{font-size:var(--s-2xl);font-weight:650;letter-spacing:-.025em;line-height:1.05}
.lede{max-width:62ch;color:var(--dim);font-size:var(--s-lg);line-height:1.55}
.lede strong{color:var(--text);font-weight:600}
.specimen{background:#323437;border-radius:16px;padding:clamp(18px,3vw,28px);display:grid;gap:14px;
  --bg:#323437;--fg:#d1d0c5;--ink-base:color-mix(in srgb,white 60%,var(--fg));color:var(--fg)}
.specimen .row{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:flex-end}
.specimen .cell{display:grid;gap:6px;justify-items:start}
.specimen .chip{font-size:1.125rem;padding:.2em .6em;border-radius:6px}
.specimen .cap{font-family:var(--mono);font-size:.6875rem;color:color-mix(in srgb,var(--fg) 70%,var(--bg))}
.specimen .arrow{font-family:var(--mono);font-size:.75rem;color:color-mix(in srgb,var(--fg) 70%,var(--bg))}
section>h2,.sec-h{font-size:var(--s-xl);font-weight:650;letter-spacing:-.015em}
.scroll{overflow-x:auto;max-width:100%;min-width:0;-webkit-overflow-scrolling:touch}
.page,.intro,.sec,.plates,.plate,.col,.blk,.specimen{grid-template-columns:minmax(0,1fr)}
.page>*,.plate>*,.sec>*{min-width:0}
table{border-collapse:collapse;font-variant-numeric:tabular-nums}
.ladder-t{width:100%;min-width:40rem;font-size:var(--s-sm)}
.ladder-t th,.ladder-t td{text-align:left;padding:10px 14px 10px 0;border-bottom:1px solid var(--rule);vertical-align:top}
.ladder-t thead th{font-family:var(--mono);font-size:.6875rem;font-weight:500;letter-spacing:.06em;text-transform:uppercase;color:var(--faint)}
.ladder-t tbody th{font-family:var(--mono);font-weight:500}
.sw{display:inline-block;width:.8em;height:.8em;border-radius:3px;vertical-align:-.08em;margin-right:.45em}
.tagnew{font-family:var(--mono);font-size:.6875rem;color:var(--text);border:1px solid var(--rule);border-radius:4px;padding:1px 6px}
.dim{color:var(--dim)}
.sec{display:grid;gap:20px}
.sec-intro{max-width:64ch;color:var(--dim)}
.plates{display:grid;gap:28px}

/* ── A plate: one app theme. Every colour below is derived exactly as proposed for globals.css. ── */
.plate{
  --sky:#55c3f2;--b1:#5b9bd5;--b2:#9b87d0;--c1:#d98a4a;
  background:var(--bg);color:var(--fg);border-radius:18px;padding:clamp(16px,3.2vw,32px);display:grid;gap:28px;
  --sub:color-mix(in srgb,var(--fg) 70%,var(--bg));--hair:color-mix(in srgb,var(--fg) 14%,transparent);
}
.plate.is-dark{--ink-base:color-mix(in srgb,white 60%,var(--fg))}
.plate.is-light{--ink-base:var(--fg)}
.plate,.specimen{
  --a1:var(--sky,#55c3f2);--a2:var(--sky,#55c3f2);--c2:var(--c1,#d98a4a);
  --w-a1:color-mix(in srgb,color-mix(in srgb,var(--a1) 78%,var(--fg)) 12%,transparent);
  --w-a2:color-mix(in srgb,color-mix(in srgb,var(--a2) 78%,var(--fg)) 12%,transparent);
  --w-b1:color-mix(in srgb,color-mix(in srgb,var(--b1,#5b9bd5) 78%,var(--fg)) 24%,transparent);
  --w-b2:color-mix(in srgb,color-mix(in srgb,var(--b2,#9b87d0) 78%,var(--fg)) 34%,transparent);
  --w-c1:color-mix(in srgb,color-mix(in srgb,var(--c1,#d98a4a) 78%,var(--fg)) 40%,transparent);
  --w-c2:var(--w-c1);
  --i-a1:color-mix(in srgb,var(--a1) 15%,var(--ink-base));--i-a2:var(--i-a1);
  --i-b1:color-mix(in srgb,var(--b1,#5b9bd5) 15%,var(--ink-base));
  --i-b2:color-mix(in srgb,var(--b2,#9b87d0) 15%,var(--ink-base));
  --i-c1:color-mix(in srgb,var(--c1,#d98a4a) 15%,var(--ink-base));
  --edge-a:color-mix(in srgb,var(--a2) 50%,var(--fg));
  --on-c2:color-mix(in srgb,var(--c2) 22%,black);
  --o-b1:color-mix(in srgb,var(--b1,#5b9bd5) 62%,var(--fg));
  --o-b2:color-mix(in srgb,var(--b2,#9b87d0) 62%,var(--fg));
  --o-c1:color-mix(in srgb,var(--c1,#d98a4a) 62%,var(--fg));
}
.specimen{--sky:#55c3f2;--b1:#5b9bd5;--b2:#9b87d0;--c1:#d98a4a}
.plate-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:6px 18px;border-bottom:1px solid var(--hair);padding-bottom:14px}
.plate-head h2{font-size:var(--s-xl);font-weight:650;letter-spacing:-.015em}
.hexes{font-family:var(--mono);font-size:var(--s-xs);color:var(--sub)}
.plate-body{display:grid;gap:28px;grid-template-columns:minmax(0,1fr)}
@media (min-width:62rem){.plate-body{grid-template-columns:minmax(0,5fr) minmax(0,6fr);gap:40px}}
.col{display:grid;gap:26px;align-content:start;min-width:0}
.blk{display:grid;gap:10px;min-width:0}
.blk .lbl{color:var(--sub)}
.blk .lbl+*{margin-bottom:6px}
.chips{display:flex;flex-wrap:wrap;gap:8px;align-items:center;min-height:22px}

/* CefrTag: rounded px-1.5 py-px text-[0.65rem] leading-[1.4] font-medium */
.chip{display:inline-block;border-radius:4px;padding:1px 6px;font-family:var(--sans);font-size:.65rem;line-height:1.4;font-weight:500}
.n-a1{background:transparent;color:var(--i-a1);box-shadow:inset 0 0 0 1px var(--edge-a)}
.n-a2{background:var(--w-a2);color:var(--i-a2)}
.n-b1{background:var(--w-b1);color:var(--i-b1)}
.n-b2{background:var(--w-b2);color:var(--i-b2)}
.n-c1{background:var(--w-c1);color:var(--i-c1)}
.n-c2{background:var(--c2);color:var(--on-c2)}
.o-b1{background:var(--w-b1);color:var(--o-b1)}
.o-b2{background:var(--w-b2);color:var(--o-b2)}
.o-c1{background:var(--w-c1);color:var(--o-c1)}
.o-none{background:transparent;color:var(--muted);box-shadow:inset 0 0 0 1px var(--border)}
.nochip{font-family:var(--mono);font-size:.65rem;color:var(--sub);padding:1px 6px;border:1px dashed var(--hair);border-radius:4px;text-decoration:line-through}

/* CefrSpread: flex h-8 gap-1; segments min-w-14 rounded-md px-2.5 font-mono text-xs */
.bar{list-style:none;margin:0;padding:0;display:flex;gap:4px;height:2rem;min-width:24rem}
.seg{flex-basis:0;min-width:3.5rem;border-radius:6px;padding:0 10px;display:flex;align-items:center;justify-content:space-between;font-family:var(--mono);font-size:.75rem}
.seg-l{font-weight:500}.seg-n{opacity:.75;font-variant-numeric:tabular-nums}
.seg.n-a1,.seg.n-a2,.seg.n-b1,.seg.n-b2,.seg.n-c1,.seg.n-c2,.seg.o-b1,.seg.o-b2,.seg.o-c1,.seg.o-none{font-size:.75rem}

/* PassagePane: rounded-[0.2em] px-[0.12em] py-[0.05em] box-decoration-clone; prose text-[0.95em] leading-[1.72] */
.m{color:inherit;border-radius:.2em;padding:.05em .12em;-webkit-box-decoration-break:clone;box-decoration-break:clone;background:transparent}
.w-a1{background:var(--w-a1)}.w-a2{background:var(--w-a2)}.w-b1{background:var(--w-b1)}
.w-b2{background:var(--w-b2)}.w-c1{background:var(--w-c1)}.w-c2{background:var(--w-c2)}
.w-none{background:color-mix(in srgb,var(--fg) 10%,transparent)}
.looked{text-decoration:underline 2px var(--b2,#9b87d0);text-underline-offset:4px}
.pen-fill{background:color-mix(in srgb,var(--primary) 40%,transparent)}
.pen-line{background:transparent;text-decoration:underline 2px var(--primary);text-underline-offset:4px}
.v-chose{background:color-mix(in srgb,var(--bad) 20%,transparent);text-decoration:underline 2px color-mix(in srgb,var(--bad) 50%,transparent);text-underline-offset:4px}
.v-missed{background:color-mix(in srgb,var(--ok) 18%,transparent);text-decoration:underline 2px color-mix(in srgb,var(--ok) 50%,transparent);text-underline-offset:4px}
.v-got{background:transparent;text-decoration:underline 2px color-mix(in srgb,var(--ok) 45%,transparent);text-underline-offset:4px}
.q{margin-right:.375rem;font-weight:700}
.q-bad{color:var(--bad)}.q-ok{color:var(--ok)}.q-got{color:color-mix(in srgb,var(--ok) 70%,transparent)}
.passage{font-size:.95rem;line-height:1.72;max-width:62ch}
.words{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:12px 14px}
.words li{display:grid;gap:2px;justify-items:start}
.words .m{font-size:.95rem;line-height:1.72}
.tag{font-family:var(--mono);font-size:.625rem;color:var(--sub);padding-left:.12em}
.key{list-style:none;margin:4px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:6px 18px;font-size:var(--s-xs);color:var(--sub)}
.key .m{color:var(--fg)}
.caveat{font-size:var(--s-sm);color:var(--sub);border-left:2px solid var(--hair);padding-left:12px;max-width:60ch}
.figs{width:100%;min-width:40rem;font-size:var(--s-sm)}
.figs th,.figs td{text-align:left;padding:8px 14px 8px 0;border-bottom:1px solid var(--hair);white-space:nowrap}
.figs thead th{font-family:var(--mono);font-size:.625rem;font-weight:500;letter-spacing:.05em;text-transform:uppercase;color:var(--sub);line-height:1.35;vertical-align:bottom}
.figs td{font-family:var(--mono)}
.figs small{color:var(--sub);font-size:.85em}
.fail{font-weight:700;text-decoration:underline 1px dotted;text-underline-offset:3px}
.fail em{font-style:normal;font-weight:500;font-size:.8em;margin-left:.4em;color:var(--sub);text-decoration:none;display:inline-block}
.note{font-size:var(--s-xs);color:var(--sub);font-family:var(--mono);line-height:1.6;max-width:100ch}

/* ── Reasoning ── */
.why{display:grid;gap:22px;grid-template-columns:minmax(0,1fr)}
@media (min-width:56rem){.why{grid-template-columns:repeat(2,minmax(0,1fr));gap:22px 40px}}
.why article{display:grid;gap:10px;align-content:start;min-width:0}
.why h3{font-size:var(--s-lg);font-weight:600}
.why p,.why li{color:var(--dim);max-width:62ch}
.why ul{margin:0;padding-left:1.1em;display:grid;gap:6px}
.why b{color:var(--text);font-weight:600}
.rejects{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr))}
.rej{background:var(--raise);border:1px solid var(--rule);border-radius:10px;padding:12px 14px;display:grid;gap:6px;min-width:0}
.rej .top{display:flex;align-items:center;gap:10px}
.rej .sw{width:1.4rem;height:1.4rem;margin:0;border-radius:5px}
.rej .nm{font-weight:600;font-size:var(--s-sm)}
.rej .hx{font-family:var(--mono);font-size:var(--s-xs);color:var(--faint)}
.rej p{font-size:var(--s-sm);color:var(--dim)}
.decide ol{margin:0;padding-left:1.4em;display:grid;gap:12px;max-width:72ch}
.decide li{color:var(--dim);padding-left:.3em}
.decide li::marker{font-family:var(--mono);color:var(--text)}
.decide b{color:var(--text);font-weight:600}
pre{margin:0;background:var(--raise);border:1px solid var(--rule);border-radius:10px;padding:16px 18px;font-family:var(--mono);font-size:.75rem;line-height:1.65;color:var(--text);overflow-x:auto}
pre .c{color:var(--faint)}
code{font-family:var(--mono);font-size:.9em}
.foot{font-size:var(--s-xs);color:var(--faint);font-family:var(--mono);border-top:1px solid var(--rule);padding-top:16px}
'''

def specimen():
    cells=[('A1','outline'),('A2','tint 12%'),('B1','tint 24%'),('B2','tint 34%'),('C1','tint 40%'),('C2','solid')]
    return ('<div class="specimen" role="img" aria-label="The six proposed chips on Serika Dark, from an empty outline for A1 to a solid orange for C2">'
      '<p class="eyebrow" style="color:color-mix(in srgb,var(--fg) 70%,var(--bg))">On Serika Dark, the default theme</p><div class="row">'+
      ''.join('<div class="cell"><span class="chip n-%s">%s</span><span class="cap">%s</span></div>'%(l.lower(),l,c) for l,c in cells)+
      '</div><p class="arrow">easier &rarr; harder &nbsp;·&nbsp; sky &rarr; blue &rarr; violet &rarr; orange &nbsp;·&nbsp; empty &rarr; tinted &rarr; solid</p></div>')

LADDER=[('A1','Basic user','#55c3f2','Sky','Outline (no ground)','12%, shared with A2','below 4','<span class="tagnew">new</span>'),
        ('A2','Basic user','#55c3f2','Sky','Tint','12%','below 4','<span class="tagnew">new</span>'),
        ('B1','Independent user','#5b9bd5','Blue','Tint','24%','4.0 to 5.0','<span class="dim">unchanged</span>'),
        ('B2','Independent user','#9b87d0','Violet','Tint','34%','5.5 to 6.5','<span class="dim">unchanged</span>'),
        ('C1','Proficient user','#d98a4a','Orange','Tint','40%, the pen&rsquo;s weight','7.0 to 8.0','<span class="dim">unchanged</span>'),
        ('C2','Proficient user','#d98a4a','Orange','Solid','40%, shared with C1','8.5 to 9.0','<span class="tagnew">new</span>')]
def ladder_table():
    rows=''.join('<tr><th scope="row">%s</th><td>%s</td><td><span class="sw" style="background:%s"></span>%s <span class="dim">%s</span></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(l,b,h,n,h,c,w,i,s) for l,b,h,n,c,w,i,s in LADDER)
    return ('<div class="scroll"><table class="ladder-t"><thead><tr><th scope="col">Level</th><th scope="col">CEFR band</th><th scope="col">Hue</th>'
            '<th scope="col">Chip</th><th scope="col">Passage wash</th><th scope="col">IELTS, approx.</th><th scope="col">Status</th></tr></thead><tbody>%s</tbody></table></div>')%rows

REJ=[('#3baca6','Teal for A1','8.3 from Serika Dark&rsquo;s correct-green and 7.7 from Serika Light&rsquo;s. The scale&rsquo;s tightest pair, B1 to B2, is 8.9, and that is between two levels, not a level and a verdict.'),
     ('#b66028','Rust for C2','8.8 from the red that means wrong. It reads as the next step after orange, which is exactly why it sits so close to red.'),
     ('#f2b772','Apricot for C2','7.4 from the pen&rsquo;s amber and 6.4 from the warning colour. It is also lighter than C1, so it reads as easier.'),
     ('#bb5faa','Magenta for C2','Clears red (12.3) and the pen, but it sits between violet and orange on the colour wheel and 10.7 from B2, so it reads as B2&rsquo;s neighbour, below C1.')]

def page():
    d=D
    worst_chip=min((r['chipCR'],t,r['lv']) for t in d for r in d[t]['rows'])
    WORST='%.2f</b> (%s on %s)'%(worst_chip[0],worst_chip[2],{'serika-dark':'Serika Dark','dracula':'Dracula','serika-light':'Serika Light'}[worst_chip[1]])
    return ('<title>CEFR Colour Scale</title>\n<style>'+CSS+'</style>\n'
     '<main class="page">'
     '<header class="intro"><p class="eyebrow">voocab.uz · Proposal for review · CEFR colour scale, B1&ndash;C1 to A1&ndash;C2</p>'
     '<h1>Four hues, six levels</h1>'
     '<p class="lede">There is room on the wheel for <strong>one new hue</strong>, a sky blue below B1. Past C1&rsquo;s orange, every warm colour already means something: wrong, the pen, or a warning. So the two ends of the scale are told apart by <strong>how full the chip is</strong>. A1 is an empty outline, C2 is solid orange, and everything between is a tint. B1, B2 and C1 keep their hues and washes exactly.</p>'
     +specimen()+'</header>'
     '<section class="sec" aria-labelledby="h-ladder"><h2 id="h-ladder" class="sec-h">The ladder</h2>'
     '<p class="sec-intro">Hue changes at the band boundaries. Fill changes at the two ends. The passage wash carries a second ordered channel for anyone who cannot tell the hues apart.</p>'
     +ladder_table()+'</section>'
     '<section class="sec" aria-labelledby="h-plates"><h2 id="h-plates" class="sec-h">On every theme</h2>'
     '<p class="sec-intro">Each plate is painted with that theme&rsquo;s real tokens from <code>globals.css</code>, and every CEFR colour on it is computed with the same <code>color-mix</code> formulas proposed for the app. Contrast is WCAG ratio; separation is OKLab &Delta;E &times;100, with the colour-blind figure being the worse of protanopia and deuteranopia (Machado 2009).</p>'
     '<div class="plates">'+''.join(plate(*t) for t in THEMES)+'</div></section>'
     '<section class="sec" aria-labelledby="h-why"><h2 id="h-why" class="sec-h">Why these colours</h2><div class="why">'
     '<article><h3>A1 and A2: sky, #55c3f2</h3><ul>'
     '<li>Cooler than blue there is only cyan and teal, and both drift toward the green that means <b>correct</b>. Sky is the bluest cyan that clears every theme&rsquo;s green by <b>16.5</b> while staying <b>10.8</b> from B1, further than B1 is from B2 (8.9).</li>'
     '<li>It is lighter than blue (OKLCH lightness 0.77 against 0.67), which reads as lighter work. Lightness also survives colour blindness: sky to blue is <b>10.2</b> under deuteranopia, where blue to violet is 1.1.</li>'
     '<li>The sector has room for one hue, not two. A1 and A2 share sky and differ by fill: A1 is an outline with no ground.</li></ul></article>'
     '<article><h3>C2: C1&rsquo;s orange, solid</h3><ul>'
     '<li>Past orange, redder is the verdict red and yellower is the pen and the warning. An exhaustive search found no hue at the scale&rsquo;s lightness that clears all of them by 15. The only survivors were dark: a deep purple, an olive and a brown.</li>'
     '<li>So C2 changes style instead of hue, the same move the pen made when it gave its blue and violet to this scale. Solid is the end of a ladder that runs empty, tinted, solid.</li>'
     '<li>The letters on the solid chip are the orange mixed 22% into black, so the chip reads the same on every theme: <b>5.82</b>.</li></ul></article>'
     '<article><h3>The passage draws four marks</h3><ul>'
     '<li>Below B1&rsquo;s 24% there is room for one visible step. Two A washes at 10% and 17% differ by at most 2 &Delta;E on any theme. One A wash at 12% sits <b>4.0 to 4.8</b> from B1, no closer than the closest step the scale already has (B1 to B2 on Serika Light, 3.7).</li>'
     '<li>C1 already stops at the weight of the reader&rsquo;s own pen. C2 shares that cap, so nothing the page says about a word is louder than what the reader said.</li>'
     '<li>The CEFR itself groups the levels in three bands. The passage shows A, B1, B2 and C; the chip, the list and the level filter show all six.</li></ul></article>'
     '<article><h3>Why the chip letters change</h3><ul>'
     '<li>Today&rsquo;s chips put coloured letters on a coloured ground and measure <b>2.30 to 3.61</b> on both Serika themes, below the 4.5 that text this small needs.</li>'
     '<li>The grounds stay exactly as they are, so the hue and the strength ramp are untouched. The letters move to 15% hue on a base pushed away from the ground: the foreground on light themes, the foreground mixed 60% toward white on dark ones.</li>'
     '<li>Worst chip after the change: <b>'+WORST+'.</li></ul></article>'
     '</div>'
     '<h3 class="sec-h" style="font-size:var(--s-lg)">Candidates that were measured and rejected</h3><div class="rejects">'+
     ''.join('<div class="rej"><div class="top"><span class="sw" style="background:%s"></span><div><div class="nm">%s</div><div class="hx">%s</div></div></div><p>%s</p></div>'%(h,n,h,t) for h,n,t in REJ)+
     '</div></section>'
     '<section class="sec decide" aria-labelledby="h-dec"><h2 id="h-dec" class="sec-h">For you to decide</h2><ol>'
     '<li><b>Four hues for six levels.</b> A1 and A2 share sky, C1 and C2 share orange, and the chip&rsquo;s fill tells them apart. The alternative is six hues, which means a teal 8.3 from correct-green and a C2 that is either near red, near the pen, or reads easier than C1.</li>'
     '<li><b>Four marks on the passage.</b> A1 and A2 share a 12% wash, and C2 shares C1&rsquo;s 40%. The alternative is a C2 wash heavier than the pen (about 46%) so it outranks C1 on the passage, which breaks the rule that the page never shouts louder than the reader.</li>'
     '<li><b>Near-neutral chip letters</b>, to pass AA. This also changes how today&rsquo;s B1, B2 and C1 chips look; their grounds do not change.</li>'
     '<li><b>Optional, already broken today:</b> on dark themes, draw the text inside any passage mark in the same ink base. On Serika Dark that lifts text on the C wash from 3.99 to 5.24 and on the pen&rsquo;s fill from 3.53 to 4.64.</li>'
     '<li><b>Optional, already broken today:</b> the pen on Dracula is the theme&rsquo;s violet, 4.5 &Delta;E from B2&rsquo;s wash. Dracula&rsquo;s own yellow, #f1fa8c, clears B2 by 15.7.</li>'
     '</ol></section>'
     '<section class="sec" aria-labelledby="h-tok"><h2 id="h-tok" class="sec-h">What it would add to the tokens</h2>'
     '<pre><span class="c">/* globals.css, the derived :root block. Four hue declarations, everything else mixed. */</span>\n'
     '--cefr-a2: #55c3f2;                 <span class="c">/* sky, the one new hue */</span>\n'
     '--cefr-a1: var(--cefr-a2);          <span class="c">/* same hue, told apart by style */</span>\n'
     '--cefr-c2: var(--cefr-c1);          <span class="c">/* same hue, told apart by style */</span>\n\n'
     '--cefr-a1-wash: <span class="c">/* 78% tint as today */</span> 12%;   --cefr-a2-wash: 12%;\n'
     '--cefr-c2-wash: var(--cefr-c1-wash);\n\n'
     '--cefr-ink-base: var(--foreground);\n'
     '--cefr-X-ink: color-mix(in srgb, var(--cefr-X) 15%, var(--cefr-ink-base));  <span class="c">/* all six; was 62% toward --foreground */</span>\n'
     '--cefr-a-edge: color-mix(in srgb, var(--cefr-a2) 50%, var(--foreground));  <span class="c">/* A1 outline, A1/A2 underline and ring */</span>\n'
     '--cefr-c2-on: color-mix(in srgb, var(--cefr-c2) 22%, black);\n\n'
     'html.dark { --cefr-ink-base: color-mix(in srgb, white 60%, var(--foreground)); }</pre>'
     '<p class="sec-intro">In <code>cefr.ts</code>, <code>CEFR_LEVELS</code> grows to six. A1&rsquo;s chip becomes an inset ring in <code>cefr-a-edge</code> with no ground, and C2&rsquo;s becomes <code>bg-cefr-c2 text-cefr-c2-on</code>. <code>CefrSpread</code> stops needing the neutral fallback for A1, A2 and C2.</p></section>'
     '<p class="foot">Figures computed from the theme tokens in frontend/src/styles/globals.css. The method reproduces the file&rsquo;s own wash figures exactly (Serika Dark 1.50 / 1.76 / 2.02, pen 2.28). CEFR levels on the sample words are illustrative.</p>'
     '</main>\n')

open('cefr-preview.html','w').write(page())
print(len(open('cefr-preview.html').read()),'bytes')
