"""data/bgm.mp3 생성기 (원본·로열티프리/CC0).

외부 CC0 음원 사이트(FreePD=JS 렌더링, archive.org=CC0 검색 불가)가 빌드 환경에서
안정적으로 접근되지 않아, 저작권·네트워크 의존이 전혀 없는 '원본' 배경 음악을 직접 합성한다.
구성: 따뜻한 메이저7 패드(C–Am–F–G) + 부드러운 아르페지오 + 약한 잔향 → 나레이션 아래 10%용.
재생성: python scripts/make_bgm.py  (출력: data/bgm.mp3, 이음매 없는 ~63초 루프)
"""
import math
from pathlib import Path
import numpy as np

SR = 44100
CHORD_SEC = 4.0
CYCLES = 4
FADE = 1.0          # 루프 이음매 크로스페이드 길이(초)
ARP_NOTE = 0.5      # 아르페지오 한 음 길이(초)

# 코드별 음정(Hz): Cmaj7 – Am7 – Fmaj7 – G7  + 서브베이스(루트 한 옥타브 아래)
CHORDS = [
    ([261.63, 329.63, 392.00, 493.88], 130.81),  # Cmaj7
    ([220.00, 261.63, 329.63, 392.00], 110.00),   # Am7
    ([174.61, 220.00, 261.63, 329.63],  87.31),   # Fmaj7
    ([196.00, 246.94, 293.66, 349.23],  98.00),   # G7
]
# 코드당 아르페지오 패턴(코드 톤 인덱스, 한 옥타브 위로 연주)
ARP_PATTERN = [0, 1, 2, 3, 2, 1, 2, 3]


def _tone(freq, n, harm):
    t = np.arange(n) / SR
    w = np.sin(2 * np.pi * freq * t)
    for k, amp in harm:
        w += amp * np.sin(2 * np.pi * k * freq * t)
    return w


def grain(freqs, sub, dur):
    """부드러운 패드 코드 (긴 어택/릴리즈로 서로 자연스럽게 겹침)."""
    n = int(dur * SR)
    sig = np.zeros(n)
    for f in freqs:
        sig += _tone(f, n, [(2, 0.30), (3, 0.12)])
    sig += 1.1 * _tone(sub, n, [(2, 0.25)])      # 따뜻한 저음
    env = np.ones(n)
    a, r = int(0.5 * SR), int(1.6 * SR)
    env[:a] = np.linspace(0, 1, a) ** 2
    env[-r:] = np.linspace(1, 0, r) ** 2
    return sig * env


def pluck(freq, n):
    """뜯는 듯한 짧은 음 (아르페지오용) — 빠른 어택 + 지수 감쇠."""
    t = np.arange(n) / SR
    env = np.exp(-t * 4.5)
    w = (_tone(freq, n, [(2, 0.4), (3, 0.15)])) * env
    a = int(0.006 * SR)
    w[:a] *= np.linspace(0, 1, a)
    return w


def echo(sig, delay_s=0.36, decay=0.33, taps=3):
    """가벼운 잔향 — 감쇠하는 지연 복사본 몇 개."""
    out = sig.copy()
    d = int(delay_s * SR)
    for i in range(1, taps + 1):
        if i * d < len(sig):
            out[i * d:] += sig[:len(sig) - i * d] * (decay ** i)
    return out


total = int(CHORD_SEC * len(CHORDS) * CYCLES * SR)
buf_len = total + int(2.0 * SR)
pad = np.zeros(buf_len)
arp = np.zeros(buf_len)

step = int(CHORD_SEC * SR)
nlen = int(ARP_NOTE * SR)
idx = 0
for c in range(CYCLES):
    for freqs, sub in CHORDS:
        # 패드(다음 코드와 1.6초 겹침)
        g = grain(freqs, sub, CHORD_SEC + 1.6)
        end = min(idx + len(g), buf_len)
        pad[idx:end] += g[:end - idx]
        # 아르페지오 (코드 톤, 한 옥타브 위)
        for k, pi in enumerate(ARP_PATTERN):
            f = freqs[pi % len(freqs)] * 2.0
            s = idx + int(k * ARP_NOTE * SR)
            p = pluck(f, nlen)
            e = min(s + len(p), buf_len)
            arp[s:e] += p[:e - s]
        idx += step

arp = echo(arp)
buf = 0.85 * pad[:total] + 0.5 * arp[:total]

# 잔잔한 트레몰로(움직임)
t = np.arange(len(buf)) / SR
buf *= (1.0 + 0.05 * np.sin(2 * np.pi * 0.12 * t))

# 이음매 없는 루프: 앞 FADE초를 끝 FADE초와 크로스페이드
F = int(FADE * SR)
head, tail = buf[:F].copy(), buf[-F:].copy()
ramp = np.linspace(0, 1, F)
buf[:F] = head * ramp + tail * (1 - ramp)
loop = buf[:len(buf) - F]

# 정규화 (-3 dBFS)
peak = np.max(np.abs(loop)) or 1.0
loop = loop / peak * (10 ** (-3 / 20))
pcm = (loop * 32767).astype(np.int16)

out = Path(__file__).parent.parent / "data" / "bgm.mp3"
out.parent.mkdir(parents=True, exist_ok=True)
try:
    import lameenc
    enc = lameenc.Encoder()
    enc.set_bit_rate(160)
    enc.set_in_sample_rate(SR)
    enc.set_channels(1)
    enc.set_quality(2)
    mp3 = enc.encode(pcm.tobytes()) + enc.flush()
    out.write_bytes(mp3)
    print(f"✅ {out} ({len(mp3)} bytes, {len(loop) / SR:.1f}s, peak={peak:.2f})")
except ImportError:
    import wave
    wav = out.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"⚠ lameenc 없음 → {wav} (WAV) 생성. ffmpeg로 mp3 변환 필요")
