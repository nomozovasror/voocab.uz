from cmath import *; from themes import T
import json
SKY='#55c3f2'
HUE={'A1':SKY,'A2':SKY,'B1':'#5b9bd5','B2':'#9b87d0','C1':'#d98a4a','C2':'#d98a4a'}
WASH={'A1':.12,'A2':.12,'B1':.24,'B2':.34,'C1':.40,'C2':.40}
APP={'serika-dark':'dark','dracula':'dark','serika-light':'light'}
L=list(HUE)
def tint(h,v): return mix(h2r(h),h2r(v['fg']),.78)
def base(t,v): return mix([1,1,1],h2r(v['fg']),.60) if APP[t]=='dark' else h2r(v['fg'])
def ink(lv,t,v): return mix(h2r(HUE[lv]),base(t,v),.15)
def edge(lv,v): return mix(h2r(HUE[lv]),h2r(v["fg"]),.50)
def wash(lv,v,surf='bg'): return over(tint(HUE[lv],v),WASH[lv],h2r(v[surf]))
def chip(lv,t,v,surf='bg'):
    if lv=='C2': return h2r(HUE['C2']), mix(h2r(HUE['C2']),[0,0,0],.22)
    if lv=='A1': return h2r(v[surf]), ink(lv,t,v)
    return wash(lv,v,surf), ink(lv,t,v)
cvd=lambda a,b: min(dE(a,b,'deutan'),dE(a,b,'protan'))
out={}
for t,v in T.items():
    bg=h2r(v['bg']); fg=h2r(v['fg'])
    rows=[]
    for lv in L:
        cb,ci=chip(lv,t,v)
        c=min(cr(ci,chip(lv,t,v,s)[0]) for s in ('bg','card'))
        w=wash(lv,v)
        rows.append(dict(lv=lv,chipBg=r2h(cb),chipInk=r2h(ci),chipCR=round(c,2),wash=r2h(w),washCR=round(cr(w,bg),2),washVis=round(dE(w,bg),1),textOnWash=round(cr(fg,w),2)))
    adj=[]
    for a,b in zip(L,L[1:]):
        ca,cb_=chip(a,t,v)[0],chip(b,t,v)[0]; wa,wb=wash(a,v),wash(b,v)
        adj.append(dict(pair=a+'→'+b,chipN=round(dE(ca,cb_),1),chipCVD=round(cvd(ca,cb_),1),washN=round(dE(wa,wb),1),washCVD=round(cvd(wa,wb),1)))
    marks={'correct/18':over(h2r(v['ok']),.18,bg),'incorrect/20':over(h2r(v['bad']),.20,bg),'pen/40':over(h2r(v['primary']),.40,bg)}
    coll={lv:{k:[round(dE(wash(lv,v),m),1),round(cvd(wash(lv,v),m),1)] for k,m in marks.items()} for lv in ('A2','B1','B2','C1')}
    # current chips
    cur=[]
    for lv in ('B1','B2','C1'):
        ci=mix(h2r(HUE[lv]),fg,.62); cbg=wash(lv,v)
        cur.append(dict(lv=lv,chipBg=r2h(cbg),chipInk=r2h(ci),chipCR=round(min(cr(ci,wash(lv,v,s)) for s in ('bg','card')),2)))
    a1edge=edge('A1',v)
    out[t]=dict(rows=rows,adj=adj,coll=coll,cur=cur,a1edge=r2h(a1edge),a1edgeCR=round(min(cr(a1edge,h2r(v[s])) for s in ('bg','card')),2),
               penCR=round(cr(marks['pen/40'],bg),2), textOnPen=round(cr(fg,marks['pen/40']),2), textOnPenFixed=round(cr(base(t,v),marks['pen/40']),2),
               textOnCFixed=round(cr(base(t,v),wash('C1',v)),2))
json.dump(out,open('table.json','w'),indent=1)
for t,o in out.items():
    print('==',t,'A1 edge',o['a1edge'],o['a1edgeCR'],'pen',o['penCR'],'text on pen',o['textOnPen'],'→',o['textOnPenFixed'],' text on C wash fixed',o['textOnCFixed'])
    for r in o['rows']: print('  ',r)
    for a in o['adj']: print('  ',a)
    for k,c in o['coll'].items(): print('  ',k,c)
    for c in o['cur']: print('   cur',c)
