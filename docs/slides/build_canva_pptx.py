"""Canva取り込み用の編集可能PPTXを生成する(入場案内+GW進行の計5枚)。

トンマナ: AI Practice Forum クロージング資料(濃紫グラデ・白文字・シアンアクセント・
Orbitron英字)に準拠。

Canvaの既知のハマりどころ対応:
  - 表は使わない(セル内文字切れ事故) → 図形+独立テキストで構築
  - 背景は背景プロパティでなく全面矩形(グラデ) → Canvaでも1要素として編集可能
"""
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# 16:9 (EMU)
W, H = 12192000, 6858000

INK = RGBColor(0xF4, 0xEF, 0xFF)
MUTED = RGBColor(0xCB, 0xBD, 0xE6)
FAINT = RGBColor(0x9B, 0x8A, 0xBC)
CYAN = RGBColor(0x3E, 0xE6, 0xFF)
LAV = RGBColor(0xC9, 0xA7, 0xFF)
MINT = RGBColor(0x52, 0xF2, 0xB8)
DARK = RGBColor(0x0B, 0x06, 0x18)
BG0 = RGBColor(0x14, 0x08, 0x22)
BG2 = RGBColor(0x51, 0x18, 0x7D)
CARD = RGBColor(0x2A, 0x14, 0x48)   # 半透明の代わりの近似色
CARD2 = RGBColor(0x22, 0x10, 0x3C)
EDGE = RGBColor(0x5A, 0x3C, 0x8A)

JP = "Noto Sans JP"
EN = "Orbitron"

prs = Presentation()
prs.slide_width = Emu(W)
prs.slide_height = Emu(H)
BLANK = prs.slide_layouts[6]


def pct(x):  # 幅比率 -> EMU
    return Emu(int(W * x))


def pcty(y):
    return Emu(int(H * y))


def add_bg(slide):
    """全面グラデ矩形(左上:濃紺紫 → 右下:紫)"""
    sp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Emu(W), Emu(H))
    sp.line.fill.background()
    sp.fill.gradient()
    stops = sp.fill.gradient_stops
    stops[0].color.rgb = BG0
    stops[0].position = 0.0
    stops[1].color.rgb = BG2
    stops[1].position = 1.0
    try:
        sp.fill.gradient_angle = 45.0
    except Exception:
        pass
    sp.shadow.inherit = False
    return sp


