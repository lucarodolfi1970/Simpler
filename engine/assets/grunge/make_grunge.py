import numpy as np
from PIL import Image
N=2048; rng=np.random.default_rng(7)
fy=np.fft.fftfreq(N)[:,None]; fx=np.fft.fftfreq(N)[None,:]
def fbm(beta, lo=1, hi=None, ax=1.0, ay=1.0, seed=0):
    r=np.random.default_rng(seed)
    f=np.sqrt((fx*N/ax)**2+(fy*N/ay)**2); f[0,0]=1
    amp=f**(-beta/2); amp[f<lo]=0
    if hi: amp*=np.exp(-(f/hi)**2)
    ph=np.exp(2j*np.pi*r.random((N,N)))
    x=np.real(np.fft.ifft2(amp*ph)); x=(x-x.mean())/x.std(); return x
def s(x,a,b): t=np.clip((x-a)/(b-a),0,1); return t*t*(3-2*t)
edge=fbm(1.6,lo=20,seed=12)
blot=s(fbm(3.2,lo=2,seed=1)+0.35*fbm(2.0,lo=8,seed=2)+0.45*edge,0.3,1.9)          # large patches, ragged edges
mid=s(fbm(2.4,lo=12,seed=3),0.6,1.8)*0.6                               # medium stains
drip=s(fbm(2.6,lo=3,ax=6,ay=0.8,seed=4),1.0,2.4)*0.5*s(fbm(3.0,lo=2,seed=9),0.0,1.2)   # a few vertical streaks, in places
dust=s(fbm(1.2,lo=60,seed=5),1.5,2.8)*0.35*(0.4+0.6*s(fbm(3,lo=2,seed=10),-0.5,1))                             # fine specks
grain=fbm(0.8,lo=200,seed=6)*0.06
m=np.clip(np.maximum(blot*0.85, np.maximum(mid,drip))+dust+grain,0,1)
m=m*(0.75+0.25*s(fbm(2.8,lo=2,seed=8),-1,1))
m=np.clip(m,0,1)
print("mean",m.mean(),"p50",np.percentile(m,50),"p90",np.percentile(m,90))
Image.fromarray((m*255).astype(np.uint8),"L").save("/home/claude/simpler/engine/assets/grunge/grunge.png",optimize=True)
Image.fromarray((m*255).astype(np.uint8),"L").resize((512,512)).save("/tmp/claude-0/grunge_prev.png")
t=np.tile(m[::4,::4],(2,2)); Image.fromarray((t*255).astype(np.uint8),"L").save("/tmp/claude-0/grunge_tile.png")
