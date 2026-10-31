# 장난감 측정기: attention 메모리를 흉내 냄 (GPU 없이 테스트용). 24GB 넘으면 OOM 실패.
import argparse, json, sys
ap=argparse.ArgumentParser(); ap.add_argument("--L",type=int); ap.add_argument("--B",type=int); ap.add_argument("--prec",default="fp32")
a=ap.parse_args(); byt={"fp32":4,"bf16":2}[a.prec]
mem = 1.5 + a.B*8*a.L*a.L*byt*6/1e9 + a.B*a.L*256*byt*40/1e9
if mem>24: print("CUDA out of memory. Tried to allocate", file=sys.stderr); sys.exit(1)
print(json.dumps({"mem_gb":round(mem,3)}))
