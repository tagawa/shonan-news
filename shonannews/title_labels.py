# Subject labels set by code from the Japanese source title, only where the model gave none.
# Backend spec, "Labels set by code (2026-11-20)". Tuned in docs/label-candidates-criteria.md, rounds 4 and 5;
# the prompt is not used for these because a measured music sentence made the model's names and facts worse.
import re
import unicodedata

MUSIC = re.compile("|".join((
    "演奏", "コンサート", "concert", "(?<!ド)ライブ(?!配信)", "合唱", "吹奏楽", "音楽", "ゴスペル", "オルガン", "太鼓",
    "三味線", "レゲエ", "reggae", "ギター", "マンドリン", "バイオリン", "ピアノ", "オペラ", "アカペラ", "室内楽", "DJ",
    "楽曲", "新曲", "歌声", "音色", "うた", "フォーク", "ジャズ", "オーケストラ", "交響", "管弦楽", "合奏", "歌謡",
    "リサイタル", "バンド(?!ウイルカ)", "軍楽隊", "歌手", "ミュージック",
    "ロカビリー", "(?<!ブ)ロック(?!ダウン)", "第九", "ピアニスト", "奏者", "アヴェマリア",
)), re.IGNORECASE)
NOT_MUSIC = re.compile("ミュージカル|盆踊り|カラオケ|お笑い|ラジオ体操")
# A festival, fair or market with music in it is music as a side attraction, unless it is a music festival by name.
MUSIC_FESTIVAL = re.compile(r"(音楽|合唱|ジャズ|ロック|ロカビリー|レゲエ|reggae|太鼓|吹奏楽|ゴスペル|フォーク|うた|歌)"
                            r"の?(祭|まつり|フェス|サミット|bash)", re.IGNORECASE)
FESTIVAL = re.compile("祭|まつり|フェス|マルシェ|フリマ|バザー|マーケット|ビアガーデン|ピクニック|キャンペーン")

EXHIBITION = re.compile(r"展|ギャラリー|画廊|個展|美術館|アートフェス|アート展|写真家|浮世絵|作品(が|も)?(ずらり|並ぶ|一堂)")
# 展 also writes development, outlook and so on; and history, treasure, nature and trade displays, prizes, side
# displays, Town News profile columns ("在住 79歳") and music in a gallery are not art shows.
NOT_EXHIBITION = re.compile(r"発展|進展|展開|展望|出展|矯正展|親展|博物館|国宝|宝物|特別公開|ロボット|防災|フェア|即売|入選|入賞|"
                            r"最優秀|展示も|も展示|(?<!アート)(祭|まつり)|盆栽|いけばな|生け花|ポスター展|パネル展|ヒョウタン|図録|"
                            r"植物|講演|再開|在住\s*\d+歳|ライブ|コンサート")


def is_music(source_title: str) -> bool:
    title = unicodedata.normalize("NFKC", source_title)
    if not MUSIC.search(title) or NOT_MUSIC.search(title):
        return False
    return not FESTIVAL.search(MUSIC_FESTIVAL.sub("", title))


def is_exhibition(source_title: str) -> bool:
    title = unicodedata.normalize("NFKC", source_title)
    return bool(EXHIBITION.search(title)) and not NOT_EXHIBITION.search(title)


def label(model_label: str | None, source_title: str) -> str | None:
    if model_label:
        return model_label
    if is_music(source_title):
        return "music"
    if is_exhibition(source_title):
        return "exhibition"
    return None
