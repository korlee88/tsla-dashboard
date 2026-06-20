"""data/bgm.mp3 생성기 (원본·로열티프리/CC0).

외부 CC0 음원 사이트(FreePD=JS 렌더링, archive.org=CC0 검색 불가)가 빌드 환경에서
안정적으로 접근되지 않아, 저작권·네트워크 의존이 전혀 없는 '원본' 배경 음악을 직접 합성한다.
구성: 따뜻한 메이저7 패드(C–Am–F–G, 좌우 채널 살짜 디튠한 스테레오 코러스) +
아르페지오(사이클마다 밀도가 달라지는 빌드업/클라이맥스 편성, 핑퐁 패닝) +
하이엔드 스파클(사이클이 진행될수록 늘어나는 결정론적 배치) + 약한 잔향 +
진폭 트레몰로와는 다른 주기로 스테레오 폭이 넓어졌다 좁아지는 "숨쉬기" 변조.
나레이션 아래 10%용 배경음악.
재생성: python scripts/make_bgm.py  (출력: data/bgm.mp3, 이음매 없는 ~63초 루프, 결정론적 합성 — 출력 항상 동일)
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

# 사이클(4회 반복)별 아르페지오 편성 — 잔잔하게 시작해 점점 쌓이는 빌드업/클라이맥스 아크.
# None = 그 박자는 쉼(패드만). 루프 크로스페이드가 클라이맥스(사이클3)→도입(사이클0) 밀도
# 변화를 실제 파형 블렌딩으로 자연스럽게 이어준다(릴리즈처럼 들림).
ARP_PATTERNS = [
    [None, None, None, None, None, None, None, None],  # 사이클0: 패드만 (도입, 잔잔)
    [0, None, 2, None, 0, None, 2, None],                # 사이클1: 절반 밀도 (빌드업)
    [0, 1, 2, 3, 2, 1, 2, 3],                             # 사이클2: 원곡 패턴 (풀 텍스처)
    [0, 1, 2, 3, 0, 2, 1, 3],                             # 사이클3: 변형 패턴 (클라이맥스)
]
SPARKLE_COUNTS = [0, 2, 3, 5]   # 사이클별 하이엔드 스파클 음 개수 — 점점 풍성해짐
PAN_STEPS = [-0.7, 0.7, -0.35, 0.35, 0.7, -0.7, 0.35, -0.35]  # 아르페지오 핑퐁 패닝


def _tone(freq, n, harm):
    t = np.arange(n) / SR
    w = np.sin(2 * np.pi * freq * t)
    for k, amp in harm:
        w += amp * np.sin(2 * np.pi * k * freq * t)
    return w


def grain_stereo(freqs, sub, dur, detune_cents=5.0):
    """따뜻한 패드 코드 — 좌우 채널을 몇 센트 디튠해 자연스러운 코러스 폭감을 낸다.
    저음(서브베이스)은 좌우 동일하게 유지(모노)해 위상 간섭·저음 흐트러짐을 방지."""
    n = int(dur * SR)
    ratio = 2 ** (detune_cents / 1200)
    sig_l = np.zeros(n)
    sig_r = np.zeros(n)
    for f in freqs:
        sig_l += _tone(f / ratio, n, [(2, 0.30), (3, 0.12)])
        sig_r += _tone(f * ratio, n, [(2, 0.30), (3, 0.12)])
    sub_tone = 1.1 * _tone(sub, n, [(2, 0.25)])
    env = np.ones(n)
    a, r = int(0.5 * SR), int(1.6 * SR)
    env[:a] = np.linspace(0, 1, a) ** 2
    env[-r:] = np.linspace(1, 0, r) ** 2
    sig_l = (sig_l + sub_tone) * env
    sig_r = (sig_r + sub_tone) * env
    return np.stack([sig_l, sig_r], axis=1)


def pluck(freq, n):
    """뜯는 듯한 짧은 음 (아르페지오·스파클용) — 빠른 어택 + 지수 감쇠. 모노."""
    t = np.arange(n) / SR
    env = np.exp(-t * 4.5)
    w = (_tone(freq, n, [(2, 0.4), (3, 0.15)])) * env
    a = int(0.006 * SR)
    w[:a] *= np.linspace(0, 1, a)
    return w


def pan(mono, p):
    """모노 신호 → 등파워 패닝 스테레오 (p: -1=완전좌 ~ 0=중앙 ~ 1=완전우)."""
    theta = (p + 1.0) * (math.pi / 4)
    return np.stack([mono * math.cos(theta), mono * math.sin(theta)], axis=1)


def echo(sig, delay_s=0.36, decay=0.33, taps=3):
    """가벼운 잔향 — 감쇠하는 지연 복사본 몇 개 (모노 채널 1개에 적용)."""
    out = sig.copy()
    d = int(delay_s * SR)
    for i in range(1, taps + 1):
        if i * d < len(sig):
            out[i * d:] += sig[:len(sig) - i * d] * (decay ** i)
    return out


total = int(CHORD_SEC * len(CHORDS) * CYCLES * SR)
buf_len = total + int(2.0 * SR)
pad = np.zeros((buf_len, 2))
arp = np.zeros((buf_len, 2))
sparkle = np.zeros((buf_len, 2))

rng = np.random.default_rng(42)  # 고정 시드 — 스파클 배치도 항상 동일하게 재현(결정론적 합성)

step = int(CHORD_SEC * SR)
nlen = int(ARP_NOTE * SR)
idx = 0
for c in range(CYCLES):
    cycle_start = idx
    pattern = ARP_PATTERNS[c % len(ARP_PATTERNS)]
    for freqs, sub in CHORDS:
        # 패드(다음 코드와 1.6초 겹침, 좌우 디튠 스테레오)
        g = grain_stereo(freqs, sub, CHORD_SEC + 1.6)
        end = min(idx + len(g), buf_len)
        pad[idx:end] += g[:end - idx]
        # 아르페지오 (코드 톤, 한 옥타브 위, 사이클별 패턴 + 핑퐁 패닝)
        for k, pi in enumerate(pattern):
            if pi is None:
                continue
            f = freqs[pi % len(freqs)] * 2.0
            s = idx + int(k * ARP_NOTE * SR)
            p = pan(pluck(f, nlen), PAN_STEPS[k % len(PAN_STEPS)])
            e = min(s + len(p), buf_len)
            arp[s:e] += p[:e - s]
        idx += step

    # 스파클: 사이클이 진행될수록 늘어나는 높은 음 텍스처 (구간 내 결정론적 무작위 배치)
    cycle_dur = idx - cycle_start
    for _ in range(SPARKLE_COUNTS[c % len(SPARKLE_COUNTS)]):
        t_off = rng.uniform(0, (cycle_dur / SR) - ARP_NOTE)
        s = cycle_start + int(t_off * SR)
        sp_freqs, _ = CHORDS[rng.integers(0, len(CHORDS))]
        f = sp_freqs[rng.integers(0, len(sp_freqs))] * 4.0
        p = pan(pluck(f, int(ARP_NOTE * 0.6 * SR)) * 0.35, rng.uniform(-0.8, 0.8))
        e = min(s + len(p), buf_len)
        sparkle[s:e] += p[:e - s]

arp[:, 0] = echo(arp[:, 0])
arp[:, 1] = echo(arp[:, 1])
buf = 0.85 * pad[:total] + 0.5 * arp[:total] + sparkle[:total]

# 진폭 트레몰로(움직임, ~8.3초 주기)
t = np.arange(len(buf)) / SR
buf *= (1.0 + 0.05 * np.sin(2 * np.pi * 0.12 * t))[:, None]

# 스테레오 폭 "숨쉬기" — 트레몰로와 다른(~22초) 느린 주기로 폭이 넓어졌다 좁아짐
mid = buf.mean(axis=1)
side = (buf[:, 0] - buf[:, 1]) / 2
width = 0.55 + 0.45 * np.sin(2 * np.pi * 0.045 * t)
buf[:, 0] = mid + side * width
buf[:, 1] = mid - side * width

# 이음매 없는 루프: 앞 FADE초를 끝 FADE초와 크로스페이드
F = int(FADE * SR)
head, tail = buf[:F].copy(), buf[-F:].copy()
ramp = np.linspace(0, 1, F)[:, None]
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
    enc.set_channels(2)
    enc.set_quality(2)
    mp3 = enc.encode(pcm.tobytes()) + enc.flush()
    out.write_bytes(mp3)
    print(f"✅ {out} ({len(mp3)} bytes, {len(loop) / SR:.1f}s, peak={peak:.2f})")
except ImportError:
    import wave
    wav = out.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"⚠ lameenc 없음 → {wav} (WAV) 생성. ffmpeg로 mp3 변환 필요")