def add_text(slide, x, y, w, h, runs, size, color=INK, bold=True, font=JP,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.0, wrap=True):
    """テキストボックス追加。runs は str か [(text, color, bold, font), ...] の行リスト"""
    tb = slide.shapes.add_textbox(pct(x), pcty(y), pct(w), pcty(h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    if isinstance(runs, str):
        runs = [[(runs, color, bold, font)]]
    for i, line in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing != 1.0:
            p.line_spacing = spacing
        if isinstance(line, str):
            line = [(line, color, bold, font)]
        for text, c, b, f in line:
            r = p.add_run()
            r.text = text
            r.font.size = Pt(size)
            r.font.bold = b
            r.font.color.rgb = c
            r.font.name = f
            _set_ea_font(r, f)
    return tb


def _set_ea_font(run, name):
    """日本語(EastAsia)フォント名も明示する"""
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", name)


def add_box(slide, x, y, w, h, fill=CARD, line=EDGE, line_w=1.0, radius=True):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    sp = slide.shapes.add_shape(shape_type, pct(x), pcty(y), pct(w), pcty(h))
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(line_w)
    sp.shadow.inherit = False
    if radius:
        try:
            sp.adjustments[0] = 0.12
        except Exception:
            pass
    return sp


def add_pill(slide, x, y, w, h, text, size, fg, bg, line=None, bold=True, font=JP):
    sp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, pct(x), pcty(y), pct(w), pcty(h))
    try:
        sp.adjustments[0] = 0.5
    except Exception:
        pass
    if bg is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = bg
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(1.2)
    sp.shadow.inherit = False
    tf = sp.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = Emu(60000)
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = fg
    r.font.name = font
    _set_ea_font(r, font)
    return sp


def add_header(slide, tag_text, pageno):
    add_pill(slide, 0.05, 0.05, 0.16, 0.065, tag_text, 14, CYAN, None, line=CYAN, font=EN)
    add_text(slide, 0.60, 0.055, 0.35, 0.05, "AI PRACTICE FORUM", 14,
             color=FAINT, font=EN, align=PP_ALIGN.RIGHT)
    add_text(slide, 0.60, 0.92, 0.35, 0.05, pageno, 16, color=CYAN, font=EN,
             align=PP_ALIGN.RIGHT)
    add_text(slide, 0.05, 0.925, 0.5, 0.04,
             "AI PRACTICE FORUM 〜 AI活用のリアルを語る場 〜", 10, color=FAINT, bold=False)


FLOW = ["オープニング・役割決め", "① AI活用のリアル", "⏳", "② AIの壁", "⏳",
        "③ スモールステップ", "🎤 全体共有", "締め"]
FLOW_W = [0.150, 0.125, 0.034, 0.088, 0.034, 0.125, 0.098, 0.062]


def add_stepper(slide, now_idx, y=0.145):
    x = 0.05
    for i, (label, w) in enumerate(zip(FLOW, FLOW_W)):
        if i < now_idx:
            add_pill(slide, x, y, w, 0.052, "✓ " + label, 10, FAINT, CARD2, line=None)
        elif i == now_idx:
            add_pill(slide, x, y, w, 0.052, "▶ " + label, 11, DARK, CYAN, line=None)
        else:
            add_pill(slide, x, y, w, 0.052, label, 10, MUTED, None, line=EDGE)
        x += w + 0.008


def add_round_slide(tag, pageno, title, timom, timenote, col1_title, col1, col2_title, col2, goal, notes, now_idx):
    s = prs.slides.add_slide(BLANK)
    add_bg(s)
    add_header(s, tag, pageno)
    add_stepper(s, now_idx)
    add_text(s, 0.05, 0.215, 0.9, 0.09, title, 34)
    add_pill(s, 0.05, 0.315, 0.10, 0.06, timom, 15, CYAN, None, line=CYAN)
    add_text(s, 0.17, 0.325, 0.5, 0.05, timenote, 12, color=FAINT, bold=False)

    for ci, (ct, items) in enumerate([(col1_title, col1), (col2_title, col2)]):
        bx = 0.05 + ci * 0.465
        add_box(s, bx, 0.41, 0.44, 0.37)
        add_text(s, bx + 0.02, 0.435, 0.40, 0.055, ct, 16, color=CYAN)
        lines = []
        for it in items:
            lines.append([("▸ ", CYAN, True, JP)] + it)
        add_text(s, bx + 0.02, 0.50, 0.40, 0.26, lines, 13, color=MUTED, bold=False, spacing=1.25)

    add_text(s, 0.05, 0.80, 0.9, 0.055, goal, 17, align=PP_ALIGN.CENTER)
    add_text(s, 0.05, 0.868, 0.9, 0.04,
             [[("   ".join(notes), FAINT, False, JP)]], 11, bold=False)
    return s


M = lambda t: (t, MUTED, False, JP)   # 本文
B = lambda t: (t, INK, True, JP)      # 強調
C = lambda t: (t, CYAN, True, JP)     # シアン強調

# ---------- 1: 入場案内 ----------
s = prs.slides.add_slide(BLANK)
add_bg(s)
# 右上HUDリング
ring = s.shapes.add_shape(MSO_SHAPE.OVAL, pct(0.82), pcty(-0.25), pct(0.28), pcty(0.50))
ring.fill.background()
ring.line.color.rgb = CYAN
ring.line.width = Pt(2.5)
ring.shadow.inherit = False

add_text(s, 0.05, 0.05, 0.5, 0.05, "AI PRACTICE FORUM", 16, color=CYAN, font=EN)
add_text(s, 0.60, 0.055, 0.30, 0.05, "2026.10.11 SUN", 13, color=FAINT, font=EN,
         align=PP_ALIGN.RIGHT)
add_text(s, 0.05, 0.12, 0.9, 0.09, "ようこそ、AI Practice Forum へ!", 36)
add_text(s, 0.05, 0.215, 0.9, 0.05,
         [[M("開始までに、お手元のスマホ / PC で "), C("3つの準備"), M(" をお願いします。")]], 18)

col_y, col_h = 0.30, 0.50
for ci in range(3):
    add_box(s, 0.05 + ci * 0.31, col_y, 0.29, col_h)

# STEP1
add_text(s, 0.07, col_y + 0.03, 0.05, 0.08, "1", 40, color=CYAN, font=EN)
add_text(s, 0.125, col_y + 0.055, 0.20, 0.05, "Discordに参加", 18)
pic = s.shapes.add_picture("qr-discord.png", pct(0.115), pcty(col_y + 0.14), pct(0.16))
add_text(s, 0.07, col_y + 0.43, 0.25, 0.04, "QRを読み取るか、URLを直接入力", 11,
         color=MUTED, bold=False, align=PP_ALIGN.CENTER)
add_text(s, 0.07, col_y + 0.465, 0.25, 0.04, "discord.gg/SdJjFswU98", 14,
         color=CYAN, font=EN, align=PP_ALIGN.CENTER)

# STEP2
add_text(s, 0.38, col_y + 0.03, 0.05, 0.08, "2", 40, color=CYAN, font=EN)
add_text(s, 0.435, col_y + 0.055, 0.20, 0.05, "使い方をチェック", 18)
add_text(s, 0.38, col_y + 0.15, 0.25, 0.30,
         [[M("参加できたら")],
          [B("# 資料共有")],
          [M("チャンネルを開いて、")],
          [B("本日のDiscordの使い方")],
          [M("をご確認ください。")]], 15, spacing=1.45)

# STEP3
add_text(s, 0.69, col_y + 0.03, 0.05, 0.08, "3", 40, color=CYAN, font=EN)
add_text(s, 0.745, col_y + 0.055, 0.20, 0.05, "コメントの準備", 18)
add_text(s, 0.69, col_y + 0.15, 0.26, 0.32,
         [[C("▸ "), B("# lt-コメント を開く")],
          [B("LT中の感想・質問・応援は、このチャンネルに投稿します。開いておいてください。")]], 14, spacing=1.3)

add_text(s, 0.05, 0.83, 0.9, 0.05, "グループ番号は受付でご案内しています。", 19)
add_text(s, 0.05, 0.885, 0.9, 0.04,
         "本日の発言・コメント・メモはAIがその場で分析し、インサイトとして皆さんに還元します。",
         11, color=FAINT, bold=False)
add_text(s, 0.60, 0.92, 0.35, 0.05, "ENTRANCE", 14, color=CYAN, font=EN, align=PP_ALIGN.RIGHT)

# ---------- 2: タイムテーブル ----------
s = prs.slides.add_slide(BLANK)
add_bg(s)
add_header(s, "GROUP WORK", "GW")
add_text(s, 0.05, 0.13, 0.9, 0.08, "グループワーク タイムテーブル", 32)
add_pill(s, 0.05, 0.225, 0.19, 0.06, "14:55 – 16:25 (90分)", 15, CYAN, None, line=CYAN)
add_text(s, 0.255, 0.235, 0.6, 0.05, "※ 各時刻は目安です。当日の進行で前後します", 12,
         color=FAINT, bold=False)

ROWS = [
    ("14:55ごろ", "オープニング / 役割決め(タイムキーパー・メモ係・マイク係)", "10分", "plain"),
    ("15:05ごろ", "ラウンド1「私のAI活用のリアル」", "約20分", "round"),
    ("15:25ごろ", "⏳ インターバル(記録 / 第2ラウンド説明)", "5分", "rest"),
    ("15:30ごろ", "ラウンド2「私が感じているAIの壁」", "約20分", "round"),
    ("15:50ごろ", "⏳ インターバル(記録 / 第3ラウンド説明)", "5分", "rest"),
    ("15:55ごろ", "ラウンド3「私のAI活用スモールステップ」(最後に投稿)", "約20分", "round"),
    ("16:15ごろ", "🎤 全体共有(各グループ代表 1分)", "約8分", "round"),
    ("16:23ごろ", "締め", "2分", "plain"),
]
ry = 0.305
for clock, label, dur, kind in ROWS:
    fill = CARD if kind != "round" else RGBColor(0x1C, 0x2E, 0x52)
    bar_c = {"plain": EDGE, "round": CYAN, "rest": MINT}[kind]
    add_box(s, 0.05, ry, 0.90, 0.068, fill=fill, line=None)
    bar = add_box(s, 0.05, ry, 0.007, 0.068, fill=bar_c, line=None, radius=False)
    add_text(s, 0.07, ry + 0.013, 0.13, 0.045, clock, 13, color=LAV, font=EN,
             anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, 0.21, ry + 0.013, 0.60, 0.045, label, 14,
             bold=(kind == "round"), color=INK if kind == "round" else MUTED,
             anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, 0.84, ry + 0.013, 0.09, 0.045, dur, 12, color=MUTED, bold=False,
             align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
    ry += 0.071

add_text(s, 0.05, 0.875, 0.9, 0.04,
         "🎙 マイク係のPCが会話を自動で文字起こし   📝 気づきは # メモ-グループ1〜6 へ",
         11, color=FAINT, bold=False)

# ---------- 2.5: 役割決め ----------
s = prs.slides.add_slide(BLANK)
add_bg(s)
add_header(s, "SETUP", "SETUP")
add_stepper(s, 0)
add_text(s, 0.05, 0.215, 0.9, 0.09, "3つの係を決めてください", 34)
add_pill(s, 0.05, 0.315, 0.14, 0.06, "各グループ3名", 15, CYAN, None, line=CYAN)
add_text(s, 0.21, 0.325, 0.5, 0.05, "決まったグループから準備スタート", 12, color=FAINT, bold=False)

ROLES = [
    ("⏱ タイムキーパー",
     [[M("時間を見ながら進行をサポート")],
      [M("一人に偏らず"), B("全員が話せる"), M("ように回す")]]),
    ("📝 メモ係",
     [[M("話の要点を "), B("# メモ-グループN"), M(" に投稿")],
      [M("全部書き取らなくてOK")],
      [M("リンクの書き込みも歓迎")]]),
    ("🎙 マイク調整",
     [[M("自分のPCで "), B("🔊グループN"), M(" に参加しマイクをオン")],
      [B("テーブル中央"), M("にPCを置き全員の声を拾う")],
      [M("声を出して"), B("緑色に点灯"), M("すれば準備OK")]]),
]
for ci, (ct, items) in enumerate(ROLES):
    bx = 0.05 + ci * 0.31
    add_box(s, bx, 0.41, 0.28, 0.37)
    add_text(s, bx + 0.015, 0.435, 0.25, 0.055, ct, 16, color=CYAN)
    lines = []
    for it in items:
        lines.append([("▸ ", CYAN, True, JP)] + it)
    add_text(s, bx + 0.015, 0.50, 0.25, 0.26, lines, 12.5, color=MUTED, bold=False, spacing=1.25)

add_text(s, 0.05, 0.80, 0.9, 0.055, "🎯 3名が決まって、マイク係のPCが🔊グループNに入ったら準備完了", 17, align=PP_ALIGN.CENTER)
add_text(s, 0.05, 0.868, 0.9, 0.04,
         [[("💡 係以外の方は何の準備もいりません   📝 気づきは誰でも # メモ-グループN に書き込みOK", FAINT, False, JP)]],
         11, bold=False)

# ---------- 3-5: ラウンド ----------
add_round_slide(
    "ROUND 1/3", "R1", "私のAI活用のリアル", "約20分", "15:05ごろ〜(時刻は目安)",
    "やること",
    [[M("自己紹介と一緒に、"), B("普段のAI活用例"), M("を一人ずつ共有")],
     [M("全員が話したら、気になる話を深掘り")],
     [M("「何を使った?」「どう頼んだ?」と"), B("真似できるところまで"), M("聞く")]],
    "ポイント",
    [[M("仕事の成果も「日常がちょっと楽になった」もOK")],
     [M("自分の当たり前が、他の人の発見になる")],
     [M("困りごとは次のラウンドで。まずは"), B("うまくいった話"), M("を集める")]],
    "🎯 この時間のゴール ─ 「自分も真似してみたい!」を最低1つ見つける",
    ["🎙 会話はマイク係のPCが自動で記録", "📝 メモ係: 要点を # メモ-グループN へ",
     "⏱ 一人に偏らず全員が話す"],
    1,
)
add_round_slide(
    "ROUND 2/3", "R2", "私が感じているAIの壁", "約20分", "15:30ごろ〜(時刻は目安)",
    "やること",
    [[B("うまくいかなかったこと・困っていること"), M("を一人1つずつ共有")],
     [M("「何をしたくて、どこでつまずいた?」をみんなで深掘り")],
     [M("試した方法や役立ちそうなアイデアがあれば共有")]],
    "ポイント",
    [[M("「この仕事、AIで楽にできない?」という相談もOK")],
     [M("「自分も同じところで困ってる!」をぜひ伝える")],
     [B("この場で解決しきらなくてOK"), M("。ヒント探しの時間")]],
    "🎯 この時間のゴール ─ お互いのつまずきを知り、次に試せそうなヒントを探す",
    ["🎙 会話はマイク係のPCが自動で記録", "📝 メモ係: 悩みとヒントを # メモ-グループN へ",
     "⏱ 一人に偏らず全員が話す"],
    3,
)
add_round_slide(
    "ROUND 3/3", "R3", "私のAI活用スモールステップを見つけよう", "約20分", "15:55ごろ〜(時刻は目安)",
    "やること",
    [[M("ここまでの話を踏まえて、"), B("自分が明日から何をするか"), M("を一人ずつ宣言")],
     [M("迷っている人は「この作業を楽にしたい」という相談からでOK")],
     [M("みんなで"), B("実際に取りかかれる一歩"), M("に具体化する")]],
    "具体化の3点セット",
    [[B("どの作業"), M("で使う?")],
     [B("最初に何"), M("をする?")],
     [B("いつ"), M("試す?")]],
    "🎯 最後に ─ アクションを1人1つ # メモ-グループN に投稿 + 全体共有の代表と内容を決める",
    ["💡 大きな仕組みは不要。自分一人でできる小さなことでOK",
     "⏱ 全員ぶんのスモールステップを考える"],
    5,
)

add_round_slide(
    "SHARING", "SH", "全体共有", "各グループ1分", "16:15ごろ〜(時刻は目安)",
    "やること",
    [[M("各グループの"), B("代表1名"), M("が、全体に向けて発表")],
     [M("内容: グループで出た話 + "), B("印象に残ったスモールステップ")],
     [M("順番: "), B("グループ1 → 6"), M("(1グループ 1分)")]],
    "皆さんへのお願い",
    [[M("🔇 "), B("マイク係の方"), M(": 発表中は "), B("Discordのマイクをミュート")],
     [M("(発表の声を各テーブルのマイクが拾ってしまうため)")],
     [M("終わったらミュート解除をお願いします")]],
    "🎯 他のグループの発見を持ち帰る",
    ["📝 気になったアイデアは # メモ-グループN にメモしてOK",
     "⏱ 1分経過で運営がベルを鳴らします"],
    6,
)

prs.save("apf-slides.pptx")
print("saved: apf-slides.pptx /", len(prs.slides.__iter__.__self__._sldIdLst), "slides")
