import sys, struct, hashlib, os, fnmatch
def index(path):
    f=open(path,'rb'); mg=f.read(3); assert mg in (b'pf8',b'pf6')
    isz,cnt=struct.unpack('<II',f.read(8))
    f.seek(7); idx=f.read(isz); key=hashlib.sha1(idx).digest() if mg==b'pf8' else None
    p=4; out=[]
    for _ in range(cnt):
        n=struct.unpack_from('<I',idx,p)[0]; p+=4
        name=idx[p:p+n].decode('utf-8','replace'); p+=n+4
        off,sz=struct.unpack_from('<II',idx,p); p+=8
        out.append((name,off,sz))
    return f,key,out
if __name__=='__main__':
    path,mode=sys.argv[1],sys.argv[2]
    f,key,ents=index(path)
    if mode=='list':
        from collections import Counter
        c=Counter(os.path.splitext(n)[1].lower() for n,_,_ in ents); print(len(ents),c.most_common(30))
        for n,o,s in ents:
            if not n.lower().endswith(('.png','.ogg','.jpg','.webp','.ttf','.otf')): print(n,s)
    else:
        pat,outdir=sys.argv[3],sys.argv[4]
        for n,o,s in ents:
            if fnmatch.fnmatch(n.lower(),pat):
                f.seek(o); d=bytearray(f.read(s))
                if key:
                    for i in range(len(d)): d[i]^=key[i%20]
                dst=os.path.join(outdir,n.replace(chr(92),'/')); os.makedirs(os.path.dirname(dst),exist_ok=True)
                open(dst,'wb').write(d)
