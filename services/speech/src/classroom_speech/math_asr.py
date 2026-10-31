"""方向四：面向课堂数学语音的识别优化——“数学语义守卫”（Math Meaning Guard）。

现成 ASR（FunASR SeACo-Paraformer）+ 课堂领域适配，不训练识别模型。

  一、数学表达解析：把转写里会改变数学含义的部分抽成语义槽（分数、分成 N 份、
      平均分 / 一样大及其否定、大小比较），记录原文位置。
  二、声调—声母仲裁：四 sì 降调 / 十 shí 升调，一 yī 零声母 / 七 qī 送气，
      只看这一个字的波形，给出与语言模型无关的第二意见。
  三、守卫：
      · 对称热词：题目里的关键表达连同易混“兄弟”一起加热词，避免把学生错答“纠正”成标准答案；
      · 反事实热词对质：只把“听错后的说法”设为热词重解码，被拉走说明模型自己拿不准；
      · 题目上下文只给待核验候选排序，永远不改写原文；
      · 输出可用 / 待核验，并列出其他听法与证据。
  四、测试替身：OracleAsr、SimulatedConfusionAsr（云端无权重时离线联调）。

只依赖 numpy；不改基准文件签名；不改 speech.v0.1 字段，额外信息放 diagnostics。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

# ======================================================================
# 一、课堂数学表达解析
# ======================================================================

DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNITS = {"十": 10, "百": 100, "千": 1000}
NUM = r"[零〇一二两三四五六七八九十百千\d]+"
INT_DIGIT = "零一二三四五六七八九"

# 声学上易混、且混了会改变数值的字。键值对称；“二/两”同值，不算关键混淆。
CONFUSABLE = {"四": ["十"], "十": ["四"], "一": ["七"], "七": ["一"], "六": ["九"], "九": ["六"]}

# 可被否定的数学条件：否定词短、轻读，重叠或噪声下最容易丢
PROPERTIES = ["平均分", "一样大", "同样大", "相等", "等分", "一样多"]
NEGATORS = ["没有", "并不", "不是", "不一定", "不能", "不算", "没", "不", "未"]

# 题目上下文、关键表达的静态热词（基准方案里的 CLASSROOM_HOTWORDS 扩充）
STATIC_HOTWORDS = ["平均分", "分数", "分母", "分子", "一样大", "等分", "几分之一", "二分之一", "三分之一", "四分之一"]


def cn_to_int(s: str) -> int | None:
    """中文 / 阿拉伯数字 → 整数（0–9999）。“十二”“二十”“一百零五”“4”。"""
    if s.isdigit():
        return int(s)
    if not s or any(c not in DIGITS and c not in UNITS for c in s):
        return None
    if all(c in DIGITS for c in s):  # “一二”这种逐位读法
        return int("".join(str(DIGITS[c]) for c in s))
    total, cur = 0, 0
    for c in s:
        if c in DIGITS:
            cur = DIGITS[c]
        else:
            total += (cur or 1) * UNITS[c]
            cur = 0
    return total + cur


def int_to_cn(n: int) -> str:
    if n < 10:
        return INT_DIGIT[n]
    if n < 20:
        return "十" + (INT_DIGIT[n - 10] if n % 10 else "")
    if n < 100:
        return INT_DIGIT[n // 10] + "十" + (INT_DIGIT[n % 10] if n % 10 else "")
    return str(n)


@dataclass
class MathClaim:
    """一条会影响数学含义的语义槽。value 是规范化取值，surface 是原文片段。"""

    kind: str  # fraction | partition | property | comparison
    surface: str
    span: tuple[int, int]  # 在原文中的字符区间 [a, b)
    value: str
    negated: bool = False
    detail: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """比较两次解析是否“同一含义”时用的键：取值 + 否定极性。"""
        return f"{self.kind}:{'¬' if self.negated else ''}{self.value}"


FRACTION_RE = re.compile(rf"(?P<den>{NUM})\s*[分份]\s*之\s*(?P<num>{NUM}|几)")
SLASH_RE = re.compile(r"(?P<num>\d+)\s*/\s*(?P<den>\d+)")
COLLOQ_RE = re.compile(rf"(?P<den>{NUM})分(?P<num>[一二三四五六七八九])(?=[，。！？、,.!?\s]|$)")
PARTITION_RE = re.compile(rf"(?P<eq>平均)?分成(?:了)?(?P<n>{NUM})(?:份|块|个部分|部分|半)")


def _negated_before(text: str, start: int) -> str | None:
    window = text[max(0, start - 4) : start]
    for neg in NEGATORS:  # 长词优先
        if window.endswith(neg) or (neg in window and neg in ("没有", "不是", "并不")):
            return neg
    return None


def extract_claims(text: str) -> list[MathClaim]:
    claims: list[MathClaim] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    for rx in (FRACTION_RE, SLASH_RE, COLLOQ_RE):
        for m in rx.finditer(text):
            if not free(*m.span()):
                continue
            den, num = cn_to_int(m["den"]), (None if m["num"] == "几" else cn_to_int(m["num"]))
            if m["den"] == "百":
                den = 100
            if den is None:
                continue
            value = f"{num}/{den}" if num is not None else f"?/{den}"
            claims.append(MathClaim("fraction", m.group(0), m.span(), value, detail={"num": num, "den": den}))
            taken.append(m.span())
    for m in PARTITION_RE.finditer(text):
        n = cn_to_int(m["n"]) if m["n"] else None
        neg = _negated_before(text, m.start())
        claims.append(MathClaim("partition", m.group(0), m.span(), f"{'equal' if m['eq'] else 'any'}x{n}",
                                negated=neg is not None, detail={"parts": n, "equal": bool(m["eq"]), "negator": neg}))
        taken.append(m.span())
    for prop in PROPERTIES:
        for m in re.finditer(prop, text):
            if not free(*m.span()):
                continue
            neg = _negated_before(text, m.start())
            a = m.start() - (len(neg) if neg and text[: m.start()].endswith(neg) else 0)
            claims.append(MathClaim("property", text[a : m.end()], (a, m.end()), prop, negated=neg is not None,
                                    detail={"negator": neg}))
            taken.append((a, m.end()))
    fr = [c for c in claims if c.kind == "fraction"]
    for x, y in zip(fr, fr[1:]):
        mid = text[x.span[1] : y.span[0]]
        m = re.fullmatch(r"\s*(还)?比\s*", mid)
        rel = re.match(r"\s*(大|小|多|少)", text[y.span[1] :])
        if m and rel:
            span = (x.span[0], y.span[1] + rel.end())
            claims.append(MathClaim("comparison", text[span[0] : span[1]], span, f"{x.value}{'>' if rel[1] in '大多' else '<'}{y.value}"))
    return sorted(claims, key=lambda c: c.span)


def counterfactuals(claim: MathClaim) -> list[str]:
    """该语义槽“听错了会变成什么”：数值易混字替换、否定极性翻转。用于反事实对质。"""
    out: list[str] = []
    s = claim.surface
    if claim.kind in ("fraction", "partition"):
        numeral = set(DIGITS) | set(UNITS)
        for i, ch in enumerate(s):
            if (i > 0 and s[i - 1] in numeral) or (i + 1 < len(s) and s[i + 1] in numeral):
                continue  # 只替换单字数：“二十”里的“十”是位值，不和“四”混
            for alt in CONFUSABLE.get(ch, []):
                out.append(s[:i] + alt + s[i + 1 :])
    if claim.kind in ("property", "partition"):
        neg = claim.detail.get("negator")
        if claim.negated and neg and s.startswith(neg):
            out.append(s[len(neg) :])
        elif not claim.negated:
            out.append(("不" if claim.value in ("一样大", "同样大", "相等", "一样多") else "没有") + s)
    return list(dict.fromkeys(o for o in out if o != s))


def confusion_class(surface: str) -> list[str]:
    """一个分数说法的整个易混类（逐字替换的闭包）：七分之一 → 七分之一、一分之一、七分之七、一分之七。

    对称热词要整类一起加：只加一部分，偏置就不对称，模型会被拉向加了的那几个。
    """
    out, frontier = [surface], [surface]
    while frontier:
        nxt = []
        for s in frontier:
            for c in extract_claims(s):
                for v in counterfactuals(c):
                    if v not in out and c.kind == "fraction":
                        out.append(v)
                        nxt.append(v)
        frontier = nxt
    return out


def context_numbers(question: str) -> set[int]:
    """题目里出现的数（含分数的分母、“分成 N 份”），作为候选排序的弱先验。"""
    nums: set[int] = set()
    for c in extract_claims(question):
        if c.kind == "fraction":
            nums.add(c.detail["den"])
        elif c.kind == "partition" and c.detail["parts"]:
            nums.add(c.detail["parts"])
    for m in re.finditer(r"\d+", question):
        nums.add(int(m.group(0)))
    return nums


def symmetric_hotwords(question: str | None, base: list[str] | None = None) -> list[str]:
    """对称热词：题目里每个关键表达连同它的易混“兄弟”一起加入。

    只把“正确答案”加成热词会让 ASR 把学生的错答“纠正”成正确答案；
    兄弟一起加，偏置相互抵消，模型只在声学证据上做选择。
    """
    words = list(base or STATIC_HOTWORDS)
    if question:
        for n in sorted(context_numbers(question)):
            if 1 < n < 100:
                words += confusion_class(f"{int_to_cn(n)}分之一")
        props = {c.value for c in extract_claims(question) if c.kind == "property"}
        props |= {"平均分" for c in extract_claims(question) if c.kind == "partition" and c.detail["equal"]}
        for p in sorted(props):
            words.append(p)
            words += counterfactuals(MathClaim("property", p, (0, len(p)), p))
    return list(dict.fromkeys(words))


def context_hotwords_naive(question: str | None) -> list[str]:
    """对照组：只把题目里的“期望表达”加成热词（常见做法，也是我们要避免的偏置）。"""
    words = list(STATIC_HOTWORDS)
    if question:
        words += [f"{int_to_cn(n)}分之一" for n in sorted(context_numbers(question)) if 1 < n < 100]
        words += [c.value for c in extract_claims(question) if c.kind == "property"]
        words += ["平均分" for c in extract_claims(question) if c.kind == "partition" and c.detail["equal"]]
    return list(dict.fromkeys(words))


# ======================================================================
# 二、声调—声母仲裁
#   四 sì  第四声（高降），声母 s（舌尖前擦音，能量集中在 5 kHz 以上）
#   十 shí 第二声（上升），声母 sh（舌尖后擦音，能量集中在 2.5–5 kHz）
#   一 yī  第一声，零声母：一开口就是浊音
#   七 qī  第一声，送气塞擦音 q：浊音前有 60 ms 以上的清音噪声
# 证据不足时弃权（favors=None），不硬判。
# ======================================================================

PAIRS = {frozenset("四十"), frozenset("一七")}


@dataclass
class PhoneticVote:
    pair: str  # 例如 "四/十"
    favors: str | None  # 声学更支持哪个字；证据不足为 None
    score: float  # >0 支持 pair 的第一个字
    features: dict


def _frames(x: np.ndarray, sr: int, win_ms: float = 40, hop_ms: float = 10) -> np.ndarray:
    w, h = int(sr * win_ms / 1000), int(sr * hop_ms / 1000)
    if len(x) < w:
        x = np.pad(x, (0, w - len(x)))
    n = 1 + (len(x) - w) // h
    return np.stack([x[i * h : i * h + w] for i in range(n)])


def f0_track(x: np.ndarray, sr: int = 16000, fmin: float = 60, fmax: float = 500) -> tuple[np.ndarray, np.ndarray]:
    """归一化自相关基频跟踪。返回每 10 ms 的 F0（Hz，清音为 0）与浊音置信度。"""
    fr = _frames(x, sr)
    fr = fr - fr.mean(axis=1, keepdims=True)
    lo, hi = int(sr / fmax), int(sr / fmin)
    f0, conf = np.zeros(len(fr)), np.zeros(len(fr))
    energy = np.sum(fr**2, axis=1)
    floor = np.percentile(energy, 90) * 1e-2 + 1e-10
    for i, f in enumerate(fr):
        if energy[i] < floor:
            continue
        spec = np.fft.rfft(f * np.hanning(len(f)), 2 * len(f))
        ac = np.fft.irfft(np.abs(spec) ** 2)[: hi + 1]
        ac = ac / (ac[0] + 1e-12)
        lag = lo + int(np.argmax(ac[lo : hi + 1]))
        conf[i] = ac[lag]
        if conf[i] > 0.45:
            # 抛物线插值细化
            if lo < lag < hi:
                a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
                lag = lag + 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
            f0[i] = sr / lag
    return f0, conf


def tone_slope(x: np.ndarray, sr: int = 16000) -> dict:
    """浊音段的音高走向（半音/秒）与降幅，抗倍频跳变。"""
    f0, _ = f0_track(x, sr)
    idx = np.flatnonzero(f0 > 0)
    if len(idx) < 5:
        return {"voiced_frames": int(len(idx))}
    # 只取最长的一段连续浊音（允许 1 帧空洞）：片段两端可能带进前后字的元音
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > 2) + 1)
    idx = max(runs, key=len)
    if len(idx) < 5:
        return {"voiced_frames": int(len(idx))}
    st = 12 * np.log2(f0[idx] / np.median(f0[idx]))
    keep = np.abs(st - np.median(st)) < 7  # 去掉倍频 / 半频误跟踪
    t, st = idx[keep] * 0.01, st[keep]
    if len(t) < 5:
        return {"voiced_frames": int(len(t))}
    a, b = int(len(t) * 0.15), max(int(len(t) * 0.9), int(len(t) * 0.15) + 3)
    coef = np.polyfit(t[a:b], st[a:b], 1)
    resid = st[a:b] - np.polyval(coef, t[a:b])
    r2 = 1 - np.var(resid) / (np.var(st[a:b]) + 1e-9)
    head, tail = np.mean(st[a : a + 3]), np.mean(st[b - 3 : b])
    span = idx[-1] - idx[0] + 1
    # 质量门：浊音连续、音高轨迹平滑、走向能被一条直线解释。混响 / 噪声下常不满足，此时弃权
    reliable = bool(len(t) / span >= 0.7 and np.max(np.abs(np.diff(st))) < 1.5 and r2 >= 0.6 and len(t) >= 8)
    return {"voiced_frames": int(len(t)), "slope_st_per_s": round(float(coef[0]), 1), "rise_st": round(float(tail - head), 2),
            "fit_r2": round(float(r2), 2), "reliable": reliable, "voice_onset_ms": int(idx[0] * 10)}


def fricative_profile(x: np.ndarray, sr: int = 16000) -> dict:
    """浊音开始前的清音段：持续时长与 5–8 kHz / 2.5–5 kHz 能量比。"""
    f0, conf = f0_track(x, sr)
    voiced = np.flatnonzero(conf > 0.45)
    fr = _frames(x, sr)
    if len(voiced):  # 浊音起点取最长浊音段的起点，跳过片段开头带进来的前字元音
        runs = np.split(voiced, np.flatnonzero(np.diff(voiced) > 2) + 1)
        voiced = max(runs, key=len)
    energy = np.sum(fr**2, axis=1)
    loud = energy > np.max(energy) * 10 ** (-35 / 10)
    if len(voiced) == 0 or not loud.any():
        return {}
    first_loud, onset = int(np.argmax(loud)), int(voiced[0])
    freqs = np.fft.rfftfreq(fr.shape[1], 1 / sr)
    spec = np.abs(np.fft.rfft(fr * np.hanning(fr.shape[1]), axis=1)) ** 2
    # 清音段只数“像擦音”的帧：2.5 kHz 以上能量占一半以上。混响拖尾是低频浊音，不会被算进来
    hf_share = spec[:, freqs >= 2500].sum(axis=1) / (spec.sum(axis=1) + 1e-12)
    pre = np.arange(first_loud, onset)
    is_fric = (hf_share[pre] > 0.5) & loud[pre] if len(pre) else np.zeros(0, bool)
    k = len(is_fric)
    for _ in range(2):  # 擦音到元音之间允许 1–2 帧过渡
        if k > 0 and not is_fric[k - 1]:
            k -= 1
    end = k
    while k > 0 and is_fric[k - 1]:  # 只数紧贴浊音起点的那一段：前一个字（如“之”）的擦音尾巴不算
        k -= 1
    fric = pre[k:end]
    sel = spec[fric] if len(fric) else spec[max(onset - 2, 0) : onset + 1]
    m = sel.mean(axis=0)
    hi = m[(freqs >= 5000) & (freqs < 8000)].sum()
    mid = m[(freqs >= 2500) & (freqs < 5000)].sum()
    return {"unvoiced_ms": int(len(fric) * 10), "hf_ratio_db": round(float(10 * np.log10((hi + 1e-12) / (mid + 1e-12))), 1)}


def arbitrate(x: np.ndarray, hyp_char: str, alt_char: str, sr: int = 16000) -> PhoneticVote | None:
    """在一个字的音频片段上，判断声学更像 hyp_char 还是 alt_char。不支持的字对返回 None。"""
    pair = frozenset((hyp_char, alt_char))
    if pair not in PAIRS:
        return None
    if pair == frozenset("四十"):
        tone, fric = tone_slope(x, sr), fricative_profile(x, sr)
        if not tone.get("reliable"):
            return PhoneticVote("四/十", None, 0.0, {**tone, **fric})
        # 降调 → 四；升调 → 十。擦音高频占比作为次要证据
        s = -tone["slope_st_per_s"] / 25.0 - tone["rise_st"] / 3.0
        if "hf_ratio_db" in fric:
            s += float(np.clip(fric["hf_ratio_db"] / 6.0, -1, 1)) * 0.5
        favors = "四" if s > 0.6 else "十" if s < -0.6 else None
        return PhoneticVote("四/十", favors, round(s, 2), {**tone, **fric})
    fric = fricative_profile(x, sr)
    if "unvoiced_ms" not in fric:
        return PhoneticVote("一/七", None, 0.0, fric)
    s = (40 - fric["unvoiced_ms"]) / 20.0  # >0 支持“一”（零声母）
    favors = "一" if s > 0.75 else "七" if s < -0.75 else None
    return PhoneticVote("一/七", favors, round(s, 2), fric)


# ======================================================================
# 三、守卫：现成 ASR + 对称热词 + 反事实对质 + 声调仲裁 + 上下文排序
# ======================================================================

PUNCT = set("，。！？、；：,.!?;: ")


@dataclass
class Decoded:
    """一次解码结果。char_times_ms 与 text 去掉标点后的字一一对应（毫秒，相对本段起点）。"""

    text: str
    char_times_ms: list[tuple[int, int]] | None = None


@dataclass
class GuardedResult:
    text: str | None  # 引擎原文，绝不按上下文改写
    engine: str
    reliability: str  # usable | needs_review | undetermined
    review_reasons: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    math_terms: list[dict] = field(default_factory=list)
    hotwords: list[str] = field(default_factory=list)
    probes_run: int = 0

    def diagnostics(self) -> dict:
        """写进 speech.v0.1 事件 diagnostics 的内容（不改契约字段）。"""
        return {"math_guard": {"review_reasons": self.review_reasons, "candidates": self.candidates,
                               "math_terms": self.math_terms, "hotwords": self.hotwords, "probes_run": self.probes_run,
                               "policy": "text 为 ASR 原文；上下文只给候选排序，不改写"}}


@dataclass
class GuardConfig:
    symmetric_hotwords: bool = True
    probe: bool = True
    phonetic: bool = True
    max_probes: int = 6  # 每段最多额外解码次数，控制延迟（Paraformer 在 2060 上一段约 30–60 ms）
    pad_ms: int = 60


def char_spans(text: str, times: list | None) -> list[tuple[int, int] | None]:
    chars = [i for i, c in enumerate(text) if c not in PUNCT]
    out: list[tuple[int, int] | None] = [None] * len(text)
    if times and len(times) == len(chars):
        for i, t in zip(chars, times):
            out[i] = (int(t[0]), int(t[1]))
    return out


def _decode(base, audio: np.ndarray, sample_rate: int, hotwords: str | None) -> Decoded | None:
    """用任意基准引擎解码，并尽量带上热词与逐字时间戳，不要求改基准引擎签名。

    - 引擎自带 decode(audio, sr, hotwords)（测试替身）→ 直接用；
    - 基准 FunAsrEngine（有 .model.generate）→ 直接调 FunASR，传 hotword、取 timestamp；
    - 其他引擎 → 只能用 transcribe()，没有热词与时间戳，对质与仲裁自动跳过。
    """
    if hasattr(base, "decode"):
        return base.decode(audio, sample_rate, hotwords)
    model = getattr(base, "model", None)
    if model is not None and hasattr(model, "generate"):
        hw = hotwords if hotwords is not None else getattr(base, "hotwords", "")
        res = model.generate(input=audio.astype(np.float32), hotword=hw)
        text = (res[0].get("text") or "").strip() if res else ""
        return Decoded(text, res[0].get("timestamp")) if text else None
    r = base.transcribe(audio, sample_rate)
    return Decoded(r.text) if r else None


def _supports_hotwords(base) -> bool:
    return hasattr(base, "decode") or hasattr(getattr(base, "model", None), "generate")


def _same_meaning_present(text: str, target: MathClaim) -> bool:
    return any(c.key == target.key for c in extract_claims(text))


def _as_claim(surface: str, like: MathClaim) -> MathClaim | None:
    parsed = [c for c in extract_claims(surface) if c.kind == like.kind]
    return parsed[0] if parsed else None


def _isolated_numerals(surface: str):
    numeral = set(DIGITS) | set(UNITS)
    for i, ch in enumerate(surface):
        if ch in CONFUSABLE and not ((i > 0 and surface[i - 1] in numeral) or (i + 1 < len(surface) and surface[i + 1] in numeral)):
            yield i, ch


class MathGuardedAsr:
    """把任意现成 ASR 包一层“数学语义守卫”。base 为 None 时返回 None（流水线报 asr_unavailable）。"""

    def __init__(self, base, cfg: GuardConfig | None = None) -> None:
        self.base, self.cfg = base, cfg or GuardConfig()
        self.name = f"{getattr(base, 'name', 'asr')}+math-guard"

    def hotwords_for(self, context: dict | None) -> list[str]:
        q = (context or {}).get("question")
        expected = (context or {}).get("expected_terms") or []
        if self.cfg.symmetric_hotwords:
            return symmetric_hotwords(" ".join([q or "", *expected]) or None)
        return context_hotwords_naive(" ".join([q or "", *expected]) or None)

    def transcribe(self, audio: np.ndarray, sample_rate: int, context: dict | None = None, overlap: bool = False) -> GuardedResult | None:
        if self.base is None:
            return None
        overlap = overlap or bool((context or {}).get("overlap"))
        hot = self.hotwords_for(context)
        main = _decode(self.base, audio, sample_rate, " ".join(hot) if _supports_hotwords(self.base) else None)
        if main is None or not main.text:
            return None
        return self.check(audio, sample_rate, main, context, overlap, hot)

    def check(self, audio, sample_rate, main: Decoded, context: dict | None, overlap: bool, hot: list[str]) -> GuardedResult:
        text = main.text
        claims = extract_claims(text)
        spans = char_spans(text, main.char_times_ms)
        q = " ".join([(context or {}).get("question") or "", *((context or {}).get("expected_terms") or [])])
        nums = context_numbers(q) if q.strip() and not (context or {}).get("rank_without_context") else set()
        budget, probes_run = self.cfg.max_probes, 0
        base_ms = int((context or {}).get("start_ms") or 0)  # 流水线传入片段起点，audio_ms 换算到会话时间轴
        terms, reasons, cands_out = [], [], []
        can_probe = self.cfg.probe and _supports_hotwords(self.base)
        for c in claims:
            if c.kind == "comparison":
                terms.append({"kind": c.kind, "surface": c.surface, "span": list(c.span), "value": c.value})
                continue
            flags: list[str] = []
            alts: dict[str, dict] = {}
            sites: dict[int, dict] = {}  # 每个易混位置（-1 为否定词）的两路证据
            verified = False
            # 1. 反事实热词对质：只把“听错后的说法”设为热词，看模型会不会被拉过去
            if can_probe:
                for v in counterfactuals(c):
                    vc = _as_claim(v, c)
                    if vc is None or budget <= 0:
                        continue
                    budget -= 1
                    probes_run += 1
                    r = _decode(self.base, audio, sample_rate, v)
                    got = r.text if r else ""
                    flipped = _same_meaning_present(got, vc) and not _same_meaning_present(got, c)
                    a = alts.setdefault(vc.key, {"surface": v, "value": vc.value, "negated": vc.negated, "evidence": {}})
                    a["evidence"]["probe"] = {"hotword": v, "decoded": got, "flipped": flipped}
                    site = next((k for k in range(min(len(v), len(c.surface))) if v[k] != c.surface[k]), -1) if len(v) == len(c.surface) else -1
                    sites.setdefault(site, {})["probe"] = flipped
                    verified |= not flipped
            # 2. 声调—声母仲裁：只看这个字的波形
            if self.cfg.phonetic and c.kind in ("fraction", "partition"):
                for i, ch in _isolated_numerals(c.surface):
                    t = spans[c.span[0] + i] if c.span[0] + i < len(spans) else None
                    if t is None:
                        continue
                    lo = max(0, int((t[0] - self.cfg.pad_ms) * sample_rate / 1000))
                    hi = min(len(audio), int((t[1] + self.cfg.pad_ms // 2) * sample_rate / 1000))
                    for alt in CONFUSABLE[ch]:
                        vote = arbitrate(audio[lo:hi], ch, alt, sample_rate)
                        if vote is None:
                            continue
                        surface = c.surface[:i] + alt + c.surface[i + 1 :]
                        vc = _as_claim(surface, c)
                        rec = {"char": ch, "alt": alt, "favors": vote.favors, "score": vote.score, "features": vote.features}
                        if vc is not None:
                            alts.setdefault(vc.key, {"surface": surface, "value": vc.value, "negated": vc.negated, "evidence": {}})["evidence"]["phonetic"] = rec
                        if vote.favors is not None:
                            sites.setdefault(i, {})["phonetic"] = "own" if vote.favors == ch else "alt"
                        verified |= vote.favors == ch
            # 两路证据融合：声调判为“像别的字”→ 存疑；对质被拉走、且声调没有站出来支持原字 → 存疑；
            # 对质被拉走但声调明确支持原字 → 视为已核实（两路互证，减少老师回听量）
            for ev in sites.values():
                if ev.get("phonetic") == "alt":
                    flags.append("phonetic_disagrees")
                elif ev.get("probe"):
                    flags.append("rescued_by_phonetic" if ev.get("phonetic") == "own" else "unstable_under_probe")
            # 3. 题目上下文：只给候选排序，不改写
            for v in counterfactuals(c):  # 没跑对质时也列出易混说法，供上下文比对与老师选择
                vc = _as_claim(v, c)
                if vc is not None:
                    alts.setdefault(vc.key, {"surface": v, "value": vc.value, "negated": vc.negated, "evidence": {}})
            if nums and c.kind == "fraction":
                own = c.detail["den"] in nums
                for a in alts.values():
                    den = int(a["value"].split("/")[1]) if "/" in a["value"] else None
                    a["evidence"]["context"] = int(den in nums) - int(own)
                if not own and any(a["evidence"].get("context", 0) > 0 for a in alts.values()):
                    flags.append("context_mismatch")
            if overlap and c.kind in ("property", "partition"):
                flags.append("negation_at_risk")  # 否定词短、轻读，重叠时最容易被盖住
            doubtful = {"unstable_under_probe", "phonetic_disagrees", "negation_at_risk"} & set(flags)
            if "context_mismatch" in flags and not verified:
                doubtful.add("context_mismatch")
            if "context_mismatch" in flags and verified and not doubtful:
                flags.append("verified_as_spoken")  # 声学证据支持原话：学生确实这么说，交给老师看思路
            if not verified and not doubtful:
                flags.append("unverified")
            state = "needs_review" if doubtful else "usable"
            ranked = sorted(alts.values(), key=_alt_score, reverse=True)
            ts = [spans[k] for k in range(c.span[0], min(c.span[1], len(spans))) if spans[k]]
            terms.append({"kind": c.kind, "surface": c.surface, "span": list(c.span), "value": c.value, "negated": c.negated,
                          "audio_ms": [base_ms + ts[0][0], base_ms + ts[-1][1]] if ts else None, "reliability": state,
                          "flags": list(dict.fromkeys(flags))})
            if state == "needs_review":
                alt_txt = "/".join(a["surface"] for a in ranked[:2])
                kind = {"fraction": "fraction_ambiguous", "partition": "partition_ambiguous"}.get(c.kind, "negation_ambiguous")
                reasons.append(f"{kind}: {c.surface}/{alt_txt}" if alt_txt else f"{kind}: {c.surface}")
                cands_out.append({"slot": c.surface, "span": list(c.span), "asr": c.surface,
                                  "alternatives": [{**a, "score": round(_alt_score(a), 2)} for a in ranked]})
        reliability = "needs_review" if reasons else "usable"
        return GuardedResult(text=text, engine=self.name, reliability=reliability, review_reasons=reasons,
                             candidates=cands_out, math_terms=terms, hotwords=hot, probes_run=probes_run)


def _alt_score(a: dict) -> float:
    e = a["evidence"]
    # 声调证据与语言模型无关，权重高于对质（对质只说明“不稳”，不说明“是哪个”）
    s = 1.5 * bool(e.get("probe", {}).get("flipped"))
    ph = e.get("phonetic")
    if ph and ph.get("favors"):
        s += 2.5 if ph["favors"] == ph["alt"] else -1.0
    return s + 0.5 * e.get("context", 0)


# ======================================================================
# 四、测试替身（云端无权重时跑端到端用）
# ======================================================================


class OracleAsr:
    """把已知文本当识别结果。queue 依次返回；用于联调流水线，不代表识别能力。"""

    name = "oracle"

    def __init__(self, texts: list[str] | None = None) -> None:
        self.queue = list(texts or [])

    def transcribe(self, audio: np.ndarray, sample_rate: int):
        from types import SimpleNamespace

        return SimpleNamespace(text=self.queue.pop(0), engine=self.name) if self.queue else None


def _covers(h: str, win: str, a: int, b: int) -> bool:
    """热词 h 在窗口里出现，且覆盖受影响区间 [a, b)（删除时 b == a，覆盖接缝即可）。"""
    i = win.find(h)
    while i >= 0:
        if i <= a and i + len(h) >= max(b, a + 1) or (b == a and i < a < i + len(h)):
            return True
        i = win.find(h, i + 1)
    return False


class SimulatedConfusionAsr:
    """模拟 SeACo-Paraformer 的热词偏置行为，用来离线验证守卫的决策逻辑。

    每个易混位置有一个“声学裕度” m（>0 偏向真实字）。解码时：
        选真实字  ⇔  m + bias·[热词含真实说法] − bias·[热词含易混说法] > 0
    裕度随信噪比下降。这是行为模型，不是真实识别；真实效果以 FunASR 实测为准。
    """

    name = "simulated-seaco"

    def __init__(self, reference: str, margins: dict[int, float], char_times_ms: list[tuple[int, int]] | None = None,
                 bias: float = 1.0) -> None:
        self.ref, self.margins, self.times, self.bias = reference, margins, char_times_ms, bias

    def decode(self, audio, sample_rate, hotwords: str | None) -> Decoded:
        hw = [h for h in (hotwords or "").split() if len(h) > 1]
        out = self.ref
        for pos in sorted(self.margins, reverse=True):  # 从后往前替换，前面的位置不受影响
            true_s, alt_s, a, b = self._variants(out, pos)
            pull = self.bias * (any(_covers(h, true_s, a, b) for h in hw) - any(_covers(h, alt_s, a, a + len(alt_s) - len(true_s) + (b - a)) for h in hw))
            if self.margins[pos] + pull <= 0:
                lo = max(0, pos - 3)
                out = out[:lo] + alt_s + out[lo + len(true_s) :]
        # 否定词被吞时字数变了，时间戳对不上；与真实引擎一样只在一一对应时给出
        return Decoded(out, self.times if len(out) == len(self.ref) else None)

    @staticmethod
    def _variants(ref: str, pos: int) -> tuple[str, str, int, int]:
        """pos 处的易混说法。数字 → 易混字；否定词 → 被吞掉。返回 (真窗, 错窗, 窗内受影响区间)。"""
        lo, hi = max(0, pos - 3), min(len(ref), pos + 6)
        win, k = ref[lo:hi], pos - lo
        ch = ref[pos]
        if ch in CONFUSABLE:
            return win, win[:k] + CONFUSABLE[ch][0] + win[k + 1 :], k, k + 1
        n = 2 if ref[pos : pos + 2] in ("没有", "不是", "并不") else 1
        return win, win[:k] + win[k + n :], k, k + n

    def transcribe(self, audio, sample_rate):
        from types import SimpleNamespace

        return SimpleNamespace(text=self.decode(audio, sample_rate, None).text, engine=self.name)
