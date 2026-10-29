# -*- coding: utf-8 -*-
import zstandard

cctx = zstandard.ZstdCompressor()
payload = '{"type":"e","seq":5}\n'.encode()
frame = cctx.compress(payload)
half = frame[:len(frame) // 2]
dctx = zstandard.ZstdDecompressor()

dobj = dctx.decompressobj()
try:
    out = dobj.decompress(half)
    print('half-frame: no exception, output=%r, eof=%s' % (out, getattr(dobj, 'eof', 'N/A')))
except Exception as e:
    print('half-frame raised: %r' % e)

out2 = dobj.decompress(frame[len(frame) // 2:])
print('continuation: output=%r, eof=%s' % (out2, getattr(dobj, 'eof', 'N/A')))

# 完整帧
dobj2 = dctx.decompressobj()
out3 = dobj2.decompress(frame)
print('full frame: output=%r, eof=%s' % (out3, getattr(dobj2, 'eof', 'N/A')))

# 帧后跟下一帧的字节
dobj3 = dctx.decompressobj()
out4 = dobj3.decompress(frame + frame)
print('two frames: output=%r, eof=%s' % (out4, getattr(dobj3, 'eof', 'N/A')))
