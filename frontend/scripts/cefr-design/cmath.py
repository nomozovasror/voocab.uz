import math
def h2r(h):
    h=h.lstrip('#'); return [int(h[i:i+2],16)/255 for i in (0,2,4)]
def r2h(c): return '#'+''.join('%02x'%max(0,min(255,round(x*255))) for x in c)
def lin(c): return [x/12.92 if x<=0.04045 else ((x+0.055)/1.055)**2.4 for x in c]
def unlin(c): return [12.92*x if x<=0.0031308 else 1.055*x**(1/2.4)-0.055 for x in c]
def lum(c):
    r,g,b=lin(c); return 0.2126*r+0.7152*g+0.0722*b
def cr(a,b):
    la,lb=lum(a),lum(b); hi,lo=max(la,lb),min(la,lb); return (hi+0.05)/(lo+0.05)
def mix(a,b,p):  # color-mix(in srgb, a p, b)
    return [a[i]*p+b[i]*(1-p) for i in range(3)]
def over(c,alpha,ground): return mix(c,ground,alpha)
def oklab(c):
    r,g,b=lin(c)
    l=0.4122214708*r+0.5363325363*g+0.0514459929*b
    m=0.2119034982*r+0.6806995451*g+0.1073969566*b
    s=0.0883024619*r+0.2817188376*g+0.6299787005*b
    l,m,s=[math.copysign(abs(x)**(1/3),x) for x in (l,m,s)]
    return [0.2104542553*l+0.7936177850*m-0.0040720468*s,
            1.9779984951*l-2.4285922050*m+0.4505937099*s,
            0.0259040371*l+0.7827717662*m-0.8086757660*s]
def oklch(c):
    L,a,b=oklab(c); return L, math.hypot(a,b), math.degrees(math.atan2(b,a))%360
def from_oklab(L,a,b):
    l=L+0.3963377774*a+0.2158037573*b; m=L-0.1055613458*a-0.0638541728*b; s=L-0.0894841775*a-1.2914855480*b
    l,m,s=l**3,m**3,s**3
    r=4.0767416621*l-3.3077115913*m+0.2309699292*s
    g=-1.2684380046*l+2.6097574011*m-0.3413193965*s
    bb=-0.0041960863*l-0.7034186147*m+1.7076147010*s
    return unlin([r,g,bb])
def from_oklch(L,C,H):
    return from_oklab(L,C*math.cos(math.radians(H)),C*math.sin(math.radians(H)))
def in_gamut(c): return all(-1e-4<=x<=1+1e-4 for x in c)
MACH={'protan':[[0.152286,1.052583,-0.204868],[0.114503,0.786281,0.099216],[-0.003882,-0.048116,1.051998]],
      'deutan':[[0.367322,0.860646,-0.227968],[0.280085,0.672501,0.047413],[-0.011820,0.042940,0.968881]],
      'tritan':[[1.255528,-0.076749,-0.178779],[-0.078411,0.930809,0.147602],[0.004733,0.691367,0.303900]]}
def sim(c,k):
    if k=='normal': return c
    L=lin(c); M=MACH[k]
    out=[max(0,min(1,sum(M[i][j]*L[j] for j in range(3)))) for i in range(3)]
    return unlin(out)
def dE(a,b,k='normal'):
    A,B=oklab(sim(a,k)),oklab(sim(b,k)); return 100*math.dist(A,B)
